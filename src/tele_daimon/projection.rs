//! One retained Telegram projection per owner-local connection.
use super::{Delivery, Projection, file_field};
use crate::{control_client, render::render_markdown_to_html, telegram::SendMessage};
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

const MAX_METADATA: u32 = 131_072;
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

fn socket_path(owner: &Path) -> PathBuf {
    let mut path = owner.as_os_str().to_owned();
    path.push(".projection");
    path.into()
}

pub(super) async fn bind(owner: &Path) -> Result<UnixListener> {
    control_client::bind_owner(&socket_path(owner)).await
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
    let mut stream = timeout(OPEN, async {
        let mut stream = control_client::connect_owner(&socket_path(owner)).await?;
        let metadata = serde_json::to_vec(&offer)?;
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
    .context("Telegram projection connection timed out")??;
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
    loop {
        let permit = connections.clone().acquire_owned().await?;
        let (stream, _) = listener.accept().await?;
        if !stream.peer_cred().is_ok_and(|peer| peer.uid() == uid) {
            continue;
        }
        let client = client.clone();
        let files = files.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let _ = receive(stream, &client, bot, &files).await;
        });
    }
}

async fn receive(
    mut stream: UnixStream,
    client: &crate::telegram::TelegramClient,
    bot: i64,
    files: &Semaphore,
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
