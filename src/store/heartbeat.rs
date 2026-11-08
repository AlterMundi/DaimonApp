//! Persistent scoped attention control. No scheduler, inference or goal mutation.
use super::*;
pub(in crate::store) mod lanes;
pub use lanes::HeartbeatLane;
mod delegation;
mod executions;
pub(in crate::store) use delegation::{
    AttentionOwner, claim_delegate_on, owner_current_on, owner_for_turn_on,
};
pub(in crate::store) mod producer;
pub use producer::{HeartbeatInboxSource, HeartbeatProducerContract, HeartbeatPurpose};
mod reports;
pub use reports::HeartbeatReportSource;
mod resources;
mod review;
pub(super) use executions::claim_on as execution_claim_on;
pub use resources::HeartbeatResources;
#[cfg(test)]
pub(in crate::store) use resources::test_contract;
pub use review::HeartbeatReviewContract;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum HeartbeatCommand {
    Status,
    Pause,
    /// Versioned app control; bare Pause remains the owner emergency action.
    SetPaused {
        paused: bool,
        generation: u64,
    },
    SetLanePaused {
        lane: HeartbeatLane,
        paused: bool,
        generation: u64,
        global_generation: u64,
    },
    Resume {
        generation: u64,
    },
    PauseLane {
        lane: HeartbeatLane,
    },
    ResumeLane {
        lane: HeartbeatLane,
        generation: u64,
    },
    ConfigureResources {
        generation: u64,
        contract: HeartbeatResources,
    },
    ConfigureProducer {
        generation: u64,
        contract: HeartbeatProducerContract,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Control {
    paused: bool,
    generation: u64,
    changed_at: String,
    #[serde(default)]
    lanes: lanes::Controls,
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
    /// Explicit owner selection of persistent operation, with a recurring rate.
    /// Historical contracts/counters and all controls remain untouched.
    pub fn heartbeat_enable_continuous(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        attempts_per_hour: u32,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::presentation::entry_on(&tx, human, entry)?;
        let raw: String = tx.query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )?;
        let control: Control = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            control.paused && control.generation == generation,
            "Pause and select the exact heartbeat generation before owner continuous adoption"
        );
        anyhow::ensure!(
            !executions::unresolved_on(&tx, human, entry)?,
            "Heartbeat execution unresolved"
        );
        let status = producer::status_on(&tx, human, session)?;
        anyhow::ensure!(
            matches!(
                status["state"].as_str(),
                Some("configured" | "expired" | "check_capacity")
            ),
            "Select the existing bound heartbeat producer; preserve stopped or uncertain work"
        );
        resources::enable_continuous_on(&tx, session, human, attempts_per_hour)?;
        tx.commit()?;
        Ok(())
    }

    /// Explicit owner-only model-free observation successor. No account change.
    pub fn heartbeat_renew_observation(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        expected_expiry: i64,
        expiry: i64,
    ) -> Result<()> {
        self.heartbeat_observation_successor(
            human,
            entry,
            generation,
            expected_expiry,
            expiry,
            None,
        )
    }

    /// Explicit cumulative ceiling for a new finite model-free observation period.
    pub fn heartbeat_renew_observation_capacity(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        expected_expiry: i64,
        expiry: i64,
        max_checks: u32,
    ) -> Result<()> {
        self.heartbeat_observation_successor(
            human,
            entry,
            generation,
            expected_expiry,
            expiry,
            Some(max_checks),
        )
    }

    fn heartbeat_observation_successor(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        expected_expiry: i64,
        expiry: i64,
        max_checks: Option<u32>,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::presentation::entry_on(&tx, human, entry)?;
        let raw: String = tx.query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )?;
        let control: Control = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            control.paused && control.generation == generation,
            "Pause and select the exact heartbeat generation before explicit owner renewal"
        );
        producer::renew_observation_on(
            &tx,
            human,
            entry,
            generation,
            expected_expiry,
            expiry,
            max_checks,
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Owner-console only: not part of HeartbeatCommand or model tool actions.
    /// Renew an expired finite window without minting capacity or activating it.
    pub fn heartbeat_renew_window(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        expected_expiry: i64,
        expiry: i64,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::presentation::entry_on(&tx, human, entry)?;
        let raw: String = tx.query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )?;
        let control: Control = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            control.paused && control.generation == generation,
            "Pause and select the exact heartbeat generation before explicit owner renewal"
        );
        anyhow::ensure!(
            !executions::unresolved_on(&tx, human, entry)?,
            "Heartbeat execution unresolved"
        );
        let receipt_key = format!("heartbeat_window_renewal:{human}:{session}");
        let mut receipt = json!({"generation":generation,"previous_expires_at_unix_ms":expected_expiry,
            "expires_at_unix_ms":expiry,"resources_refilled":false,"activated":false});
        let previous: Option<String> = tx
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [&receipt_key],
                |r| r.get(0),
            )
            .optional()?;
        if previous
            .as_deref()
            .map(serde_json::from_str::<Value>)
            .transpose()?
            .as_ref()
            .is_some_and(|previous| {
                previous["generation"] == generation
                    && previous["previous_expires_at_unix_ms"] == expected_expiry
                    && previous["expires_at_unix_ms"] == expiry
            })
        {
            // Same command after a lost ACK observes its retained effect.
            return Ok(());
        }
        let now = chrono::Utc::now().timestamp_millis();
        anyhow::ensure!(
            expected_expiry <= now && expiry > now && expiry <= now + 7 * 86400 * 1000,
            "Select an expired predecessor and a new finite window within seven days"
        );
        resources::renew_window_on(&tx, session, human, expected_expiry, expiry)?;
        receipt["retry"] = serde_json::to_value(producer::renew_window_on(
            &tx,
            human,
            entry,
            expected_expiry,
            expiry,
        )?)?;
        // One replaceable current receipt, not an accumulating renewal journal.
        tx.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            params![receipt_key,serde_json::to_string(&receipt)?])?;
        tx.commit()?;
        Ok(())
    }

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
                lanes: Default::default(),
            });
        // Normalize only after both revisions have been checked under the same
        // write transaction. A stale app must not persist a fence or cancel work.
        let command = match command {
            HeartbeatCommand::SetPaused { paused, generation } => {
                anyhow::ensure!(
                    generation == control.generation,
                    "Heartbeat generation changed; refresh before changing its state"
                );
                if paused {
                    HeartbeatCommand::Pause
                } else {
                    HeartbeatCommand::Resume { generation }
                }
            }
            HeartbeatCommand::SetLanePaused {
                lane,
                paused,
                generation,
                global_generation,
            } => {
                anyhow::ensure!(
                    global_generation == control.generation,
                    "Heartbeat generation changed; refresh before changing a lane"
                );
                let current = control.lanes.get(&lane).map_or(0, |c| c.generation);
                anyhow::ensure!(
                    generation == current,
                    "Lane generation changed; refresh before changing its state"
                );
                if paused {
                    HeartbeatCommand::PauseLane { lane }
                } else {
                    HeartbeatCommand::ResumeLane { lane, generation }
                }
            }
            other => other,
        };
        let lane_change = match &command {
            HeartbeatCommand::PauseLane { lane } => Some((*lane, true, None)),
            HeartbeatCommand::ResumeLane { lane, generation } => {
                Some((*lane, false, Some(*generation)))
            }
            _ => None,
        };
        if let Some((lane, paused, generation)) = lane_change {
            anyhow::ensure!(
                paused || lane.supported(),
                "This activation lane is not implemented"
            );
            let c = control.lanes.entry(lane).or_default();
            anyhow::ensure!(
                generation.is_none_or(|g| g == c.generation),
                "Lane generation changed; inspect status before resume"
            );
            if c.paused != paused {
                anyhow::ensure!(
                    paused || c.generation < 9_007_199_254_740_991,
                    "Lane generation capacity reached"
                );
                c.paused = paused;
                c.generation = c.generation.saturating_add(1).min(9_007_199_254_740_991);
                control.changed_at = now_string();
            }
            tx.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key,serde_json::to_string(&control)?])?;
            if !paused {
                super::workflows::resume_attention_on(
                    &tx,
                    human,
                    entry,
                    &native,
                    control.generation,
                )?;
                producer::resume_on(&tx, human, entry, control.generation)?;
            }
        }
        let selected = match command {
            HeartbeatCommand::SetPaused { .. } | HeartbeatCommand::SetLanePaused { .. } => {
                unreachable!("normalized above")
            }
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

            HeartbeatCommand::ConfigureProducer {
                generation,
                contract,
            } => {
                anyhow::ensure!(
                    control.paused && control.generation == generation,
                    "Pause and select the exact heartbeat generation before configuring its producer"
                );
                anyhow::ensure!(
                    !executions::unresolved_on(&tx, human, entry)?,
                    "Heartbeat execution is unresolved"
                );
                producer::configure_on(&tx, human, entry, contract)?;
                None
            }
            HeartbeatCommand::Status
            | HeartbeatCommand::PauseLane { .. }
            | HeartbeatCommand::ResumeLane { .. } => None,
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
                    producer::resume_on(&tx, human, entry, control.generation)?;
                }
            }
        }
        tx.commit()?;
        // A damaged resource record must never roll back the pause fence.
        let resources = resources::status_on(&conn, session, human)
            .unwrap_or_else(|_| json!({"state":"unavailable"}));
        let producer = producer::status_on(&conn, human, session)
            .unwrap_or_else(|_| json!({"state":"unavailable"}));
        let renewal: Option<String> = conn
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [format!("heartbeat_window_renewal:{human}:{session}")],
                |r| r.get(0),
            )
            .optional()?;
        let renewal = renewal
            .as_deref()
            .map(serde_json::from_str::<Value>)
            .transpose()
            .unwrap_or_else(|_| Some(json!({"state":"unavailable"})));
        Ok(
            json!({"schema":"telecodex.heartbeat-control/v1","admission_paused":control.paused,"generation":control.generation,"changed_at":control.changed_at,"lanes":lanes::status(&control),
            "controls":{"schema":"telecodex.heartbeat-controls/v1","conditional_global":true,"conditional_lane":true,"actions":["set_paused","set_lane_paused"],"configuration_activates":false},
            "attention_engine":if producer["state"]=="not_configured" {"not_configured"} else {"finite_canonical_offer_producer"},"producer":producer,"owned_execution_control":"not_implemented","resources":resources,"window_renewal":renewal,"scope":"heartbeat_attention_only","maintenance_shutdown":false,"funding_changed":false,"goals_changed":false}),
        )
    }
}

