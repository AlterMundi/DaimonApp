//! Execution ownership is independent of publication and native collection.
use super::*;

fn key(local: i64) -> String {
    format!("heartbeat_execution:{local}")
}
pub(super) fn load(conn: &Connection, local: i64) -> Result<Option<Value>> {
    conn.query_row(
        "SELECT value FROM bot_state WHERE key=?1",
        [key(local)],
        |r| r.get::<_, String>(0),
    )
    .optional()?
    .map(|raw| serde_json::from_str(&raw).map_err(Into::into))
    .transpose()
}
pub(super) fn save(conn: &Connection, local: i64, value: &Value) -> Result<()> {
    conn.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key(local),serde_json::to_string(value)?])?;
    Ok(())
}
pub(super) fn selected(conn: &Connection, human: i64, entry: SessionKey) -> Result<Vec<Value>> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let mut q=conn.prepare("SELECT b.value FROM bot_state b JOIN turns t ON b.key='heartbeat_execution:'||t.id WHERE t.from_user_id=?2 AND ((t.session_id=?1 AND json_extract(b.value,'$.owner') IS NULL) OR (json_extract(b.value,'$.owner.entry.chat_id')=?3 AND json_extract(b.value,'$.owner.entry.thread_id')=?4)) ORDER BY t.id DESC LIMIT 18")?;
    q.query_map(
        params![session, human, entry.chat_id, entry.thread_id],
        |r| r.get::<_, String>(0),
    )?
    .map(|raw| Ok(serde_json::from_str(&raw?)?))
    .collect()
}

pub(super) fn unresolved_on(conn: &Connection, human: i64, entry: SessionKey) -> Result<bool> {
    Ok(selected(conn, human, entry)?
        .iter()
        .any(|r| matches!(r["phase"].as_str(), Some("owned" | "stopping"))))
}

/// Only a fresh serialized entry-worker turn may claim ownership. An internal
/// return steered into an existing turn never establishes cancellation rights.
#[allow(clippy::too_many_arguments)]
pub(in crate::store) fn claim_on(
    conn: &rusqlite::Transaction<'_>,
    local: i64,
    human: i64,
    entry: SessionKey,
    native: &str,
    generation: u64,
    source: &str,
    activation: &lanes::Activation,
) -> Result<()> {
    anyhow::ensure!(
        generation_current_on(conn, human, entry, generation)?,
        "Heartbeat admission is paused or stale"
    );
    anyhow::ensure!(
        lanes::current_on(conn, human, entry, activation)?,
        "Heartbeat lane is paused or stale"
    );
    anyhow::ensure!(
        load(conn, local)?.is_none(),
        "Heartbeat execution already claimed"
    );
    let fresh:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM turns t WHERE t.id=?1 AND t.status='running' AND t.prompt='' AND t.from_user_id=?2 AND EXISTS(SELECT 1 FROM sessions s WHERE s.id=t.session_id AND s.creator_user_id=?2 AND s.chat_id=?3 AND s.thread_id=?4 AND s.codex_thread_id=?5) AND NOT EXISTS(SELECT 1 FROM native_collections n WHERE n.local_turn=t.id) AND NOT EXISTS(SELECT 1 FROM conversation_inputs c WHERE c.local_turn=t.id) AND NOT EXISTS(SELECT 1 FROM incoming_updates i WHERE i.turn_id=t.id))",params![local,human,entry.chat_id,entry.thread_id,native],|r|r.get(0))?;
    anyhow::ensure!(fresh, "Heartbeat requires its own fresh physical execution");
    let retained = selected(conn, human, entry)?;
    anyhow::ensure!(
        !retained
            .iter()
            .any(|r| matches!(r["phase"].as_str(), Some("owned" | "stopping"))),
        "An unresolved heartbeat execution already exists"
    );
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let finite_review = if activation.lane == HeartbeatLane::Reports {
        super::producer::load_return(conn, source)?
            .map(|(p, _)| p)
            .filter(|p| p.review.is_some())
    } else {
        None
    };
    let allowance = if let Some(parent) = finite_review {
        super::review::reserve_on(conn, &parent)?
    } else {
        super::resources::reserve_on(conn, session, human)?
    };
    // Keep the live ownership plus fifteen previous terminal/transferred
    // records. Never delete native turns, source receipts or an uncertain owner.
    for old in retained.iter().skip(15) {
        if matches!(old["phase"].as_str(), Some("terminal" | "transferred")) {
            conn.execute(
                "DELETE FROM bot_state WHERE key=?1",
                [key(old["local"]
                    .as_i64()
                    .context("Invalid heartbeat local turn")?)],
            )?;
        }
    }
    save(
        conn,
        local,
        &json!({"local":local,"generation":generation,"activation":activation,"source":source,"native":native,"physical":null,"phase":"owned","terminal_status":null,"inference_allowance":allowance}),
    )?;
    conn.execute_batch("CREATE TRIGGER IF NOT EXISTS heartbeat_execution_turn_deleted AFTER DELETE ON turns BEGIN DELETE FROM bot_state WHERE key='heartbeat_execution:'||OLD.id; END;")?;
    Ok(())
}

