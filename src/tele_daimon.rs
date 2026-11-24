//! Telegram transport. The Gateway acknowledges admission before TeleDaimon
//! advances the polling cursor.
use std::{future::Future, path::Path, time::Duration};

use anyhow::{Context, Result, bail};
use tokio::time::sleep;

use crate::config::TelegramConfig;
use crate::render::render_markdown_to_html;
pub(crate) use crate::render::split_text as projection_parts;
use crate::telegram::{
    BotCommand, Message, SendMessage, TelegramClient, TelegramError, Update, User,
};

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

/// A transport observation. Gateway owns its canonical interpretation and row.
pub(crate) enum Delivery {
    Unsent,
    Acknowledged(i64),
    CoolingDown,
    Rejected,
    Unconfirmed,
}

pub(crate) struct Projection<'a> {
    pub client: &'a TelegramClient,
    pub chat: i64,
    pub topic: Option<i64>,
}

pub(crate) struct ProjectedFile<'a> {
    pub name: &'a str,
    pub bytes: Vec<u8>,
    pub mime: Option<&'a str>,
    pub caption: &'a str,
}

impl Projection<'_> {
    pub(crate) async fn text(
        &self,
        markdown: &str,
        reserve: impl FnOnce() -> Result<bool>,
    ) -> Result<Delivery> {
        let mut reserved = false;
        let result = self
            .client
            .send_message_checked(self.chat, || {
                reserved = reserve()?;
                Ok(reserved.then(|| {
                    (
                        SendMessage::html(self.chat, self.topic, render_markdown_to_html(markdown)),
                        (),
                    )
                }))
            })
            .await
            .map(|result| result.map(|(message, ())| message));
        self.receipt(reserved, result)
    }

    pub(crate) async fn file(
        &self,
        file: ProjectedFile<'_>,
        reserve: impl FnOnce() -> Result<bool>,
    ) -> Result<Delivery> {
        let extension = Path::new(file.name)
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let field = match extension.as_str() {
            "png" | "jpg" | "jpeg" | "webp" => "photo",
            "mp3" | "wav" | "m4a" | "ogg" => "audio",
            "mp4" | "mov" | "webm" => "video",
            _ => "document",
        };
        let mut reserved = false;
        let result = self
            .client
            .send_file_bytes_checked(
                self.chat,
                self.topic,
                field,
                file.bytes,
                file.name,
                file.mime,
                Some(file.caption),
                || {
                    reserved = reserve()?;
                    Ok(reserved)
                },
            )
            .await;
        self.receipt(reserved, result)
    }

    fn receipt(&self, reserved: bool, result: Result<Option<Message>>) -> Result<Delivery> {
        match result {
            Ok(None) => Ok(Delivery::Unsent),
            Ok(Some(message))
                if message.chat.id == self.chat
                    && message.message_thread_id.unwrap_or(0) == self.topic.unwrap_or(0)
                    && message.message_id > 0 =>
            {
                Ok(Delivery::Acknowledged(message.message_id))
            }
            Ok(Some(_)) => Ok(Delivery::Unconfirmed),
            Err(error) if !reserved => Err(error),
            Err(error) => {
                let telegram = error.downcast_ref::<TelegramError>();
                Ok(match telegram {
                    Some(response) if response.retry_after.is_some() => Delivery::CoolingDown,
                    Some(response) if response.status.is_client_error() => Delivery::Rejected,
                    _ => Delivery::Unconfirmed,
                })
            }
        }
    }
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
