//! Direct portable workers use the canonical routed instruction and result.
use super::*;
use crate::{
    execution::Harness,
    interaction::{Delivery, Instruction, SourceInput, TransportPhase as Phase},
};
use anyhow::bail;
use serde_json::Value;

pub(super) fn telegram_original_epoch(
    conn: &Connection,
    source: &SourceInput,
    target: SessionKey,
) -> Result<Option<String>> {
    let Some(update) = source.update_id else {
        return Ok(None);
    };
    // Match the exact Telegram original. A cross-topic route additionally
    // requires retained native acceptance in the owned source conversation.
    if source.event_id != update.to_string()
        || source.tribu_source.is_some()
        || source.transcription.is_some()
        || source.origin.chat_id != target.chat_id
        || source.text.len() > 16 * 1024
    {
        return Ok(None);
    }
    let retained: Option<(String, String, String)> = conn
        .query_row(
            "SELECT i.payload_json, e.value, i.status FROM incoming_updates i
         JOIN bot_state e ON e.key='stop_input_epoch:'||i.update_id
         JOIN bot_state b ON b.key='telegram_identity'
         WHERE i.update_id=?1
           AND ?2='telegram:'||json_extract(b.value,'$.id')",
            params![update, source.channel],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    let Some((raw, epoch, status)) = retained else {
        return Ok(None);
    };
    let original: crate::telegram::Update = serde_json::from_str(&raw)?;
    let matching = original.update_id == update
        && original.message.is_some_and(|message| {
            Some(message.message_id) == source.origin.message_id
                && message.chat.id == target.chat_id
                && message.message_thread_id == Some(source.origin.thread_id)
                && message
                    .from
                    .as_ref()
                    .is_some_and(|user| user.id == source.human_id && !user.is_bot)
                && if source.telegram_files.is_empty() {
                    original.direct_human_text
                        && message.text.as_deref() == Some(source.text.as_str())
                        && message.is_text_only()
                } else {
                    original.direct_human_attachment
                        && source.origin.thread_id == target.thread_id
                        && message.has_own_attachment()
                        && message.attachment_caption() == source.text
                }
        });
    if !matching {
        return Ok(None);
    }
    if source.origin.thread_id == target.thread_id {
        return Ok(matches!(status.as_str(), "processing" | "handled").then_some(epoch));
    }
    let origin = SessionKey::new(source.origin.chat_id, Some(source.origin.thread_id));
    let native: Option<String> = conn
        .query_row(
            "SELECT codex_thread_id FROM sessions WHERE chat_id=?1 AND thread_id=?2
             AND creator_user_id=?3 AND force_fresh_thread=0",
            params![origin.chat_id, origin.thread_id, source.human_id],
            |row| row.get(0),
        )
        .optional()?
        .flatten();
    let Some(native) = native else {
        return Ok(None);
    };
    let accepted =
        super::dialogue::entry_inputs_on(conn, origin, source.human_id, &native, Some(update))?;
    Ok((!accepted.is_empty()).then_some(epoch))
}

fn current_on(conn: &Connection, input: &Instruction, writer: &str) -> Result<bool> {
    let source = super::routing::source_on(conn, &input.id, input.human_id)?;
    let allowed = if source.channel == "conversation" {
        source.tribu_source.is_none()
            && source.update_id.is_none()
            && super::dialogue::dispatched_source_on(conn, &input.id, input.human_id, writer)?
    } else if matches!(
        source.channel.as_str(),
        "local-session" | "local-session-result"
    ) {
        let expected = if source.channel == "local-session" {
            "session_request"
        } else {
            "session_result"
        };
        super::session_requests::author_on(conn, &input.input_id)?
            .is_some_and(|value| value["kind"] == expected)
            && super::session_requests::session_input_allowed_on(conn, &input.id, input.human_id)?
    } else {
        telegram_original_epoch(conn, &source, input.target)?
            .as_ref()
            .is_some_and(|epoch| Some(epoch) == input.admission_epoch.as_ref())
    };
    if !allowed {
        return Ok(false);
    }
    Ok(input
        .target_execution
        .as_ref()
        .is_some_and(|binding| binding.harness.is_portable())
        && super::interaction::target_execution_allowed_on(conn, input)?
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

#[allow(clippy::too_many_arguments)]
pub(super) fn controller_parent_on(
    conn: &Connection,
    parent: &Instruction,
    caller: SessionKey,
    human: i64,
    native: &str,
    turn: &str,
    local: i64,
    instance: &str,
) -> Result<bool> {
    if parent.id != turn
        || parent.target != caller
        || parent.human_id != human
        || parent.phase != Phase::Submitting
        || parent.local_turn != Some(local)
        || parent.native_thread.as_deref() != Some(native)
        || !parent
            .target_execution
            .as_ref()
            .is_some_and(|value| value.harness == Harness::Claude)
        || super::session_requests::author_on(conn, &parent.input_id)?.is_some()
        || !current_on(conn, parent, instance)?
    {
        return Ok(false);
    }
    Ok(conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id
         JOIN users u ON u.tg_user_id=s.creator_user_id
         JOIN conversation_entry_generations g ON g.session_id=s.id
         JOIN interaction_instructions i ON i.session_id=s.id
         WHERE t.id=?1 AND t.session_id=?2 AND t.from_user_id=?3 AND s.creator_user_id=?3
           AND u.allowed=1 AND t.native_thread_id=?4 AND t.execution_harness='claude'
           AND t.execution_generation=g.generation AND t.status='running'
           AND i.id=?5 AND i.instance_id=?6 AND i.phase='submitting')",
        params![local, parent.target_session, human, native, turn, instance],
        |row| row.get(0),
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
    pub(crate) fn routed_portable_status(
        &self,
        session: i64,
        human: i64,
        engine: &str,
    ) -> Result<(Option<String>, i64)> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.query_row(
            "SELECT (SELECT t.started_at FROM turns t WHERE t.session_id=s.id AND t.from_user_id=?2
                AND t.execution_harness=?3 AND t.status='running' ORDER BY t.id DESC LIMIT 1),
                (SELECT count(*) FROM interaction_instructions i
                 WHERE i.session_id=s.id AND i.instance_id=?4 AND i.phase='queued'
                 AND json_extract(i.doc,'$.target_execution.harness')=?3
                 AND json_extract(i.doc,'$.local_turn') IS NULL)
             FROM sessions s WHERE s.id=?1 AND s.creator_user_id=?2",
            params![session, human, engine, self.instance_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?)
    }

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
        let paired = if source.channel == "conversation" {
            super::conversation_inputs::read_on(&tx, &source.event_id, current.human_id)?
                .paired_actor
        } else {
            // A retained same-session result may continue its opted-in, already
            // authorized parent, while a new session-authored request has no
            // independent grant to the paired human's host tools.
            source.channel != "local-session"
        };
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
        Ok((local, paired))
    }

    pub(crate) fn routed_claude_continuations(
        &self,
        local: i64,
        body: &Value,
    ) -> Result<Vec<ClaudeContinuation>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        // The worker has already been selected for this authenticated body.
        // A manifest-only update preserves local history for the same incarnation.
        // The worker and Gateway still require the exact effective scope before exposure.
        let mut entries = conn.prepare(
            "WITH prior AS (
                SELECT p.id,p.status,p.native_thread_id,p.execution_native_scope AS scope
                FROM turns p JOIN turns t ON t.id=?1 AND t.session_id=p.session_id
                WHERE p.id<t.id AND p.execution_harness='claude'
                  AND p.execution_generation=t.execution_generation
                  AND (p.execution_native_scope='resume_unavailable'
                       OR (p.native_thread_id IS NOT NULL
                           AND json_extract(p.execution_body,'$.beingRef')=json_extract(?2,'$.beingRef')
                           AND json_extract(p.execution_body,'$.embodimentId')=json_extract(?2,'$.embodimentId')
                           AND json_extract(p.execution_body,'$.incarnationId')=json_extract(?2,'$.incarnationId')))
                  AND NOT EXISTS (SELECT 1 FROM interaction_instructions i
                    WHERE i.session_id=p.session_id AND i.phase='rejected'
                    AND json_extract(i.doc,'$.local_turn')=p.id
                    AND json_type(i.doc,'$.subscription_limit')='object')
             ), ranked AS (
                SELECT *,row_number() OVER (PARTITION BY scope ORDER BY id DESC) AS position
                FROM prior WHERE id>coalesce((SELECT max(id) FROM prior WHERE scope='resume_unavailable'),0)
             )
             SELECT native_thread_id,scope FROM ranked
             WHERE position=1 AND status='completed' AND scope IS NOT NULL
             ORDER BY id DESC LIMIT 8",
        )?;
        let rows = entries.query_map(params![local, serde_json::to_string(body)?], |row| {
            Ok(ClaudeContinuation {
                session_id: row.get(0)?,
                scope: row.get(1)?,
            })
        })?;
        let mut valid = Vec::new();
        for row in rows {
            let row = row?;
            if valid_claude_scope(&row.scope)
                && Uuid::parse_str(&row.session_id)
                    .is_ok_and(|uuid| uuid.to_string() == row.session_id)
            {
                valid.push(row);
            }
        }
        Ok(valid)
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
        let limit = (current.phase == Phase::Submitting
            && current.native_thread.as_deref() == outcome["sessionId"].as_str()
            && current
                .target_execution
                .as_ref()
                .is_some_and(|binding| binding.harness == Harness::Claude))
        .then(|| crate::interaction::SubscriptionLimit::from_worker(outcome))
        .flatten();
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
                _ if outcome["phase"] == "not_submitted"
                    || (limit.is_some()
                        && crate::interaction::SubscriptionLimit::refused_before_work(outcome)) =>
                {
                    Phase::Rejected
                }
                _ => Phase::Uncertain,
            };
            super::interaction::transport_on(&tx, &input.id, input.human_id, local, phase, None)?;
            if let Some(limit) = limit {
                tx.execute(
                    "UPDATE interaction_instructions
                    SET doc=json_set(doc,'$.subscription_limit',json(?2)) WHERE id=?1",
                    params![input.id, serde_json::to_string(&limit)?],
                )?;
            }
        }
        let missing = (outcome["reason"] == "claude_resume_session_missing")
            .then_some(&outcome["resumeUnavailable"]);
        let missing_scope =
            missing.map(|candidate| candidate["scope"].as_str().unwrap_or("resume_unavailable"));
        let missing_session = missing.and_then(|candidate| candidate["sessionId"].as_str());
        let missing_body = outcome
            .get("resumeUnavailableBody")
            .map(serde_json::to_string)
            .transpose()?;
        anyhow::ensure!(tx.execute("UPDATE turns SET status=?1,assistant_text=?2,completed_at=?3,
            execution_native_scope=coalesce(?5,execution_native_scope),
            native_thread_id=coalesce(?7,native_thread_id),execution_body=coalesce(?8,execution_body)
            WHERE id=?4 AND status='running'
              AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?6)",
            params![if reply.is_some() {"completed"} else {"failed"},reply,now_string(),local,missing_scope,self.instance_id,missing_session,missing_body])?==1,
            "Routed result writer changed");
        tx.execute(
            "UPDATE sessions SET busy=0 WHERE id=?1 AND NOT EXISTS (SELECT 1 FROM turns WHERE session_id=?1 AND status='running')",
            [input.target_session],
        )?;
        tx.commit()?;
        Ok(deliveries)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_continuations_keep_each_exact_scope_and_fence_uncertain_work() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        let body = serde_json::json!({"beingRef":"same", "embodimentId":"same", "incarnationId":"same","manifestHash":"selected"});
        let prior_body = serde_json::json!({"beingRef":"same", "embodimentId":"same", "incarnationId":"same","manifestHash":"other"});
        let first = "a".repeat(64);
        let second = "b".repeat(64);
        let third = "c".repeat(64);
        let record = |status: &str, scope: &str, identity: &Value| {
            let native = Uuid::new_v4().to_string();
            let conn = store.conn.lock().unwrap();
            let local = conn.query_row(
                "INSERT INTO turns (session_id,from_user_id,prompt,status,started_at,native_thread_id,
                     execution_harness,execution_generation,execution_native_scope,execution_body)
                 VALUES (?1,100,'scope test',?2,'2026-11-26',?3,'claude','same',?4,?5) RETURNING id",
                params![session.id,status,&native,scope,identity.to_string()], |r| r.get::<_, i64>(0),
            ).unwrap();
            (local, native)
        };
        let (_, one) = record("completed", &first, &body);
        record("completed", &second, &body);
        record("completed", &third, &body);
        record("failed", &third, &body);
        let (_, from_previous_manifest) = record("completed", &second, &prior_body);
        let other_incarnation = serde_json::json!({
            "beingRef":"same","embodimentId":"same","incarnationId":"retired","manifestHash":"selected"
        });
        record("completed", &second, &other_incarnation);
        let (local, _) = record("running", "", &body);
        let scopes = store.routed_claude_continuations(local, &body).unwrap();
        assert_eq!(
            scopes
                .iter()
                .map(|c| c.session_id.as_str())
                .collect::<Vec<_>>(),
            vec![from_previous_manifest.as_str(), one.as_str()]
        );
        record("failed", &first, &body);
        let (next, _) = record("running", "", &body);
        let scopes = store.routed_claude_continuations(next, &body).unwrap();
        assert_eq!(scopes.len(), 1);
        assert_eq!(scopes[0].session_id, from_previous_manifest);
        record("failed", "resume_unavailable", &body);
        let (next, _) = record("running", "", &body);
        assert!(
            store
                .routed_claude_continuations(next, &body)
                .unwrap()
                .is_empty()
        );
    }
}