#[cfg(test)]
pub(in crate::store) fn enable_test_lanes(store: &Store, human: i64, entry: SessionKey) {
    store
        .heartbeat_control(human, entry, HeartbeatCommand::Pause)
        .unwrap();
    for lane in HeartbeatLane::IMPLEMENTED {
        let status = store
            .heartbeat_control(human, entry, HeartbeatCommand::Status)
            .unwrap();
        let name = serde_json::to_value(lane).unwrap();
        let c = &status["lanes"][name.as_str().unwrap()];
        if c["paused"] == true {
            store
                .heartbeat_control(
                    human,
                    entry,
                    HeartbeatCommand::ResumeLane {
                        lane,
                        generation: c["generation"].as_u64().unwrap(),
                    },
                )
                .unwrap();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn versioned_app_controls_reject_stale_global_and_lane_changes_atomically() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "same-native")
            .unwrap();
        let apply =
            |value| store.heartbeat_control(100, entry, serde_json::from_value(value).unwrap());
        let status = || {
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Status)
                .unwrap()
        };
        apply(json!({"action":"set_lane_paused","lane":"messaging","paused":false,"generation":0,"global_generation":0})).unwrap();
        apply(json!({"action":"set_paused","paused":false,"generation":0})).unwrap();
        let current = status();
        assert_eq!(current["generation"], 1);
        assert_eq!(current["lanes"]["messaging"]["generation"], 1);
        for stale in [
            json!({"action":"set_paused","paused":true,"generation":0}),
            json!({"action":"set_lane_paused","lane":"messaging","paused":true,"generation":1,"global_generation":0}),
            json!({"action":"set_lane_paused","lane":"messaging","paused":true,"generation":0,"global_generation":1}),
        ] {
            assert!(apply(stale).is_err());
            assert_eq!(status(), current, "a stale app changed persisted state");
        }
        let paused = apply(json!({"action":"set_lane_paused","lane":"messaging","paused":true,"generation":1,"global_generation":1})).unwrap();
        assert_eq!(paused["generation"], 1);
        assert_eq!(paused["lanes"]["messaging"]["generation"], 2);
        assert!(apply(json!({"action":"set_lane_paused","lane":"messaging","paused":false,"generation":1,"global_generation":1})).is_err());
        assert_eq!(status(), paused);
        apply(json!({"action":"set_paused","paused":true,"generation":1})).unwrap();
        drop(store);
        let reopened = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let saved = reopened
            .heartbeat_control(100, entry, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(saved["admission_paused"], true);
        assert_eq!(saved["generation"], 2);
        assert_eq!(saved["lanes"]["messaging"]["generation"], 2);
        assert_eq!(saved["resources"]["state"], "not_configured");
        assert_eq!(saved["producer"]["state"], "not_configured");
        assert_eq!(saved["controls"]["conditional_global"], true);
    }

    #[test]
    fn versioned_lane_control_cannot_activate_unsupported_lanes() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "same-native")
            .unwrap();
        let before = store
            .heartbeat_control(100, entry, HeartbeatCommand::Status)
            .unwrap();
        let command = serde_json::from_value(json!({"action":"set_lane_paused","lane":"sensory","paused":false,"generation":0,"global_generation":0})).unwrap();
        assert!(store.heartbeat_control(100, entry, command).is_err());
        assert_eq!(
            store
                .heartbeat_control(100, entry, HeartbeatCommand::Status)
                .unwrap(),
            before
        );
    }

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