impl Store {
    pub(crate) fn heartbeat_executions(
        &self,
        human: i64,
        entry: SessionKey,
        claim_pause: bool,
    ) -> Result<Vec<Value>> {
        self.heartbeat_executions_scoped(human, entry, claim_pause, None)
    }
    pub(crate) fn heartbeat_executions_scoped(
        &self,
        human: i64,
        entry: SessionKey,
        claim_pause: bool,
        lane: Option<HeartbeatLane>,
    ) -> Result<Vec<Value>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let mut records = selected(&tx, human, entry)?;
        if claim_pause {
            // The caller persisted pause first. A competing external input
            // either transferred ownership before this transaction or refuses
            // before its provider write once this claim wins.
            for r in &mut records {
                if r["phase"] == "owned"
                    && lane.is_none_or(|lane| {
                        r["activation"]["lane"] == serde_json::to_value(lane).unwrap()
                    })
                {
                    r["phase"] = json!("stopping");
                    save(
                        &tx,
                        r["local"].as_i64().context("Invalid heartbeat turn")?,
                        r,
                    )?;
                }
            }
        }
        tx.commit()?;
        Ok(records)
    }
    /// Read the already-reserved allocation at the last submission boundary.
    /// Reading never charges/refills it or establishes new execution ownership.
    pub(crate) fn heartbeat_inference_allowance(
        &self,
        local: i64,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<crate::codex::NativeInferenceAllowance>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let Some(record) = load(&conn, local)? else {
            return Ok(None);
        };
        let (session, _) = super::super::presentation::entry_on(&conn, human, entry)?;
        let bound:bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE t.id=?1 AND t.session_id=?2 AND t.from_user_id=?3 AND t.status='running' AND s.codex_thread_id=?4)",
            params![local,session,human,record["native"].as_str().context("Missing heartbeat native binding")?],|r|r.get(0))?;
        anyhow::ensure!(
            bound && record["phase"] == "owned" && record["physical"].is_null(),
            "Heartbeat allocation no longer owns a fresh execution"
        );
        let activation: lanes::Activation = serde_json::from_value(record["activation"].clone())?;
        if let Some(owner) = record.get("owner") {
            super::delegation::owner_current_on(
                &conn,
                human,
                &serde_json::from_value(owner.clone())?,
            )?;
        } else {
            anyhow::ensure!(
                lanes::current_on(&conn, human, entry, &activation)?,
                "Heartbeat lane is paused or stale"
            );
            anyhow::ensure!(
                generation_current_on(
                    &conn,
                    human,
                    entry,
                    record["generation"]
                        .as_u64()
                        .context("Missing heartbeat generation")?
                )?,
                "Heartbeat admission is paused or stale"
            );
        }
        let allocation = &record["inference_allowance"];
        Ok(Some(crate::codex::NativeInferenceAllowance {
            max_provider_attempts: u32::try_from(
                allocation["max_provider_attempts"]
                    .as_u64()
                    .context("Missing reserved provider attempts")?,
            )?,
            max_request_bytes: u32::try_from(
                allocation["max_request_bytes"]
                    .as_u64()
                    .context("Missing reserved request byte limit")?,
            )?,
            deadline_unix_ms: allocation["deadline_unix_ms"]
                .as_i64()
                .context("Missing reserved inference deadline")?,
        }))
    }

    /// Called at the actual shared native steer boundary, before any external
    /// input/goal/internal-return packet can join this physical execution.
    pub(crate) fn heartbeat_external_input(&self, local: i64) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        if let Some(mut r) = load(&tx, local)? {
            anyhow::ensure!(
                r["phase"] != "stopping",
                "Heartbeat interruption pending; external input was not submitted"
            );
            if r["phase"] == "owned" {
                r["phase"] = json!("transferred");
                save(&tx, local, &r)?;
            }
        }
        tx.commit()?;
        Ok(())
    }
    /// Late native ACK after pause still records the exact physical identity;
    /// returning true asks this same runner to interrupt only its own turn.
    pub(crate) fn heartbeat_native_started(&self, local: i64, physical: &str) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let Some(mut r) = load(&conn, local)? else {
            return Ok(false);
        };
        if r["phase"] == "transferred" {
            return Ok(false);
        }
        anyhow::ensure!(
            r["physical"].as_str().is_none_or(|id| id == physical),
            "Heartbeat physical successor requires a new ownership admission"
        );
        r["physical"] = json!(physical);
        let stopping = r["phase"] == "stopping";
        save(&conn, local, &r)?;
        Ok(stopping)
    }
    pub(crate) fn heartbeat_native_not_submitted(&self, local: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        if let Some(mut r) = load(&conn, local)? {
            anyhow::ensure!(
                r["physical"].is_null(),
                "An admitted heartbeat cannot be relabeled unsent"
            );
            r["phase"] = json!("terminal");
            r["terminal_status"] = json!("not_submitted");
            save(&conn, local, &r)?;
        }
        Ok(())
    }
    pub(crate) fn heartbeat_native_terminal(
        &self,
        local: i64,
        physical: &str,
        status: &str,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let Some(mut r) = load(&conn, local)? else {
            return Ok(());
        };
        // Handover may precede the initial ACK or collect a new human
        // successor. Neither becomes a heartbeat-owned physical identity.
        if r["phase"] == "transferred" && r["physical"].as_str() != Some(physical) {
            return Ok(());
        }
        anyhow::ensure!(
            matches!(status, "completed" | "failed" | "interrupted"),
            "Heartbeat native state is not terminal"
        );
        anyhow::ensure!(
            r["physical"].as_str() == Some(physical),
            "Heartbeat terminal identity changed"
        );
        r["terminal_status"] = json!(status);
        if r["phase"] != "transferred" {
            r["phase"] = json!("terminal");
        }
        save(&conn, local, &r)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn setup() -> (tempfile::NamedTempFile, Store, SessionRecord) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &crate::store::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "heartbeat-native")
            .unwrap();
        store
            .heartbeat_control(100, entry, HeartbeatCommand::Pause)
            .unwrap();
        store
            .heartbeat_control(
                100,
                entry,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract: super::super::test_contract(),
                },
            )
            .unwrap();
        super::super::enable_test_lanes(&store, 100, entry);
        store
            .heartbeat_control(100, entry, HeartbeatCommand::Resume { generation: 1 })
            .unwrap();
        let session = store.get_session(entry).unwrap().unwrap();
        (file, store, session)
    }
    fn fresh(s: &Store, entry: &SessionRecord, prompt: &str) -> i64 {
        s.record_turn_started(
            entry.id,
            &TurnRequest {
                session_key: entry.key,
                from_user_id: 100,
                prompt: prompt.into(),
                runtime_instructions: None,
                attachments: vec![],
                review_mode: None,
                override_search_mode: None,
            },
        )
        .unwrap()
    }
    fn own(s: &Store, entry: &SessionRecord, local: i64) -> Result<()> {
        let mut conn = s.conn.lock().unwrap();
        let tx = conn.transaction()?;
        claim_on(
            &tx,
            local,
            100,
            entry.key,
            "heartbeat-native",
            2,
            "exact-source",
            &lanes::Activation {
                lane: HeartbeatLane::Messaging,
                generation: 1,
            },
        )?;
        tx.commit()?;
        Ok(())
    }
    #[test]
    fn heartbeat_lane_pause_claims_only_its_exact_owned_execution() {
        let (_f, s, entry) = setup();
        let local = fresh(&s, &entry, "");
        own(&s, &entry, local).unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            HeartbeatCommand::PauseLane {
                lane: HeartbeatLane::Reports,
            },
        )
        .unwrap();
        let unrelated = s
            .heartbeat_executions_scoped(100, entry.key, true, Some(HeartbeatLane::Reports))
            .unwrap();
        assert_eq!(unrelated[0]["phase"], "owned");
        assert!(
            s.heartbeat_inference_allowance(local, 100, entry.key)
                .unwrap()
                .is_some()
        );
        s.heartbeat_control(
            100,
            entry.key,
            HeartbeatCommand::PauseLane {
                lane: HeartbeatLane::Messaging,
            },
        )
        .unwrap();
        let selected = s
            .heartbeat_executions_scoped(100, entry.key, true, Some(HeartbeatLane::Messaging))
            .unwrap();
        assert_eq!(selected[0]["phase"], "stopping");
        assert!(
            s.heartbeat_inference_allowance(local, 100, entry.key)
                .is_err()
        );
        assert!(
            s.heartbeat_native_started(local, "late-exact-physical")
                .unwrap()
        );
        assert_eq!(
            s.heartbeat_executions(100, entry.key, false).unwrap()[0]["physical"],
            "late-exact-physical"
        );
    }

    #[test]
    fn inference_reservation_read_is_exact_nonrefilling_and_fenced_by_owner_and_pause() {
        let (_file, s, entry) = setup();
        let local = fresh(&s, &entry, "");
        assert!(
            s.heartbeat_inference_allowance(local, 100, entry.key)
                .unwrap()
                .is_none()
        );
        own(&s, &entry, local).unwrap();
        let before = s
            .heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap()["resources"]
            .clone();
        let first = s
            .heartbeat_inference_allowance(local, 100, entry.key)
            .unwrap()
            .unwrap();
        let second = s
            .heartbeat_inference_allowance(local, 100, entry.key)
            .unwrap()
            .unwrap();
        assert_eq!(first.max_provider_attempts, 3);
        assert_eq!(first.deadline_unix_ms, second.deadline_unix_ms);
        assert!(
            s.heartbeat_inference_allowance(local, 101, entry.key)
                .is_err()
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"],
            before
        );
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert!(
            s.heartbeat_inference_allowance(local, 100, entry.key)
                .is_err()
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            3
        );
    }

    #[test]
    fn pause_wins_before_external_input_and_late_identity_is_not_lost() {
        let (file, s, entry) = setup();
        let local = fresh(&s, &entry, "");
        own(&s, &entry, local).unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        let records = s.heartbeat_executions(100, entry.key, true).unwrap();
        assert_eq!(records[0]["phase"], "stopping");
        assert!(records[0]["physical"].is_null());
        assert!(s.heartbeat_external_input(local).is_err());
        assert!(s.heartbeat_native_started(local, "exact-physical").unwrap());
        assert!(s.heartbeat_native_not_submitted(local).is_err());
        assert!(
            s.heartbeat_native_terminal(local, "other-physical", "interrupted")
                .is_err()
        );
        drop(s);
        let s = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        assert_eq!(
            s.heartbeat_executions(100, entry.key, false).unwrap()[0]["phase"],
            "stopping"
        );
        s.heartbeat_native_terminal(local, "exact-physical", "interrupted")
            .unwrap();
        let r = s.heartbeat_executions(100, entry.key, false).unwrap();
        assert_eq!(r[0]["phase"], "terminal");
        assert_eq!(r[0]["terminal_status"], "interrupted");
    }
    #[test]
    fn external_input_wins_and_pause_never_claims_its_new_physical_turn() {
        let (_file, s, entry) = setup();
        let local = fresh(&s, &entry, "");
        own(&s, &entry, local).unwrap();
        assert!(!s.heartbeat_native_started(local, "old-physical").unwrap());
        s.heartbeat_external_input(local).unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert_eq!(
            s.heartbeat_executions(100, entry.key, true).unwrap()[0]["phase"],
            "transferred"
        );
        assert!(
            !s.heartbeat_native_started(local, "human-successor")
                .unwrap()
        );
        let r = s.heartbeat_executions(100, entry.key, false).unwrap();
        assert_eq!(r[0]["physical"], "old-physical");
    }
    #[test]
    fn prepared_human_handover_precedes_first_native_identity() {
        let (_file, s, entry) = setup();
        let local = fresh(&s, &entry, "");
        own(&s, &entry, local).unwrap();
        s.heartbeat_external_input(local).unwrap();
        assert!(
            !s.heartbeat_native_started(local, "human-first-physical")
                .unwrap()
        );
        s.heartbeat_native_terminal(local, "human-first-physical", "completed")
            .unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        let r = s.heartbeat_executions(100, entry.key, true).unwrap();
        assert_eq!(r[0]["phase"], "transferred");
        assert!(r[0]["physical"].is_null());
    }
    #[test]
    fn only_one_unresolved_owner_and_no_human_turn_can_be_claimed() {
        let (_file, s, entry) = setup();
        let human = fresh(&s, &entry, "human original");
        assert!(own(&s, &entry, human).is_err());
        let first = fresh(&s, &entry, "");
        own(&s, &entry, first).unwrap();
        let second = fresh(&s, &entry, "");
        assert!(own(&s, &entry, second).is_err());
        let status = s
            .heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(status["resources"]["reserved_provider_attempts"], 3);
        s.heartbeat_native_not_submitted(first).unwrap();
        own(&s, &entry, second).unwrap();
        assert!(
            s.heartbeat_native_terminal(second, "not-observed", "completed")
                .is_err()
        );
    }
    #[test]
    fn metadata_retention_does_not_remove_native_history() {
        let (_file, s, entry) = setup();
        for _ in 0..24 {
            let local = fresh(&s, &entry, "");
            own(&s, &entry, local).unwrap();
            s.heartbeat_native_not_submitted(local).unwrap();
        }
        let conn = s.conn.lock().unwrap();
        let resources = super::super::resources::status_on(&conn, entry.id, 100).unwrap();
        assert_eq!(resources["reserved_provider_attempts"], 72);
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM bot_state WHERE key LIKE 'heartbeat_execution:%'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            16
        );
        assert_eq!(
            conn.query_row("SELECT count(*) FROM turns", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            24
        );
    }
}
