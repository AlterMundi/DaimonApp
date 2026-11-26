//! Direct portable workers use the canonical routed instruction and result.
use super::*;
use crate::{
    execution::Harness,
    interaction::{Delivery, Instruction, TransportPhase as Phase},
};
use anyhow::bail;
use serde_json::Value;

struct PriorExecution {
    status: String,
    session: Option<String>,
    scope: Option<String>,
    body: Option<String>,
}

fn current_on(conn: &Connection, input: &Instruction, writer: &str) -> Result<bool> {
    let source = super::routing::source_on(conn, &input.id, input.human_id)?;
    if source.channel != "conversation"
        || source.tribu_source.is_some()
        || source.update_id.is_some()
    {
        return Ok(false);
    }
    Ok(input
        .target_execution
        .as_ref()
        .is_some_and(|binding| binding.harness.is_portable())
        && super::interaction::target_execution_allowed_on(conn, input)?
        && super::dialogue::dispatched_source_on(conn, &input.id, input.human_id, writer)?
        && input.admission_epoch.as_deref()
            == Some(super::stopping::admission_epoch_on(conn, input.target)?.as_str())
        && !super::stopping::fenced_on(conn, input.target)?
        && !super::maintenance_writer_held_on(conn, input.target)?
        && conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?1)",
            [writer],
            |row| row.get::<_, bool>(0),
        )?)
}

pub(super) fn recover_on(conn: &Connection, writer: &str) -> Result<()> {
    conn.execute(
        "UPDATE turns SET status='failed',completed_at=?2 WHERE status='running'
        AND execution_harness<>'codex' AND id IN (SELECT json_extract(doc,'$.local_turn')
        FROM interaction_instructions WHERE instance_id<>?1 AND phase IN ('queued','submitting','cancelled'))",
        params![writer, now_string()],
    )?;
    conn.execute("UPDATE sessions SET busy=0 WHERE busy=1 AND id IN (
        SELECT i.session_id FROM interaction_instructions i JOIN turns t ON t.id=json_extract(i.doc,'$.local_turn')
        WHERE i.instance_id<>?1 AND i.phase IN ('queued','submitting','cancelled') AND t.execution_harness<>'codex')
        AND NOT EXISTS(SELECT 1 FROM turns WHERE session_id=sessions.id AND status='running')",[writer])?;
    Ok(())
}

