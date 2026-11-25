//! Telegram transport. The Gateway acknowledges admission before TeleDaimon
//! advances the polling cursor.
use std::{future::Future, path::Path, time::Duration};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use tokio::time::sleep;

#[cfg(unix)]
pub(crate) mod projection;

use crate::config::TelegramConfig;
use crate::render::render_markdown_to_html;
pub(crate) use crate::render::split_text as projection_parts;
use crate::telegram::{
    BotCommand, Message, SendMessage, TelegramClient, TelegramError, Update, User,
};

pub(crate) trait GatewayIngress {
    async fn next_offset(&self) -> Result<Option<i64>>;

    async fn before_poll(&self, offset: Option<i64>) -> Result<Option<i64>> {
        Ok(offset)
    }

    /// Return the next durable Telegram cursor after accepting this original.
    /// A duplicate may return the same cursor without creating native work.
    async fn accept(&mut self, update: Update) -> Result<Option<i64>>;
}

pub(crate) enum Lifecycle {
    Started,
    Stopped,
    PollConflict,
}

/// A transport observation. Gateway owns its canonical interpretation and row.
#[derive(Deserialize, Serialize)]
pub(crate) enum Delivery {
    Unsent,
    Acknowledged(i64),
    CoolingDown(u64),
    Rejected,
    Unconfirmed,
}

pub(crate) struct Projection<'a> {
    pub client: &'a TelegramClient,
    pub chat: i64,
    pub topic: Option<i64>,
    pub remote: Option<(&'a Path, i64)>,
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
        if let Some((socket, bot)) = self.remote {
            #[cfg(unix)]
            return projection::send(
                socket,
                self,
                bot,
                projection::Payload::Text {
                    markdown: markdown.into(),
                },
                &[],
                reserve,
            )
            .await;
            #[cfg(not(unix))]
            bail!("External Telegram projection requires Unix");
        }
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
        if let Some((socket, bot)) = self.remote {
            #[cfg(unix)]
            return projection::send(
                socket,
                self,
                bot,
                projection::Payload::File {
                    name: file.name.into(),
                    size: u32::try_from(file.bytes.len())?,
                    mime: file.mime.map(Into::into),
                    caption: file.caption.into(),
                },
                &file.bytes,
                reserve,
            )
            .await;
            #[cfg(not(unix))]
            bail!("External Telegram projection requires Unix");
        }
        let field = file_field(file.name);
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
                    Some(TelegramError {
                        retry_after: Some(seconds),
                        ..
                    }) => Delivery::CoolingDown(*seconds),
                    Some(response) if response.status.is_client_error() => Delivery::Rejected,
                    _ => Delivery::Unconfirmed,
                })
            }
        }
    }
}

