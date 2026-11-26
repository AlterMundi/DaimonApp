mod app;
mod ascii;
mod backend;
mod codex;
mod codex_history;
mod commands;
mod config;
mod control_client;
mod execution;
mod files;
mod interaction;
mod limits;
mod models;
mod nexus;
mod render;
mod store;
mod tele_daimon;
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
    let executable = std::path::Path::new(&args[0])
        .file_stem()
        .and_then(std::ffi::OsStr::to_str);
    let gateway = executable == Some("daimon-gateway");
    let first = args.get(1).map(String::as_str);
    let adapter_config = match (executable, first) {
        (Some("teledaimon"), Some(path)) if args.len() == 2 && !path.starts_with('-') => Some(path),
        (Some("teledaimon"), _) => anyhow::bail!("Usage: teledaimon CONFIG"),
        (Some("daimon-gateway"), Some("--tele-daimon-poll")) => {
            anyhow::bail!("Run Telegram polling with teledaimon CONFIG")
        }
        (_, Some("--tele-daimon-poll")) if args.len() == 3 => Some(args[2].as_str()),
        (_, Some("--tele-daimon-poll")) => {
            anyhow::bail!("Usage: telecodex --tele-daimon-poll CONFIG")
        }
        _ => None,
    };
    if let Some(path) = adapter_config {
        init_logging(true);
        let path = std::path::Path::new(path);
        return tele_daimon::run_external(config::TelegramPollConfig::load(path)?).await;
    }
    let load_config: fn(std::path::PathBuf) -> Result<config::Config> = if gateway {
        config::Config::load_gateway
    } else {
        config::Config::load
    };
    if gateway && first == Some("--preflight") {
        anyhow::ensure!(args.len() == 3, "Usage: daimon-gateway --preflight CONFIG");
        let config = load_config(args[2].clone().into())?;
        if store::Store::preflight_receiving(&config)? {
            println!("Gateway profile and selected Reports record are readable.");
        } else {
            println!("Gateway profile is readable. No selected Reports record exists.");
        }
        return Ok(());
    }
    if first == Some("--controller") {
        if args.len() != 4 {
            anyhow::bail!(
                "Usage: {} --controller TURN_ACCESS_FILE OPERATION_JSON",
                executable.unwrap_or("daimon-gateway")
            );
        }
        return control_client::controller(std::path::Path::new(&args[2]), &args[3]).await;
    }
    if first == Some("--control") {
        if owner_control_command(&args).is_none() {
            anyhow::bail!(
                "Usage: {} --control CONFIG stop all|status ID|resume ID; attach-active CHAT TOPIC NATIVE_THREAD NATIVE_TURN; presentation list|before DELIVERY_CURSOR NATIVE_CURSOR [MATRIX_CURSOR]|part SOURCE REVISION OFFSET; creation status ID|reconcile ID EVENT_UPDATE|resume ID; workflow status ID|result ID STEP REVISION OFFSET|recover ID REVISION; input submit|retry JSON|status UUID|list CURSOR; requests list CURSOR|detail ID OFFSET [REVISION]|decide JSON; matrix status UUID|return JSON; topics list DAYS|notices NATIVE_THREAD [AFTER]; heartbeat status|pause|resume GENERATION|select-review GENERATION CONTRACT_JSON|configure-resources GENERATION CONTRACT_JSON|renew-window GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS|renew-observation GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS [MAX_CHECKS]; observer observe #Topic [--retry]|summary #Topic|sources #Topic",
                executable.unwrap_or("daimon-gateway")
            );
        }
        let config = load_config(args[2].clone().into())?;
        if args.get(3).map(String::as_str) == Some("matrix")
            && args.get(4).map(String::as_str) == Some("publication")
            && matches!(args.get(5).map(String::as_str), Some("commit" | "complete"))
        {
            use std::io::Read;
            anyhow::ensure!(args.len() == 6, "Pass the exact publication JSON on stdin");
            let mut raw = String::new();
            std::io::stdin().take(65537).read_to_string(&mut raw)?;
            anyhow::ensure!(raw.len() <= 65536, "Publication request exceeds bound");
            return control_client::run(&config, &format!("matrix publication {} {raw}", args[5]))
                .await;
        }
        let command = owner_control_command(&args).expect("validated control command");
        return control_client::run(&config, &command).await;
    }
    if first == Some("--probe-native") {
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
    init_logging(!gateway);
    if let Some(delay_ms) = restart_delay_ms_from_env() {
        sleep(Duration::from_millis(delay_ms)).await;
    }

    let config_path = match (gateway, first) {
        (true, Some(path)) if args.len() == 2 && !path.starts_with('-') => path,
        (true, _) => anyhow::bail!("Usage: daimon-gateway CONFIG"),
        (false, path) => path.unwrap_or("telecodex.toml"),
    };
    let config = load_config(config_path.into())?;
    let app = app::App::bootstrap(config).await?;
    app.run().await
}

fn init_logging(load_dotenv: bool) {
    if load_dotenv {
        let _ = dotenvy::dotenv();
    }
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("telecodex=info,reqwest=warn")),
        )
        .with_target(false)
        .compact()
        .init();
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
        | "heartbeat" | "topics" | "goal" | "workflow" | "creation" | "owner-action" => {
            Some(args[3..].join(" "))
        }
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
            owner_control_command(&args(&["creation", "reconcile", "id", "22"])).as_deref(),
            Some("creation reconcile id 22")
        );
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
