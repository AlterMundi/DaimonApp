//! Scoped interaction records never resurrect a native response channel.

use super::*;
use serde::{Deserialize, Serialize};
use sha2::Digest;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HumanInteraction {
    pub id: String,
    pub kind: String,
    pub state: String,
    pub requester: i64,
    pub native_thread: String,
    pub local_turn: i64,
    pub title: String,
    pub action: String,
    pub blocking: bool,
    pub source: serde_json::Value,
}

pub struct InteractionPage {
    pub items: Vec<HumanInteraction>,
    pub actionable_total: usize,
    pub pending_total: usize,
    pub history_total: usize,
}
#[derive(Debug, Clone)]
pub struct TaskWithdrawal {
    pub id: String,
    pub reason: String,
    pub links: serde_json::Value,
}

/// Project structured native async questions into the existing durable task ledger.
/// The native item is the immutable source; this creates no response channel.
pub(super) fn native_async_questions_on(
    conn: &Connection,
    local: i64,
    native: &str,
    physical: &str,
    item: &str,
    questions: &serde_json::Value,
) -> Result<usize> {
    use anyhow::bail;
    let rows = questions
        .as_array()
        .context("Invalid native async questions")?;
    if rows.is_empty() || rows.len() > 10 || serde_json::to_vec(questions)?.len() > 65_536 {
        bail!("Native async question bounds exceeded");
    }
    let (session, user): (i64, i64) = conn
        .query_row(
            "SELECT s.id,t.from_user_id FROM turns t JOIN sessions s ON s.id=t.session_id
         JOIN users u ON u.tg_user_id=t.from_user_id
         JOIN interaction_native_messages m ON m.local_turn=t.id AND m.native_thread=?2
           AND m.native_turn=?3 AND m.item_id=?4
         WHERE t.id=?1 AND t.native_thread_id=?2 AND s.codex_thread_id=?2
           AND s.creator_user_id=t.from_user_id AND s.force_fresh_thread=0 AND u.allowed=1",
            params![local, native, physical, item],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .context("Native async question has no current owned source")?;
    let mut prepared = Vec::new();
    for (index, row) in rows.iter().enumerate() {
        let title = row["title"]
            .as_str()
            .filter(|v| !v.trim().is_empty() && !v.contains('\0'))
            .context("Native async question title missing")?;
        let mut action = title.to_owned();
        if let Some(options) = row.get("options").filter(|value| !value.is_null()) {
            let options = options.as_array().context("Invalid native async choices")?;
            if options.len() > 32 {
                bail!("Native async choice bounds exceeded");
            }
            for option in options {
                let text = option
                    .as_str()
                    .filter(|v| !v.trim().is_empty() && !v.contains('\0'))
                    .context("Invalid native async choice")?;
                action.push_str("\n- ");
                action.push_str(text);
            }
        }
        if action.chars().count() > 8000 {
            bail!("Native async question text exceeds task bounds");
        }
        let identity = serde_json::json!([
            "native-async-question/v1",
            user,
            native,
            physical,
            item,
            index
        ]);
        let id = format!(
            "{:x}",
            sha2::Sha256::digest(identity.to_string().as_bytes())
        )[..32]
            .to_owned();
        let source = serde_json::json!({"links":[],"nativeAsyncQuestion":{
            "thread":native,"turn":physical,"item":item,"index":index,"question":row,
            "revision":format!("{:x}",sha2::Sha256::digest(serde_json::to_vec(row)?)),
            "meaning":"Ordinary conversational question; not a native RPC answer or approval."}});
        let entry = HumanInteraction {
            id: id.clone(),
            kind: "task".into(),
            state: "pending".into(),
            requester: user,
            native_thread: native.into(),
            local_turn: local,
            title: title.chars().take(120).collect(),
            action,
            blocking: false,
            source,
        };
        prepared.push((id, entry));
    }
    let mut fresh = Vec::new();
    for (id, entry) in prepared {
        let prior: Option<String> = conn
            .query_row(
                "SELECT payload_json FROM human_interactions WHERE id=?1",
                [&id],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(raw) = prior {
            let previous: HumanInteraction = serde_json::from_str(&raw)?;
            if previous.source != entry.source
                || previous.requester != user
                || previous.native_thread != native
            {
                bail!("Native async question source changed");
            }
            continue; // A repeated event must not reopen an answered/dismissed question.
        }
        fresh.push((id, entry));
    }
    let existing: usize = conn.query_row(
        "SELECT count(*) FROM human_interactions
        WHERE requester=?1 AND native_thread=?2 AND kind='task'
        AND json_extract(payload_json,'$.source.nativeAsyncQuestion.turn')=?3",
        params![user, native, physical],
        |r| r.get(0),
    )?;
    if existing + fresh.len() > 10 {
        bail!("Native async turn question bounds exceeded");
    }
    let mut inserted = 0;
    for (id, entry) in fresh {
        conn.execute(
            "INSERT INTO human_interactions(id,session_id,requester,native_thread,local_turn,
            kind,state,instance_id,client_id,payload_json,created_at,updated_at)
            VALUES(?1,?2,?3,?4,?5,'task','pending',?6,?1,?7,?8,?8)",
            params![
                id,
                session,
                user,
                native,
                local,
                "native-async-question/v1",
                serde_json::to_string(&entry)?,
                now_string()
            ],
        )?;
        inserted += 1;
    }
    Ok(inserted)
}

fn projected(
    mut item: HumanInteraction,
    state: String,
    current: Option<String>,
) -> HumanInteraction {
    item.state = if matches!(state.as_str(), "pending" | "answering" | "unknown")
        && current.as_deref() != Some(item.native_thread.as_str())
    {
        "source_changed".into()
    } else if state == "cancelled" && item.source["agentWithdrawal"].is_object() {
        "withdrawn".into()
    } else {
        state
    };
    item
}

// Reused by the observer so pending state and source cuts share its read snapshot.
pub(super) fn interaction_page_on(
    conn: &Connection,
    key: SessionKey,
    user: i64,
    offset: usize,
    history: bool,
) -> Result<InteractionPage> {
    let active =
        "h.state IN ('pending','answering','unknown') AND h.native_thread=s.codex_thread_id";
    let scope = "FROM human_interactions h JOIN sessions s ON s.id=h.session_id JOIN users u ON u.tg_user_id=h.requester WHERE s.chat_id=?1 AND s.thread_id=?2 AND h.requester=?3 AND u.allowed=1";
    let (actionable_total,pending_total,total):(usize,usize,usize)=conn.query_row(&format!("SELECT COALESCE(SUM(CASE WHEN {active} THEN 1 ELSE 0 END),0),COALESCE(SUM(CASE WHEN h.state='pending' AND h.native_thread=s.codex_thread_id THEN 1 ELSE 0 END),0),COUNT(*) {scope}"),params![key.chat_id,key.thread_id,user],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
    let items = {
        let query = format!(
            "SELECT h.payload_json,h.state,s.codex_thread_id {scope} AND (CASE WHEN {active} THEN 1 ELSE 0 END)=?5 ORDER BY CASE WHEN h.state='pending' THEN 0 ELSE 1 END,h.created_at DESC,h.id DESC LIMIT 51 OFFSET ?4"
        );
        let mut stmt = conn.prepare(&query)?;
        stmt.query_map(
            params![
                key.chat_id,
                key.thread_id,
                user,
                offset as i64,
                i64::from(!history)
            ],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, Option<String>>(2)?,
                ))
            },
        )?
        .map(|row| {
            let (raw, state, current) = row?;
            Ok(projected(serde_json::from_str(&raw)?, state, current))
        })
        .collect::<Result<Vec<_>>>()?
    };
    Ok(InteractionPage {
        items,
        actionable_total,
        pending_total,
        history_total: total - actionable_total,
    })
}

