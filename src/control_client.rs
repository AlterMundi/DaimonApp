//! Connect-only owner-local client. It starts no listener or model turn.
use anyhow::{Context, Result, bail};
#[cfg(unix)]
pub async fn run(config: &crate::config::Config, command: &str) -> Result<()> {
    let cfg = config
        .session_control
        .as_ref()
        .context("No receiving session_control configured")?;
    exchange(&cfg.socket_path, command).await
}

/// Read the owner-only turn credential without putting its token in argv/output.
#[cfg(unix)]
pub async fn controller(path: &std::path::Path, payload: &str) -> Result<()> {
    use std::{
        io::Read,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
    };
    if payload.len() > 16000 {
        bail!("Controller arguments exceed bound");
    }
    let mut envelope: serde_json::Value = serde_json::from_str(payload)?;
    let object = envelope
        .as_object_mut()
        .context("Controller envelope required")?;
    if object.len() != 2
        || !object.get("operation").is_some_and(|v| v.is_string())
        || !object.get("arguments").is_some_and(|v| v.is_object())
    {
        bail!("Expected operation and arguments only");
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
        || meta.len() > 16384
    {
        bail!("Unsafe live controller credential");
    }
    let mut bytes = Vec::new();
    file.take(16385).read_to_end(&mut bytes)?;
    let access: crate::app::controller::Access = serde_json::from_slice(&bytes)?;
    if access.schema != "telecodex.turn-controller/v1" || access.token.len() != 64 {
        bail!("Unsupported live controller credential");
    }
    object.insert("token".into(), serde_json::json!(access.token));
    exchange(&access.socket, &format!("controller {}", envelope)).await
}

#[cfg(unix)]
async fn exchange(path: &std::path::Path, command: &str) -> Result<()> {
    let nonce = uuid::Uuid::now_v7().to_string();
    // A selected native run includes bounded Matrix host and worker calls.
    let timeout = if [
        "matrix claude run ",
        "matrix goose run ",
        "matrix antigravity run ",
    ]
    .iter()
    .any(|prefix| command.starts_with(prefix))
    {
        320
    } else {
        30
    };
    let reply = request_with_timeout(
        path,
        serde_json::json!({"command": command, "nonce": nonce}),
        timeout,
    )
    .await?;
    println!("{}", serde_json::to_string_pretty(&reply)?);
    if reply["ok"] != true {
        bail!("Receiving control did not confirm success");
    }
    if reply["result"]["success"] == false {
        bail!("Selected controller operation was refused");
    }
    Ok(())
}

#[cfg(unix)]
pub(crate) async fn request(
    path: &std::path::Path,
    request: serde_json::Value,
) -> Result<serde_json::Value> {
    request_with_timeout(path, request, 30).await
}

#[cfg(unix)]
async fn request_with_timeout(
    path: &std::path::Path,
    request: serde_json::Value,
    timeout: u64,
) -> Result<serde_json::Value> {
    use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
    tokio::time::timeout(std::time::Duration::from_secs(timeout), async {
        let mut stream = connect_owner(path).await?;
        let mut bytes = serde_json::to_vec(&request)?;
        if bytes.len() as u64 >= crate::tele_daimon::INGRESS_FRAME_LIMIT {
            bail!("Control request exceeds receiving bound");
        }
        bytes.push(b'\n');
        stream.write_all(&bytes).await?;
        let mut bytes = Vec::new();
        BufReader::new(stream.take(262145))
            .read_until(b'\n', &mut bytes)
            .await?;
        if bytes.is_empty() {
            return Err(std::io::Error::from(std::io::ErrorKind::UnexpectedEof).into());
        }
        if bytes.len() > 262144 {
            bail!("Control reply exceeds bound");
        }
        Ok(serde_json::from_slice(&bytes)?)
    })
    .await
    .context("Control acceptance unavailable; inspect the retained operation before retrying")?
}
#[cfg(unix)]
pub(crate) async fn connect_owner(path: &std::path::Path) -> Result<tokio::net::UnixStream> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt};
    let uid = unsafe { libc::geteuid() };
    let meta = std::fs::symlink_metadata(path)?;
    if !meta.file_type().is_socket() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
        bail!("Unsafe receiving owner socket");
    }
    let stream = tokio::net::UnixStream::connect(path).await?;
    if stream.peer_cred()?.uid() != uid {
        bail!("Receiving socket peer owner mismatch");
    }
    Ok(stream)
}

#[cfg(unix)]
pub(crate) async fn bind_owner(path: &std::path::Path) -> Result<tokio::net::UnixListener> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt};
    use tokio::net::{UnixListener, UnixStream};
    let uid = unsafe { libc::geteuid() };
    let parent = path.parent().context("Owner socket parent missing")?;
    let meta = std::fs::symlink_metadata(parent)?;
    if !meta.is_dir() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
        bail!("Owner socket needs an owner-only directory");
    }
    if let Ok(old) = std::fs::symlink_metadata(path) {
        if !old.file_type().is_socket() || old.uid() != uid {
            bail!("Refusing to replace an unsafe owner socket path");
        }
        if UnixStream::connect(path).await.is_ok() {
            bail!("A listener already owns this path");
        }
        std::fs::remove_file(path)?;
    }
    let listener = UnixListener::bind(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(listener)
}

#[cfg(not(unix))]
pub async fn run(_config: &crate::config::Config, _command: &str) -> Result<()> {
    bail!("Owner-local session control requires Unix")
}
#[cfg(not(unix))]
pub async fn controller(_path: &std::path::Path, _payload: &str) -> Result<()> {
    bail!("Live turn controller requires Unix")
}
