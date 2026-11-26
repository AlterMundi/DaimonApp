//! Selected native workers use the existing original and turn journal.
use super::*;
use crate::{
    execution::Harness,
    interaction::MatrixDestination,
    store::{ClaudeContinuation, valid_claude_scope},
};
use serde_json::{Value, json};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub(crate) struct Selection {
    pub harness: Harness,
    pub body: MatrixDestination,
    binding: String,
}

struct PreviousExecution {
    input_row: i64,
    status: String,
    native_session: Option<String>,
    scope: Option<String>,
    body: Option<String>,
}

impl ConversationInput {
    pub(crate) fn targets_claude(&self) -> bool {
        self.private_matrix.is_some()
            || self
                .portable
                .as_ref()
                .is_some_and(|target| target.harness == Harness::Claude)
    }

    pub(super) fn same_selected_route(
        &self,
        signed: Option<&PrivateMatrixSelection>,
        host: bool,
        portable: Option<&Selection>,
    ) -> bool {
        self.private_matrix.as_ref() == signed
            && self.private_matrix_host_access == host
            && self.portable.as_ref() == portable
            || portable.is_some_and(|target| {
                self.private_matrix_host_access
                    && self
                        .private_matrix
                        .as_ref()
                        .is_some_and(|prior| prior.recipient == target.body)
            })
    }

    pub(super) fn portable_reply(&self, conn: &Connection) -> Result<Option<String>> {
        if self.phase != "claude_replied" {
            return Ok(None);
        }
        let (Some(target), Some(local)) = (&self.portable, self.local_turn) else {
            return Ok(None);
        };
        Ok(conn
            .query_row(
                "SELECT assistant_text FROM turns WHERE id=?1 AND session_id=?2 AND from_user_id=?3
               AND execution_harness=?4 AND status='completed' AND assistant_text IS NOT NULL",
                params![local, self.session, self.human, target.harness.name()],
                |r| r.get(0),
            )
            .optional()?)
    }

    pub(super) fn reply_view(&self, conn: &Connection) -> Result<Option<Value>> {
        if let Some(reply) = self.portable_reply(conn)? {
            let text: String = reply.chars().take(2048).collect();
            let next = (text.len() < reply.len()).then_some(2048);
            return Ok(Some(
                json!({"text":text,"message_id":self.id,"next_offset":next}),
            ));
        }
        Ok(self
            .private_matrix_reply
            .as_ref()
            .map(|reply| json!({"text":reply.text,"message_id":reply.event_id})))
    }
}

pub(super) fn current_on(conn: &Connection, input: &ConversationInput) -> Result<bool> {
    let Some(target) = &input.portable else {
        return Ok(false);
    };
    let Ok((session, _)) = crate::store::presentation::entry_on(conn, input.human, input.entry)
    else {
        return Ok(false);
    };
    Ok(session == input.session
        && crate::store::presentation::entry_binding(conn, input.human, input.entry, session)?
            == target.binding)
}

fn admitted_on(conn: &Connection, input: &ConversationInput, writer: &str) -> Result<bool> {
    Ok(current_on(conn, input)?
        && crate::store::stopping::admission_epoch_on(conn, input.entry)? == input.epoch
        && !crate::store::stopping::fenced_on(conn, input.entry)?
        && !crate::store::maintenance_writer_held_on(conn, input.entry)?
        && conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?1)",
            [writer],
            |row| row.get::<_, bool>(0),
        )?)
}

pub(in crate::store) fn portable_controller_on(
    conn: &Connection,
    local: i64,
    key: SessionKey,
    human: i64,
    writer: &str,
) -> Result<Harness> {
    let id: String = conn
        .query_row(
            "SELECT id FROM conversation_inputs WHERE local_turn=?1 AND human_id=?2
         AND instance_id=?3 AND phase='sending' AND retired=0
         AND json_type(doc,'$.portable')='object'",
            params![local, human, writer],
            |row| row.get(0),
        )
        .optional()?
        .context("Controller original is unavailable for this attempt")?;
    let input = read_on(conn, &id, human)?;
    anyhow::ensure!(
        input.entry == key && admitted_on(conn, &input, writer)?,
        "Controller original or admission changed"
    );
    Ok(input
        .portable
        .context("Portable selection unavailable")?
        .harness)
}

