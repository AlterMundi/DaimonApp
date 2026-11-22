//! Independent persisted activation fences within the existing heartbeat owner.
use super::*;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HeartbeatLane {
    Messaging,
    WorkflowReturns,
    Reports,
    SessionProgress,
    Sensory,
    Issues,
    Tasks,
    Bitacora,
}
impl HeartbeatLane {
    pub(super) const ALL: [Self; 8] = [
        Self::Messaging,
        Self::WorkflowReturns,
        Self::Reports,
        Self::SessionProgress,
        Self::Sensory,
        Self::Issues,
        Self::Tasks,
        Self::Bitacora,
    ];
    pub(in crate::store) const IMPLEMENTED: [Self; 4] = [
        Self::Messaging,
        Self::WorkflowReturns,
        Self::Reports,
        Self::SessionProgress,
    ];
    pub(super) fn supported(self) -> bool {
        Self::IMPLEMENTED.contains(&self)
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(in crate::store) struct Activation {
    pub lane: HeartbeatLane,
    pub generation: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LaneControl {
    pub paused: bool,
    pub generation: u64,
}
impl Default for LaneControl {
    fn default() -> Self {
        Self {
            paused: true,
            generation: 0,
        }
    }
}
pub(super) type Controls = BTreeMap<HeartbeatLane, LaneControl>;

pub(super) fn selected(control: &Control, lane: HeartbeatLane) -> Option<Activation> {
    control
        .lanes
        .get(&lane)
        .filter(|c| !c.paused && lane.supported())
        .map(|c| Activation {
            lane,
            generation: c.generation,
        })
}
pub(in crate::store) fn current_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    activation: &Activation,
) -> Result<bool> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let raw: Option<String> = conn
        .query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )
        .optional()?;
    let Some(raw) = raw else { return Ok(false) };
    let control: Control = serde_json::from_str(&raw)?;
    Ok(!control.paused && selected(&control, activation.lane).as_ref() == Some(activation))
}
pub(super) fn status(control: &Control) -> Value {
    let mut value = serde_json::Map::new();
    for lane in HeartbeatLane::ALL {
        let missing = LaneControl::default();
        let c = control.lanes.get(&lane).unwrap_or(&missing);
        value.insert(
            serde_json::to_value(lane).unwrap().as_str().unwrap().into(),
            json!({"paused":c.paused,"generation":c.generation,"supported":lane.supported()}),
        );
    }
    Value::Object(value)
}

pub(in crate::store) fn refreshed(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    activation: &Activation,
) -> Result<Option<Activation>> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let raw: Option<String> = conn
        .query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )
        .optional()?;
    let Some(raw) = raw else { return Ok(None) };
    let control: Control = serde_json::from_str(&raw)?;
    Ok(if control.paused {
        None
    } else {
        selected(&control, activation.lane)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lane_pause_persists_without_changing_global_or_unrelated_generation() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &crate::store::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "same-integrator")
            .unwrap();
        let status = store
            .heartbeat_control(100, entry, HeartbeatCommand::Resume { generation: 0 })
            .unwrap();
        assert!(
            status["lanes"]
                .as_object()
                .unwrap()
                .values()
                .all(|c| c["paused"] == true)
        );
        for lane in [HeartbeatLane::Messaging, HeartbeatLane::WorkflowReturns] {
            store
                .heartbeat_control(
                    100,
                    entry,
                    HeartbeatCommand::ResumeLane {
                        lane,
                        generation: 0,
                    },
                )
                .unwrap();
        }
        let paused = store
            .heartbeat_control(
                100,
                entry,
                HeartbeatCommand::PauseLane {
                    lane: HeartbeatLane::Messaging,
                },
            )
            .unwrap();
        assert_eq!(paused["generation"], 1);
        assert_eq!(paused["lanes"]["workflow_returns"]["generation"], 1);
        assert_eq!(paused["lanes"]["workflow_returns"]["paused"], false);
        assert_eq!(paused["lanes"]["messaging"]["generation"], 2);
        assert!(
            store
                .heartbeat_control(
                    100,
                    entry,
                    HeartbeatCommand::ResumeLane {
                        lane: HeartbeatLane::Messaging,
                        generation: 0
                    }
                )
                .is_err()
        );
        assert!(
            store
                .heartbeat_control(
                    100,
                    entry,
                    HeartbeatCommand::ResumeLane {
                        lane: HeartbeatLane::Sensory,
                        generation: 0
                    }
                )
                .is_err()
        );
        drop(store);
        let store = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let state = store
            .heartbeat_control(100, entry, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(state["lanes"], paused["lanes"]);
        store
            .heartbeat_control(100, entry, HeartbeatCommand::Pause)
            .unwrap();
        let conn = store.conn.lock().unwrap();
        assert!(
            !current_on(
                &conn,
                100,
                entry,
                &Activation {
                    lane: HeartbeatLane::WorkflowReturns,
                    generation: 1
                }
            )
            .unwrap()
        );
    }
}
