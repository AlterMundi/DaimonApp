//! Telegram file IDs and bounded chunks cross the adapter socket. The provider
//! path stays with the adapter and the destination stays with Gateway.
use super::{OPEN, Offer, Payload, open_offer, read_result, write_result};
use crate::telegram::{AttachmentTooLarge, TELEGRAM_DOWNLOAD_TIMEOUT, TelegramClient};
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::{path::Path, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWrite, AsyncWriteExt, duplex},
    net::UnixStream,
    sync::Semaphore,
    time::timeout,
};

const CHUNK: usize = 64 * 1024;
const OVER_LIMIT: u32 = u32::MAX;
const TRANSFER: Duration = Duration::from_secs(630);

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    extension: String,
    size: Option<u64>,
}

pub(crate) struct Download {
    stream: UnixStream,
    metadata: Metadata,
    max_bytes: Option<u64>,
}

impl Download {
    pub(crate) async fn open(
        owner: &Path,
        bot: i64,
        file_id: &str,
        max_bytes: Option<u64>,
        authorize: impl FnOnce() -> Result<()>,
    ) -> Result<Self> {
        let mut stream = open_offer(
            owner,
            &Offer {
                bot,
                chat: 0,
                topic: None,
                payload: Payload::Download {
                    file_id: file_id.into(),
                    max_bytes,
                },
            },
            &[],
        )
        .await?;
        ensure!(
            timeout(OPEN, stream.read_u8()).await?? == 1,
            "TeleDaimon did not prepare the download"
        );
        authorize()?;
        stream.write_u8(1).await?;
        let value = timeout(TRANSFER, read_result(&mut stream))
            .await
            .context("Telegram attachment metadata timed out")??;
        let metadata: Metadata = serde_json::from_value(value)
            .map_err(|_| anyhow::anyhow!("Malformed Telegram attachment metadata"))?;
        if max_bytes
            .zip(metadata.size)
            .is_some_and(|(limit, size)| size > limit)
        {
            return Err(AttachmentTooLarge.into());
        }
        ensure!(
            !metadata.extension.is_empty()
                && metadata.extension.len() <= 64
                && metadata
                    .extension
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric()),
            "Invalid Telegram attachment extension"
        );
        Ok(Self {
            stream,
            metadata,
            max_bytes,
        })
    }

    pub(crate) fn extension(&self) -> &str {
        &self.metadata.extension
    }

    pub(crate) async fn copy_into(
        mut self,
        output: &mut (impl AsyncWrite + Unpin),
        authorize: impl FnOnce() -> Result<()>,
    ) -> Result<()> {
        authorize()?;
        timeout(TRANSFER, async {
            self.stream.write_u8(1).await?;
            let mut count = 0u64;
            let mut buffer = vec![0; CHUNK];
            loop {
                let size = self.stream.read_u32().await?;
                if size == 0 {
                    let complete = self.stream.read_u64().await?;
                    ensure!(
                        complete == count && self.metadata.size.is_none_or(|size| size == count),
                        "Incomplete Telegram file download"
                    );
                    return Ok(());
                }
                if size == OVER_LIMIT {
                    return Err(AttachmentTooLarge.into());
                }
                ensure!(
                    size as usize <= CHUNK,
                    "Telegram chunk exceeds transport bounds"
                );
                count = count
                    .checked_add(size as u64)
                    .context("Telegram attachment size overflow")?;
                if self.max_bytes.is_some_and(|limit| count > limit) {
                    return Err(AttachmentTooLarge.into());
                }
                ensure!(
                    self.metadata.size.is_none_or(|expected| count <= expected),
                    "Telegram attachment exceeds the declared length"
                );
                let chunk = &mut buffer[..size as usize];
                self.stream.read_exact(chunk).await?;
                output.write_all(chunk).await?;
            }
        })
        .await
        .context("Telegram attachment transfer timed out")?
    }
}

