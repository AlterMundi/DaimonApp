//! Direct portable workers use the canonical routed instruction and result.
use super::*;
use crate::{
    execution::Harness,
    interaction::{Delivery, Instruction, SourceInput, TransportPhase as Phase},
};
use anyhow::bail;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

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

fn paired_host_access_on(conn: &Connection, input: &Instruction) -> Result<bool> {
    let source = super::routing::source_on(conn, &input.id, input.human_id)?;
    match source.channel.as_str() {
        "conversation" => {
            Ok(
                super::conversation_inputs::read_on(conn, &source.event_id, input.human_id)?
                    .paired_actor,
            )
        }
        "local-session" => super::session_requests::paired_request_parent_on(conn, input),
        _ => Ok(true),
    }
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

pub(super) fn claude_quoted_seed_on(
    conn: &Connection,
    original: &super::ConversationInput,
    reference: &super::conversation_routing::ConversationReply,
    target: SessionKey,
) -> Result<Option<Value>> {
    if !reference.source.starts_with("delivery:") {
        return Ok(None);
    }
    let Some(source) =
        super::presentation::source_on(conn, original.human, original.entry, &reference.source)?
    else {
        return Ok(None);
    };
    let Some(assistant) = source["text"]
        .as_str()
        .filter(|text| !text.trim().is_empty())
    else {
        return Ok(None);
    };
    // An older captured input may have only a presentation revision. A
    // capture-time text digest survives status changes without substituting text.
    let same_original = match original.reply_text_sha256.as_deref() {
        Some(hash) => source["text_sha256"].as_str() == Some(hash),
        None => !reference.context_only && source["revision"] == reference.revision,
    };
    if !same_original || source["kind"] != "worker_result" || source["target"] != json!(target) {
        return Ok(None);
    }
    let seed = json!({
        "source":reference.source,
        "revision":reference.revision,
        "assistant":assistant
    });
    Ok((serde_json::to_vec(&seed)?.len() <= 12 * 1024).then_some(seed))
}

pub(super) fn telegram_reply_message_on(
    conn: &Connection,
    source: &SourceInput,
) -> Result<Option<i64>> {
    if !source.channel.starts_with("telegram:") {
        return Ok(None);
    }
    let (Some(update), Some(message)) = (source.update_id, source.origin.message_id) else {
        return Ok(None);
    };
    Ok(conn
        .query_row(
            "SELECT json_extract(payload_json,'$.message.reply_to_message.message_id')
         FROM incoming_updates WHERE update_id=?1
           AND json_extract(payload_json,'$.message.message_id')=?2
           AND json_extract(payload_json,'$.message.chat.id')=?3
           AND json_extract(payload_json,'$.message.message_thread_id')=?4
           AND json_extract(payload_json,'$.message.from.id')=?5
           AND json_type(payload_json,'$.message.reply_to_message.message_id')='integer'",
            params![
                update,
                message,
                source.origin.chat_id,
                source.origin.thread_id,
                source.human_id
            ],
            |row| row.get(0),
        )
        .optional()?)
}

#[derive(Debug, PartialEq)]
pub(super) enum TelegramQuote {
    Unrelated,
    Unavailable,
    Selected(Value),
}

pub(super) fn claude_telegram_quote_on(
    conn: &Connection,
    source: &SourceInput,
    target: SessionKey,
    message: i64,
) -> Result<TelegramQuote> {
    let mut results = conn.prepare(
        "WITH receipts AS (
            SELECT d.result_id AS id, instr(p.text,?7)=0 AS answer
            FROM interaction_delivery_parts p
            JOIN interaction_public_deliveries d ON d.id=p.delivery_id
            WHERE p.message_id=?1 AND d.human_id=?2
              AND json_extract(d.doc,'$.origin.chat_id')=?3
              AND json_extract(d.doc,'$.origin.thread_id')=?4
            UNION
            SELECT p.source AS id, p.body=r.body AS answer FROM topic_publications p
            JOIN topic_publication_parts x ON x.publication=p.id
            JOIN interaction_results r ON r.id=p.source AND r.local_turn=p.local_turn
            JOIN turns t ON t.id=r.local_turn AND t.session_id=p.session_id
            JOIN sessions sender ON sender.id=p.session_id
            WHERE x.message_id=?1 AND x.phase='sent' AND p.kind='portable_report'
              AND p.human_id=?2 AND sender.chat_id=?3 AND sender.thread_id=?4
              AND sender.creator_user_id=?2
         )
         SELECT r.id,r.body,max(receipts.answer)
                AND coalesce(t.execution_generation=g.generation,0) AND t.status='completed'
                AND (r.item_id='final' OR EXISTS (
                   SELECT 1 FROM interaction_native_messages m
                   WHERE m.local_turn=t.id AND m.native_thread=r.native_thread
                     AND m.native_turn=r.native_turn AND m.item_id=r.item_id
                     AND m.phase='final_answer'))
         FROM receipts JOIN interaction_results r ON r.id=receipts.id
         JOIN turns t ON t.id=r.local_turn
         JOIN sessions s ON s.id=t.session_id
         JOIN users u ON u.tg_user_id=s.creator_user_id AND u.allowed=1
         JOIN conversation_entry_generations g ON g.session_id=s.id
         WHERE t.from_user_id=?2 AND s.creator_user_id=?2 AND s.chat_id=?5 AND s.thread_id=?6
         GROUP BY r.id LIMIT 2",
    )?;
    let mut rows = results.query(params![
        message,
        source.human_id,
        source.origin.chat_id,
        source.origin.thread_id,
        target.chat_id,
        target.thread_id,
        crate::interaction::WITHHELD_RESULT_NOTICE
    ])?;
    let Some(row) = rows.next()? else {
        return Ok(TelegramQuote::Unrelated);
    };
    let id: String = row.get(0)?;
    let assistant: String = row.get(1)?;
    let visible: bool = row.get(2)?;
    if rows.next()?.is_some() || !visible || assistant.trim().is_empty() {
        return Ok(TelegramQuote::Unavailable);
    }
    let revision = format!("{:x}", Sha256::digest(assistant.as_bytes()));
    let seed = json!({"source":format!("telegram-result:{id}"),"revision":revision,
                      "assistant":assistant});
    if serde_json::to_vec(&seed)?.len() > 12 * 1024 {
        return Ok(TelegramQuote::Unavailable);
    }
    Ok(TelegramQuote::Selected(seed))
}

