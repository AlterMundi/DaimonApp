//! Finite owner-attributed pause/restoration journal, independent of model leases.
use super::*;
use crate::codex::NativeGoalSnapshot;
use anyhow::bail;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MaintenanceTarget {
    pub target: SessionKey,
    pub binding: Value,
    pub snapshot: NativeGoalSnapshot,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MaintenancePlan {
    pub request_id: String,
    /// Actual retained human instruction/reference supplied by the authenticated owner.
    pub source: String,
    pub entry: SessionKey,
    pub deadline: i64,
    pub targets: Vec<MaintenanceTarget>,
}
fn key(id: &str) -> Result<String> {
    Uuid::parse_str(id)?;
    Ok(format!("scoped_maintenance:{id}"))
}
fn read(conn: &Connection, human: i64, id: &str) -> Result<Value> {
    let raw: String = conn.query_row(
        "SELECT value FROM bot_state WHERE key=?1",
        [key(id)?],
        |r| r.get(0),
    )?;
    let value: Value = serde_json::from_str(&raw)?;
    if value["human"] != human {
        bail!("Maintenance owner mismatch");
    }
    Ok(value)
}
fn eligible(conn: &Connection, human: i64, value: &Value, index: usize) -> Result<()> {
    let target = &value["targets"][index];
    let selected: SessionKey = serde_json::from_value(target["target"].clone())?;
    let entry: SessionKey = serde_json::from_value(value["plan"]["entry"].clone())?;
    if super::goal_controls::binding_on(conn, human, entry)? != value["entry_binding"]
        || super::goal_controls::binding_on(conn, human, selected)? != target["admission_binding"]
        || serde_json::to_value(super::goal_controls::command_generation_on(conn, selected)?)?
            != target["command_generation"]
        || super::stopping::fenced_on(conn, entry)?
        || super::stopping::fenced_on(conn, selected)?
        || super::maintenance_writer_held_on(conn, entry)?
        || super::maintenance_writer_held_on(conn, selected)?
    {
        bail!("Later direction, binding or writer fence superseded maintenance authority");
    }
    Ok(())
}
impl Store {
    pub(crate) fn maintenance_prepare(&self, human: i64, plan: &MaintenancePlan) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let storage = key(&plan.request_id)?;
        let raw: Option<String> = tx
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [&storage],
                |r| r.get(0),
            )
            .optional()?;
        let request = serde_json::to_value(plan)?;
        if let Some(raw) = raw {
            let prior: Value = serde_json::from_str(&raw)?;
            if prior["human"] != human || prior["plan"] != request {
                bail!("Maintenance request identity reused");
            }
            return Ok(prior);
        }
        let now = Utc::now().timestamp();
        if plan.source.trim().is_empty()
            || plan.source.len() > 2000
            || plan.targets.is_empty()
            || plan.targets.len() > 4
            || plan.deadline < now + 60 + 40 * plan.targets.len() as i64
            || plan.deadline > now + 300
        {
            bail!(
                "Expected actual source, 1..4 targets and absolute (60+40*targets)..300 second deadline"
            );
        }
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM bot_state WHERE key LIKE 'scoped_maintenance:%'",
            [],
            |r| r.get(0),
        )?;
        if count >= 64 {
            bail!(
                "Maintenance journal capacity reached; retain unresolved receipts, no automatic deletion"
            );
        }
        let entry_binding = super::goal_controls::binding_on(&tx, human, plan.entry)?;
        let mut targets = Vec::new();
        for target in &plan.targets {
            let conflict: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM bot_state b,json_each(json_extract(b.value,'$.targets')) t WHERE b.key LIKE 'scoped_maintenance:%' AND json_extract(t.value,'$.target.chat_id')=?1 AND json_extract(t.value,'$.target.thread_id')=?2 AND json_extract(t.value,'$.phase') NOT IN ('restored','not_paused','preserved','superseded'))",params![target.target.chat_id,target.target.thread_id],|r|r.get(0))?;
            if conflict {
                bail!("Target has an existing unresolved maintenance transaction");
            }

            if targets
                .iter()
                .any(|t: &Value| t["target"] == serde_json::to_value(target.target).unwrap())
            {
                bail!("Duplicate maintenance target");
            }
            if target.snapshot.goal.as_ref().is_none_or(|g| {
                g.thread_id != target.binding["entry_binding"][3].as_str().unwrap_or("")
            }) || target.snapshot.revision.is_empty()
                || target.snapshot.revision.len() > 512
            {
                bail!("Exact native goal identity/revision required");
            }
            let actual = super::goal_controls::binding_on(&tx, human, target.target)?;
            if json!({"binding":actual[0],"entry_binding":[human,target.target,actual[1],actual[2]]})
                != target.binding
            {
                bail!("Selected public binding changed");
            }
            let mut doc = serde_json::to_value(target)?;
            doc["admission_binding"] = actual;
            doc["command_generation"] = serde_json::to_value(
                super::goal_controls::command_generation_on(&tx, target.target)?,
            )?;
            doc["phase"] = json!(if target
                .snapshot
                .goal
                .as_ref()
                .is_some_and(|g| g.status == "active")
            {
                "prepared"
            } else {
                "preserved"
            });
            targets.push(doc);
        }
        let doc = json!({"schema":"telecodex.scoped-maintenance/v1","human":human,"plan":request,"entry_binding":entry_binding,
            "prepared_at":now,"targets":targets,"restoration":"only acknowledged exact owned pauses; no unknown write replay","notification":"integrator must report actual outcome to affected sessions; this journal is not delivery"});
        for i in 0..targets.len() {
            eligible(&tx, human, &doc, i)?;
        }
        if doc.to_string().len() > 131072 {
            bail!("Maintenance journal byte bound exceeded");
        }
        tx.execute(
            "INSERT INTO bot_state(key,value) VALUES(?1,?2)",
            params![storage, doc.to_string()],
        )?;
        tx.commit()?;
        Ok(doc)
    }
    pub(crate) fn maintenance_arm(&self, human: i64, id: &str) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let mut doc = read(&tx, human, id)?;
        if doc["armed"] == true {
            return Ok(false);
        }
        if doc["plan"]["deadline"].as_i64().unwrap_or(0) <= Utc::now().timestamp() + 45 {
            bail!("Maintenance deadline exhausted before arming");
        }
        doc["armed"] = json!(true);
        tx.execute(
            "UPDATE bot_state SET value=?2 WHERE key=?1",
            params![key(id)?, doc.to_string()],
        )?;
        tx.commit()?;
        Ok(true)
    }
    pub(crate) fn maintenance_read(&self, human: i64, id: &str) -> Result<Value> {
        read(&self.conn.lock().expect("store mutex poisoned"), human, id)
    }
    pub(crate) fn maintenance_pending(&self) -> Result<Vec<(i64, String)>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut q=conn.prepare("SELECT json_extract(value,'$.human'),json_extract(value,'$.plan.request_id') FROM bot_state b WHERE key LIKE 'scoped_maintenance:%' AND EXISTS(SELECT 1 FROM json_each(json_extract(b.value,'$.targets')) WHERE json_extract(json_each.value,'$.phase') IN ('prepared','pause_submitted','paused','restore_submitted')) LIMIT 64")?;
        Ok(q.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }
    /// Durable exact transition BEFORE native submission. The expected full document
    /// also serializes concurrent owner commands and the one-shot deadline continuation.
    pub(crate) fn maintenance_transition(
        &self,
        human: i64,
        id: &str,
        index: usize,
        expected: &Value,
        phase: &str,
        receipt: Value,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let mut doc = read(&tx, human, id)?;
        if &doc != expected || index >= doc["targets"].as_array().context("Targets missing")?.len()
        {
            bail!("Maintenance changed; inspect its retained outcome");
        }
        if phase == "restore_submitted" {
            if doc["targets"][index]["phase"] != "paused" {
                bail!("Only an acknowledged owned pause can reserve restoration");
            }
            eligible(&tx, human, &doc, index)?;
            let target: SessionKey =
                serde_json::from_value(doc["targets"][index]["target"].clone())?;
            doc["targets"][index]["pre_restore_command_generation"] =
                doc["targets"][index]["command_generation"].clone();
            doc["targets"][index]["command_generation"] = json!(id);
            tx.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",params![format!("goal_intent:{}:{}",target.chat_id,target.thread_id),id])?;
        }
        doc["targets"][index]["phase"] = json!(phase);
        doc["targets"][index][format!("{phase}_receipt")] = receipt;
        if doc.to_string().len() > 131072 {
            bail!("Maintenance receipt bound exceeded");
        }
        tx.execute(
            "UPDATE bot_state SET value=?2 WHERE key=?1",
            params![key(id)?, doc.to_string()],
        )?;
        tx.commit()?;
        Ok(doc)
    }
    pub(crate) fn maintenance_admission(
        &self,
        human: i64,
        id: &str,
        index: usize,
        phase: &str,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let doc = read(&conn, human, id)?;
        if doc["targets"][index]["phase"] != phase {
            bail!("Maintenance submission no longer owns its exact phase");
        }
        if phase == "pause_submitted"
            && doc["plan"]["deadline"].as_i64().unwrap_or(0)
                < Utc::now().timestamp()
                    + 40 * doc["targets"].as_array().map_or(4, |v| v.len()) as i64
                    + 45
        {
            bail!("Insufficient pause/restoration window");
        }
        if phase == "restore_submitted"
            && doc["targets"][index]["restore_submitted_receipt"]["admit_until"]
                .as_i64()
                .is_none_or(|t| t < Utc::now().timestamp())
        {
            bail!("Restoration admission deadline elapsed; no delayed native work");
        }
        eligible(&conn, human, &doc, index)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codex::NativeGoal;
    fn defaults() -> SessionDefaults {
        SessionDefaults {
            cwd: "/tmp".into(),
            model: None,
            reasoning_effort: None,
            session_prompt: None,
            sandbox_mode: "read-only".into(),
            approval_policy: "never".into(),
            search_mode: SearchMode::Disabled,
            add_dirs: vec![],
        }
    }
    fn fixture(store: &Store, status: &str) -> MaintenancePlan {
        let target = SessionKey::new(100, Some(7));
        store.ensure_session(target, 100, &defaults()).unwrap();
        store.set_session_codex_thread(target, "native").unwrap();
        MaintenancePlan {
            request_id: Uuid::now_v7().to_string(),
            source: "retained-human-instruction:scoped-maintenance-fixture".into(),
            entry: target,
            deadline: Utc::now().timestamp() + 240,
            targets: vec![MaintenanceTarget {
                target,
                binding: store.conversation_request_binding(100, target).unwrap(),
                snapshot: NativeGoalSnapshot {
                    revision: "opaque-goal-incarnation:1".into(),
                    goal: Some(NativeGoal {
                        thread_id: "native".into(),
                        objective: "Preserve unfinished work".into(),
                        status: status.into(),
                        token_budget: Some(1000),
                        tokens_used: 42,
                        time_used_seconds: 17,
                        created_at: 10,
                        updated_at: 11,
                    }),
                },
            }],
        }
    }
    #[test]
    fn scoped_maintenance_durable_identity_and_single_arm() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100, 200], &defaults()).unwrap();
        let plan = fixture(&store, "active");
        let before = store.maintenance_prepare(100, &plan).unwrap();
        assert_eq!(before["targets"][0]["snapshot"]["goal"]["tokensUsed"], 42);
        assert_eq!(store.maintenance_prepare(100, &plan).unwrap(), before);
        let mut other = plan.clone();
        other.source = "different approval".into();
        assert!(store.maintenance_prepare(100, &other).is_err());
        assert!(store.maintenance_read(200, &plan.request_id).is_err());
        assert!(store.maintenance_arm(100, &plan.request_id).unwrap());
        assert!(!store.maintenance_arm(100, &plan.request_id).unwrap());
        let armed = store.maintenance_read(100, &plan.request_id).unwrap();
        assert!(
            store
                .maintenance_transition(
                    100,
                    &plan.request_id,
                    0,
                    &before,
                    "pause_submitted",
                    json!({})
                )
                .is_err()
        );
        let submitted = store
            .maintenance_transition(
                100,
                &plan.request_id,
                0,
                &armed,
                "pause_submitted",
                json!({"automatic_retry":false}),
            )
            .unwrap();
        drop(store);
        let reopened = Store::open(file.path(), &[100], &defaults()).unwrap();
        assert_eq!(
            reopened.maintenance_read(100, &plan.request_id).unwrap(),
            submitted
        );
        assert_eq!(
            reopened.maintenance_pending().unwrap(),
            vec![(100, plan.request_id.clone())]
        );
        let mut duplicate = plan.clone();
        duplicate.request_id = Uuid::now_v7().to_string();
        assert!(reopened.maintenance_prepare(100, &duplicate).is_err());
    }
    #[test]
    fn scoped_maintenance_preserves_prior_paused_blocked_and_rejects_bounds() {
        for status in ["paused", "blocked", "complete"] {
            let file = tempfile::NamedTempFile::new().unwrap();
            let store = Store::open(file.path(), &[100], &defaults()).unwrap();
            let mut plan = fixture(&store, status);
            let doc = store.maintenance_prepare(100, &plan).unwrap();
            assert_eq!(doc["targets"][0]["phase"], "preserved");
            assert!(store.maintenance_pending().unwrap().is_empty());
            plan.request_id = Uuid::now_v7().to_string();
            plan.deadline = Utc::now().timestamp() + 360;
            assert!(store.maintenance_prepare(100, &plan).is_err());
            plan.deadline = Utc::now().timestamp() + 240;
            plan.targets.push(plan.targets[0].clone());
            assert!(store.maintenance_prepare(100, &plan).is_err());
        }
    }
    #[test]
    fn scoped_maintenance_later_direction_and_fences_revoke_submission() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &defaults()).unwrap();
        let plan = fixture(&store, "active");
        let doc = store.maintenance_prepare(100, &plan).unwrap();
        store
            .maintenance_transition(100, &plan.request_id, 0, &doc, "pause_submitted", json!({}))
            .unwrap();
        assert!(
            store
                .maintenance_admission(100, &plan.request_id, 0, "pause_submitted")
                .is_ok()
        );
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "INSERT INTO bot_state(key,value) VALUES('goal_intent:100:7','later-human-pause')",
                [],
            )
            .unwrap();
        assert!(
            store
                .maintenance_admission(100, &plan.request_id, 0, "pause_submitted")
                .is_err()
        );
    }
    #[test]
    fn scoped_maintenance_delayed_restore_cannot_start_native_work() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &defaults()).unwrap();
        let plan = fixture(&store, "active");
        let doc = store.maintenance_prepare(100, &plan).unwrap();
        let paused = store
            .maintenance_transition(
                100,
                &plan.request_id,
                0,
                &doc,
                "paused",
                json!({"synthetic_matched_receipt":true}),
            )
            .unwrap();
        let submitted = store
            .maintenance_transition(
                100,
                &plan.request_id,
                0,
                &paused,
                "restore_submitted",
                json!({"admit_until":Utc::now().timestamp()-1}),
            )
            .unwrap();
        assert!(
            store
                .maintenance_admission(100, &plan.request_id, 0, "restore_submitted")
                .is_err()
        );
        assert_eq!(
            store.maintenance_read(100, &plan.request_id).unwrap(),
            submitted
        );
    }
}
