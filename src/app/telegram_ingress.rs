//! Optional Telegram Bot API ingress. The Gateway owns the shared store,
//! session admission and native processing used by this adapter.
use super::*;
use crate::commands::default_bot_commands;

pub(super) async fn connect(
    config: &Config,
    store: &Store,
) -> Result<(TelegramClient, Option<crate::telegram::User>)> {
    if config.telegram.enabled {
        let token = config.telegram.resolve_token()?;
        let client = TelegramClient::new(token, config.telegram.api_base.clone())
            .with_reaction_capture(config.telegram.capture_message_reactions)
            .with_local_file_root(config.telegram.local_file_root.clone())?;
        let identity = if config.interaction.is_some() {
            tokio::time::timeout(Duration::from_secs(5), client.get_me()).await
        } else {
            Ok(client.get_me().await)
        };
        match identity {
            Ok(Ok(me)) => {
                store.save_bot_state("telegram_identity", &serde_json::to_string(&me)?)?;
                return Ok((client, Some(me)));
            }
            // Keep standalone Conversation available. An unverified bot must
            // never poll with a retained identity or project new outputs.
            _ if config.interaction.is_some() => {
                tracing::warn!(
                    "Telegram identity unavailable; starting DaimonGateway without Telegram"
                );
                // Preserve configured projection intent for retained operations.
                // The unavailable client refuses every Bot API side effect.
            }
            Ok(Err(error)) => return Err(error).context("telegram getMe failed"),
            Err(error) => return Err(error).context("telegram getMe timed out"),
        }
    }
    let retained = store
        .bot_state_value("telegram_identity")?
        .map(|value| serde_json::from_str(&value))
        .transpose()?;
    Ok((TelegramClient::disabled(), retained))
}

impl App {
    pub(super) async fn run_telegram_ingress(&self) -> Result<()> {
        topic_publications::recover(self.shared.clone())?;
        let mut menu = default_bot_commands();
        if self.shared.config.nexus.is_some() {
            menu.push(crate::telegram::BotCommand {
                command: "nexus".into(),
                description: "/nexus [connect|disconnect|status|reconcile|recover|open] [table]"
                    .into(),
            });
        }
        self.shared
            .telegram
            .set_my_commands(&menu)
            .await
            .context("failed to register bot commands")?;
        self.notify_primary_user(&format!("🟢 Telecodex {} started", app_version_label()))
            .await;

        // Polling must not wait for native steering, uploads or outbound rate limits.
        // Preserve arrival order within a topic while other topics keep dispatching.
        let mut dispatchers = HashMap::<
            SessionKey,
            mpsc::UnboundedSender<(crate::telegram::Update, tokio::task::JoinHandle<Result<()>>)>,
        >::new();
        let mut offset = self.shared.store.last_update_id()?.map(|value| value + 1);
        tracing::info!("telecodex started {}", app_version_label());
        let shutdown = shutdown_signal(self.shared.shutdown.clone());
        tokio::pin!(shutdown);

        loop {
            tokio::select! {
                _ = &mut shutdown => {
                    tracing::info!("shutdown signal received");
                    self.notify_primary_user(&format!("🔴 Telecodex {} stopped", app_version_label()))
                        .await;
                    return Ok(());
                }
                result = self
                    .shared
                    .telegram
                    .get_updates(offset, self.shared.config.poll_timeout_seconds) => {
                    match result {
                        Ok(updates) => {
                            for update in updates {
                                let admitted = self.shared.store.admit_update(&update)?;
                                offset = self.shared.store.last_update_id()?.map(|id| id + 1);
                                if !admitted {
                                    continue;
                                }
                                // Capture independently of topic work and further polling. A slow
                                // Nexus provider must not serialize unrelated updates or controls.
                                let capture_input = nexus::prepare_ingress(&self.shared, &update)?;
                                let capture_shared = self.shared.clone();
                                let capture_id = update.update_id;
                                let capture = tokio::spawn(async move {
                                    nexus::capture_ingress(&capture_shared, capture_id, capture_input).await
                                });
                                let message = update.message.as_ref().or_else(|| {
                                    update.callback_query.as_ref().and_then(|callback| callback.message.as_ref())
                                });
                                let key = message.map(|message| SessionKey {
                                    chat_id: message.chat.id,
                                    thread_id: message.message_thread_id.unwrap_or(0),
                                }).unwrap_or(SessionKey { chat_id: 0, thread_id: 0 });
                                let sender = dispatchers.entry(key).or_insert_with(|| {
                                    let (sender, mut receiver) = mpsc::unbounded_channel::<(crate::telegram::Update, tokio::task::JoinHandle<Result<()>>)>();
                                    let app = self.clone();
                                    tokio::spawn(async move {
                                        while let Some((update, capture)) = receiver.recv().await {
                                            let update_id = update.update_id;
                                            let result = async {
                                                // Admission capture runs even while a previous
                                                // message holds this topic dispatcher.
                                                capture.await.context("Nexus ingress capture task interrupted")??;
                                                app.shared.store.begin_update(update_id)?;
                                                HUMAN_UPDATE_ID.scope(update_id, app.process_update(update)).await
                                            }.await;
                                            if let Err(error) = app.shared.store.finish_update_dispatch(update_id, result.is_ok()) {
                                                tracing::error!("failed to record update dispatch: {error:#}");
                                            }
                                            if let Err(error) = result {
                                                tracing::error!("update processing failed: {error:#}");
                                            }
                                        }
                                    });
                                    sender
                                });
                                sender.send((update, capture)).map_err(|_| anyhow!("topic update dispatcher dropped"))?;
                            }
                        }
                        Err(error) => {
                            if telegram_status(&error) == Some(reqwest::StatusCode::CONFLICT) {
                                self.notify_primary_user(&format!("🔴 Telecodex {} stopped: getUpdates conflict", app_version_label()))
                                    .await;
                                return Err(anyhow!(
                                    "telegram getUpdates conflict: another bot instance is already running"
                                ));
                            }
                            if let Some(retry_after) = telegram_retry_after(&error) {
                                tracing::warn!("telegram asked to back off for {retry_after}s");
                                sleep(Duration::from_secs(retry_after)).await;
                            } else {
                                tracing::error!("getUpdates failed: {error:#}");
                                sleep(Duration::from_secs(3)).await;
                            }
                        }
                    }
                }
            }
        }
    }
}
