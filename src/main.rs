mod app;
mod ascii;
mod backend;
mod codex;
mod codex_history;
mod commands;
mod config;
mod control_client;
mod files;
mod interaction;
mod limits;
mod models;
mod nexus;
mod render;
mod store;
mod telegram;
mod transcribe;
mod user_input;
mod visual;
mod voice;

use anyhow::Result;
use tokio::time::{Duration, sleep};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--controller") {
        if args.len() != 4 {
            anyhow::bail!("Usage: telecodex --controller TURN_ACCESS_FILE OPERATION_JSON");
        }
        return control_client::controller(std::path::Path::new(&args[2]), &args[3]).await;
    }
    if args.get(1).map(String::as_str) == Some("--control") {
        if owner_control_command(&args).is_none() {
            anyhow::bail!(
                "Usage: telecodex --control CONFIG stop all|status ID|resume ID; attach-active CHAT TOPIC NATIVE_THREAD NATIVE_TURN; presentation list|before DELIVERY_CURSOR NATIVE_CURSOR [MATRIX_CURSOR]|part SOURCE REVISION OFFSET; workflow status ID|recover ID REVISION; input submit|retry JSON|status UUID|list CURSOR; requests list CURSOR|detail ID OFFSET [REVISION]|decide JSON; matrix status UUID|return JSON; topics list DAYS|notices NATIVE_THREAD [AFTER]; heartbeat status|pause|resume GENERATION|select-review GENERATION CONTRACT_JSON|configure-resources GENERATION CONTRACT_JSON|renew-window GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS|renew-observation GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS [MAX_CHECKS]; observer observe #Topic [--retry]|summary #Topic|sources #Topic"
            );
        }
        let config = config::Config::load(args[2].clone().into())?;
        if args.get(3).map(String::as_str) == Some("matrix")
            && args.get(4).map(String::as_str) == Some("publication")
            && args.get(5).map(String::as_str) == Some("commit")
        {
            use std::io::Read;
            anyhow::ensure!(args.len() == 6, "Pass the exact publication JSON on stdin");
            let mut raw = String::new();
            std::io::stdin().take(65537).read_to_string(&mut raw)?;
            anyhow::ensure!(raw.len() <= 65536, "Publication request exceeds bound");
            return control_client::run(&config, &format!("matrix publication commit {raw}")).await;
        }
        let command = owner_control_command(&args).expect("validated control command");
        return control_client::run(&config, &command).await;
    }
    if args.get(1).map(String::as_str) == Some("--probe-native") {
        if !(args.len() == 4 || (args.len() == 5 && args[4] == "--create-thread-probes")) {
            anyhow::bail!(
                "Usage: telecodex --probe-native CODEX_BINARY CWD [--create-thread-probes]"
            );
        }
        let cwd = std::fs::canonicalize(&args[3])?;
        if !cwd.is_dir() {
            anyhow::bail!("native probe cwd must be a directory");
        }
        let result =
            codex::probe_native(std::path::Path::new(&args[2]), &cwd, args.len() == 5).await?;
        println!("{}", serde_json::to_string_pretty(&result)?);
        return Ok(());
    }
    let _ = dotenvy::dotenv();
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("telecodex=info,reqwest=warn")),
        )
        .with_target(false)
        .compact()
        .init();

    if let Some(delay_ms) = restart_delay_ms_from_env() {
        sleep(Duration::from_millis(delay_ms)).await;
    }

    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "telecodex.toml".to_string());
    let config = config::Config::load(config_path.into())?;
    let app = app::App::bootstrap(config).await?;
    app.run().await
}

fn restart_delay_ms_from_env() -> Option<u64> {
    std::env::var("TELECODEX_RESTART_DELAY_MS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
}

fn owner_control_command(args: &[String]) -> Option<String> {
    if args.len() < 5 {
        return None;
    }
    match args[3].as_str() {
        "stop" => Some(args[4..].join(" ")),
        "attach-active" | "presentation" | "input" | "requests" | "matrix" | "observer"
        | "heartbeat" | "topics" | "goal" | "workflow" => Some(args[3..].join(" ")),
        _ => None,
    }
}

#[cfg(test)]
mod control_cli_tests {
    use super::owner_control_command;
    #[test]
    fn workflow_owner_cli_keeps_verb_and_exact_revision() {
        let args = |tail: &[&str]| {
            [vec!["telecodex", "--control", "config.toml"], tail.to_vec()]
                .concat()
                .into_iter()
                .map(str::to_owned)
                .collect::<Vec<_>>()
        };
        assert_eq!(
            owner_control_command(&args(&["workflow", "status", "id"])).as_deref(),
            Some("workflow status id")
        );
        assert_eq!(
            owner_control_command(&args(&["workflow", "recover", "id", "revision"])).as_deref(),
            Some("workflow recover id revision")
        );
        assert_eq!(
            owner_control_command(&args(&["stop", "status", "id"])).as_deref(),
            Some("status id")
        );
        assert!(owner_control_command(&args(&["unknown", "id"])).is_none());
    }
}