fn claude_history_seed_on(conn: &Connection, local: i64, body: &Value) -> Result<Option<Value>> {
    let exchange: Option<(i64, String, String)> = conn.query_row(
        "SELECT prior.id,json_extract(source.doc,'$.text'),result.body
         FROM turns current
         JOIN conversation_entry_generations generation ON generation.session_id=current.session_id
         JOIN sessions owner ON owner.id=current.session_id AND owner.creator_user_id=current.from_user_id
         JOIN users human ON human.tg_user_id=owner.creator_user_id AND human.allowed=1
         JOIN turns prior ON prior.session_id=current.session_id
         JOIN bot_state root ON root.key='execution_root:'||prior.id
         JOIN interaction_instructions instruction ON instruction.id=json_extract(root.value,'$')
           AND instruction.session_id=prior.session_id AND instruction.phase='accepted'
         JOIN interaction_sources source ON source.id=instruction.input_id AND source.human_id=current.from_user_id
         JOIN interaction_results result ON result.local_turn=prior.id AND result.native_thread=prior.native_thread_id
           AND result.native_turn='gateway:claude:'||instruction.id AND result.item_id='final'
         WHERE current.id=?1 AND current.status='running'
           AND current.execution_generation=generation.generation
           AND prior.id<current.id AND prior.status='completed'
           AND prior.from_user_id=current.from_user_id AND prior.execution_generation=current.execution_generation
           AND prior.execution_harness='claude'
           AND json_extract(prior.execution_body,'$.beingRef')=json_extract(?2,'$.beingRef')
           AND json_extract(prior.execution_body,'$.embodimentId')=json_extract(?2,'$.embodimentId')
           AND source.origin_chat=owner.chat_id
           AND ((source.channel LIKE 'telegram:%' AND source.origin_thread=owner.thread_id)
             OR (source.channel='conversation' AND EXISTS (
                 SELECT 1 FROM conversation_inputs original WHERE original.id=source.event_id
                   AND original.human_id=current.from_user_id AND original.retired=0
                   AND json_extract(original.doc,'$.paired_actor')=1)))
           AND json_type(source.doc,'$.tribu_source') IS NOT 'object'
           AND json_type(source.doc,'$.text')='text'
         ORDER BY prior.id DESC LIMIT 1",
        params![local, body.to_string()],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    ).optional()?;
    let Some((turn, human, assistant)) = exchange else {
        return Ok(None);
    };
    // Keep both originals whole. Never offer a clipped proposal as the
    // evidence for an approval. A broader history reader can page it later.
    let seed = json!({"turn":turn,"human":human,"assistant":assistant});
    Ok((!human.trim().is_empty()
        && !assistant.trim().is_empty()
        && serde_json::to_vec(&seed)?.len() <= 12 * 1024)
        .then_some(seed))
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
        let paired = paired_host_access_on(&tx, &current)?;
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

    pub(crate) fn routed_claude_preserves_quote(
        &self,
        source: &SourceInput,
        target: SessionKey,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        if source.channel != "conversation" {
            let Some(message) = telegram_reply_message_on(&conn, source)? else {
                return Ok(false);
            };
            return Ok(claude_telegram_quote_on(&conn, source, target, message)?
                != TelegramQuote::Unrelated);
        }
        let original =
            super::conversation_inputs::read_on(&conn, &source.event_id, source.human_id)?;
        Ok(original.paired_actor
            && !original.retired
            && original.reply.as_ref().is_some_and(|reference| {
                reference.source.starts_with("delivery:")
                    && (!reference.context_only || original.reply_text_sha256.is_some())
            }))
    }

    /// Recover an exact quoted result, or the last completed paired exchange
    /// when the current input did not quote a specific message.
    pub(crate) fn routed_claude_history_seed(
        &self,
        input: &Instruction,
        local: i64,
        body: &Value,
    ) -> Result<Option<Value>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let source = super::routing::source_on(&conn, &input.id, input.human_id)?;
        let implicit = if source.channel == "conversation" {
            let original =
                super::conversation_inputs::read_on(&conn, &source.event_id, input.human_id)?;
            if original.retired || !original.paired_actor {
                return Ok(None);
            }
            if let Some(reference) = original
                .reply
                .as_ref()
                .filter(|reference| !reference.source.starts_with("session:"))
            {
                let quote = claude_quoted_seed_on(&conn, &original, reference, input.target)?;
                anyhow::ensure!(
                    !reference.source.starts_with("delivery:")
                        || reference.context_only
                        || quote.is_some(),
                    "The selected conversation reply is unavailable; original retained without submission"
                );
                return Ok(quote);
            }
            true
        } else if source.channel.starts_with("telegram:") {
            if let Some(message) = telegram_reply_message_on(&conn, &source)? {
                return match claude_telegram_quote_on(&conn, &source, input.target, message)? {
                    TelegramQuote::Selected(seed) => Ok(Some(seed)),
                    TelegramQuote::Unrelated => Ok(None),
                    TelegramQuote::Unavailable => anyhow::bail!(
                        "The selected Telegram reply is unavailable; original retained without submission"
                    ),
                };
            }
            true
        } else {
            false
        };
        if !implicit {
            return Ok(None);
        }
        claude_history_seed_on(&conn, local, body)
    }

    pub(crate) fn expose_routed_portable(
        &self,
        input: &Instruction,
        local: i64,
        body: &Value,
        prepared: &Value,
        paired_host_access: bool,
        history_seed: Option<&Value>,
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
        if paired_host_access
            && super::routing::source_on(&tx, &current.id, current.human_id)?.channel
                == "local-session"
            && !super::session_requests::paired_request_parent_on(&tx, &current)?
        {
            return Ok(false);
        }
        if let Some(quote) = history_seed.filter(|seed| seed["source"].is_string()) {
            let source = super::routing::source_on(&tx, &current.id, current.human_id)?;
            let resolved = if source.channel == "conversation" {
                let original =
                    super::conversation_inputs::read_on(&tx, &source.event_id, current.human_id)?;
                if original.retired || !original.paired_actor {
                    return Ok(false);
                }
                let Some(reference) = original.reply.as_ref() else {
                    return Ok(false);
                };
                claude_quoted_seed_on(&tx, &original, reference, current.target)?
            } else if let Some(message) = telegram_reply_message_on(&tx, &source)? {
                match claude_telegram_quote_on(&tx, &source, current.target, message)? {
                    TelegramQuote::Selected(seed) => Some(seed),
                    _ => None,
                }
            } else {
                None
            };
            if harness != Harness::Claude || !paired_host_access || resolved.as_ref() != Some(quote)
            {
                return Ok(false);
            }
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

    pub(crate) fn routed_claude_steer_allowed(
        &self,
        root: &Instruction,
        local: i64,
        id: &str,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let Some(active) = super::interaction::instruction_on(&conn, &root.id, root.human_id)?
        else {
            return Ok(false);
        };
        let Some(next) = super::interaction::instruction_on(&conn, id, root.human_id)? else {
            return Ok(false);
        };
        Ok(active.phase == Phase::Submitting
            && active.local_turn == Some(local)
            && next.phase == Phase::Steering
            && next.local_turn == Some(local)
            && next.target_execution == active.target_execution
            && active.native_thread.is_some()
            && active.native_thread == next.native_thread
            && super::session_requests::author_on(&conn, &next.input_id)?.is_none()
            && paired_host_access_on(&conn, &next)?
            && current_on(&conn, &active, &self.instance_id)?
            && current_on(&conn, &next, &self.instance_id)?)
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
            let mut followups = Vec::new();
            if let Some(results) = outcome["steerResults"].as_array() {
                for result in results {
                    let ids = result["ids"]
                        .as_array()
                        .context("Claude result lacks steer IDs")?;
                    let selected = ids
                        .last()
                        .and_then(Value::as_str)
                        .context("Claude result lacks its final steer ID")?;
                    let reply = result["text"].as_str();
                    let result_anchor = if reply.is_some() {
                        format!("gateway:claude:{selected}")
                    } else {
                        anchor.clone()
                    };
                    for id in ids {
                        let id = id.as_str().context("Invalid Claude steer ID")?;
                        let steered = super::interaction::instruction_on(&tx, id, input.human_id)?
                            .context("Claude steer input missing")?;
                        anyhow::ensure!(
                            steered.phase == Phase::Steering
                                && steered.native_thread.as_deref() == Some(native)
                                && steered.local_turn == Some(local),
                            "Claude steering receipt does not match the retained input"
                        );
                        super::interaction::transport_on(
                            &tx,
                            id,
                            input.human_id,
                            local,
                            Phase::Accepted,
                            Some(&result_anchor),
                        )?;
                    }
                    if let Some(reply) = reply {
                        followups.push((selected, result_anchor, reply));
                    }
                }
            }
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
            for (selected, result_anchor, reply) in followups {
                deliveries.extend(super::routing::result_on(
                    &tx,
                    &self.instance_id,
                    selected,
                    input.human_id,
                    local,
                    native,
                    &result_anchor,
                    "final",
                    reply,
                    true,
                    true,
                )?);
            }
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
    fn claude_history_seed_is_the_exact_owned_exchange_in_the_current_generation() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        let body = json!({"beingRef":"same","embodimentId":"claude"});
        let (prior, current) = {
            let conn = store.conn.lock().unwrap();
            let record = |status: &str| {
                conn.query_row(
                    "INSERT INTO turns(session_id,from_user_id,prompt,status,assistant_text,started_at,
                         execution_harness,execution_generation,execution_body,native_thread_id)
                     SELECT ?1,100,'Synthetic wrapper',?2,'I can update the layout next.','2026-11-27',
                         'claude',generation,?3,'native-thread' FROM conversation_entry_generations WHERE session_id=?1
                     RETURNING id",
                    params![session.id, status, body.to_string()],
                    |r| r.get::<_, i64>(0),
                ).unwrap()
            };
            let prior = record("completed");
            conn.execute(
                "INSERT INTO bot_state(key,value) VALUES(?1,?2)",
                params![
                    format!("execution_root:{prior}"),
                    json!("instruction").to_string()
                ],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO interaction_sources
                (id,human_id,channel,event_id,origin_chat,origin_thread,doc,created_at)
                VALUES('original',100,'telegram:100','original',100,7,?1,'2026-11-27')",
                [json!({"text":"Review the layout."}).to_string()],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO interaction_instructions
                (id,input_id,session_id,sequence,phase,doc,instance_id)
                VALUES('instruction','original',?1,1,'accepted','{}','test')",
                [session.id],
            )
            .unwrap();
            conn.execute("INSERT INTO interaction_results
                (id,local_turn,native_thread,native_turn,item_id,body)
                VALUES('result',?1,'native-thread','gateway:claude:instruction','final','I can update the layout next.')",
                [prior]).unwrap();
            (prior, record("running"))
        };
        assert_eq!(
            claude_history_seed_on(&store.conn.lock().unwrap(), current, &body).unwrap(),
            Some(
                json!({"turn":prior,"human":"Review the layout.","assistant":"I can update the layout next."})
            )
        );
        assert!(
            claude_history_seed_on(
                &store.conn.lock().unwrap(),
                current,
                &json!({"beingRef":"other","embodimentId":"claude"})
            )
            .unwrap()
            .is_none()
        );
        {
            let conn = store.conn.lock().unwrap();
            conn.execute(
                "UPDATE interaction_sources SET origin_thread=8 WHERE id='original'",
                [],
            )
            .unwrap();
        }
        assert!(
            claude_history_seed_on(&store.conn.lock().unwrap(), current, &body)
                .unwrap()
                .is_none()
        );
        {
            let conn = store.conn.lock().unwrap();
            conn.execute(
                "UPDATE interaction_sources SET channel='conversation' WHERE id='original'",
                [],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO conversation_inputs
                (id,human_id,session_id,native_thread,phase,doc,instance_id,created_at)
                VALUES('original',100,?1,'source-binding','answered',?2,'test','2026-11-27')",
                params![session.id, json!({"paired_actor":true}).to_string()],
            )
            .unwrap();
            assert!(
                claude_history_seed_on(&conn, current, &body)
                    .unwrap()
                    .is_some()
            );
            conn.execute(
                "UPDATE conversation_inputs SET retired=1 WHERE id='original'",
                [],
            )
            .unwrap();
            assert!(
                claude_history_seed_on(&conn, current, &body)
                    .unwrap()
                    .is_none()
            );
            // Restore only this synthetic row so the next assertion isolates the
            // target generation check from source retirement.
            conn.execute(
                "UPDATE conversation_inputs SET retired=0 WHERE id='original'",
                [],
            )
            .unwrap();
            conn.execute("UPDATE conversation_entry_generations SET generation='replacement' WHERE session_id=?1",
                         [session.id]).unwrap();
        }
        assert!(
            claude_history_seed_on(&store.conn.lock().unwrap(), current, &body)
                .unwrap()
                .is_none()
        );
    }

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
