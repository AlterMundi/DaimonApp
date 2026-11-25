//! Gateway admission and dispatch for the optional Telegram adapter.
use super::*;
use crate::{
    commands::default_bot_commands,
    tele_daimon::{self, GatewayIngress, IngressReply, IngressRequest, Lifecycle},
    telegram::Update,
};

pub(super) async fn connect(
    config: &Config,
    store: &Store,
) -> Result<(TelegramClient, Option<crate::telegram::User>)> {
    if config.telegram.enabled && !config.telegram.external_polling {
        let client = tele_daimon::client(&config.telegram)?;
        if let Some(identity) = tele_daimon::identify(&client, config.interaction.is_some()).await?
        {
            store.save_bot_state("telegram_identity", &serde_json::to_string(&identity)?)?;
            return Ok((client, Some(identity)));
        }
        tracing::warn!("Telegram identity unavailable; starting DaimonGateway without Telegram");
    }
    let retained: Option<crate::telegram::User> = store
        .bot_state_value("telegram_identity")?
        .map(|value| serde_json::from_str(&value))
        .transpose()?;
    #[cfg(unix)]
    if config.telegram.enabled && config.telegram.external_polling {
        let selected = config.telegram.external_bot_id;
        let previous = retained.as_ref().map(|bot| bot.id);
        anyhow::ensure!(
            selected
                .zip(previous)
                .is_none_or(|(selected, previous)| selected == previous),
            "External Telegram bot does not match the journal identity"
        );
        if let Some(id) = selected.or(previous).filter(|id| *id > 0) {
            let control = config
                .session_control
                .as_ref()
                .context("Missing owner control socket")?;
            return Ok((
                TelegramClient::new_relay(control.socket_path.clone(), id),
                retained,
            ));
        }
        tracing::warn!("External Telegram requires a selected bot ID; Gateway remains available");
    }
    Ok((TelegramClient::disabled(), retained))
}

impl App {
    fn telegram_menu(&self) -> Vec<crate::telegram::BotCommand> {
        let mut menu = default_bot_commands();
        if self.shared.config.nexus.is_some() {
            menu.push(crate::telegram::BotCommand {
                command: "nexus".into(),
                description: "/nexus [connect|disconnect|status|reconcile|recover|open] [table]"
                    .into(),
            });
        }
        menu
    }

    pub(super) async fn run_telegram_ingress(&self) -> Result<()> {
        topic_publications::recover(self.shared.clone())?;
        let menu = self.telegram_menu();
        let mut gateway = TelegramGateway::new(self.clone());
        tele_daimon::poll(
            &self.shared.telegram,
            &menu,
            self.shared.config.poll_timeout_seconds,
            &mut gateway,
            shutdown_signal(self.shared.shutdown.clone()),
            |notice| {
                let app = self.clone();
                async move {
                    let (icon, status) = match notice {
                        Lifecycle::Started => ("🟢", "started"),
                        Lifecycle::Stopped => ("🔴", "stopped"),
                        Lifecycle::PollConflict => ("🔴", "stopped: getUpdates conflict"),
                    };
                    tracing::info!("Telegram ingress {status}");
                    app.notify_primary_user(&format!(
                        "{icon} Telecodex {} {status}",
                        app_version_label()
                    ))
                    .await;
                }
            },
        )
        .await
    }
}

type Capture = tokio::task::JoinHandle<Result<()>>;
pub(super) struct TelegramGateway {
    app: App,
    adapter_identified: bool,
    dispatchers: HashMap<SessionKey, mpsc::UnboundedSender<(Update, Capture)>>,
}

impl TelegramGateway {
    pub(super) fn new(app: App) -> Self {
        Self {
            app,
            adapter_identified: false,
            dispatchers: HashMap::new(),
        }
    }

    pub(super) async fn external(&mut self, request: IngressRequest) -> Result<IngressReply> {
        let bot_id = match &request {
            IngressRequest::Ready { bot_id, .. }
            | IngressRequest::ProjectionReady { bot_id }
            | IngressRequest::Admit { bot_id, .. } => *bot_id,
        };
        let shared = &self.app.shared;
        anyhow::ensure!(
            shared.config.telegram.external_polling
                && shared.telegram.is_available()
                && shared.bot_id > 0
                && shared.bot_id == bot_id,
            "External Telegram ingress is unavailable for the selected bot"
        );
        match request {
            IngressRequest::Ready { identity, .. } => {
                if let Some(identity) = identity {
                    anyhow::ensure!(
                        identity.is_bot && identity.id == bot_id,
                        "Telegram bot identity mismatch"
                    );
                    shared
                        .store
                        .save_bot_state("telegram_identity", &serde_json::to_string(&identity)?)?;
                    *shared
                        .bot_metadata
                        .lock()
                        .expect("bot metadata lock poisoned") = Some(identity);
                    self.adapter_identified = true;
                }
                Ok(IngressReply::Ready {
                    next_offset: self.next_offset().await?,
                    menu: self.app.telegram_menu(),
                    identified: self.adapter_identified,
                })
            }
            IngressRequest::ProjectionReady { .. } => {
                anyhow::ensure!(
                    self.adapter_identified,
                    "TeleDaimon has not identified the selected bot"
                );
                topic_publications::recover(self.app.shared.clone())?;
                Ok(IngressReply::Accepted {
                    next_offset: self.next_offset().await?,
                })
            }
            IngressRequest::Admit { update, .. } => {
                anyhow::ensure!(
                    self.adapter_identified,
                    "TeleDaimon has not identified the selected bot"
                );
                Ok(IngressReply::Accepted {
                    next_offset: self.accept(*update).await?,
                })
            }
        }
    }
}

