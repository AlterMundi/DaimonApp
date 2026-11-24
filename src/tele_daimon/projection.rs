//! One owner-local Telegram operation per connection.
use super::{Delivery, Projection, file_field};
use crate::{
    control_client,
    render::render_markdown_to_html,
    telegram::{Message, SendMessage, TelegramError},
};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::{
    borrow::Cow,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{UnixListener, UnixStream},
    sync::Semaphore,
    time::timeout,
};

mod download;
pub(crate) use download::Download;

const MAX_METADATA: u32 = 131_072;
const MAX_JSON_RESULT: u32 = 4 * 1024 * 1024;
const MAX_FILE: usize = 256 * 1024 * 1024;
const OPEN: Duration = Duration::from_secs(30);
const WAIT: Duration = Duration::from_secs(180);
const RECEIPT: Duration = Duration::from_secs(150);

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Offer<'a> {
    bot: i64,
    chat: i64,
    topic: Option<i64>,
    #[serde(borrow)]
    payload: Payload<'a>,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Payload<'a> {
    Json {
        method: JsonMethod,
        document: Option<serde_json::Value>,
    },
    Download {
        #[serde(borrow)]
        file_id: Cow<'a, str>,
        max_bytes: Option<u64>,
    },
    Upload {
        #[serde(borrow)]
        file: Upload<'a>,
    },
    Text {
        #[serde(borrow)]
        markdown: Cow<'a, str>,
    },
    File {
        #[serde(borrow)]
        name: Cow<'a, str>,
        size: u32,
        #[serde(borrow)]
        mime: Option<Cow<'a, str>>,
        #[serde(borrow)]
        caption: Cow<'a, str>,
    },
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Upload<'a> {
    pub field: UploadKind,
    pub size: u64,
    #[serde(borrow)]
    pub name: Cow<'a, str>,
    #[serde(borrow)]
    pub mime: Option<Cow<'a, str>>,
}

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum UploadKind {
    Photo,
    Audio,
    Video,
    Document,
}

impl UploadKind {
    pub(crate) fn from_field(field: &str) -> Result<Self> {
        match field {
            "photo" => Ok(Self::Photo),
            "audio" => Ok(Self::Audio),
            "video" => Ok(Self::Video),
            "document" => Ok(Self::Document),
            _ => anyhow::bail!("Unsupported Telegram upload"),
        }
    }

    pub(crate) fn field(self) -> &'static str {
        match self {
            Self::Photo => "photo",
            Self::Audio => "audio",
            Self::Video => "video",
            Self::Document => "document",
        }
    }

    pub(crate) fn method(self) -> &'static str {
        match self {
            Self::Photo => "sendPhoto",
            Self::Audio => "sendAudio",
            Self::Video => "sendVideo",
            Self::Document => "sendDocument",
        }
    }
}

#[derive(Clone, Copy, Serialize, Deserialize)]
pub(crate) enum JsonMethod {
    SendMessage,
    SendChatAction,
    EditMessageText,
    AnswerCallbackQuery,
    CreateForumTopic,
    CloseForumTopic,
    DeleteForumTopic,
    EditForumTopic,
    GetForumTopicIconStickers,
    SendMessageDraft,
}

impl JsonMethod {
    const ALL: [Self; 10] = [
        Self::SendMessage,
        Self::SendChatAction,
        Self::EditMessageText,
        Self::AnswerCallbackQuery,
        Self::CreateForumTopic,
        Self::CloseForumTopic,
        Self::DeleteForumTopic,
        Self::EditForumTopic,
        Self::GetForumTopicIconStickers,
        Self::SendMessageDraft,
    ];

    pub(crate) fn from_api(method: &str) -> Option<Self> {
        Self::ALL
            .into_iter()
            .find(|candidate| candidate.api() == method)
    }

