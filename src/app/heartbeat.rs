//! Human console and scoped integrator share one model-free attention control.
use super::*;
use crate::store::HeartbeatCommand;
use serde_json::Value;

pub(super) fn execute(
    app: &App,
    human: i64,
    entry: SessionKey,
    command: HeartbeatCommand,
) -> Result<Value> {
    let cfg = super::routing::profile(&app.shared)?;
    if cfg.human_id != human || cfg.entry() != entry {
        bail!("Heartbeat control belongs to the configured integrating entry");
    }
    app.shared.store.heartbeat_control(human, entry, command)
}
pub(super) fn owner(app: &App, human: i64, args: &str) -> Result<Value> {
    let fields = args.split_whitespace().collect::<Vec<_>>();
    let command = match fields.as_slice() {
        ["status"] => HeartbeatCommand::Status,
        ["pause"] => HeartbeatCommand::Pause,
        ["resume", generation] => HeartbeatCommand::Resume {
            generation: generation.parse()?,
        },
        _ => bail!("Expected heartbeat status|pause|resume GENERATION"),
    };
    execute(
        app,
        human,
        super::routing::profile(&app.shared)?.entry(),
        command,
    )
}