/// Same ledger mutation for completed-turn manifests and live scoped controllers.
#[allow(clippy::too_many_arguments)]
pub(super) fn withdraw_task_on(
    tx: &Connection,
    session: i64,
    user: i64,
    native: &str,
    turn: i64,
    entry: &TaskWithdrawal,
    actor: &serde_json::Value,
) -> Result<bool> {
    if entry.reason.trim().is_empty() || entry.reason.chars().count() > 2000 {
        return Err(anyhow!("withdrawal needs a bounded explicit reason"));
    }
    let links = entry
        .links
        .as_array()
        .context("withdrawal evidence must be links")?;
    if links.len() > 5 {
        return Err(anyhow!("too many withdrawal links"));
    }
    for link in links {
        let label = link["label"]
            .as_str()
            .context("missing withdrawal link label")?;
        let address = link["url"]
            .as_str()
            .context("missing withdrawal link address")?;
        let url = reqwest::Url::parse(address)?;
        if label.trim().is_empty()
            || label.chars().count() > 80
            || address.len() > 2048
            || !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err(anyhow!("invalid withdrawal evidence link"));
        }
    }
    let row:Option<(String,String)>=tx.query_row("SELECT state,payload_json FROM human_interactions WHERE id=?1 AND session_id=?2 AND requester=?3 AND native_thread=?4 AND kind='task'",params![entry.id,session,user,native],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
    let (state, raw) =
        row.context("withdrawal target is not an owned task in this source session")?;
    let mut doc: serde_json::Value = serde_json::from_str(&raw)?;
    if state == "cancelled"
        && doc["source"]["agentWithdrawal"]["reason"] == entry.reason
        && doc["source"]["agentWithdrawal"]["links"] == entry.links
        && (actor.is_null() || doc["source"]["agentWithdrawal"]["actor"] == *actor)
    {
        return Ok(false);
    }
    if state != "pending" {
        return Err(anyhow!(
            "withdrawal target is already resolved or has an uncertain receipt"
        ));
    }
    let at = now_string();
    doc["source"]["agentWithdrawal"] = serde_json::json!({"reason":entry.reason,"links":entry.links,"sourceTurn":turn,"at":at,"actor":actor});
    tx.execute("UPDATE human_interactions SET state='cancelled',payload_json=?2,updated_at=?3 WHERE id=?1 AND state='pending'",params![entry.id,serde_json::to_string(&doc)?,at])?;
    tx.execute("INSERT INTO audit_log(actor_user_id,action,details_json,created_at) VALUES(NULL,'human_task_withdrawn_by_agent',?1,?2)",params![serde_json::json!({"interaction_id":entry.id,"requester":user,"source_turn":turn,"reason":entry.reason,"links":entry.links,"actor":actor}).to_string(),at])?;
    if actor.is_object() {
        super::topic_publications::task_withdrawal_on(tx, &entry.id)?;
    }
    Ok(true)
}