    fn api(self) -> &'static str {
        match self {
            Self::SendMessage => "sendMessage",
            Self::SendChatAction => "sendChatAction",
            Self::EditMessageText => "editMessageText",
            Self::AnswerCallbackQuery => "answerCallbackQuery",
            Self::CreateForumTopic => "createForumTopic",
            Self::CloseForumTopic => "closeForumTopic",
            Self::DeleteForumTopic => "deleteForumTopic",
            Self::EditForumTopic => "editForumTopic",
            Self::GetForumTopicIconStickers => "getForumTopicIconStickers",
            Self::SendMessageDraft => "sendMessageDraft",
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case", deny_unknown_fields)]
enum JsonResult {
    Confirmed {
        value: serde_json::Value,
    },
    Provider {
        status: u16,
        description: String,
        retry_after: Option<u64>,
    },
    Unconfirmed,
}

fn socket_path(owner: &Path) -> PathBuf {
    let mut path = owner.as_os_str().to_owned();
    path.push(".projection");
    path.into()
}

pub(super) async fn bind(owner: &Path) -> Result<UnixListener> {
    control_client::bind_owner(&socket_path(owner)).await
}

async fn open_offer(owner: &Path, offer: &Offer<'_>, bytes: &[u8]) -> Result<UnixStream> {
    timeout(OPEN, async {
        let mut stream = control_client::connect_owner(&socket_path(owner)).await?;
        let metadata = serde_json::to_vec(offer)?;
        ensure!(
            metadata.len() <= MAX_METADATA as usize && bytes.len() <= MAX_FILE,
            "Telegram projection exceeds transfer bounds"
        );
        stream.write_u32(metadata.len() as u32).await?;
        stream.write_all(&metadata).await?;
        stream.write_all(bytes).await?;
        Ok::<_, anyhow::Error>(stream)
    })
    .await
    .context("Telegram projection connection timed out")?
}

pub(crate) async fn json(
    owner: &Path,
    bot: i64,
    method: JsonMethod,
    document: Option<serde_json::Value>,
    authorize: impl FnOnce() -> Result<()>,
) -> Result<serde_json::Value> {
    let mut stream = open_offer(
        owner,
        &Offer {
            bot,
            chat: 0,
            topic: None,
            payload: Payload::Json { method, document },
        },
        &[],
    )
    .await?;
    ensure!(
        timeout(OPEN, stream.read_u8()).await?? == 1,
        "TeleDaimon did not prepare the operation"
    );
    authorize()?;
    timeout(OPEN, async {
        stream.write_u8(1).await?;
        read_result(&mut stream).await
    })
    .await
    .context("Telegram operation outcome unconfirmed")?
}

async fn read_result(input: &mut (impl tokio::io::AsyncRead + Unpin)) -> Result<serde_json::Value> {
    let size = input.read_u32().await?;
    ensure!(
        size <= MAX_JSON_RESULT,
        "Telegram response exceeds transport bounds"
    );
    let mut bytes = vec![0; size as usize];
    input.read_exact(&mut bytes).await?;
    // Do not include a reflected body fragment in a protocol error.
    let result: JsonResult = serde_json::from_slice(&bytes)
        .map_err(|_| anyhow::anyhow!("Malformed Telegram operation response"))?;
    match result {
        JsonResult::Confirmed { value } => Ok(value),
        JsonResult::Provider {
            status,
            description,
            retry_after,
        } => Err(TelegramError {
            status: reqwest::StatusCode::from_u16(status)?,
            description,
            retry_after,
        }
        .into()),
        JsonResult::Unconfirmed => anyhow::bail!("Telegram operation outcome unconfirmed"),
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn upload(
    owner: &Path,
    bot: i64,
    chat: i64,
    topic: Option<i64>,
    upload: Upload<'_>,
    file: tokio::fs::File,
    authorize: impl FnOnce() -> Result<()>,
) -> Result<Message> {
    let size = upload.size;
    let mut stream = open_offer(
        owner,
        &Offer {
            bot,
            chat,
            topic,
            payload: Payload::Upload { file: upload },
        },
        &[],
    )
    .await?;
    ensure!(
        timeout(WAIT, stream.read_u8()).await?? == 1,
        "TeleDaimon did not prepare the upload"
    );
    authorize()?;
    timeout(RECEIPT, async {
        stream.write_u8(1).await?;
        let (mut input, mut output) = stream.into_split();
        let transfer = async {
            let copied = tokio::io::copy(&mut file.take(size), &mut output).await;
            let shutdown = output.shutdown().await;
            let count = copied?;
            shutdown?;
            ensure!(
                count == size,
                "Telegram upload source ended before its declared size"
            );
            Ok::<_, anyhow::Error>(())
        };
        let (transfer, receipt) = tokio::join!(transfer, read_result(&mut input));
        let receipt = receipt?;
        transfer?;
        serde_json::from_value(receipt)
            .map_err(|_| anyhow::anyhow!("Malformed Telegram upload receipt"))
    })
    .await
    .context("Telegram upload outcome unconfirmed")?
}

pub(super) async fn send(
    owner: &Path,
    projection: &Projection<'_>,
    bot: i64,
    payload: Payload<'_>,
    bytes: &[u8],
    reserve: impl FnOnce() -> Result<bool>,
) -> Result<Delivery> {
    let offer = Offer {
        bot,
        chat: projection.chat,
        topic: projection.topic,
        payload,
    };
    let mut stream = open_offer(owner, &offer, bytes).await?;
    timeout(WAIT, async {
        ensure!(
            stream.read_u8().await? == 1,
            "TeleDaimon did not prepare the projection"
        );
        // Preserve the original cross-operation Bot API limiter during migration.
        projection.client.wait_projection(projection.chat).await?;
        Ok::<_, anyhow::Error>(())
    })
    .await
    .context("Telegram projection was not prepared in time")??;
    if !reserve()? {
        return Ok(Delivery::Unsent);
    }
    // The journal owns the send now. Socket loss cannot prove that Telegram
    // did not receive it, including loss during the one-byte commit.
    let result = timeout(RECEIPT, async {
        stream.write_u8(1).await?;
        let size = stream.read_u32().await?;
        ensure!(size <= 256, "Invalid Telegram receipt");
        let mut receipt = vec![0; size as usize];
        stream.read_exact(&mut receipt).await?;
        Ok::<Delivery, anyhow::Error>(serde_json::from_slice(&receipt)?)
    })
    .await;
    match result {
        Ok(Ok(delivery @ Delivery::CoolingDown(seconds))) => {
            projection
                .client
                .projection_backoff(projection.chat, seconds)
                .await;
            Ok(delivery)
        }
        Ok(Ok(delivery @ Delivery::Acknowledged(id))) if id > 0 => Ok(delivery),
        Ok(Ok(Delivery::Rejected)) => Ok(Delivery::Rejected),
        _ => Ok(Delivery::Unconfirmed),
    }
}

pub(super) async fn serve(
    listener: UnixListener,
    client: crate::telegram::TelegramClient,
    bot: i64,
) -> Result<()> {
    let uid = unsafe { libc::geteuid() };
    let connections = Arc::new(Semaphore::new(16));
    let files = Arc::new(Semaphore::new(2));
    let downloads = Arc::new(Semaphore::new(2));
    loop {
        let permit = connections.clone().acquire_owned().await?;
        let (stream, _) = listener.accept().await?;
        if !stream.peer_cred().is_ok_and(|peer| peer.uid() == uid) {
            continue;
        }
        let client = client.clone();
        let files = files.clone();
        let downloads = downloads.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let _ = receive(stream, &client, bot, &files, &downloads).await;
        });
    }
}

async fn receive(
    mut stream: UnixStream,
    client: &crate::telegram::TelegramClient,
    bot: i64,
    files: &Semaphore,
    downloads: &Semaphore,
) -> Result<()> {
    let metadata = timeout(OPEN, async {
        let size = stream.read_u32().await?;
        ensure!(size <= MAX_METADATA, "Invalid Telegram projection metadata");
        let mut metadata = vec![0; size as usize];
        stream.read_exact(&mut metadata).await?;
        Ok::<_, anyhow::Error>(metadata)
    })
    .await??;
    let offer: Offer<'_> = serde_json::from_slice(&metadata)?;
    ensure!(
        bot > 0 && offer.bot == bot,
        "Telegram projection bot mismatch"
    );
    if let Payload::Json { method, document } = offer.payload {
        return receive_json(stream, client, method, document).await;
    }
    if let Payload::Download { file_id, max_bytes } = offer.payload {
        return download::receive(stream, client, &file_id, max_bytes, downloads).await;
    }
    if let Payload::Upload { file } = offer.payload {
        let _permit = timeout(WAIT, files.acquire()).await??;
        timeout(WAIT, async {
            client.wait_projection(offer.chat).await?;
            stream.write_u8(1).await?;
            ensure!(
                stream.read_u8().await? == 1,
                "Telegram upload was not authorized"
            );
            Ok::<_, anyhow::Error>(())
        })
        .await??;
        let (input, mut output) = stream.into_split();
        let result = client
            .upload_stream(offer.chat, offer.topic, file, input)
            .await
            .and_then(|message| Ok(client.redact_relay_value(serde_json::to_value(message)?)));
        return write_result(&mut output, result).await;
    }
    let mut file_permit = None;
    let mut bytes = Vec::new();
    if let Payload::File { size, .. } = offer.payload {
        let size = size as usize;
        ensure!(size <= MAX_FILE, "Telegram projection exceeds file bound");
        file_permit = Some(files.try_acquire()?);
        bytes.resize(size, 0);
        timeout(OPEN, stream.read_exact(&mut bytes)).await??;
    }
    timeout(WAIT, async {
        client.wait_projection(offer.chat).await?;
        stream.write_u8(1).await?;
        ensure!(
            stream.read_u8().await? == 1,
            "Projection was not authorized"
        );
        Ok::<_, anyhow::Error>(())
    })
    .await??;

    let result = match offer.payload {
        Payload::Json { .. } | Payload::Upload { .. } | Payload::Download { .. } => {
            unreachable!("Direct operations use a typed result")
        }
        Payload::Text { markdown } => {
            client
                .projection_text(
                    offer.chat,
                    SendMessage::html(offer.chat, offer.topic, render_markdown_to_html(&markdown)),
                )
                .await
        }
        Payload::File {
            name,
            mime,
            caption,
            ..
        } => {
            client
                .projection_file(
                    offer.chat,
                    offer.topic,
                    file_field(&name),
                    bytes,
                    &name,
                    mime.as_deref(),
                    Some(&caption),
                )
                .await
        }
    };
    drop(file_permit);
    let receipt = Projection {
        client,
        chat: offer.chat,
        topic: offer.topic,
        remote: None,
    }
    .receipt(true, result.map(Some))?;
    let receipt = serde_json::to_vec(&receipt)?;
    timeout(OPEN, async {
        stream.write_u32(receipt.len() as u32).await?;
        stream.write_all(&receipt).await
    })
    .await??;
    Ok(())
}

async fn receive_json(
    mut stream: UnixStream,
    client: &crate::telegram::TelegramClient,
    method: JsonMethod,
    document: Option<serde_json::Value>,
) -> Result<()> {
    ensure!(
        document.as_ref().is_none_or(serde_json::Value::is_object),
        "Telegram operation requires a JSON object"
    );
    timeout(OPEN, async {
        stream.write_u8(1).await?;
        ensure!(
            stream.read_u8().await? == 1,
            "Telegram operation was not authorized"
        );
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    let result = client.direct_json(method.api(), document.as_ref()).await;
    if let Err(error) = &result
        && let Some(provider) = error.downcast_ref::<TelegramError>()
        && let Some(seconds) = provider.retry_after
        && let Some(chat) = document
            .as_ref()
            .and_then(|value| value["chat_id"].as_i64())
    {
        client.projection_backoff(chat, seconds).await;
    }
    write_result(&mut stream, result).await
}

async fn write_result(
    output: &mut (impl tokio::io::AsyncWrite + Unpin),
    result: Result<serde_json::Value>,
) -> Result<()> {
    let result = match result {
        Ok(value) => JsonResult::Confirmed { value },
        Err(error) => match error.downcast_ref::<TelegramError>() {
            Some(provider) => JsonResult::Provider {
                status: provider.status.as_u16(),
                description: provider.description.chars().take(1024).collect(),
                retry_after: provider.retry_after,
            },
            None => JsonResult::Unconfirmed,
        },
    };
    let bytes = serde_json::to_vec(&result)?;
    ensure!(
        bytes.len() <= MAX_JSON_RESULT as usize,
        "Telegram response exceeds transport bounds"
    );
    timeout(OPEN, async {
        output.write_u32(bytes.len() as u32).await?;
        output.write_all(&bytes).await
    })
    .await??;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::telegram::{PublicationRetired, TelegramClient, tests::serve_api};
    use serde_json::json;

    #[tokio::test]
    async fn direct_relay_checks_gateway_permission_and_preserves_a_known_provider_refusal() {
        let root = tempfile::tempdir().unwrap();
        let socket = root.path().join("control.sock");
        let (api, observed) = serve_api(vec![(
            429,
            json!({"ok": false, "description": "Wait before retrying adapter-token",
                "parameters": {"retry_after": 7}}),
        )]);
        let listener = bind(&socket).await.unwrap();
        let server = tokio::spawn(serve(
            listener,
            TelegramClient::new("adapter-token".into(), api),
            101,
        ));
        let gateway = TelegramClient::new("gateway-token".into(), "http://127.0.0.1:1".into())
            .with_direct_relay(socket, 101);
        let retired = gateway.clone().with_publication_guard(|| Ok(false));
        let error = retired
            .send_message(SendMessage::html(100, Some(2), "Retired".into()))
            .await
            .unwrap_err();
        assert!(error.is::<PublicationRetired>());

        let error = gateway
            .send_message(SendMessage::html(101, Some(3), "Authorized".into()))
            .await
            .unwrap_err();
        let provider = error.downcast_ref::<TelegramError>().unwrap();
        assert_eq!(provider.status, reqwest::StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(provider.retry_after, Some(7));
        assert!(!provider.description.contains("adapter-token"));
        let requests = observed.join().unwrap();
        assert_eq!(requests.len(), 1);
        assert!(requests[0].0.contains("/sendMessage "));
        assert_eq!(requests[0].1["text"], "Authorized");
        assert_eq!(requests[0].1["message_thread_id"], 3);
        server.abort();
    }

    #[tokio::test]
    async fn truncated_file_cannot_be_confirmed_even_if_a_receipt_arrives() {
        let root = tempfile::tempdir().unwrap();
        let socket = root.path().join("control.sock");
        let listener = bind(&socket).await.unwrap();
        let transfer = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let size = stream.read_u32().await.unwrap();
            let mut metadata = vec![0; size as usize];
            stream.read_exact(&mut metadata).await.unwrap();
            let offer: Offer<'_> = serde_json::from_slice(&metadata).unwrap();
            assert!(matches!(offer.payload, Payload::Upload { file } if file.size == 8));
            stream.write_u8(1).await.unwrap();
            assert_eq!(stream.read_u8().await.unwrap(), 1);
            let mut received = Vec::new();
            stream.read_to_end(&mut received).await.unwrap();
            assert_eq!(received, b"short");
            write_result(
                &mut stream,
                Ok(json!({
                    "message_id": 123, "chat": {"id": 100, "type": "private"},
                    "message_thread_id": 2
                })),
            )
            .await
            .unwrap();
        });
        let file = root.path().join("truncated.txt");
        tokio::fs::write(&file, b"short").await.unwrap();
        let result = timeout(
            OPEN,
            upload(
                &socket,
                101,
                100,
                Some(2),
                Upload {
                    field: UploadKind::Document,
                    size: 8,
                    name: "truncated.txt".into(),
                    mime: None,
                },
                tokio::fs::File::open(file).await.unwrap(),
                || Ok(()),
            ),
        )
        .await
        .unwrap();
        assert!(result.unwrap_err().to_string().contains("declared size"));
        transfer.await.unwrap();
    }
}
