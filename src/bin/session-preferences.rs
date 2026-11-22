//! Owner-local preference adapter; shares the canonical Store implementation.
use anyhow::{Context, Result};
use rusqlite::{Connection, OptionalExtension, params};
use std::path::{Path, PathBuf};
fn now_string() -> String {
    chrono::Utc::now().to_rfc3339()
}
#[path = "../store/session_preferences.rs"]
mod session_preferences;
fn main() -> Result<()> {
    use std::{
        io::Read,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
    };
    let args: Vec<_> = std::env::args().collect();
    anyhow::ensure!(
        args.len() == 4,
        "Usage: session-preferences CONFIG inspect|set JSON"
    );
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&args[1])?;
    let meta = file.metadata()?;
    anyhow::ensure!(
        meta.is_file()
            && meta.uid() == unsafe { libc::geteuid() }
            && meta.mode() & 0o077 == 0
            && meta.len() <= 65536,
        "Owner-only receiving config required"
    );
    let mut raw = String::new();
    file.take(65537).read_to_string(&mut raw)?;
    let config: toml::Value = toml::from_str(&raw)?;
    let human = config
        .get("session_control")
        .and_then(|v| v.get("human_id"))
        .and_then(toml::Value::as_integer)
        .context("Configured control owner required")?;
    let db = PathBuf::from(
        config
            .get("db_path")
            .and_then(toml::Value::as_str)
            .context("Explicit receiving database required")?,
    );
    let value = session_preferences::owner_local(&db, human, &args[2], &args[3])?;
    println!("{}", serde_json::to_string_pretty(&value)?);
    Ok(())
}
