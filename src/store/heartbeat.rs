//! Persistent scoped attention control. No scheduler, inference or goal mutation.
use super::*;
mod delegation;
mod executions;
pub(in crate::store) use delegation::{
    AttentionOwner, claim_delegate_on, owner_current_on, owner_for_turn_on,
};
mod resources;
pub(super) use executions::claim_on as execution_claim_on;
pub use resources::HeartbeatResources;
#[cfg(test)]
pub(in crate::store) use resources::test_contract;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum HeartbeatCommand {
    Status,
    Pause,
    Resume {
        generation: u64,
    },
    ConfigureResources {
        generation: u64,
        contract: HeartbeatResources,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Control {
    paused: bool,
    generation: u64,
    changed_at: String,
}
/// Admission-only fence. Presentation/history remain readable while paused.
/// A missing control record never authorizes an automatic attention generation.
pub(super) fn generation_current_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    generation: u64,
) -> Result<bool> {
    let (session, _) = super::presentation::entry_on(conn, human, entry)?;
    let raw: Option<String> = conn
        .query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )
        .optional()?;
    let Some(raw) = raw else {
        return Ok(false);
    };
    let control: Control = serde_json::from_str(&raw)?;
    Ok(!control.paused && control.generation == generation)
}

impl Store {
    /// One control record per existing integrating entry. Restart never resumes
    /// attention or replenishes a resource account. Default is paused.
    pub fn heartbeat_control(
        &self,
        human: i64,
        entry: SessionKey,
        command: HeartbeatCommand,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, native) = super::presentation::entry_on(&tx, human, entry)?;
        let key = format!("heartbeat_control:{human}:{session}");
        let raw: Option<String> = tx
            .query_row("SELECT value FROM bot_state WHERE key=?1", [&key], |r| {
                r.get(0)
            })
            .optional()?;
        let mut control: Control = raw
            .as_deref()
            .map(serde_json::from_str)
            .transpose()?
            .unwrap_or(Control {
                paused: true,
                generation: 0,
                changed_at: String::new(),
            });
        let selected = match command {
            HeartbeatCommand::ConfigureResources {
                generation,
                contract,
            } => {
                anyhow::ensure!(
                    control.paused && control.generation == generation,
                    "Pause and select the current heartbeat generation before configuring resources"
                );
                anyhow::ensure!(
                    !executions::unresolved_on(&tx, human, entry)?,
                    "Heartbeat execution is unresolved; no resource account was created"
                );
                resources::configure_on(&tx, session, human, contract)?;
                None
            }

            HeartbeatCommand::Status => None,
            HeartbeatCommand::Pause => Some(true),
            HeartbeatCommand::Resume { generation } => {
                if generation != control.generation {
                    anyhow::bail!(
                        "Heartbeat generation changed; inspect current status before an explicit resume"
                    );
                }
                Some(false)
            }
        };
        if let Some(paused) = selected {
            if paused != control.paused || raw.is_none() {
                const MAX_GENERATION: u64 = 9_007_199_254_740_991;
                if !paused && control.generation >= MAX_GENERATION {
                    anyhow::bail!(
                        "Heartbeat resume generation capacity reached; pause remains available"
                    );
                }
                control.paused = paused;
                control.generation = control.generation.saturating_add(1).min(MAX_GENERATION);
                control.changed_at = now_string();
                tx.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",params![key,serde_json::to_string(&control)?])?;
                if !paused {
                    super::workflows::resume_attention_on(
                        &tx,
                        human,
                        entry,
                        &native,
                        control.generation,
                    )?;
                }
            }
        }
        tx.commit()?;
        // A damaged resource record must never roll back the pause fence.
        let resources = resources::status_on(&conn, session, human)
            .unwrap_or_else(|_| json!({"state":"unavailable"}));
        // This release supplies the persistent admission control only. Do not
        // pretend its flag interrupts automatic inference that is not yet wired.
        Ok(
            json!({"schema":"telecodex.heartbeat-control/v1","admission_paused":control.paused,"generation":control.generation,"changed_at":control.changed_at,
            "attention_engine":"not_implemented","owned_execution_control":"not_implemented","resources":resources,"scope":"heartbeat_attention_only","maintenance_shutdown":false,"funding_changed":false,"goals_changed":false}),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn pause_is_durable_idempotent_and_stale_resume_cannot_reopen_a_generation() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store =
            Store::open(file.path(), &[100, 101], &super::super::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "same-native")
            .unwrap();
        let before = store.get_session(entry).unwrap().unwrap();
        assert_eq!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Status)
                .unwrap()["admission_paused"],
            true
        );
        let paused = store
            .heartbeat_control(100, entry, HeartbeatCommand::Pause)
            .unwrap();
        assert_eq!(paused["generation"], 1);
        assert_eq!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Pause)
                .unwrap(),
            paused
        );
        assert!(
            store
                .heartbeat_control(101, entry, HeartbeatCommand::Pause)
                .is_err()
        );
        assert!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Resume { generation: 0 })
                .is_err()
        );
        let resumed = store
            .heartbeat_control(100, entry, HeartbeatCommand::Resume { generation: 1 })
            .unwrap();
        assert_eq!(resumed["generation"], 2);
        assert_eq!(resumed["admission_paused"], false);
        let paused = store
            .heartbeat_control(100, entry, HeartbeatCommand::Pause)
            .unwrap();
        assert_eq!(paused["generation"], 3);
        drop(store);
        let store =
            Store::open(file.path(), &[100, 101], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Status)
                .unwrap(),
            paused
        );
        assert!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Resume { generation: 1 })
                .is_err()
        );
        let after = store.get_session(entry).unwrap().unwrap();
        assert_eq!(before.codex_thread_id, after.codex_thread_id);
        assert_eq!(before.model, after.model);
        assert_eq!(before.reasoning_effort, after.reasoning_effort);
        assert_eq!(before.busy, after.busy);
    }
}