pub(super) async fn receive(
    mut stream: UnixStream,
    client: &TelegramClient,
    file_id: &str,
    max_bytes: Option<u64>,
    downloads: &Semaphore,
) -> Result<()> {
    ensure!(
        !file_id.is_empty() && file_id.len() <= 8192,
        "Invalid Telegram file ID"
    );
    let _permit = timeout(OPEN, downloads.acquire()).await??;
    timeout(OPEN, authorize(&mut stream)).await??;
    let file = match client.get_file(file_id).await {
        Ok(file) => file,
        Err(error) => return write_result(&mut stream, Err(error)).await,
    };
    let source = file.file_path.context("Telegram file path missing")?;
    let extension = client.attachment_relay_extension(&source);
    write_result(
        &mut stream,
        Ok(serde_json::to_value(Metadata {
            extension: extension.into(),
            size: file.file_size,
        })?),
    )
    .await?;

    timeout(TRANSFER, async {
        ensure!(
            stream.read_u8().await? == 1,
            "Telegram download was not authorized"
        );
        let (mut writer, mut reader) = duplex(CHUNK);
        let transfer = async move {
            client
                .copy_attachment(
                    &source,
                    file.file_size,
                    TELEGRAM_DOWNLOAD_TIMEOUT,
                    max_bytes,
                    &mut writer,
                )
                .await
        };
        // The pump finishes its current frame when upstream fails. A terminal
        // marker can therefore never be mistaken for attachment bytes.
        let output = &mut stream;
        let pump = async move {
            let mut buffer = vec![0; CHUNK];
            loop {
                let count = reader.read(&mut buffer).await?;
                if count == 0 {
                    return Ok::<_, anyhow::Error>(());
                }
                output.write_u32(count as u32).await?;
                output.write_all(&buffer[..count]).await?;
            }
        };
        let (transfer, pump) = tokio::join!(transfer, pump);
        pump?;
        match transfer {
            Ok(count) => {
                stream.write_u32(0).await?;
                stream.write_u64(count).await?;
            }
            Err(error) if error.is::<AttachmentTooLarge>() => stream.write_u32(OVER_LIMIT).await?,
            Err(error) => return Err(error),
        }
        Ok(())
    })
    .await
    .context("Telegram download did not complete in time")?
}

async fn authorize(stream: &mut UnixStream) -> Result<()> {
    stream.write_u8(1).await?;
    ensure!(
        stream.read_u8().await? == 1,
        "Telegram file resolution was not authorized"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn gateway_publishes_only_a_complete_bounded_download() {
        let root = super::super::private_test_socket_dir();
        let owner = root.path().join("control.sock");
        let listener = super::super::bind(&owner).await.unwrap();
        let server = tokio::spawn(async move {
            for mode in ["short", "over_limit", "complete"] {
                let (mut socket, _) = listener.accept().await.unwrap();
                let size = socket.read_u32().await.unwrap();
                let mut offer = vec![0; size as usize];
                socket.read_exact(&mut offer).await.unwrap();
                let offer: Offer<'_> = serde_json::from_slice(&offer).unwrap();
                assert!(matches!(offer.payload,
                    Payload::Download { file_id, max_bytes: Some(5) } if file_id == mode));
                authorize(&mut socket).await.unwrap();
                let announced_size = (mode != "over_limit").then_some(5);
                write_result(
                    &mut socket,
                    Ok(json!({"extension": "txt", "size": announced_size})),
                )
                .await
                .unwrap();
                assert_eq!(socket.read_u8().await.unwrap(), 1);
                let bytes: &[u8] = match mode {
                    "short" => b"abc",
                    "over_limit" => b"abcdef",
                    _ => b"abcde",
                };
                socket.write_u32(bytes.len() as u32).await.unwrap();
                socket.write_all(bytes).await.unwrap();
                let _ = socket.write_u32(0).await;
                let _ = socket.write_u64(5).await;
            }
        });
        let gateway = TelegramClient::new_relay(owner, 101);
        for mode in ["short", "over_limit", "complete"] {
            let destination = root.path().join(mode);
            let result = gateway
                .save_attachment(mode, Some(5), |ext| {
                    assert_eq!(ext, "txt");
                    (destination.clone(), "attachment.txt".into())
                })
                .await;
            match mode {
                "short" => {
                    assert!(result.unwrap_err().to_string().contains("Incomplete"));
                    assert!(!destination.exists());
                }
                "over_limit" => {
                    assert!(result.unwrap_err().is::<AttachmentTooLarge>());
                    assert!(!destination.exists());
                }
                _ => {
                    assert_eq!(result.unwrap().0, destination);
                    assert_eq!(tokio::fs::read(&destination).await.unwrap(), b"abcde");
                }
            }
        }
        server.await.unwrap();
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 2);
    }
}