pub(super) fn recover_retired_writer(conn: &Connection, writer: &str) -> Result<()> {
    conn.execute(
        "UPDATE turns SET status='failed',completed_at=?2
        WHERE status='running' AND execution_harness<>'codex' AND id IN (
            SELECT local_turn FROM conversation_inputs WHERE instance_id<>?1
             AND phase IN ('queued','sending') AND json_type(doc,'$.portable')='object')",
        params![writer, now_string()],
    )?;
    conn.execute("UPDATE sessions SET busy=0 WHERE id IN (
        SELECT session_id FROM conversation_inputs WHERE instance_id<>?1
          AND local_turn IS NOT NULL AND phase IN ('queued','sending') AND json_type(doc,'$.portable')='object')
        AND NOT EXISTS (SELECT 1 FROM turns WHERE session_id=sessions.id AND status='running')",[writer])?;
    Ok(())
}

fn signed_predecessor(
    conn: &Connection,
    input: &ConversationInput,
    target: &Selection,
    body: &Value,
    after: i64,
) -> Result<Option<Option<ClaudeContinuation>>> {
    let row: Option<(String,String,String,Option<String>)> = conn.query_row(
        "SELECT c.doc,m.doc,m.phase,m.submission FROM conversation_inputs c
         JOIN interaction_matrix_requests m ON m.claude_input=c.id AND m.human_id=c.human_id AND m.entry_session=c.session_id
         WHERE c.session_id=?1 AND c.human_id=?2 AND m.source_channel='/we'
           AND json_extract(c.doc,'$.private_matrix_host_access')=1
           AND json_extract(m.doc,'$.entry_generation')=?3 AND c.rowid>?4
           AND (m.phase NOT IN ('starting','rejected') OR json_extract(m.submission,'$.reason')='claude_resume_session_missing')
         ORDER BY c.rowid DESC LIMIT 1", params![input.session,input.human,target.binding,after],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
    let Some((original, request, phase, outcome)) = row else {
        return Ok(None);
    };
    let Some(outcome) = outcome.filter(|_| phase == "delivered") else {
        return Ok(Some(None));
    };
    let original: ConversationInput = serde_json::from_str(&original)?;
    let request: Value = serde_json::from_str(&request)?;
    let outcome: Value = serde_json::from_str(&outcome)?;
    if original
        .private_matrix
        .as_ref()
        .is_none_or(|selected| selected.recipient != target.body)
        || original
            .private_matrix_origin
            .as_ref()
            .is_none_or(|origin| {
                request["original"]["event_id"] != origin.message_id
                    || request["original"]["receipt_event_id"] != origin.receipt_event_id
            })
        || original.private_matrix_reply.as_ref().is_none_or(|reply| {
            outcome["delivery"]["message_id"] != reply.event_id
                || outcome["delivery"]["receipt_event_id"] != reply.receipt_event_id
        })
        || request["body"]["manifest_hash"] != body["manifestHash"]
        || request["body"]["local_origin"]["incarnation_id"] != body["incarnationId"]
        || request["body"]["local_origin"]["embodiment_id"] != body["embodimentId"]
    {
        return Ok(Some(None));
    };
    Ok(Some(
        outcome["native_session_id"]
            .as_str()
            .filter(|value| Uuid::parse_str(value).is_ok_and(|u| u.to_string() == *value))
            .zip(
                outcome["native_session_scope"]
                    .as_str()
                    .filter(|scope| valid_claude_scope(scope)),
            )
            .map(|(session_id, scope)| ClaudeContinuation {
                session_id: session_id.into(),
                scope: scope.into(),
            }),
    ))
}

impl Store {
    pub(crate) fn capture_portable_turn(
        &self,
        human: i64,
        entry: SessionKey,
        binding: &str,
        id: &str,
        text: &str,
        body: &MatrixDestination,
    ) -> Result<(ConversationInput, bool)> {
        body.validate()?;
        anyhow::ensure!(
            matches!(body, MatrixDestination::Body { .. }) && text.len() <= 16384,
            "Invalid selected portable destination"
        );
        self.capture_original_mode(
            human,
            entry,
            binding,
            id,
            text,
            None,
            true,
            None,
            None,
            None,
            None,
            Vec::new(),
            None,
            None,
            Some(SelectedRoute::Portable(Selection {
                harness: Harness::Claude,
                body: body.clone(),
                binding: binding.into(),
            })),
        )
    }

    pub(crate) fn queue_portable_turn(&self, input: &ConversationInput) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = read_on(&tx, &input.id, input.human)?;
        let pending: i64 = tx.query_row(
            "SELECT count(*) FROM conversation_inputs WHERE session_id=?1 AND phase='queued'
               AND instance_id=?2 AND json_type(doc,'$.portable')='object'",
            params![input.session, self.instance_id],
            |row| row.get(0),
        )?;
        let ready = current.phase == "retained"
            && admitted_on(&tx, &current, &self.instance_id)?
            && pending < 4;
        let phase = if ready { "queued" } else { "retained_unsent" };
        let changed = tx.execute(
            "UPDATE conversation_inputs SET phase=?1
            WHERE id=?2 AND instance_id=?3 AND phase='retained'",
            params![phase, input.id, self.instance_id],
        )?;
        tx.commit()?;
        Ok(ready && changed == 1)
    }

    pub(crate) fn begin_portable_turn(
        &self,
        input: &ConversationInput,
        request: &TurnRequest,
    ) -> Result<i64> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = read_on(&tx, &input.id, input.human)?;
        let target = current
            .portable
            .as_ref()
            .context("Portable target missing")?;
        anyhow::ensure!(
            current.phase == "queued"
                && current.local_turn.is_none()
                && request.session_key == current.entry
                && request.from_user_id == current.human
                && request.prompt == current.text
                && admitted_on(&tx, &current, &self.instance_id)?,
            "Portable original cannot begin"
        );
        let local = crate::store::record_turn_started_on(&tx, current.session, request, None)?;
        tx.execute(
            "UPDATE turns SET execution_harness=?1 WHERE id=?2",
            params![target.harness.name(), local],
        )?;
        anyhow::ensure!(tx.execute("UPDATE conversation_inputs SET local_turn=?1
            WHERE id=?2 AND phase='queued' AND instance_id=?3 AND json_extract(doc,'$.queue_start_claimed')=1",
            params![local,input.id,self.instance_id])?==1, "Portable original was not claimed by this worker");
        tx.execute("UPDATE sessions SET busy=1 WHERE id=?1", [current.session])?;
        tx.commit()?;
        Ok(local)
    }

    pub(crate) fn prior_portable_session(
        &self,
        input: &ConversationInput,
        local: i64,
        body: &Value,
    ) -> Result<Option<ClaudeContinuation>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let target = input.portable.as_ref().context("Portable target missing")?;
        let prior: Option<PreviousExecution>=conn.query_row(
            "SELECT p.rowid,t.status,t.native_thread_id,t.execution_native_scope,t.execution_body FROM turns t
             JOIN conversation_inputs p ON p.local_turn=t.id
             JOIN turns current ON current.id=?1 AND current.session_id=t.session_id
             WHERE t.id<current.id AND t.from_user_id=?2 AND t.execution_harness=?3
               AND t.execution_generation=current.execution_generation AND
                  (t.native_thread_id IS NOT NULL OR t.execution_native_scope='resume_unavailable')
             ORDER BY t.id DESC LIMIT 1",params![local,input.human,target.harness.name()],
            |r| Ok(PreviousExecution{input_row:r.get(0)?,status:r.get(1)?,native_session:r.get(2)?,
                scope:r.get(3)?,body:r.get(4)?})).optional()?;
        let after = prior.as_ref().map_or(0, |prior| prior.input_row);
        if let Some(signed) = signed_predecessor(&conn, input, target, body, after)? {
            return Ok(signed);
        }
        if let Some(PreviousExecution {
            status,
            native_session: Some(session_id),
            scope: Some(scope),
            body: Some(identity),
            ..
        }) = prior
        {
            return Ok((status == "completed"
                && valid_claude_scope(&scope)
                && serde_json::from_str::<Value>(&identity)? == *body)
                .then_some(ClaudeContinuation { session_id, scope }));
        }
        Ok(None)
    }

    pub(crate) fn expose_portable_turn(
        &self,
        input: &ConversationInput,
        local: i64,
        body: &Value,
        prepared: &Value,
    ) -> Result<bool> {
        let session = prepared["native_session_id"]
            .as_str()
            .filter(|id| Uuid::parse_str(id).is_ok_and(|x| x.to_string() == *id))
            .context("Native session required")?;
        let scope = prepared["native_session_scope"]
            .as_str()
            .filter(|x| valid_claude_scope(x))
            .context("Native session scope required")?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = read_on(&tx, &input.id, input.human)?;
        if current.phase != "queued"
            || current.local_turn != Some(local)
            || !admitted_on(&tx, &current, &self.instance_id)?
        {
            return Ok(false);
        }
        let changed=tx.execute("UPDATE turns SET native_thread_id=?1,execution_native_scope=?2,execution_body=?3
            WHERE id=?4 AND status='running' AND native_thread_id IS NULL
             AND execution_generation=(SELECT generation FROM conversation_entry_generations WHERE session_id=turns.session_id)",
            params![session,scope,body.to_string(),local])?;
        if changed != 1 {
            return Ok(false);
        }
        tx.execute(
            "UPDATE conversation_inputs SET phase='sending' WHERE id=?1",
            [&input.id],
        )?;
        tx.commit()?;
        Ok(true)
    }

    pub(crate) fn finish_portable_turn(
        &self,
        input: &ConversationInput,
        local: i64,
        reply: Option<&str>,
        resume_unavailable: bool,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = read_on(&tx, &input.id, input.human)?;
        anyhow::ensure!(
            current.local_turn == Some(local) && current.portable.is_some(),
            "Portable result belongs to another attempt"
        );
        let (status, phase) = match (current.phase.as_str(), reply) {
            ("sending", Some(_)) => ("completed", "claude_replied"),
            ("sending", None) => ("failed", "claude_unconfirmed"),
            ("queued", None) => ("failed", "claude_rejected"),
            _ => bail!("Portable turn is already settled or unexposed"),
        };
        anyhow::ensure!(tx.execute("UPDATE turns SET status=?1,assistant_text=?2,completed_at=?3
            WHERE id=?4 AND status='running' AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?5)",
            params![status,reply,now_string(),local,self.instance_id])?==1,"Portable result owner changed");
        if resume_unavailable && current.phase == "queued" {
            tx.execute(
                "UPDATE turns SET execution_native_scope='resume_unavailable' WHERE id=?1",
                [local],
            )?;
        }
        tx.execute(
            "UPDATE conversation_inputs SET phase=?1 WHERE id=?2",
            params![phase, input.id],
        )?;
        tx.execute("UPDATE sessions SET busy=0 WHERE id=?1", [current.session])?;
        tx.commit()?;
        Ok(())
    }

    pub(crate) fn portable_turn_running(&self, key: SessionKey, human: i64) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id
             JOIN conversation_inputs c ON c.local_turn=t.id AND c.session_id=s.id
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3
               AND t.from_user_id=?3 AND t.execution_harness<>'codex' AND t.status='running'
               AND c.instance_id=?4 AND json_type(c.doc,'$.portable')='object')",
            params![key.chat_id, key.thread_id, human, self.instance_id],
            |row| row.get(0),
        )?)
    }

    pub(crate) fn conversation_claude_reply(
        &self,
        input: &ConversationInput,
    ) -> Result<Option<Value>> {
        input.reply_view(&self.conn.lock().expect("store mutex poisoned"))
    }
}