impl GatewayIngress for TelegramGateway {
    async fn next_offset(&self) -> Result<Option<i64>> {
        self.app
            .shared
            .store
            .last_update_id()?
            .map(|id| id.checked_add(1).context("Telegram offset is exhausted"))
            .transpose()
    }

    async fn accept(&mut self, update: Update) -> Result<Option<i64>> {
        anyhow::ensure!(
            (0..i64::MAX).contains(&update.update_id),
            "Invalid Telegram update ID"
        );
        let admitted = self.app.shared.store.admit_update(&update)?;
        let next_offset = self.next_offset().await?;
        if !admitted {
            return Ok(next_offset);
        }
        // Capture independently of per-topic dispatch and further polling.
        let capture_input = nexus::prepare_ingress(&self.app.shared, &update)?;
        let capture_shared = self.app.shared.clone();
        let capture_id = update.update_id;
        let capture = tokio::spawn(async move {
            nexus::capture_ingress(&capture_shared, capture_id, capture_input).await
        });
        let message = update.message.as_ref().or_else(|| {
            update
                .callback_query
                .as_ref()
                .and_then(|callback| callback.message.as_ref())
        });
        let key = message.map_or(
            SessionKey {
                chat_id: 0,
                thread_id: 0,
            },
            |message| SessionKey {
                chat_id: message.chat.id,
                thread_id: message.message_thread_id.unwrap_or(0),
            },
        );
        let sender = self.dispatchers.entry(key).or_insert_with(|| {
            let (sender, mut receiver) = mpsc::unbounded_channel::<(Update, Capture)>();
            let app = self.app.clone();
            tokio::spawn(async move {
                while let Some((update, capture)) = receiver.recv().await {
                    let update_id = update.update_id;
                    let result = async {
                        capture
                            .await
                            .context("Nexus ingress capture task interrupted")??;
                        app.shared.store.begin_update(update_id)?;
                        HUMAN_UPDATE_ID
                            .scope(update_id, app.process_update(update))
                            .await
                    }
                    .await;
                    if let Err(error) = app
                        .shared
                        .store
                        .finish_update_dispatch(update_id, result.is_ok())
                    {
                        tracing::error!("failed to record update dispatch: {error:#}");
                    }
                    if let Err(error) = result {
                        tracing::error!("update processing failed: {error:#}");
                    }
                }
            });
            sender
        });
        sender
            .send((update, capture))
            .map_err(|_| anyhow!("topic update dispatcher dropped"))?;
        Ok(next_offset)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn telegram_client_reconnect_preserves_the_gateway_offset_and_native_binding() {
        let root = tempfile::tempdir().unwrap();
        let database = root.path().join("gateway.sqlite");
        let mut config =
            super::super::tests::cold_interaction_config(database.clone(), root.path().into(), 100);
        config.telegram.enabled = true;
        let entry = config.interaction.as_ref().unwrap().entry();
        let me = json!({"ok":true,"result":{
            "id":101,"is_bot":true,"first_name":"Fixture","username":"fixture_bot"
        }});
        let menu_ack = json!({"ok":true,"result":true});
        let conflict = json!({"ok":false,"error_code":409,"description":"Fixture conflict"});
        let update = |id| json!({"update_id":id});
        for (expected_before, updates, expected_after) in [
            (None, vec![update(41)], 42),
            (Some(42), vec![update(41), update(42)], 43),
        ] {
            let (url, server) = crate::telegram::tests::serve_api(vec![
                (200, me.clone()),
                (200, menu_ack.clone()),
                (200, json!({"ok":true,"result":updates})),
                (409, conflict.clone()),
            ]);
            config.telegram.api_base = url;
            let app = App::bootstrap(config.clone()).await.unwrap();
            if expected_before.is_none() {
                app.shared
                    .store
                    .set_session_codex_thread(entry, "retained-native")
                    .unwrap();
            }
            let error = app.run_telegram_ingress().await.unwrap_err();
            assert!(error.to_string().contains("getUpdates conflict"));
            assert_eq!(
                app.shared.store.last_update_id().unwrap(),
                Some(expected_after - 1)
            );
            let requests = server.join().unwrap();
            for (request, offset) in [
                (&requests[2], expected_before),
                (&requests[3], Some(expected_after)),
            ] {
                assert!(request.0.contains("/getUpdates "));
                assert_eq!(request.1["offset"], json!(offset));
            }
            let retained_writer = Arc::downgrade(&app.shared);
            drop(app);
            tokio::time::timeout(Duration::from_secs(5), async {
                while retained_writer.upgrade().is_some() {
                    tokio::task::yield_now().await;
                }
            })
            .await
            .expect("The previous Gateway must drain its admitted dispatch before reopening");

            let mut standalone = config.clone();
            standalone.telegram.enabled = false;
            standalone.telegram.bot_token = None;
            let gateway = App::bootstrap(standalone).await.unwrap();
            assert!(!gateway.shared.telegram.is_available());
            assert_eq!(
                gateway.shared.store.last_update_id().unwrap(),
                Some(expected_after - 1)
            );
            let session = gateway.shared.store.get_session(entry).unwrap().unwrap();
            assert_eq!(session.codex_thread_id.as_deref(), Some("retained-native"));
        }
        let conn = rusqlite::Connection::open(database).unwrap();
        let counts: (i64, i64) = conn
            .query_row(
                "SELECT (SELECT count(*) FROM incoming_updates),
                    (SELECT count(*) FROM original_ingress_order WHERE channel='telegram')",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(counts, (2, 2));
    }
}
