//! Telegram transport. The Gateway acknowledges admission before TeleDaimon
//! advances the polling cursor.
use std::{future::Future, time::Duration};

use anyhow::{Context, Result, bail};
use tokio::time::sleep;

use crate::config::TelegramConfig;
use crate::telegram::{BotCommand, TelegramClient, TelegramError, Update, User};

pub(crate) trait GatewayIngress {
    fn next_offset(&self) -> Result<Option<i64>>;

    /// Return the next durable Telegram cursor after accepting this original.
    /// A duplicate may return the same cursor without creating native work.
    fn accept(&mut self, update: Update) -> Result<Option<i64>>;
}

pub(crate) enum Lifecycle {
    Started,
    Stopped,
    PollConflict,
}

pub(crate) fn client(config: &TelegramConfig) -> Result<TelegramClient> {
    TelegramClient::new(config.resolve_token()?, config.api_base.clone())
        .with_reaction_capture(config.capture_message_reactions)
        .with_local_file_root(config.local_file_root.clone())
}

pub(crate) async fn identify(
    client: &TelegramClient,
    shared_backend: bool,
) -> Result<Option<User>> {
    let identity = if shared_backend {
        tokio::time::timeout(Duration::from_secs(5), client.get_me()).await
    } else {
        Ok(client.get_me().await)
    };
    match identity {
        Ok(Ok(identity)) => Ok(Some(identity)),
        _ if shared_backend => Ok(None),
        Ok(Err(error)) => Err(error).context("telegram getMe failed"),
        Err(error) => Err(error).context("telegram getMe timed out"),
    }
}

pub(crate) async fn poll<NoticeFuture: Future<Output = ()> + Send>(
    client: &TelegramClient,
    commands: &[BotCommand],
    timeout_seconds: u32,
    gateway: &mut impl GatewayIngress,
    shutdown: impl Future<Output = ()>,
    notify: impl Fn(Lifecycle) -> NoticeFuture,
) -> Result<()> {
    client
        .set_my_commands(commands)
        .await
        .context("failed to register bot commands")?;
    notify(Lifecycle::Started).await;
    let mut offset = gateway.next_offset()?;
    tokio::pin!(shutdown);

    loop {
        tokio::select! {
            _ = &mut shutdown => {
                notify(Lifecycle::Stopped).await;
                return Ok(());
            }
            result = client.get_updates(offset, timeout_seconds) => {
                let delay = match result {
                    Ok(updates) => {
                        for update in updates {
                            offset = gateway.accept(update)?;
                        }
                        continue;
                    }
                    Err(error) => {
                        let telegram = error.downcast_ref::<TelegramError>();
                        if telegram.is_some_and(|response| response.status == reqwest::StatusCode::CONFLICT) {
                            notify(Lifecycle::PollConflict).await;
                            bail!("telegram getUpdates conflict: another bot instance is already running");
                        }
                        if let Some(retry_after) = telegram.and_then(|response| response.retry_after) {
                            tracing::warn!("telegram asked to back off for {retry_after}s");
                            Duration::from_secs(retry_after)
                        } else {
                            tracing::error!("getUpdates failed: {error:#}");
                            Duration::from_secs(3)
                        }
                    }
                };
                tokio::select! {
                    _ = &mut shutdown => {
                        notify(Lifecycle::Stopped).await;
                        return Ok(());
                    }
                    _ = sleep(delay) => {}
                }
            }
        }
    }
}
