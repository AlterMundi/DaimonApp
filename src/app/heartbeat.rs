//! Human console and scoped integrator share one model-free attention control.
use super::*;
use crate::store::HeartbeatCommand;
use serde_json::Value;

pub(super) async fn execute(
    app: &App,
    human: i64,
    entry: SessionKey,
    command: HeartbeatCommand,
) -> Result<Value> {
    let cfg = super::routing::profile(&app.shared)?;
    if cfg.human_id != human || cfg.entry() != entry {
        bail!("Heartbeat control belongs to the configured integrating entry");
    }
    let pause = matches!(&command, HeartbeatCommand::Pause);
    // Persist the fence before attempting cancellation or any native read.
    let mut value = app.shared.store.heartbeat_control(human, entry, command)?;
    let records = app.shared.store.heartbeat_executions(human, entry, pause)?;
    let mut observations = Vec::new();
    for r in records.iter().filter(|r| r["phase"] == "stopping" && pause) {
        let Some(physical) = r["physical"].as_str() else {
            observations.push(serde_json::json!({"local":r["local"],"state":"unconfirmed","reason":"physical_identity_not_yet_observed"}));
            continue;
        };
        let native = r["native"]
            .as_str()
            .context("Heartbeat native identity missing")?;
        let acknowledged = app
            .shared
            .codex
            .interrupt_selected_turn(native, physical)
            .await
            .is_ok();
        let terminal = app
            .shared
            .codex
            .admitted_turn_status(native, Some(physical), "")
            .await
            .ok()
            .flatten()
            .filter(|(id, status)| {
                id == physical && matches!(status.as_str(), "completed" | "failed" | "interrupted")
            });
        if let Some((_, status)) = terminal {
            app.shared.store.heartbeat_native_terminal(
                r["local"]
                    .as_i64()
                    .context("Heartbeat local identity missing")?,
                physical,
                &status,
            )?;
            observations.push(serde_json::json!({"local":r["local"],"state":"terminal","status":status,"interrupt_acknowledged":acknowledged}));
        } else {
            observations.push(serde_json::json!({"local":r["local"],"state":"unconfirmed","interrupt_acknowledged":acknowledged}));
        }
    }
    value["owned_execution_control"] = serde_json::json!("exact_native_interrupt");
    value["executions"] =
        serde_json::to_value(app.shared.store.heartbeat_executions(human, entry, false)?)?;
    value["cancellation_observations"] = serde_json::to_value(observations)?;
    Ok(value)
}
pub(super) async fn owner(app: &App, human: i64, args: &str) -> Result<Value> {
    if let Some(rest) = args.strip_prefix("configure-resources ") {
        let (generation, raw) = rest
            .split_once(' ')
            .context("Expected heartbeat configure-resources GENERATION CONTRACT_JSON")?;
        return execute(
            app,
            human,
            super::routing::profile(&app.shared)?.entry(),
            HeartbeatCommand::ConfigureResources {
                generation: generation.parse()?,
                contract: serde_json::from_str::<crate::store::HeartbeatResources>(raw)?,
            },
        )
        .await;
    }
    let fields = args.split_whitespace().collect::<Vec<_>>();
    let command = match fields.as_slice() {
        ["status"] => HeartbeatCommand::Status,
        ["pause"] => HeartbeatCommand::Pause,
        ["resume", generation] => HeartbeatCommand::Resume {
            generation: generation.parse()?,
        },
        _ => bail!(
            "Expected heartbeat status|pause|resume GENERATION|configure-resources GENERATION CONTRACT_JSON"
        ),
    };
    execute(
        app,
        human,
        super::routing::profile(&app.shared)?.entry(),
        command,
    )
    .await
}