impl Store {
    pub fn record_native_async_questions(
        &self,
        local: i64,
        native: &str,
        physical: &str,
        item: &str,
        questions: &serde_json::Value,
    ) -> Result<usize> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let count = native_async_questions_on(&tx, local, native, physical, item, questions)?;
        tx.commit()?;
        Ok(count)
    }
    pub(super) fn init_interactions(&self) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute_batch("CREATE TABLE IF NOT EXISTS human_interactions(
            id TEXT PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            requester INTEGER NOT NULL REFERENCES users(tg_user_id), native_thread TEXT NOT NULL,
            local_turn INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE, kind TEXT NOT NULL CHECK(kind IN ('native','task')),
            state TEXT NOT NULL CHECK(state IN ('pending','answering','answered','completed','cancelled','expired','unknown')),
            instance_id TEXT NOT NULL, client_id TEXT,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(local_turn,kind,client_id));
            CREATE INDEX IF NOT EXISTS human_interactions_scope
            ON human_interactions(session_id,requester,state);
            CREATE TABLE IF NOT EXISTS human_interaction_messages(
            chat_id INTEGER NOT NULL, thread_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            interaction_id TEXT NOT NULL REFERENCES human_interactions(id) ON DELETE CASCADE,
            PRIMARY KEY(chat_id,thread_id,message_id));")?;
        conn.execute("UPDATE human_interactions SET state=CASE WHEN state='pending' THEN 'expired' ELSE 'unknown' END,
            updated_at=?1 WHERE kind='native' AND state IN ('pending','answering') AND instance_id!=?2",
            params![now_string(),self.instance_id])?;
        Ok(())
    }

    pub fn save_interaction(
        &self,
        key: SessionKey,
        item: &HumanInteraction,
        client_id: Option<&str>,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let session: Option<i64> = conn.query_row("SELECT s.id FROM sessions s JOIN users u
            ON u.tg_user_id=?3 JOIN turns t ON t.session_id=s.id AND t.id=?5
            WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.codex_thread_id=?4 AND u.allowed=1 AND t.from_user_id=?3",
            params![key.chat_id,key.thread_id,item.requester,item.native_thread,item.local_turn],
            |r| r.get(0)).optional()?;
        let session = session.context("human interaction has no authorized source binding")?;
        conn.execute(
            "INSERT INTO human_interactions(id,session_id,requester,native_thread,local_turn,
            kind,state,instance_id,client_id,payload_json,created_at,updated_at)
            VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?11)",
            params![
                item.id,
                session,
                item.requester,
                item.native_thread,
                item.local_turn,
                item.kind,
                item.state,
                self.instance_id,
                client_id,
                serde_json::to_string(item)?,
                now_string()
            ],
        )?;
        Ok(())
    }

    /// Read-only attention across the owner's current internal sessions.
    /// This does not widen canonical For you, create a responder, or alter ingress.
    pub fn internal_pending_page(
        &self,
        human: i64,
        entry: SessionKey,
        after: i64,
    ) -> Result<serde_json::Value> {
        if after < 0 {
            anyhow::bail!("Invalid internal pending cursor");
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (entry_session, native) = super::presentation::entry_on(&tx, human, entry)?;
        let binding = super::presentation::entry_binding(&tx, human, entry, entry_session)?;
        let mut stmt = tx.prepare(
            "SELECT h.rowid,h.payload_json,h.state,s.chat_id,s.thread_id,s.session_title,
                    h.created_at,h.updated_at
             FROM human_interactions h JOIN sessions s ON s.id=h.session_id
             JOIN users u ON u.tg_user_id=h.requester JOIN turns t ON t.id=h.local_turn
             WHERE h.rowid>?1 AND h.requester=?2 AND s.creator_user_id=?2 AND u.allowed=1
               AND s.id<>?3 AND h.kind IN ('task','native')
               AND h.state IN ('pending','answering','unknown')
               AND s.force_fresh_thread=0 AND s.codex_thread_id=h.native_thread
               AND t.session_id=s.id AND t.from_user_id=?2 AND t.native_thread_id=h.native_thread
             ORDER BY h.rowid LIMIT 21",
        )?;
        let rows = stmt
            .query_map(params![after, human, entry_session], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i64>(3)?,
                    r.get::<_, i64>(4)?,
                    r.get::<_, Option<String>>(5)?,
                    r.get::<_, String>(6)?,
                    r.get::<_, String>(7)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let more = rows.len() > 20;
        let mut cursor = after;
        let mut items = Vec::new();
        for (sequence, raw, state, chat, topic, label, created, updated) in
            rows.into_iter().take(20)
        {
            let mut item: HumanInteraction = serde_json::from_str(&raw)?;
            item.state = state;
            let target = SessionKey::new(chat, Some(topic));
            let revision = format!(
                "{:x}",
                sha2::Sha256::digest(
                    serde_json::json!(["internal-pending/v1", binding, target, item])
                        .to_string()
                        .as_bytes()
                )
            );
            items.push(serde_json::json!({"id":item.id,"kind":item.kind,"state":item.state,
                "target":target,"label":label.unwrap_or_else(||format!("Session {topic}")).chars().take(120).collect::<String>(),
                "title":item.title.chars().take(200).collect::<String>(),"preview":item.action.chars().take(240).collect::<String>(),
                "revision":revision,"created_at":created,"updated_at":updated,
                "source_native":item.native_thread,"live_response":"not_established_by_ledger_read"}));
            cursor = sequence;
        }
        drop(stmt);
        tx.commit()?;
        Ok(
            serde_json::json!({"schema":"telecodex.internal-pending-list/v1",
            "binding":binding,"entry_binding":[human,entry,entry_session,native],
            "items":items,"cursor":cursor,"more":more,"read_only":true}),
        )
    }

    #[cfg(test)]
    pub fn interactions(&self, key: SessionKey, user: i64) -> Result<Vec<HumanInteraction>> {
        let mut pending = self.interactions_page(key, user, 0, false)?.items;
        pending.extend(self.interactions_page(key, user, 0, true)?.items);
        Ok(pending)
    }

    pub fn interactions_page(
        &self,
        key: SessionKey,
        user: i64,
        offset: usize,
        history: bool,
    ) -> Result<InteractionPage> {
        // Counts and page share a read snapshot, including concurrent owner-local maintenance.
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let page = interaction_page_on(&tx, key, user, offset, history)?;
        tx.commit()?;
        Ok(page)
    }

    pub fn interaction(
        &self,
        key: SessionKey,
        user: i64,
        id: &str,
    ) -> Result<Option<HumanInteraction>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let row = conn
            .query_row(
                "SELECT h.payload_json,h.state,s.codex_thread_id FROM human_interactions h
            JOIN sessions s ON s.id=h.session_id JOIN users u ON u.tg_user_id=h.requester
            WHERE s.chat_id=?1 AND s.thread_id=?2 AND h.requester=?3 AND h.id=?4 AND u.allowed=1",
                params![key.chat_id, key.thread_id, user, id],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, Option<String>>(2)?,
                    ))
                },
            )
            .optional()?;
        row.map(|(payload, state, current)| {
            let mut item = projected(serde_json::from_str(&payload)?, state, current);
            if let Some(update) = item.source["answerUpdateId"].as_i64() {
                let delivery: Option<String> = conn
                    .query_row(
                        "SELECT status FROM incoming_updates WHERE update_id=?1",
                        [update],
                        |r| r.get(0),
                    )
                    .optional()?;
                item.source["delivery"] =
                    serde_json::json!(delivery.unwrap_or_else(|| "unknown".into()));
            }
            Ok(item)
        })
        .transpose()
    }

    #[cfg(test)]
    pub fn save_human_tasks(
        &self,
        key: SessionKey,
        tasks: &[(String, HumanInteraction)],
    ) -> Result<()> {
        self.save_human_requests(key, tasks, None)
    }
    #[cfg(test)]
    pub fn save_human_requests(
        &self,
        key: SessionKey,
        tasks: &[(String, HumanInteraction)],
        withdrawal: Option<(i64, &str, i64, &[TaskWithdrawal])>,
    ) -> Result<()> {
        self.save_human_requests_checked(key, tasks, withdrawal, None)
            .map(|_| ())
    }
    pub fn save_human_requests_checked(
        &self,
        key: SessionKey,
        tasks: &[(String, HumanInteraction)],
        withdrawal: Option<(i64, &str, i64, &[TaskWithdrawal])>,
        live: Option<(&LiveTaskActor<'_>, &tokio_util::sync::CancellationToken)>,
    ) -> Result<Vec<String>> {
        use anyhow::bail;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        if let Some((actor, closed)) = live {
            super::live_tasks::actor_on(&tx, actor, closed)?;
            if key != actor.key
                || tasks.iter().any(|(_, item)| {
                    item.requester != actor.human
                        || item.native_thread != actor.native
                        || item.local_turn != actor.local
                })
                || withdrawal.is_some_and(|(user, native, turn, rows)| {
                    user != actor.human
                        || native != actor.native
                        || turn != actor.local
                        || !rows.is_empty()
                })
            {
                bail!("Live task declaration differs from current actor");
            }
        }
        let mut receipts = Vec::new();
        for (client, item) in tasks {
            let prior: Option<(String,String)> = tx.query_row(
                "SELECT h.id,h.payload_json FROM human_interactions h JOIN sessions s ON s.id=h.session_id JOIN users u ON u.tg_user_id=h.requester WHERE h.local_turn=?1 AND h.kind='task' AND h.client_id=?2 AND s.chat_id=?3 AND s.thread_id=?4 AND s.codex_thread_id=h.native_thread AND u.allowed=1",
                params![item.local_turn,client,key.chat_id,key.thread_id], |r| Ok((r.get(0)?,r.get(1)?))).optional()?;
            if let Some((id, raw)) = prior {
                let previous: HumanInteraction = serde_json::from_str(&raw)?;
                if previous.requester != item.requester
                    || previous.native_thread != item.native_thread
                    || previous.title != item.title
                    || previous.action != item.action
                    || previous.source["links"] != item.source["links"]
                {
                    bail!("Human task declaration changed; original retained");
                }
                receipts.push(id);
                continue;
            }
            let count: i64 = tx.query_row(
                "SELECT count(*) FROM human_interactions WHERE local_turn=?1 AND kind='task'",
                [item.local_turn],
                |r| r.get(0),
            )?;
            if count >= 10 {
                bail!("Task declarations exceed ten per logical turn");
            }
            receipts.push(item.id.clone());
            let session: Option<i64> = tx
                .query_row(
                    "SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=?3
                JOIN turns t ON t.session_id=s.id AND t.id=?5 WHERE s.chat_id=?1 AND s.thread_id=?2
                AND s.codex_thread_id=?4 AND u.allowed=1 AND t.from_user_id=?3",
                    params![
                        key.chat_id,
                        key.thread_id,
                        item.requester,
                        item.native_thread,
                        item.local_turn
                    ],
                    |r| r.get(0),
                )
                .optional()?;
            let session = session.context("human task has no authorized source binding")?;
            tx.execute(
                "INSERT INTO human_interactions(id,session_id,requester,native_thread,local_turn,
                kind,state,instance_id,client_id,payload_json,created_at,updated_at)
                VALUES(?1,?2,?3,?4,?5,'task','pending',?6,?7,?8,?9,?9)",
                params![
                    item.id,
                    session,
                    item.requester,
                    item.native_thread,
                    item.local_turn,
                    self.instance_id,
                    client,
                    serde_json::to_string(item)?,
                    now_string()
                ],
            )?;
        }
        if let Some((user, native, turn, withdrawals)) = withdrawal {
            let session:Option<i64>=tx.query_row("SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=?3 JOIN turns t ON t.session_id=s.id AND t.id=?5 WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.codex_thread_id=?4 AND u.allowed=1 AND t.from_user_id=?3",params![key.chat_id,key.thread_id,user,native,turn],|r|r.get(0)).optional()?;
            let session = session.context("withdrawal has no authorized current source binding")?;
            for entry in withdrawals {
                withdraw_task_on(
                    &tx,
                    session,
                    user,
                    native,
                    turn,
                    entry,
                    &serde_json::Value::Null,
                )?;
            }
        }
        if let Some((actor, closed)) = live {
            super::live_tasks::actor_on(&tx, actor, closed)?;
        }
        tx.commit()?;
        Ok(receipts)
    }

    pub fn update_native_interaction(
        &self,
        id: &str,
        title: &str,
        action: &str,
        index: usize,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute("UPDATE human_interactions SET payload_json=json_set(payload_json,'$.title',?2,'$.action',?3,'$.source.conversationIndex',?6),updated_at=?4
            WHERE id=?1 AND instance_id=?5 AND kind='native' AND state='pending'",
            params![id,title,action,now_string(),self.instance_id,index as i64])?;
        Ok(())
    }

    pub fn transition_interaction(
        &self,
        key: SessionKey,
        user: i64,
        id: &str,
        from: &str,
        to: &str,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.execute("UPDATE human_interactions SET state=?5,updated_at=?6
            WHERE id=?4 AND requester=?3 AND state=?7 AND (kind='task' OR instance_id=?8) AND session_id IN
            (SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=?3
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND u.allowed=1 AND s.codex_thread_id=human_interactions.native_thread)",
            params![key.chat_id,key.thread_id,user,id,to,now_string(),from,self.instance_id])?==1)
    }

    pub fn finish_native_interactions(
        &self,
        turn: i64,
        request: Option<&crate::user_input::NativeRequestId>,
        accepted: bool,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let request = request.map(serde_json::to_string).transpose()?;
        conn.execute(
            "UPDATE human_interactions SET state=CASE
            WHEN ?3=1 AND state='answering' THEN 'answered'
            WHEN state='answering' THEN 'unknown' ELSE 'expired' END,updated_at=?4
            WHERE kind='native' AND local_turn=?1 AND state IN ('pending','answering')
            AND (?2 IS NULL OR json_extract(payload_json,'$.source.requestId')=?2)",
            params![turn, request, accepted, now_string()],
        )?;
        Ok(())
    }

    pub fn answer_human_task(
        &self,
        key: SessionKey,
        user: i64,
        id: &str,
        update: i64,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.execute("UPDATE human_interactions SET state='answered',updated_at=?5,
            payload_json=json_set(payload_json,'$.source.answerUpdateId',?6)
            WHERE id=?4 AND kind='task' AND state='pending' AND requester=?3
            AND session_id IN (SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=?3
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND u.allowed=1 AND s.codex_thread_id=human_interactions.native_thread)",
            params![key.chat_id,key.thread_id,user,id,now_string(),update])?==1)
    }

    pub fn record_interaction_message(
        &self,
        key: SessionKey,
        message: i64,
        id: &str,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute(
            "INSERT INTO human_interaction_messages VALUES(?1,?2,?3,?4)",
            params![key.chat_id, key.thread_id, message, id],
        )?;
        Ok(())
    }

    pub fn interaction_message(&self, key: SessionKey, message: i64) -> Result<Option<String>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.query_row("SELECT interaction_id FROM human_interaction_messages WHERE chat_id=?1 AND thread_id=?2 AND message_id=?3",
                       params![key.chat_id,key.thread_id,message],|r|r.get(0)).optional().map_err(Into::into)
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use serde_json::json;
    fn fixture() -> (tempfile::TempDir, Store, SessionKey, i64) {
        let root = tempfile::tempdir().unwrap();
        let defaults = SessionDefaults {
            cwd: root.path().into(),
            model: None,
            reasoning_effort: None,
            session_prompt: None,
            sandbox_mode: "read-only".into(),
            approval_policy: "never".into(),
            search_mode: crate::config::SearchMode::Disabled,
            add_dirs: vec![],
        };
        let store = Store::open(&root.path().join("db"), &[100, 101], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        store.set_session_codex_thread(key, "source").unwrap();
        let turn = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: "Human-directed work".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        (root, store, key, turn)
    }
    fn task(id: &str, turn: i64) -> HumanInteraction {
        HumanInteraction {
            id: id.into(),
            kind: "task".into(),
            state: "pending".into(),
            requester: 100,
            native_thread: "source".into(),
            local_turn: turn,
            title: "A long mobile title ".repeat(5),
            action: "Do the selected human action".into(),
            blocking: false,
            source: json!({"links":[]}),
        }
    }
    fn withdrawal(id: &str) -> TaskWithdrawal {
        TaskWithdrawal {
            id: id.into(),
            reason: "The selected handoff is already observed; no human approval is inferred"
                .into(),
            links: json!([{ "label":"Evidence","url":"https://example.org/receipt" }]),
        }
    }
    #[test]
    fn native_async_questions_reuse_tasks_without_responder_or_reopening() {
        let (_root, store, key, turn) = fixture();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .record_native_message(
                turn,
                "source",
                "physical",
                "question",
                Some("final_answer"),
                "Choose",
            )
            .unwrap();
        let questions = json!([{"title":"Choose a symbol","options":["Luna","Estrella"]}]);
        assert_eq!(
            store
                .record_native_async_questions(turn, "source", "physical", "question", &questions)
                .unwrap(),
            1
        );
        let page = store.interactions_page(key, 100, 0, false).unwrap();
        assert_eq!(page.pending_total, 1);
        let question = &page.items[0];
        assert_eq!(question.kind, "task");
        assert!(!question.blocking);
        assert_eq!(question.action, "Choose a symbol\n- Luna\n- Estrella");
        assert!(question.source["requestId"].is_null());
        assert_eq!(question.source["nativeAsyncQuestion"]["item"], "question");
        let view = store
            .conversation_human_task(100, key, &question.id)
            .unwrap();
        assert_eq!(view["native_question"]["question"], questions[0]);
        assert!(
            store
                .conversation_human_task(101, key, &question.id)
                .is_err()
        );
        assert_eq!(
            store
                .record_native_async_questions(turn, "source", "physical", "question", &questions)
                .unwrap(),
            0
        );
        store
            .transition_interaction(key, 100, &question.id, "pending", "answered")
            .unwrap();
        assert_eq!(
            store
                .record_native_async_questions(turn, "source", "physical", "question", &questions)
                .unwrap(),
            0
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 0, false)
                .unwrap()
                .pending_total,
            0
        );
        assert!(
            store
                .record_native_async_questions(
                    turn,
                    "source",
                    "physical",
                    "question",
                    &json!([{"title":"Changed"}])
                )
                .is_err()
        );
        assert!(
            store
                .record_native_async_questions(turn, "other", "physical", "question", &questions)
                .is_err()
        );
        assert!(
            store
                .record_native_async_questions(turn, "source", "unobserved", "question", &questions)
                .is_err()
        );
    }

    #[test]
    fn native_async_question_bounds_are_atomic() {
        let (_root, store, key, turn) = fixture();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .record_native_message(
                turn,
                "source",
                "physical",
                "question",
                Some("final_answer"),
                "Choose",
            )
            .unwrap();
        let invalid = json!([{"title":"Valid"},{"title":"Invalid","options":[123]}]);
        assert!(
            store
                .record_native_async_questions(turn, "source", "physical", "question", &invalid)
                .is_err()
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 0, false)
                .unwrap()
                .pending_total,
            0
        );
        assert!(
            store
                .record_native_async_questions(turn, "source", "physical", "question", &json!([]))
                .is_err()
        );
    }

    #[test]
    fn native_async_freeform_questions_and_turn_bound_preserve_closed_cards() {
        let (_root, store, key, turn) = fixture();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .record_native_message(
                turn,
                "source",
                "physical",
                "open",
                Some("final_answer"),
                "Questions",
            )
            .unwrap();
        let questions =
            json!([{"title":"Tell me more"},{"title":"Any preference?","options":null}]);
        assert_eq!(
            store
                .record_native_async_questions(turn, "source", "physical", "open", &questions)
                .unwrap(),
            2
        );
        let page = store.interactions_page(key, 100, 0, false).unwrap();
        assert_eq!(page.pending_total, 2);
        for row in page.items {
            assert!(!row.action.contains("\n-"));
            store
                .transition_interaction(key, 100, &row.id, "pending", "cancelled")
                .unwrap();
        }
        assert_eq!(
            store
                .record_native_async_questions(turn, "source", "physical", "open", &questions)
                .unwrap(),
            0
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 0, false)
                .unwrap()
                .pending_total,
            0
        );
        store
            .record_native_message(
                turn,
                "source",
                "physical",
                "excess",
                Some("final_answer"),
                "More",
            )
            .unwrap();
        let excess = serde_json::Value::Array(
            (0..9)
                .map(|i| json!({"title":format!("Question {i}")}))
                .collect(),
        );
        assert!(
            store
                .record_native_async_questions(turn, "source", "physical", "excess", &excess)
                .is_err()
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 0, true)
                .unwrap()
                .history_total,
            2
        );
    }
    #[test]
    fn internal_pending_keeps_entry_separate_and_rechecks_source_ownership() {
        let (_root, store, worker, turn) = fixture();
        let entry = SessionKey::new(100, Some(9));
        let defaults = super::super::tests::defaults();
        store.ensure_session(entry, 100, &defaults).unwrap();
        store.set_session_codex_thread(entry, "integrator").unwrap();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .save_human_tasks(worker, &[("worker-task".into(), task("worker-task", turn))])
            .unwrap();
        let page = store.internal_pending_page(100, entry, 0).unwrap();
        assert_eq!(page["items"].as_array().unwrap().len(), 1);
        assert_eq!(page["items"][0]["id"], "worker-task");
        assert_eq!(page["items"][0]["target"], json!(worker));
        assert!(page["read_only"].as_bool().unwrap());
        assert!(store.internal_pending_page(101, entry, 0).is_err());
        assert!(store.internal_pending_page(100, entry, -1).is_err());
        assert!(
            store.internal_pending_page(100, worker, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        let cursor = page["cursor"].as_i64().unwrap();
        assert!(
            store.internal_pending_page(100, entry, cursor).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        store
            .set_session_codex_thread(worker, "replacement")
            .unwrap();
        assert!(
            store.internal_pending_page(100, entry, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        store.set_session_codex_thread(worker, "source").unwrap();
        {
            let conn = store.conn.lock().unwrap();
            conn.execute("UPDATE turns SET from_user_id=101 WHERE id=?1", [turn])
                .unwrap();
        }
        assert!(
            store.internal_pending_page(100, entry, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn internal_task_detail_and_dismiss_share_ledger_without_widening_for_you() {
        let (_root, store, worker, turn) = fixture();
        let entry = SessionKey::new(100, Some(9));
        store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store.set_session_codex_thread(entry, "integrator").unwrap();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .save_human_tasks(
                worker,
                &[("direct-action".into(), task("direct-action", turn))],
            )
            .unwrap();
        assert!(
            store
                .conversation_human_task(100, entry, "direct-action")
                .is_err()
        );
        assert!(
            store
                .internal_human_task(101, entry, "direct-action")
                .is_err()
        );
        let selected = store
            .internal_human_task(100, entry, "direct-action")
            .unwrap();
        let binding = selected["binding"].as_str().unwrap();
        let revision = selected["revision"].as_str().unwrap();
        assert!(
            store
                .internal_dismiss_human_task(100, entry, binding, "direct-action", &"0".repeat(64))
                .is_err()
        );
        let result = store
            .internal_dismiss_human_task(100, entry, binding, "direct-action", revision)
            .unwrap();
        assert_eq!(result["state"], "cancelled");
        assert_eq!(result["human_completion"], false);
        assert_eq!(result["work_cancelled"], false);
        assert_eq!(
            store
                .internal_dismiss_human_task(100, entry, binding, "direct-action", revision)
                .unwrap()["new_dismissal"],
            false
        );
        assert!(
            store
                .conversation_human_task(100, entry, "direct-action")
                .is_err()
        );
        assert!(
            store.internal_pending_page(100, entry, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn internal_pending_pages_do_not_drop_or_repeat_items() {
        let (_root, store, worker, turn) = fixture();
        let entry = SessionKey::new(100, Some(9));
        store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store.record_turn_native_thread(turn, "source").unwrap();
        // Historical ledgers may exceed the new declaration bound; pagination must retain them.
        for index in 0..23 {
            let id = format!("worker-{index}");
            store
                .save_interaction(worker, &task(&id, turn), Some(&id))
                .unwrap();
        }
        store
            .transition_interaction(worker, 100, "worker-2", "pending", "completed")
            .unwrap();
        let first = store.internal_pending_page(100, entry, 0).unwrap();
        assert_eq!(first["items"].as_array().unwrap().len(), 20);
        assert_eq!(first["more"], true);
        let second = store
            .internal_pending_page(100, entry, first["cursor"].as_i64().unwrap())
            .unwrap();
        assert_eq!(second["items"].as_array().unwrap().len(), 2);
        assert_eq!(second["more"], false);
        let ids: std::collections::BTreeSet<_> = first["items"]
            .as_array()
            .unwrap()
            .iter()
            .chain(second["items"].as_array().unwrap())
            .map(|v| v["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids.len(), 22);
        assert!(!ids.contains("worker-2"));
    }

    #[test]
    fn pages_have_topic_totals_and_separate_terminal_history() {
        let (_root, store, key, turn) = fixture();
        // Populate retained historical rows without using the bounded new-declaration writer.
        for n in 0..60 {
            let id = format!("task-{n:03}");
            store
                .save_interaction(key, &task(&id, turn), Some(&id))
                .unwrap();
        }
        store
            .transition_interaction(key, 100, "task-000", "pending", "completed")
            .unwrap();
        store
            .transition_interaction(key, 100, "task-001", "pending", "cancelled")
            .unwrap();
        let mut unknown = task("native-unknown", turn);
        unknown.kind = "native".into();
        unknown.state = "unknown".into();
        store.save_interaction(key, &unknown, None).unwrap();
        let page = store.interactions_page(key, 100, 0, false).unwrap();
        assert_eq!(
            (
                page.actionable_total,
                page.pending_total,
                page.history_total,
                page.items.len()
            ),
            (59, 58, 2, 51)
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 50, false)
                .unwrap()
                .items
                .len(),
            9
        );
        let history = store.interactions_page(key, 100, 0, true).unwrap();
        assert_eq!(history.items.len(), 2);
        assert!(
            history
                .items
                .iter()
                .all(|i| matches!(i.state.as_str(), "completed" | "cancelled"))
        );
        assert!(
            store
                .interactions_page(key, 101, 0, false)
                .unwrap()
                .items
                .is_empty()
        );
        assert!(
            store
                .interactions_page(SessionKey::new(100, Some(8)), 100, 0, true)
                .unwrap()
                .items
                .is_empty()
        );
        store.set_session_codex_thread(key, "replacement").unwrap();
        assert_eq!(
            store
                .interactions_page(key, 100, 0, false)
                .unwrap()
                .actionable_total,
            0
        );
        assert!(
            store
                .interactions_page(key, 100, 0, true)
                .unwrap()
                .items
                .iter()
                .any(|i| i.state == "source_changed")
        );
    }
    #[test]
    fn withdrawal_is_scoped_audited_idempotent_and_cannot_reopen() {
        let (_root, store, key, turn) = fixture();
        store
            .save_human_tasks(key, &[("old".into(), task("old", turn))])
            .unwrap();
        let entry = withdrawal("old");
        store
            .save_human_requests(
                key,
                &[],
                Some((100, "source", turn, std::slice::from_ref(&entry))),
            )
            .unwrap();
        let item = store.interaction(key, 100, "old").unwrap().unwrap();
        assert_eq!(item.state, "withdrawn");
        assert_eq!(item.source["agentWithdrawal"]["sourceTurn"], turn);
        assert_eq!(item.action, "Do the selected human action");
        assert_eq!(
            store
                .interactions_page(key, 100, 0, false)
                .unwrap()
                .pending_total,
            0
        );
        assert_eq!(
            store
                .interactions_page(key, 100, 0, true)
                .unwrap()
                .history_total,
            1
        );
        store
            .save_human_requests(key, &[], Some((100, "source", turn, &[entry])))
            .unwrap();
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT COUNT(*) FROM audit_log WHERE action='human_task_withdrawn_by_agent'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            1
        );
        assert!(
            !store
                .transition_interaction(key, 100, "old", "pending", "completed")
                .unwrap()
        );
        assert!(!store.answer_human_task(key, 100, "old", 1).unwrap());
        let mut changed = withdrawal("old");
        changed.reason = "Another claimed reason".into();
        assert!(
            store
                .save_human_requests(key, &[], Some((100, "source", turn, &[changed])))
                .is_err()
        );
    }
    #[test]
    fn mixed_declaration_rolls_back_and_wrong_binding_native_or_resolved_targets_refuse() {
        let (_root, store, key, turn) = fixture();
        store
            .save_human_tasks(key, &[("old".into(), task("old", turn))])
            .unwrap();
        let entries = [withdrawal("old"), withdrawal("missing")];
        assert!(
            store
                .save_human_requests(
                    key,
                    &[("new".into(), task("new", turn))],
                    Some((100, "source", turn, &entries))
                )
                .is_err()
        );
        assert!(store.interaction(key, 100, "new").unwrap().is_none());
        assert_eq!(
            store.interaction(key, 100, "old").unwrap().unwrap().state,
            "pending"
        );
        for (wrong_key, user, native) in [
            (SessionKey::new(100, Some(8)), 100, "source"),
            (key, 101, "source"),
            (key, 100, "other-source"),
        ] {
            assert!(
                store
                    .save_human_requests(
                        wrong_key,
                        &[],
                        Some((user, native, turn, &[withdrawal("old")]))
                    )
                    .is_err()
            );
        }
        let mut channel = task("channel", turn);
        channel.kind = "native".into();
        channel.state = "unknown".into();
        store.save_interaction(key, &channel, None).unwrap();
        assert!(
            store
                .save_human_requests(
                    key,
                    &[],
                    Some((100, "source", turn, &[withdrawal("channel")]))
                )
                .is_err()
        );
        assert_eq!(
            store
                .interaction(key, 100, "channel")
                .unwrap()
                .unwrap()
                .state,
            "unknown"
        );
        store
            .transition_interaction(key, 100, "old", "pending", "completed")
            .unwrap();
        assert!(
            store
                .save_human_requests(key, &[], Some((100, "source", turn, &[withdrawal("old")])))
                .is_err()
        );
        assert_eq!(
            store.interaction(key, 100, "old").unwrap().unwrap().state,
            "completed"
        );
    }
    #[test]
    fn live_publication_is_atomic_bounded_and_never_reopens_originals() {
        use crate::store::LiveTaskActor;
        use tokio_util::sync::CancellationToken;
        let (_root, store, key, turn) = fixture();
        store.record_turn_native_thread(turn, "source").unwrap();
        let closed = CancellationToken::new();
        let actor = LiveTaskActor {
            key,
            human: 100,
            local: turn,
            native: "source",
            physical: "current",
            integrator: false,
        };
        let mut entry = task("original", turn);
        let publish = |rows: &[(String, HumanInteraction)]| {
            store.save_human_requests_checked(key, rows, None, Some((&actor, &closed)))
        };
        assert_eq!(
            publish(&[("phone".into(), entry.clone())]).unwrap(),
            vec!["original"]
        );
        store
            .transition_interaction(key, 100, "original", "pending", "completed")
            .unwrap();
        entry.id = "retry-uuid".into();
        assert_eq!(
            publish(&[("phone".into(), entry.clone())]).unwrap(),
            vec!["original"]
        );
        assert_eq!(
            store
                .interaction(key, 100, "original")
                .unwrap()
                .unwrap()
                .state,
            "completed"
        );
        // Final manifest uses the same receipt rather than duplicating a live request.
        store
            .save_human_requests(key, &[("phone".into(), entry.clone())], None)
            .unwrap();
        let mut changed = entry.clone();
        changed.action = "Different task".into();
        assert!(
            publish(&[
                ("fresh".into(), task("fresh", turn)),
                ("phone".into(), changed)
            ])
            .is_err()
        );
        assert!(store.interaction(key, 100, "fresh").unwrap().is_none());
        let mut foreign = entry.clone();
        foreign.requester = 101;
        assert!(publish(&[("foreign".into(), foreign)]).is_err());
        let many: Vec<_> = (0..10)
            .map(|n| (format!("task-{n}"), task(&format!("task-{n}"), turn)))
            .collect();
        assert!(publish(&many).is_err());
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM human_interactions", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            1
        );
        closed.cancel();
        assert!(publish(&[("cancelled".into(), entry)]).is_err());
    }

    #[test]
    fn live_retirement_requires_current_actor_and_exact_task_and_preserves_human_meaning() {
        use crate::store::LiveTaskActor;
        use tokio_util::sync::CancellationToken;
        let (_root, store, key, turn) = fixture();
        store.record_turn_native_thread(turn, "source").unwrap();
        store
            .save_human_tasks(key, &[("live".into(), task("live", turn))])
            .unwrap();
        let closed = CancellationToken::new();
        let actor = LiveTaskActor {
            key,
            human: 100,
            local: turn,
            native: "source",
            physical: "actual-physical",
            integrator: false,
        };
        let page = store.live_human_tasks(&actor, 0, &closed).unwrap();
        assert_eq!(page["items"].as_array().unwrap().len(), 1);
        let selected = store.live_human_task(&actor, "live", &closed).unwrap();
        let revision = selected["revision"].as_str().unwrap();
        assert!(
            store
                .live_withdraw_task(&actor, &"0".repeat(64), &withdrawal("live"), &closed)
                .is_err()
        );
        let result = store
            .live_withdraw_task(&actor, revision, &withdrawal("live"), &closed)
            .unwrap();
        assert_eq!(result["new_withdrawal"], true);
        assert_eq!(result["human_completion"], false);
        assert_eq!(
            store
                .live_withdraw_task(&actor, revision, &withdrawal("live"), &closed)
                .unwrap()["new_withdrawal"],
            false
        );
        let item = store.interaction(key, 100, "live").unwrap().unwrap();
        assert_eq!(item.state, "withdrawn");
        assert_eq!(item.action, "Do the selected human action");
        assert!(
            store.topic_publication_inventory(100).unwrap()["items"]
                .as_array()
                .unwrap()
                .iter()
                .all(|item| item["kind"] != "task_control")
        );
        assert_eq!(
            item.source["agentWithdrawal"]["actor"]["session"],
            json!(key)
        );
        assert_eq!(
            store.live_human_tasks(&actor, 0, &closed).unwrap()["items"]
                .as_array()
                .unwrap()
                .len(),
            0
        );
        store
            .save_human_tasks(key, &[("pending".into(), task("pending", turn))])
            .unwrap();
        let selected = store.live_human_task(&actor, "pending", &closed).unwrap();
        store
            .transition_interaction(key, 100, "pending", "pending", "answered")
            .unwrap();
        assert!(
            store
                .live_withdraw_task(
                    &actor,
                    selected["revision"].as_str().unwrap(),
                    &withdrawal("pending"),
                    &closed
                )
                .is_err()
        );
        let mut channel = task("native-question", turn);
        channel.kind = "native".into();
        store.save_interaction(key, &channel, None).unwrap();
        assert!(
            store
                .live_human_task(&actor, "native-question", &closed)
                .is_err()
        );
        assert!(
            store
                .live_withdraw_task(
                    &actor,
                    &"0".repeat(64),
                    &withdrawal("native-question"),
                    &closed
                )
                .is_err()
        );
        store
            .save_human_tasks(
                key,
                &[("uncertain-task".into(), task("uncertain-task", turn))],
            )
            .unwrap();
        let uncertain = store
            .live_human_task(&actor, "uncertain-task", &closed)
            .unwrap();
        store
            .transition_interaction(key, 100, "uncertain-task", "pending", "unknown")
            .unwrap();
        assert!(
            store
                .live_withdraw_task(
                    &actor,
                    uncertain["revision"].as_str().unwrap(),
                    &withdrawal("uncertain-task"),
                    &closed
                )
                .is_err()
        );
        let stranger = LiveTaskActor {
            human: 101,
            ..actor
        };
        assert!(store.live_human_tasks(&stranger, 0, &closed).is_err());
        closed.cancel();
        assert!(store.live_human_tasks(&actor, 0, &closed).is_err());
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT COUNT(*) FROM audit_log WHERE action='human_task_withdrawn_by_agent'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            1
        );
    }
}