impl Store {
    pub(crate) fn begin_routed_portable(
        &self,
        input: &Instruction,
        request: &TurnRequest,
    ) -> Result<(i64, bool)> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = super::interaction::instruction_on(&tx, &input.id, input.human_id)?
            .context("Routed input missing")?;
        anyhow::ensure!(
            current.phase == Phase::Queued
                && current.local_turn.is_none()
                && current.target == request.session_key
                && current.human_id == request.from_user_id
                && current_on(&tx, &current, &self.instance_id)?,
            "Routed input retired before native preparation"
        );
        let source = super::routing::source_on(&tx, &current.id, current.human_id)?;
        let original =
            super::conversation_inputs::read_on(&tx, &source.event_id, current.human_id)?;
        let local =
            super::record_turn_started_on(&tx, current.target_session, request, Some(&current.id))?;
        let harness = current
            .target_execution
            .as_ref()
            .context("Routed harness is missing")?
            .harness;
        tx.execute(
            "UPDATE turns SET execution_harness=?2 WHERE id=?1",
            params![local, harness.name()],
        )?;
        super::interaction::transport_on(
            &tx,
            &current.id,
            current.human_id,
            local,
            Phase::Queued,
            None,
        )?;
        tx.execute(
            "UPDATE sessions SET busy=1 WHERE id=?1",
            [current.target_session],
        )?;
        tx.commit()?;
        Ok((local, original.paired_actor))
    }

    pub(crate) fn routed_claude_continuation(
        &self,
        local: i64,
        body: &Value,
    ) -> Result<Option<ClaudeContinuation>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let prior: Option<PriorExecution> = conn.query_row(
            "SELECT p.status,p.native_thread_id,p.execution_native_scope,p.execution_body
             FROM turns p JOIN turns t ON t.id=?1 AND t.session_id=p.session_id
             WHERE p.id<t.id AND p.execution_harness='claude' AND p.execution_generation=t.execution_generation
               AND (p.native_thread_id IS NOT NULL OR p.execution_native_scope='resume_unavailable')
             ORDER BY p.id DESC LIMIT 1",[local],|r|Ok(PriorExecution { status:r.get(0)?, session:r.get(1)?, scope:r.get(2)?, body:r.get(3)? }),
        ).optional()?;
        let Some(PriorExecution {
            status,
            session: Some(session_id),
            scope: Some(scope),
            body: Some(identity),
        }) = prior
        else {
            return Ok(None);
        };
        Ok((status == "completed"
            && valid_claude_scope(&scope)
            && serde_json::from_str::<Value>(&identity)? == *body)
            .then_some(ClaudeContinuation { session_id, scope }))
    }

    pub(crate) fn expose_routed_portable(
        &self,
        input: &Instruction,
        local: i64,
        body: &Value,
        prepared: &Value,
    ) -> Result<bool> {
        let harness = input
            .target_execution
            .as_ref()
            .context("Routed harness is missing")?
            .harness;
        let native = prepared["native_session_id"]
            .as_str()
            .filter(|id| match harness {
                Harness::Claude | Harness::Antigravity => {
                    Uuid::parse_str(id).is_ok_and(|v| v.to_string() == *id)
                }
                Harness::Goose => {
                    !id.is_empty()
                        && id.len() <= 256
                        && !id.chars().any(|ch| ch.is_control() || ch.is_whitespace())
                }
                Harness::Codex => false,
            })
            .context("Routed native session missing or invalid")?;
        let scope = if harness == Harness::Claude {
            Some(
                prepared["native_session_scope"]
                    .as_str()
                    .filter(|v| valid_claude_scope(v))
                    .context("Routed native session scope missing")?,
            )
        } else {
            None
        };
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = super::interaction::instruction_on(&tx, &input.id, input.human_id)?
            .context("Routed input missing")?;
        if current.phase != Phase::Queued
            || current.local_turn != Some(local)
            || !current_on(&tx, &current, &self.instance_id)?
        {
            return Ok(false);
        }
        let changed = tx.execute("UPDATE turns SET native_thread_id=?1,execution_native_scope=?2,execution_body=?3
            WHERE id=?4 AND status='running' AND execution_harness=?5 AND native_thread_id IS NULL
            AND execution_generation=(SELECT generation FROM conversation_entry_generations WHERE session_id=turns.session_id)",
            params![native,scope,body.to_string(),local,harness.name()])?;
        if changed != 1 {
            return Ok(false);
        }
        super::interaction::transport_on(
            &tx,
            &input.id,
            input.human_id,
            local,
            Phase::Submitting,
            None,
        )?;
        tx.commit()?;
        Ok(true)
    }

    pub(crate) fn finish_routed_portable(
        &self,
        input: &Instruction,
        local: i64,
        outcome: &Value,
    ) -> Result<Vec<Delivery>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = super::interaction::instruction_on(&tx, &input.id, input.human_id)?
            .context("Routed input missing")?;
        anyhow::ensure!(
            current.local_turn == Some(local),
            "Retained routed attempt changed"
        );
        let reply = match (current.phase, outcome["phase"].as_str()) {
            (Phase::Submitting, Some("completed"))
                if current.native_thread.as_deref() == outcome["sessionId"].as_str() =>
            {
                Some(
                    outcome["text"]
                        .as_str()
                        .context("Routed native reply missing")?,
                )
            }
            (Phase::Submitting | Phase::Queued | Phase::Cancelled, _) => None,
            _ => bail!("Routed native attempt already settled"),
        };
        let mut deliveries = Vec::new();
        if let Some(text) = reply {
            let native = current
                .native_thread
                .as_deref()
                .context("Routed native writer missing")?;
            // Portable adapters bound a discrete exchange, not a Codex turn.
            // Reserve a Gateway turn anchor qualified by the selected harness.
            let harness = current
                .target_execution
                .as_ref()
                .context("Routed harness is missing")?
                .harness;
            let anchor = format!("gateway:{}:{}", harness.name(), input.id);
            super::interaction::transport_on(
                &tx,
                &input.id,
                input.human_id,
                local,
                Phase::Accepted,
                Some(&anchor),
            )?;
            deliveries = super::routing::result_on(
                &tx,
                &self.instance_id,
                &input.id,
                input.human_id,
                local,
                native,
                &anchor,
                "final",
                text,
                true,
                true,
            )?;
        } else if current.phase != Phase::Cancelled {
            let phase = match current.phase {
                Phase::Queued => Phase::RetainedUnsent,
                _ if outcome["phase"] == "not_submitted" => Phase::Rejected,
                _ => Phase::Uncertain,
            };
            super::interaction::transport_on(&tx, &input.id, input.human_id, local, phase, None)?;
        }
        let resume_unavailable = outcome["reason"] == "claude_resume_session_missing";
        anyhow::ensure!(tx.execute("UPDATE turns SET status=?1,assistant_text=?2,completed_at=?3,
            execution_native_scope=CASE WHEN ?5 THEN 'resume_unavailable' ELSE execution_native_scope END
            WHERE id=?4 AND status='running'
              AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?6)",
            params![if reply.is_some() {"completed"} else {"failed"},reply,now_string(),local,resume_unavailable,self.instance_id])?==1,
            "Routed result writer changed");
        tx.execute(
            "UPDATE sessions SET busy=0 WHERE id=?1 AND NOT EXISTS (SELECT 1 FROM turns WHERE session_id=?1 AND status='running')",
            [input.target_session],
        )?;
        tx.commit()?;
        Ok(deliveries)
    }
}