fn file_field(name: &str) -> &'static str {
    let extension = Path::new(name)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    match extension.as_str() {
        "png" | "jpg" | "jpeg" | "webp" => "photo",
        "mp3" | "wav" | "m4a" | "ogg" => "audio",
        "mp4" | "mov" | "webm" => "video",
        _ => "document",
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
    let mut offset = gateway.next_offset().await?;
    tokio::pin!(shutdown);

    loop {
        offset = tokio::select! {
            _ = &mut shutdown => {
                notify(Lifecycle::Stopped).await;
                return Ok(());
            }
            offset = gateway.before_poll(offset) => offset?,
        };
        tokio::select! {
            _ = &mut shutdown => {
                notify(Lifecycle::Stopped).await;
                return Ok(());
            }
            result = client.get_updates(offset, timeout_seconds) => {
                let delay = match result {
                    Ok(updates) => {
                        for update in updates {
                            offset = gateway.accept(update).await?;
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

pub(crate) const INGRESS_FRAME_LIMIT: u64 = 1_048_832;

#[derive(Serialize, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum IngressRequest {
    Ready { bot_id: i64, identity: Option<User> },
    ProjectionReady { bot_id: i64 },
    Admit { bot_id: i64, update: Box<Update> },
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum IngressReply {
    Ready {
        next_offset: Option<i64>,
        menu: Vec<BotCommand>,
        identified: bool,
    },
    Accepted {
        next_offset: Option<i64>,
    },
}

#[cfg(unix)]
struct RemoteGateway<'a> {
    socket: &'a Path,
    identity: User,
    initial_offset: Option<i64>,
}

#[cfg(unix)]
impl RemoteGateway<'_> {
    async fn request(&self, selected: IngressRequest) -> Result<IngressReply> {
        let reply = crate::control_client::request(
            self.socket,
            serde_json::json!({"telegram_ingress": selected}),
        )
        .await?;
        anyhow::ensure!(
            reply["ok"] == true,
            "Gateway did not acknowledge the selected Telegram ingress operation"
        );
        Ok(serde_json::from_value(reply["result"].clone())?)
    }

    async fn ready(&self, identify: bool) -> Result<IngressReply> {
        self.request(IngressRequest::Ready {
            bot_id: self.identity.id,
            identity: identify.then(|| self.identity.clone()),
        })
        .await
    }

    async fn projection_ready(&self) -> Result<Option<i64>> {
        match self
            .request(IngressRequest::ProjectionReady {
                bot_id: self.identity.id,
            })
            .await?
        {
            IngressReply::Accepted { next_offset } => Ok(next_offset),
            _ => bail!("Gateway did not acknowledge Telegram projection readiness"),
        }
    }
}

#[cfg(unix)]
impl GatewayIngress for RemoteGateway<'_> {
    async fn next_offset(&self) -> Result<Option<i64>> {
        Ok(self.initial_offset)
    }

    async fn before_poll(&self, _offset: Option<i64>) -> Result<Option<i64>> {
        match self.ready(false).await? {
            IngressReply::Ready {
                identified: true,
                next_offset,
                ..
            } => Ok(next_offset),
            IngressReply::Ready {
                identified: false, ..
            } => {
                let IngressReply::Ready {
                    identified: true, ..
                } = self.ready(true).await?
                else {
                    bail!("Gateway did not confirm Telegram re-identification");
                };
                self.projection_ready().await
            }
            _ => bail!("Gateway returned an unexpected Telegram readiness response"),
        }
    }

    async fn accept(&mut self, update: Update) -> Result<Option<i64>> {
        let reply = self
            .request(IngressRequest::Admit {
                bot_id: self.identity.id,
                update: Box::new(update),
            })
            .await?;
        match reply {
            IngressReply::Accepted { next_offset } => Ok(next_offset),
            _ => bail!("Gateway returned an unexpected Telegram ingress response"),
        }
    }
}

#[cfg(unix)]
pub(crate) async fn run_external(config: crate::config::TelegramPollConfig) -> Result<()> {
    anyhow::ensure!(
        config.telegram.enabled && config.telegram.external_polling,
        "External Telegram polling is not selected"
    );
    let socket = &config.session_control.socket_path;
    let client = client(&config.telegram)?;
    let identity = client.get_me().await?;
    let mut gateway = RemoteGateway {
        socket,
        identity,
        initial_offset: None,
    };
    let IngressReply::Ready {
        menu,
        identified: true,
        ..
    } = gateway.ready(true).await?
    else {
        bail!("Gateway returned an unexpected Telegram readiness response");
    };
    let listener = projection::bind(socket).await?;
    gateway.initial_offset = gateway.projection_ready().await?;
    let bot_id = gateway.identity.id;
    tokio::select! {
        result = projection::serve(listener, client.clone(), bot_id) => result,
        result = poll(
            &client,
            &menu,
            config.poll_timeout_seconds,
            &mut gateway,
            crate::app::shutdown_signal(tokio_util::sync::CancellationToken::new()),
            |_| async {},
        ) => result,
    }
}

#[cfg(not(unix))]
pub(crate) async fn run_external(_config: crate::config::TelegramPollConfig) -> Result<()> {
    bail!("External Telegram polling requires the owner-local Unix socket")
}
