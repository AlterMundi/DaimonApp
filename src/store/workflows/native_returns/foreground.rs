//! Context is another attributed native return source, never work admission.
use super::*;

#[derive(Clone, Deserialize)]
pub(super) struct ForegroundParent {
    pub dialogue: String,
    pub human: i64,
    pub entry: SessionKey,
    pub native: String,
    pub binding: String,
    pub epoch: String,
    pub incorporated: u64,
    pub generation: String,
    pub checkpoint: Value,
    #[serde(default)]
    pub checkpoint_request: Option<Value>,
    pub range: Option<Value>,
    #[serde(default)]
    pub native_returns: Vec<WorkflowReturn>,
}

fn parent(conn: &Connection, dialogue: &str) -> Result<ForegroundParent> {
    let raw: String = conn.query_row(
        "SELECT doc FROM live_context WHERE dialogue=?1",
        [dialogue],
        |r| r.get(0),
    )?;
    Ok(serde_json::from_str(&raw)?)
}
pub(super) fn load(conn: &Connection, id: &str) -> Result<Option<(ReturnContext, usize)>> {
    let Some((dialogue, _)) = id
        .strip_prefix("foreground:")
        .and_then(|v| v.split_once(':'))
    else {
        return Ok(None);
    };
    let p = parent(conn, dialogue)?;
    let index = p
        .native_returns
        .iter()
        .position(|r| r.id == id)
        .context("Missing Live return receipt")?;
    Ok(Some((ReturnContext::foreground(p), index)))
}
pub(super) fn save(
    conn: &Connection,
    p: &ForegroundParent,
    returns: &[WorkflowReturn],
) -> Result<()> {
    crate::store::live_context::save_returns_on(conn, &p.dialogue, returns)
}
pub(super) fn current(
    conn: &Connection,
    p: &ForegroundParent,
    r: &WorkflowReturn,
    admission: bool,
) -> Result<bool> {
    let Ok((session, native)) = crate::store::presentation::entry_on(conn, p.human, p.entry) else {
        return Ok(false);
    };
    if native != p.native
        || crate::store::presentation::entry_binding(conn, p.human, p.entry, session)? != p.binding
        || crate::store::stopping::admission_epoch_on(conn, p.entry)? != p.epoch
        || crate::store::stopping::fenced_on(conn, p.entry)?
    {
        return Ok(false);
    }
    // Incorporation ends admission of this batch, not observation of its exact
    // already acknowledged physical turn. Closed producers may finish context.
    Ok(!admission
        || (r.reported_revision.is_none()
            && p.range
                .as_ref()
                .is_some_and(|range| range["revision"] == r.envelope["revision"])
            && (r.envelope["through"]
                .as_u64()
                .is_some_and(|n| n > p.incorporated)
                || p.checkpoint_request.as_ref().is_some_and(|q| {
                    q["acknowledged"] == false
                        && r.envelope["checkpoint_generation"] == q["generation"]
                }))))
}
pub(super) fn retained(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
) -> Result<Vec<ReturnContext>> {
    let mut q=conn.prepare("SELECT doc FROM live_context WHERE human=?1 AND chat=?2 AND topic=?3 AND EXISTS(SELECT 1 FROM json_each(doc,'$.native_returns') r WHERE json_extract(r.value,'$.phase')='retained_unsent') ORDER BY rowid LIMIT 64")?;
    let rows = q
        .query_map(params![human, entry.chat_id, entry.thread_id], |r| {
            r.get::<_, String>(0)
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    rows.into_iter()
        .map(|raw| Ok(ReturnContext::foreground(serde_json::from_str(&raw)?)))
        .collect()
}

impl Store {
    /// One current context-only physical writer already acknowledged by Core.
    /// This selects observation/collection, never another native submission.
    pub(crate) fn native_foreground_attachment(
        &self,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<(String, String)>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut query = conn.prepare("SELECT doc FROM live_context WHERE human=?1 AND chat=?2 AND topic=?3 AND EXISTS(SELECT 1 FROM json_each(doc,'$.native_returns') r WHERE json_extract(r.value,'$.phase')='accepted_uncollected' AND json_extract(r.value,'$.reported_revision') IS NULL) ORDER BY rowid DESC LIMIT 64")?;
        let rows = query
            .query_map(params![human, entry.chat_id, entry.thread_id], |r| {
                r.get::<_, String>(0)
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        for raw in rows {
            let parent: ForegroundParent = serde_json::from_str(&raw)?;
            for receipt in parent.native_returns.iter().rev() {
                if receipt.phase == "accepted_uncollected"
                    && receipt.reported_revision.is_none()
                    && receipt.collection_local.is_some()
                    && current(&conn, &parent, receipt, false)?
                    && let Some(physical) = &receipt.native_turn
                {
                    return Ok(Some((parent.native.clone(), physical.clone())));
                }
            }
        }
        Ok(None)
    }
    pub(in crate::store) fn init_native_foreground_returns(&self) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let rows = {
            let mut q = tx.prepare("SELECT doc FROM live_context ORDER BY rowid LIMIT 64")?;
            q.query_map([], |r| r.get::<_, String>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        for raw in rows {
            let mut context = ReturnContext::foreground(serde_json::from_str(&raw)?);
            for r in &mut context.native_returns {
                if r.instance != self.instance_id {
                    r.phase = match r.phase.as_str() {
                        "reserved" => "retained_unsent",
                        "submitting" => "uncertain",
                        other => other,
                    }
                    .into();
                    if r.phase == "retained_unsent" && r.retry_after.is_none() {
                        r.retry_after =
                            retry_delay(r.attempts).map(|seconds| Utc::now().timestamp() + seconds);
                    }
                }
            }
            for i in 0..context.native_returns.len() {
                if context.native_returns[i].phase == "accepted_uncollected" {
                    detached_on(&tx, &mut context, i)?;
                }
            }
            super::save_on(&tx, &context)?;
        }
        tx.execute_batch("CREATE TRIGGER IF NOT EXISTS foreground_context_turn_deleted AFTER DELETE ON turns BEGIN DELETE FROM bot_state WHERE key='foreground_context_local:'||OLD.id; END;")?;
        tx.commit()?;
        Ok(())
    }
    pub(crate) fn native_foreground_reserve(
        &self,
        human: i64,
        entry: SessionKey,
        dialogue: &str,
    ) -> Result<Option<ReturnDispatch>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let Some(doc) =
            crate::store::live_context::reserve_on(&tx, human, entry, dialogue, &self.instance_id)?
        else {
            return Ok(None);
        };
        let p: ForegroundParent = serde_json::from_value(doc)?;
        let context = ReturnContext::foreground(p);
        let index = context.native_returns.len() - 1;
        let r = &context.native_returns[index];
        let result = ReturnDispatch {
            name: context.name(),
            id: r.id.clone(),
            attempts: r.attempts,
            human,
            entry,
            native: context.native.clone(),
            epoch: context.epoch.clone(),
            output: context.output(index),
        };
        tx.commit()?;
        Ok(Some(result))
    }
}
