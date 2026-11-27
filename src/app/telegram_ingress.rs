//! Gateway admission and dispatch for the optional Telegram adapter.
use super::*;
use crate::{
    commands::default_bot_commands,
    store::TelegramUpdateAdmission,
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
        release_ready_topics(self)?;
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

pub(super) type Dispatchers = StdMutex<HashMap<SessionKey, mpsc::UnboundedSender<Dispatch>>>;

pub(super) enum Dispatch {
    Live(Box<Update>, Capture),
    Release,
}

fn enqueue(app: &App, key: SessionKey, work: Dispatch) -> Result<()> {
    let mut dispatchers = app
        .shared
        .telegram_dispatchers
        .lock()
        .expect("Telegram dispatchers poisoned");
    let sender = dispatchers.entry(key).or_insert_with(|| {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let shared = Arc::downgrade(&app.shared);
        let workers = Arc::downgrade(&app.workers);
        let shutdown = app.shared.shutdown.clone();
        tokio::spawn(async move {
            while let Some(work) = tokio::select! {
                _ = shutdown.cancelled() => None,
                next = receiver.recv() => next,
            } {
                let (Some(shared), Some(workers)) = (shared.upgrade(), workers.upgrade()) else {
                    break;
                };
                let app = App { shared, workers };
                if let Err(error) = dispatch_work(&app, key, work).await {
                    tracing::error!("Telegram dispatch failed: {error:#}");
                }
            }
        });
        sender
    });
    sender
        .send(work)
        .map_err(|_| anyhow!("Topic update dispatcher dropped"))
}

pub(super) fn release_created_topic(app: &App, key: SessionKey) -> Result<()> {
    enqueue(app, key, Dispatch::Release)
}

pub(super) fn wake_released_topics(shared: &AppShared, topics: &[SessionKey]) {
    if topics.is_empty() {
        return;
    }
    let dispatchers = shared
        .telegram_dispatchers
        .lock()
        .expect("Telegram dispatchers poisoned");
    for topic in topics {
        if let Some(sender) = dispatchers.get(topic)
            && sender.send(Dispatch::Release).is_err()
        {
            tracing::warn!("Created topic updates remain retained after Stop resume");
        }
    }
}

fn release_ready_topics(app: &App) -> Result<()> {
    for key in app.shared.store.ready_creation_update_topics()? {
        release_created_topic(app, key)?;
    }
    Ok(())
}

async fn dispatch_work(app: &App, key: SessionKey, work: Dispatch) -> Result<()> {
    let update = match work {
        Dispatch::Live(update, capture) => {
            capture
                .await
                .context("Nexus ingress capture task interrupted")??;
            let stop = update
                .message
                .as_ref()
                .and_then(|message| message.text.as_deref())
                .and_then(|text| normalize_command(text, app.shared.bot_username().as_deref()))
                .is_some_and(|(command, _)| matches!(command.as_str(), "/stop" | "/interrupt"));
            if app.shared.store.begin_creation_aware_update(&update)? {
                return Ok(());
            }
            if stop {
                run_journaled_update(app, *update).await;
                return Ok(());
            }
            Some(update)
        }
        Dispatch::Release => None,
    };
    while let Some(held) = app.shared.store.claim_creation_update(key)? {
        run_journaled_update(app, held).await;
    }
    if let Some(update) = update {
        run_journaled_update(app, *update).await;
    }
    Ok(())
}

async fn run_journaled_update(app: &App, update: Update) {
    let id = update.update_id;
    let result = HUMAN_UPDATE_ID
        .scope(id, Box::pin(app.process_update(update)))
        .await;
    if let Err(error) = app.shared.store.finish_update_dispatch(id, result.is_ok()) {
        tracing::error!("Failed to record Telegram dispatch: {error:#}");
    }
    if let Err(error) = result {
        tracing::error!("Telegram update processing failed: {error:#}");
    }
}

pub(super) struct TelegramGateway {
    app: App,
    adapter_identified: bool,
    pub(super) credential_fingerprint: Option<String>,
}

impl TelegramGateway {
    pub(super) fn new(app: App) -> Self {
        Self {
            app,
            adapter_identified: false,
            credential_fingerprint: None,
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
            IngressRequest::Ready {
                identity,
                credential_fingerprint,
                ..
            } => {
                anyhow::ensure!(
                    identity.is_some() || credential_fingerprint.is_none(),
                    "TeleDaimon credential fingerprint requires verified identity"
                );
                if let Some(identity) = identity {
                    anyhow::ensure!(
                        credential_fingerprint
                            .as_ref()
                            .is_none_or(|fingerprint| fingerprint.len() == 64
                                && fingerprint
                                    .bytes()
                                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))),
                        "Invalid TeleDaimon credential fingerprint"
                    );
                    anyhow::ensure!(
                        self.credential_fingerprint.is_none()
                            || self.credential_fingerprint == credential_fingerprint,
                        "TeleDaimon credential changed"
                    );
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
                    self.credential_fingerprint = credential_fingerprint;
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
                release_ready_topics(&self.app)?;
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
        let admission = self.app.shared.store.admit_telegram_update(&update)?;
        let next_offset = self.next_offset().await?;
        if admission != TelegramUpdateAdmission::Dispatch {
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
        enqueue(&self.app, key, Dispatch::Live(Box::new(update), capture))?;
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

#[cfg(unix)]
#[derive(serde::Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum SessionsTelegram {
    Status,
    Alert {
        credential_fingerprint: String,
        text: String,
    },
    MenuRead {
        credential_fingerprint: String,
    },
    MenuWrite {
        credential_fingerprint: String,
        menu: SessionsMenu,
    },
}

#[cfg(unix)]
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum SessionsMenu {
    Default,
    Commands,
    WebApp {
        text: String,
        web_app: SessionsWebApp,
    },
}

#[cfg(unix)]
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SessionsWebApp {
    url: String,
}

#[cfg(unix)]
pub(super) async fn sessions_telegram(
    app: &App,
    human: i64,
    gateway: &Mutex<TelegramGateway>,
    request: SessionsTelegram,
) -> Result<serde_json::Value> {
    use crate::tele_daimon::projection::{self, JsonMethod};
    use serde_json::json;

    let shared = &app.shared;
    let authorize = || {
        anyhow::ensure!(
            shared
                .store
                .get_user(human)?
                .is_some_and(|user| user.allowed),
            "Sessions Telegram grant unavailable"
        );
        Ok(())
    };
    authorize()?;
    let fingerprint = gateway
        .lock()
        .await
        .credential_fingerprint
        .clone()
        .context("TeleDaimon credential not observed")?;
    let socket = &shared
        .config
        .session_control
        .as_ref()
        .context("Missing owner control socket")?
        .socket_path;
    let (method, document, expected) = match request {
        SessionsTelegram::Status => {
            // Obtain a readiness acknowledgement from the live bound adapter,
            // then drop the connection without authorizing any Bot API call.
            let prepared = projection::prepare_json(
                socket,
                shared.bot_id,
                JsonMethod::GetChatMenuButton,
                Some(json!({"chat_id":human})),
                Some(fingerprint.clone()),
                None,
            )
            .await?;
            drop(prepared);
            let identity = shared
                .bot_metadata
                .lock()
                .expect("bot metadata lock poisoned");
            let identity = identity
                .as_ref()
                .context("TeleDaimon identity not observed")?;
            return Ok(json!({
                "id": identity.id, "username": identity.username,
                "has_main_web_app": identity.has_main_web_app.unwrap_or(false),
                "credential_fingerprint": fingerprint
            }));
        }
        SessionsTelegram::Alert {
            text,
            credential_fingerprint,
        } => {
            anyhow::ensure!(
                !text.trim().is_empty() && text.chars().count() <= 4096,
                "Invalid Sessions alert text"
            );
            (
                JsonMethod::SendMessage,
                json!({"chat_id":human,"text":text}),
                credential_fingerprint,
            )
        }
        SessionsTelegram::MenuRead {
            credential_fingerprint,
        } => (
            JsonMethod::GetChatMenuButton,
            json!({"chat_id":human}),
            credential_fingerprint,
        ),
        SessionsTelegram::MenuWrite {
            menu,
            credential_fingerprint,
        } => {
            if let SessionsMenu::WebApp { text, web_app } = &menu {
                let url = reqwest::Url::parse(&web_app.url).context("Invalid Sessions menu URL")?;
                anyhow::ensure!(
                    !text.trim().is_empty()
                        && text.chars().count() <= 64
                        && web_app.url.len() <= 2048
                        && url.scheme() == "https"
                        && url.host().is_some()
                        && url.username().is_empty()
                        && url.password().is_none(),
                    "Invalid Sessions web app menu"
                );
            }
            (
                JsonMethod::SetChatMenuButton,
                json!({"chat_id":human,"menu_button":menu}),
                credential_fingerprint,
            )
        }
    };
    anyhow::ensure!(
        expected == fingerprint,
        "Sessions Telegram credential changed"
    );
    if matches!(method, JsonMethod::SendMessage) {
        shared.telegram.wait_projection(human).await?;
    }
    let result = projection::json(
        socket,
        shared.bot_id,
        method,
        Some(document),
        Some(fingerprint),
        None,
        authorize,
    )
    .await;
    match result {
        Ok(result) => Ok(json!({"ok":true,"result":result})),
        Err(error) => {
            if error.is::<projection::JsonNotSubmitted>() {
                return Ok(json!({"ok":false,"not_submitted":true}));
            }
            if let Some(provider) = error.downcast_ref::<crate::telegram::TelegramError>() {
                return Ok(json!({"ok":false,"error_code":provider.status.as_u16()}));
            }
            bail!("Sessions Telegram operation unconfirmed")
        }
    }
}
