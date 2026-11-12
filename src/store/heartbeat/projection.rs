//! One current/previous fixed-action receipt, using the existing owner journal.
//! An unresolved invocation is never another queued job or an automatic retry.
use super::*;
use sha2::{Digest, Sha256};

fn key(human: i64, session: i64) -> String {
    format!("private_projection:{human}:{session}")
}

fn load(conn: &Connection, key: &str) -> Result<Value> {
    let raw: Option<String> = conn
        .query_row("SELECT value FROM bot_state WHERE key=?1", [key], |r| {
            r.get(0)
        })
        .optional()?;
    Ok(raw
        .map(|s| serde_json::from_str(&s))
        .transpose()?
        .unwrap_or_else(|| json!({})))
}

fn save(conn: &Connection, key: &str, value: &Value) -> Result<()> {
    let raw = serde_json::to_string(value)?;
    anyhow::ensure!(
        raw.len() <= 32768,
        "Private projection receipt exceeds bound"
    );
    conn.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key,raw])?;
    Ok(())
}

impl Store {
    pub(crate) fn private_projection_status(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
    ) -> Result<Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, actual) = super::super::presentation::entry_on(&conn, human, entry)?;
        anyhow::ensure!(actual == native, "Private projection owner changed");
        load(&conn, &key(human, session))
    }

    /// Returns retained evidence unless a new action was atomically claimed.
    /// The remaining deadline belongs to the already reserved physical execution.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn private_projection_claim(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        physical: &str,
        return_id: &str,
        batch_revision: &str,
        task_id: &str,
        task_revision: &str,
        descriptor: &str,
        snapshot: &str,
        reconciliation: &str,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (p, index) =
            producer::load_return(&tx, return_id)?.context("Unknown heartbeat return")?;
        let r = &p.native_returns[index];
        anyhow::ensure!(
            p.human == human && p.entry == entry && p.native == native && producer::bound(&tx, &p)?,
            "Private projection owner retired"
        );
        anyhow::ensure!(
            r.native_turn.as_deref() == Some(physical)
                && r.phase.starts_with("accepted")
                && r.envelope["revision"] == batch_revision,
            "Private projection requires its current accepted return"
        );
        let activation = r
            .attention_activation
            .as_ref()
            .context("Missing Reports activation")?;
        anyhow::ensure!(
            activation.lane == HeartbeatLane::Reports
                && lanes::current_on(&tx, human, entry, activation)?
                && generation_current_on(
                    &tx,
                    human,
                    entry,
                    r.attention_generation
                        .context("Missing heartbeat generation")?
                )?,
            "Private projection Reports lane paused or changed"
        );
        let offers: Vec<producer::Offer> = serde_json::from_value(r.envelope["offers"].clone())?;
        let offer = offers
            .iter()
            .find(|o| o.key == format!("review-task:{task_id}") && o.revision == task_revision)
            .context("Projection task not offered at this revision")?;
        anyhow::ensure!(
            review::task_current(&tx, &p, offer)?,
            "Projection purpose retired"
        );
        let local = r.local.context("Missing heartbeat execution")?;
        let running: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM turns WHERE id=?1 AND session_id=?2 AND from_user_id=?3 AND status='running')", params![local,p.session,human], |row| row.get(0))?;
        anyhow::ensure!(running, "Projection local execution already ended");
        let execution = executions::load(&tx, local)?.context("Missing heartbeat owner")?;
        let deadline = execution["inference_allowance"]["deadline_unix_ms"]
            .as_i64()
            .context("Missing execution deadline")?;
        anyhow::ensure!(
            execution["phase"] == "owned"
                && execution["local"] == local
                && execution["native"] == native
                && execution["generation"] == r.attention_generation.unwrap()
                && execution["activation"] == serde_json::to_value(activation)?
                && execution["owner"].is_null()
                && execution["physical"] == physical
                && execution["source"] == return_id
                && deadline > Utc::now().timestamp_millis(),
            "Projection execution no longer active"
        );
        let storage = key(human, p.session);
        let previous = load(&tx, &storage)?;
        if !previous["current"].is_null() {
            let current = &previous["current"];
            // Neither a lost ACK nor another periodic return retries an unknown effect.
            if current["return_id"] == return_id
                || current["phase"] != "observed"
                || (current["descriptor"] == descriptor && current["snapshot"] == snapshot)
            {
                return Ok(json!({"claimed":false,"current":current}));
            }
        }
        let digest = |v: &str| v.len() == 64 && v.bytes().all(|b| b.is_ascii_hexdigit());
        anyhow::ensure!(
            [descriptor, snapshot, reconciliation]
                .iter()
                .all(|s| digest(s)),
            "Exact projection digests required"
        );
        let invocation = format!(
            "{:x}",
            Sha256::digest(format!(
                "{return_id}\0{physical}\0{descriptor}\0{snapshot}\0{reconciliation}"
            ))
        );
        let current = json!({"invocation":invocation,"phase":"prepared_effect_unknown","return_id":return_id,"physical":physical,"descriptor":descriptor,"snapshot":snapshot,"reconciliation":reconciliation,"deadline_unix_ms":deadline});
        save(
            &tx,
            &storage,
            &json!({"current":current,"previous":previous.get("current").cloned().unwrap_or(Value::Null)}),
        )?;
        tx.commit()?;
        Ok(json!({"claimed":true,"current":current}))
    }

    pub(crate) fn private_projection_finish(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        invocation: &str,
        outcome: Value,
    ) -> Result<()> {
        anyhow::ensure!(
            serde_json::to_vec(&outcome)?.len() <= 8192,
            "Bounded projection outcome required"
        );
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, actual) = super::super::presentation::entry_on(&tx, human, entry)?;
        anyhow::ensure!(
            actual == native,
            "Projection owner changed; preserve retained intent"
        );
        let storage = key(human, session);
        let mut record = load(&tx, &storage)?;
        anyhow::ensure!(
            record["current"]["invocation"] == invocation,
            "Projection invocation changed"
        );
        record["current"]["phase"] = outcome["phase"].clone();
        record["current"]["outcome"] = outcome;
        save(&tx, &storage, &record)?;
        tx.commit()?;
        Ok(())
    }
}
