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
    telegram_original_epoch_on(conn, source, target, None)
}

pub(super) fn telegram_original_epoch_for_parent(
    conn: &Connection,
    source: &SourceInput,
    parent: &Instruction,
) -> Result<Option<String>> {
    let accepted_parent = if parent.phase == Phase::Accepted {
        parent
            .local_turn
            .zip(parent.native_thread.as_deref())
            .zip(parent.native_turn.as_deref())
            .map(|((local, thread), turn)| (local, thread, turn))
    } else {
        None
    };
    telegram_original_epoch_on(conn, source, parent.target, accepted_parent)
}

fn telegram_original_epoch_on(
    conn: &Connection,
    source: &SourceInput,
    target: SessionKey,
    accepted_parent: Option<(i64, &str, &str)>,
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
    let retained: Option<(String, String, String, Option<i64>)> = conn
        .query_row(
            "SELECT i.payload_json, e.value, i.status, i.turn_id FROM incoming_updates i
         JOIN bot_state e ON e.key='stop_input_epoch:'||i.update_id
         JOIN bot_state b ON b.key='telegram_identity'
         WHERE i.update_id=?1
           AND ?2='telegram:'||json_extract(b.value,'$.id')",
            params![update, source.channel],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;
    let Some((raw, epoch, status, retained_turn)) = retained else {
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
        let accepted_parent = if let Some((local, thread, turn)) = accepted_parent
            && Some(local) == retained_turn
        {
            match status.as_str() {
                "started" | "settled" => true,
                // Reattaching a collector can leave the Telegram transport
                // uncertain after native input acceptance was already retained.
                "undetermined" => conn.query_row(
                    "SELECT EXISTS(SELECT 1 FROM native_input_receipts
                     WHERE update_id=?1 AND native_thread=?2 AND native_turn=?3)",
                    params![update, thread, turn],
                    |row| row.get(0),
                )?,
                _ => false,
            }
        } else {
            false
        };
        return Ok(
            (matches!(status.as_str(), "processing" | "handled") || accepted_parent)
                .then_some(epoch),
        );
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
        "local-session-result" => super::session_requests::paired_result_parent_on(conn, input),
        _ => Ok(true),
    }
}

pub(super) fn controller_parent_eligible_steer_on(
    conn: &Connection,
    input: &Instruction,
    instance: &str,
) -> Result<bool> {
    Ok(
        super::session_requests::author_on(conn, &input.input_id)?.is_none()
            && paired_host_access_on(conn, input)?
            && current_on(conn, input, instance)?,
    )
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
        || !super::session_requests::controller_parent_eligible_on(conn, human, parent)?
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
    if !reference.portable_quote_candidate() {
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
    if reference.source.starts_with("native:")
        && (source["native_binding_current"] != true
            || !conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM turns t
                 JOIN conversation_entry_generations g ON g.session_id=t.session_id
                 WHERE t.id=?1 AND t.status='completed' AND t.execution_generation=g.generation)",
                [source["local_turn"].as_i64()],
                |row| row.get::<_, bool>(0),
            )?)
    {
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
            SELECT p.source AS id, (CASE WHEN p.kind='portable_report' THEN p.body=r.body
               ELSE p.phase='sent' AND substr(p.body,-length(r.body))=r.body
                 AND EXISTS(SELECT 1 FROM interaction_public_deliveries d
                     WHERE d.result_id=r.id AND d.human_id=p.human_id)
               END) AS answer FROM topic_publications p
            JOIN topic_publication_parts x ON x.publication=p.id
            JOIN interaction_results r ON r.id=p.source AND r.local_turn=p.local_turn
            JOIN turns t ON t.id=r.local_turn AND (
                t.session_id=p.session_id OR p.kind='portable_entry_exchange')
            JOIN sessions sender ON sender.id=p.session_id
            WHERE x.message_id=?1 AND x.phase='sent'
              AND p.kind IN ('portable_report','portable_topic_exchange','portable_entry_exchange')
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
    owned_history_seed_on(conn, local, body, false, None)
}

fn numbered_history_references(text: &str) -> impl Iterator<Item = &str> {
    static REFERENCE: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| {
        regex::Regex::new(
            r"(?i)\b(?:\p{L}[\p{L}\p{N}_-]{2,40}[ \t]+v[0-9]{1,6}(?:\.[0-9]{1,4}){0,2}|\p{L}[\p{L}_-]{2,32}[ \t]+\p{L}[\p{L}_-]{2,32}[ \t]+[0-9]{1,5})\b",
        )
        .expect("valid numbered topic history reference")
    });
    REFERENCE
        .find_iter(text)
        .filter(move |matched| {
            matched.len() <= 256
                && !text[matched.end()..]
                    .strip_prefix('.')
                    .and_then(|tail| tail.as_bytes().first())
                    .is_some_and(u8::is_ascii_digit)
        })
        .map(|matched| matched.as_str())
}

fn claude_history_for_input_on(
    conn: &Connection,
    local: i64,
    body: &Value,
    text: &str,
) -> Result<Option<Value>> {
    let mut references = numbered_history_references(text);
    if let Some(reference) = references.next()
        && references.all(|other| other.eq_ignore_ascii_case(reference))
    {
        let found = owned_history_seed_on(conn, local, body, false, Some(reference))?
            .context("Owned history unavailable")?;
        let exchanges = found["exchanges"]
            .as_array()
            .context("Invalid topic history")?;
        let mut compatible: Vec<_> = exchanges
            .iter()
            .filter(|exchange| {
                exchange["harness"] != "claude"
                    || exchange["nativeThread"]
                        .as_str()
                        .is_some_and(|id| Uuid::parse_str(id).is_ok_and(|u| u.to_string() == id))
            })
            .collect();
        compatible.sort_by_key(|exchange| exchange["turn"].as_i64());
        if !compatible.is_empty() {
            let seed = json!({"exchanges":compatible,"matchedReference":reference});
            if serde_json::to_vec(&seed)?.len() <= 12 * 1024 {
                return Ok(Some(seed));
            }
        }
    }
    claude_history_seed_on(conn, local, body)
}

fn history_terms(text: &str) -> impl Iterator<Item = &str> {
    text.split(|character: char| !character.is_alphanumeric())
        .filter(|term| term.chars().count() >= 4)
}

fn owned_history_seed_on(
    conn: &Connection,
    local: i64,
    body: &Value,
    include_only_claude: bool,
    search: Option<&str>,
) -> Result<Option<Value>> {
    let references: std::collections::HashSet<_> = search
        .into_iter()
        .flat_map(numbered_history_references)
        .map(str::to_lowercase)
        .collect();
    let exact_reference =
        search.is_some_and(|text| numbered_history_references(text).next() == Some(text));
    let phrase = search.map(str::to_lowercase);
    let terms: std::collections::HashSet<_> = phrase
        .as_deref()
        .into_iter()
        .flat_map(history_terms)
        .collect();
    let mut query = conn.prepare(
        "WITH search_window AS (
            SELECT p.id FROM turns current
            JOIN turns p ON p.session_id=current.session_id AND p.from_user_id=current.from_user_id
            WHERE ?4 IS NOT NULL AND current.id=?1 AND p.id<current.id AND p.status='completed'
              AND p.execution_generation=current.execution_generation
            ORDER BY p.id DESC LIMIT 192
         ), owned AS (
            SELECT p.id,p.session_id,p.from_user_id,p.native_thread_id,p.execution_harness,
                   owner.chat_id,owner.thread_id,p.prompt
            FROM turns current
            JOIN conversation_entry_generations g ON g.session_id=current.session_id
            JOIN sessions owner ON owner.id=current.session_id AND owner.creator_user_id=current.from_user_id
            JOIN users human ON human.tg_user_id=owner.creator_user_id AND human.allowed=1
            JOIN turns p ON p.session_id=current.session_id AND p.from_user_id=current.from_user_id
            WHERE current.id=?1 AND current.status='running' AND current.execution_generation=g.generation
              AND p.id<current.id AND p.status='completed' AND p.execution_generation=g.generation
              AND (?4 IS NULL OR p.id IN (SELECT id FROM search_window))
              AND ((p.execution_harness='claude'
                    AND json_extract(p.execution_body,'$.beingRef')=json_extract(?2,'$.beingRef')
                    AND json_extract(p.execution_body,'$.embodimentId')=json_extract(?2,'$.embodimentId'))
                OR (NOT ?3 AND p.execution_harness='codex' AND p.native_thread_id=owner.codex_thread_id))
         ), routed AS (
            SELECT prior.id,json_extract(source.doc,'$.text') AS human,result.body AS assistant,
                   prior.execution_harness AS harness, prior.native_thread_id AS native_thread
            FROM owned prior
            JOIN bot_state root ON root.key='execution_root:'||prior.id
            JOIN interaction_instructions instruction ON instruction.id=json_extract(root.value,'$')
              AND instruction.session_id=prior.session_id AND instruction.phase='accepted'
            JOIN interaction_sources source ON source.id=instruction.input_id AND source.human_id=prior.from_user_id
            JOIN interaction_results result ON result.local_turn=prior.id AND result.native_thread=prior.native_thread_id
            WHERE ((prior.execution_harness='claude'
                    AND result.native_turn='gateway:claude:'||instruction.id AND result.item_id='final'
                    AND ((NOT ?3 AND ?4 IS NULL) OR NOT EXISTS (SELECT 1 FROM interaction_instructions sibling
                      WHERE sibling.session_id=prior.session_id AND sibling.id<>instruction.id
                        AND sibling.phase='accepted' AND json_extract(sibling.doc,'$.local_turn')=prior.id
                        AND json_extract(sibling.doc,'$.native_turn')=result.native_turn)))
                OR (prior.execution_harness='codex'
                    AND result.native_turn=json_extract(instruction.doc,'$.native_turn')
                    AND NOT EXISTS (SELECT 1 FROM interaction_instructions sibling
                      WHERE sibling.session_id=prior.session_id AND sibling.id<>instruction.id
                        AND sibling.phase='accepted' AND json_extract(sibling.doc,'$.local_turn')=prior.id
                        AND json_extract(sibling.doc,'$.native_turn')=result.native_turn)
                    AND EXISTS (SELECT 1 FROM interaction_native_messages m
                      WHERE m.local_turn=prior.id AND m.native_thread=result.native_thread
                        AND m.native_turn=result.native_turn AND m.item_id=result.item_id AND m.phase='final_answer')))
              AND source.origin_chat=prior.chat_id
              AND ((source.channel LIKE 'telegram:%' AND source.origin_thread=prior.thread_id)
                OR (source.channel='conversation' AND EXISTS (
                    SELECT 1 FROM conversation_inputs original WHERE original.id=source.event_id
                      AND original.human_id=prior.from_user_id AND original.retired=0
                      AND json_extract(original.doc,'$.paired_actor')=1)))
              AND json_type(source.doc,'$.tribu_source') IS NOT 'object'
              AND json_type(source.doc,'$.text')='text'
         ), direct AS (
            SELECT prior.id,
                   coalesce(json_extract(original.payload_json,'$.message.text'),
                            json_extract(original.payload_json,'$.message.caption')) AS human,
                   native.text AS assistant, prior.execution_harness AS harness, prior.native_thread_id AS native_thread
            FROM owned prior
            JOIN bot_state root ON root.key='execution_root:'||prior.id AND json_type(root.value,'$')='null'
            JOIN incoming_updates original ON original.turn_id=prior.id AND original.status='settled'
            JOIN native_input_receipts receipt ON receipt.update_id=original.update_id
              AND receipt.native_thread=prior.native_thread_id
            JOIN interaction_native_messages native ON native.local_turn=prior.id
              AND native.native_thread=receipt.native_thread AND native.native_turn=receipt.native_turn
              AND native.phase='final_answer'
            WHERE prior.execution_harness='codex'
              AND (SELECT count(*) FROM native_input_receipts other
                   WHERE other.native_thread=receipt.native_thread AND other.native_turn=receipt.native_turn)=1
              AND (json_extract(original.payload_json,'$.direct_human_text')=1
                OR json_extract(original.payload_json,'$.direct_human_attachment')=1)
              AND trim(coalesce(json_extract(original.payload_json,'$.message.text'),
                                json_extract(original.payload_json,'$.message.caption')),
                       char(9)||char(10)||char(13)||' ')=prior.prompt
              AND NOT EXISTS (SELECT 1 FROM interaction_instructions i WHERE i.session_id=prior.session_id
                AND i.phase='accepted' AND json_extract(i.doc,'$.local_turn')=prior.id
                AND json_extract(i.doc,'$.native_turn')=receipt.native_turn)
              AND json_extract(original.payload_json,'$.message.from.id')=prior.from_user_id
              AND json_extract(original.payload_json,'$.message.chat.id')=prior.chat_id
              AND coalesce(json_extract(original.payload_json,'$.message.message_thread_id'),0)=prior.thread_id
              AND (SELECT count(*) FROM incoming_updates receipts WHERE receipts.turn_id=prior.id)=1
              AND (SELECT count(*) FROM interaction_native_messages finals WHERE finals.local_turn=prior.id
                   AND finals.native_thread=receipt.native_thread AND finals.native_turn=receipt.native_turn
                   AND finals.phase='final_answer')=1
         )
         , ranked AS (
            SELECT *,row_number() OVER (PARTITION BY harness,native_thread ORDER BY id DESC) AS position
            FROM (SELECT * FROM routed UNION ALL SELECT * FROM direct)
            WHERE human IS NOT NULL AND native_thread IS NOT NULL
              AND (?4 IS NULL OR length(CAST(human AS BLOB))+length(CAST(assistant AS BLOB))<12288)
         )
         SELECT id,human,assistant,harness,native_thread FROM ranked
         WHERE position=1 OR ?4 IS NOT NULL
         ORDER BY id DESC
         LIMIT (CASE WHEN ?4 IS NULL THEN 3 ELSE 192 END)",
    )?;
    let mut rows = query.query(params![
        local,
        body.to_string(),
        include_only_claude,
        search,
    ])?;
    let mut candidates = Vec::new();
    while let Some(row) = rows.next()? {
        let turn: i64 = row.get(0)?;
        let human: String = row.get(1)?;
        let assistant: String = row.get(2)?;
        let harness: String = row.get(3)?;
        let native_thread: String = row.get(4)?;
        if human.trim().is_empty() || assistant.trim().is_empty() {
            continue;
        }
        if !references.is_empty() {
            let candidate_references = numbered_history_references(&human)
                .chain(numbered_history_references(&assistant))
                .map(str::to_lowercase)
                .collect();
            if !references.is_subset(&candidate_references) {
                continue;
            }
        }
        let relevance = if let Some(phrase) = &phrase {
            let human = human.to_lowercase();
            let assistant = assistant.to_lowercase();
            if human.contains(phrase) {
                3
            } else if assistant.contains(phrase) {
                2
            } else if exact_reference {
                // Complete numbered references were checked above.
                1
            } else {
                let words: std::collections::HashSet<_> = history_terms(&human)
                    .chain(history_terms(&assistant))
                    .collect();
                if terms.len() < 2 || !terms.is_subset(&words) {
                    continue;
                }
                0
            }
        } else {
            0
        };
        candidates.push((
            relevance,
            turn,
            json!({"turn":turn,"human":human,"assistant":assistant,
                            "harness":harness,"nativeThread":native_thread}),
        ));
    }
    if search.is_some() {
        candidates.sort_by_key(|(relevance, turn, _)| std::cmp::Reverse((*relevance, *turn)));
    }
    let mut exchanges = Vec::new();
    for (_, _, exchange) in candidates {
        exchanges.push(exchange);
        if serde_json::to_vec(&json!({"exchanges":exchanges}))?.len() > 12 * 1024 {
            // Never clip a quotation that could change the meaning of an approval.
            exchanges.pop();
        }
        if exchanges.len() == 3 {
            break;
        }
    }
    if search.is_some() {
        return Ok(Some(json!({"exchanges":exchanges})));
    }
    if exchanges.len() > 1 {
        // Present oldest first while keeping the newest owned exchange in each lineage.
        exchanges.reverse();
        return Ok(Some(json!({"exchanges":exchanges})));
    }
    let Some(mut seed) = exchanges.pop() else {
        return Ok(None);
    };
    if seed["harness"] == "codex" {
        seed.as_object_mut()
            .expect("exchange object")
            .remove("nativeThread");
    } else if seed["nativeThread"]
        .as_str()
        .is_some_and(|id| Uuid::parse_str(id).is_err())
    {
        // Retained older fixtures and non-resumable historical rows remain readable.
        let seed = seed.as_object_mut().expect("exchange object");
        seed.remove("nativeThread");
        seed.remove("harness");
    }
    Ok(Some(seed))
}

fn agy_scope(workspace: &str) -> String {
    format!("agy-cli/{:x}", Sha256::digest(workspace.as_bytes()))
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

    pub(crate) fn routed_agy_session(
        &self,
        local: i64,
        body: &Value,
        workspace: &str,
    ) -> Result<Option<String>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.query_row(
            "SELECT p.native_thread_id FROM turns p
             JOIN turns t ON t.id=?1 AND t.session_id=p.session_id
             WHERE p.id<t.id AND p.execution_harness='antigravity'
               AND p.execution_generation=t.execution_generation
               AND p.execution_native_scope=?2 AND p.native_thread_id IS NOT NULL
               AND json_extract(p.execution_body,'$.beingRef')=json_extract(?3,'$.beingRef')
               AND json_extract(p.execution_body,'$.embodimentId')=json_extract(?3,'$.embodimentId')
               AND json_extract(p.execution_body,'$.incarnationId')=json_extract(?3,'$.incarnationId')
             ORDER BY p.id DESC LIMIT 1",
            params![local, agy_scope(workspace), body.to_string()],
            |row| row.get(0),
        ).optional().context("Could not read the selected agy session")
    }

    pub(crate) fn routed_claude_continuations(
        &self,
        local: i64,
        body: &Value,
        goal_control: bool,
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
             WHERE position=1 AND (status='completed' OR (?3 AND status='failed'))
               AND scope IS NOT NULL
             ORDER BY id DESC LIMIT 8",
        )?;
        let rows = entries.query_map(
            params![local, serde_json::to_string(body)?, goal_control],
            |row| {
                Ok(ClaudeContinuation {
                    session_id: row.get(0)?,
                    scope: row.get(1)?,
                })
            },
        )?;
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

    pub(crate) fn routed_conversation_claude_goal(&self, input: &Instruction) -> Result<bool> {
        if !input
            .target_execution
            .as_ref()
            .is_some_and(|binding| binding.harness == Harness::Claude)
            || !crate::interaction::native_claude_goal(&input.text)
        {
            return Ok(false);
        }
        let conn = self.conn.lock().expect("store mutex poisoned");
        let source = super::routing::source_on(&conn, &input.id, input.human_id)?;
        if source.channel != "conversation"
            || super::session_requests::author_on(&conn, &input.input_id)?.is_some()
        {
            return Ok(false);
        }
        let original =
            super::conversation_inputs::read_on(&conn, &source.event_id, input.human_id)?;
        Ok(original.selected_claude_goal()
            && original.text == input.text
            && original.routing.is_some_and(|route| {
                route.target == input.target
                    && route.session == input.target_session
                    && route.selection == "session_destination"
                    && route.instruction.as_deref() == Some(input.id.as_str())
            }))
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
                reference.portable_quote_candidate()
                    && (original.reply_text_sha256.is_some()
                        || (!reference.context_only && reference.source.starts_with("delivery:")))
            }))
    }

    /// Resolve the previous harness and its owned exchanges at a paired Codex turn.
    pub(crate) fn codex_claude_predecessor(
        &self,
        local: i64,
        session: &SessionRecord,
        human: i64,
        update: Option<i64>,
        conversation: Option<&str>,
        routed: Option<&str>,
    ) -> Result<Option<(i64, Option<Value>)>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        // Include the predecessor only at the first ordinary Codex boundary
        // after Claude. A later Codex turn already has its native context.
        let predecessor: Option<(i64, String, Option<String>)> = conn.query_row(
            "SELECT prior.id,prior.execution_harness,prior.execution_body
             FROM turns current JOIN turns prior ON prior.session_id=current.session_id
             JOIN sessions owner ON owner.id=current.session_id AND owner.creator_user_id=?3
             JOIN users actor ON actor.tg_user_id=owner.creator_user_id AND actor.allowed=1
             JOIN conversation_entry_generations g ON g.session_id=owner.id
             WHERE current.id=?1 AND current.session_id=?2 AND current.from_user_id=?3
               AND current.status='running' AND current.execution_generation=g.generation
               AND prior.id<current.id AND prior.from_user_id=?3 AND prior.execution_generation=g.generation
               AND prior.status='completed'
               AND prior.native_thread_id IS NOT NULL
             ORDER BY prior.id DESC LIMIT 1",
            params![local, session.id, human],
            |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)),
        ).optional()?;
        let Some((id, harness, Some(body))) = predecessor else {
            return Ok(None);
        };
        if harness != "claude" {
            return Ok(None);
        }
        let paired = if let Some(routed) = routed {
            let input = super::interaction::instruction_on(&conn, routed, human)?
                .context("Selected Codex continuation original missing")?;
            let local_root: bool = conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM bot_state WHERE key=?1 AND json_extract(value,'$')=?2)",
                params![format!("execution_root:{local}"), routed],
                |row| row.get(0),
            )?;
            if !local_root
                || input.target_session != session.id
                || input.target != session.key
                || !input
                    .target_execution
                    .as_ref()
                    .is_some_and(|e| e.harness == Harness::Codex)
                || super::session_requests::author_on(&conn, &input.input_id)?.is_some()
            {
                return Ok(None);
            }
            let source = super::routing::source_on(&conn, routed, human)?;
            match source.channel.as_str() {
                "conversation" => super::conversation_inputs::read_on(
                    &conn,
                    &source.event_id,
                    human,
                )
                .is_ok_and(|original| {
                    original.paired_actor && !original.retired && original.tribu_source.is_none()
                }),
                channel if channel.starts_with("telegram:") => {
                    telegram_original_epoch(&conn, &source, session.key)?.is_some()
                }
                _ => false,
            }
        } else if let Some(input) = conversation {
            super::conversation_inputs::read_on(&conn, input, human).is_ok_and(|original| {
                original.session == session.id
                    && original.entry == session.key
                    && original.local_turn.is_none_or(|turn| turn == local)
                    && original.paired_actor
                    && !original.retired
                    && original.tribu_source.is_none()
            })
        } else if let Some(update) = update {
            conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM incoming_updates WHERE update_id=?1
                    AND status='started' AND turn_id=?5 AND instance_id=?6
                    AND (json_extract(payload_json,'$.direct_human_text')=1
                         OR json_extract(payload_json,'$.direct_human_attachment')=1)
                    AND json_extract(payload_json,'$.message.from.id')=?2
                    AND json_extract(payload_json,'$.message.chat.id')=?3
                    AND coalesce(json_extract(payload_json,'$.message.message_thread_id'),0)=?4)",
                params![
                    update,
                    human,
                    session.key.chat_id,
                    session.key.thread_id,
                    local,
                    self.instance_id
                ],
                |row| row.get(0),
            )?
        } else {
            false
        };
        if !paired {
            return Ok(None);
        }
        let body: Value = serde_json::from_str(&body)?;
        Ok(Some((
            id,
            owned_history_seed_on(&conn, local, &body, true, None)?,
        )))
    }

    pub(crate) fn routed_topic_history(
        &self,
        caller: SessionKey,
        human: i64,
        request: &crate::execution::ToolInvocation,
        search: &str,
    ) -> Result<Value> {
        let search = search.trim();
        anyhow::ensure!(
            (3..=160).contains(&search.len()) && !search.chars().any(char::is_control),
            "Supply one short phrase from the earlier conversation"
        );
        let conn = self.conn.lock().expect("store mutex poisoned");
        let parent = super::interaction::instruction_on(&conn, &request.native_turn, human)?
            .context("Active original is unavailable")?;
        anyhow::ensure!(
            request.harness == Harness::Claude
                && controller_parent_on(
                    &conn,
                    &parent,
                    caller,
                    human,
                    &request.native_session,
                    &request.native_turn,
                    request.local_turn,
                    &self.instance_id,
                )?
                && super::session_requests::author_on(&conn, &parent.input_id)?.is_none()
                && paired_host_access_on(&conn, &parent)?,
            "History lookup requires the current paired-human topic turn"
        );
        let body: String = conn.query_row(
            "SELECT execution_body FROM turns WHERE id=?1",
            [request.local_turn],
            |r| r.get(0),
        )?;
        let body = serde_json::from_str(&body)?;
        let found = owned_history_seed_on(&conn, request.local_turn, &body, false, Some(search))?
            .context("Owned history unavailable")?;
        if found["exchanges"].as_array().is_some_and(Vec::is_empty)
            && let mut references = numbered_history_references(search)
            && let Some(reference) = references.next().filter(|value| *value != search)
            && references.all(|other| other.eq_ignore_ascii_case(reference))
        {
            return owned_history_seed_on(
                &conn,
                request.local_turn,
                &body,
                false,
                Some(reference),
            )?
            .context("Owned history unavailable");
        }
        Ok(found)
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
                let exact_quote_selected = reference.source.starts_with("delivery:")
                    || (reference.source.starts_with("native:")
                        && original.reply_text_sha256.is_some());
                anyhow::ensure!(
                    !exact_quote_selected || reference.context_only || quote.is_some(),
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
        claude_history_for_input_on(&conn, local, body, &input.text)
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
                    .context("Routed native session scope missing")?
                    .to_owned(),
            )
        } else if harness == Harness::Antigravity && prepared["adapter"] == "agy" {
            Some(agy_scope(
                prepared["workspace"]
                    .as_str()
                    .context("agy preparation omitted its workspace")?,
            ))
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
            && super::routing::source_on(&tx, &current.id, current.human_id)?
                .channel
                .starts_with("local-session")
            && !paired_host_access_on(&tx, &current)?
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
        if let Some(seed) = history_seed
            .filter(|seed| seed["nativeThread"].is_string() || seed["exchanges"].is_array())
        {
            if harness != Harness::Claude
                || !paired_host_access
                || claude_history_for_input_on(&tx, local, body, &current.text)?.as_ref()
                    != Some(seed)
            {
                return Ok(false);
            }
        }
        let changed = tx.execute("UPDATE turns SET native_thread_id=?1,execution_native_scope=?2,execution_body=?3
            WHERE id=?4 AND status='running' AND execution_harness=?5 AND native_thread_id IS NULL
            AND execution_generation=(SELECT generation FROM conversation_entry_generations WHERE session_id=turns.session_id)
            AND (?6 IS NULL OR EXISTS(SELECT 1 FROM sessions s WHERE s.id=turns.session_id AND s.cwd=?6))",
            params![native,scope,body.to_string(),local,harness.name(),prepared["workspace"].as_str()])?;
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

    pub(crate) fn set_owned_session_cwd(
        &self,
        key: SessionKey,
        human: i64,
        cwd: &std::path::Path,
    ) -> Result<()> {
        let path = cwd.to_str().context("Workspace path is not UTF-8")?;
        anyhow::ensure!(
            cwd.is_absolute() && path.len() <= 4096,
            "Invalid workspace directory"
        );
        let conn = self.conn.lock().expect("store mutex poisoned");
        anyhow::ensure!(conn.execute(
            "UPDATE sessions SET cwd=?1,updated_at=?2 WHERE chat_id=?3 AND thread_id=?4
             AND creator_user_id=?5 AND EXISTS(SELECT 1 FROM users WHERE tg_user_id=?5 AND allowed=1)",
            params![path, now_string(), key.chat_id, key.thread_id, human],
        )? == 1, "Selected topic workspace owner changed");
        Ok(())
    }

    pub(crate) fn routed_claude_steer_allowed(
        &self,
        root: &Instruction,
        local: i64,
        id: &str,
        workspace: &std::path::Path,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let Some(active) = super::interaction::instruction_on(&conn, &root.id, root.human_id)?
        else {
            return Ok(false);
        };
        let Some(next) = super::interaction::instruction_on(&conn, id, root.human_id)? else {
            return Ok(false);
        };
        let same_workspace: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM sessions WHERE id=?1 AND cwd=?2)",
            params![
                active.target_session,
                workspace.to_str().context("Workspace path is not UTF-8")?
            ],
            |row| row.get(0),
        )?;
        Ok(same_workspace
            && active.phase == Phase::Submitting
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

    /// Retain incorporation observed on a native reply frame before the final
    /// result, so ordinary coordination can use the correct human original.
    pub(crate) fn acknowledge_claude_steer(
        &self,
        root: &Instruction,
        local: i64,
        ids: &[&str],
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let active = super::interaction::instruction_on(&tx, &root.id, root.human_id)?
            .context("Steer has no retained root")?;
        let writer: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?1)",
            [&self.instance_id],
            |row| row.get(0),
        )?;
        anyhow::ensure!(
            writer
                && active.phase == Phase::Submitting
                && active.local_turn == Some(local)
                && active.native_thread.is_some(),
            "Claude steering writer changed"
        );
        let anchor = format!("gateway:claude:{}", root.id);
        for id in ids {
            let next = super::interaction::instruction_on(&tx, id, root.human_id)?
                .context("Claude steer input missing")?;
            anyhow::ensure!(
                next.phase == Phase::Steering
                    && next.local_turn == Some(local)
                    && next.native_thread == active.native_thread
                    && next.target_execution == active.target_execution,
                "Claude incorporation does not match the retained input"
            );
            super::interaction::transport_on(
                &tx,
                id,
                root.human_id,
                local,
                Phase::Accepted,
                Some(&anchor),
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    /// Record incorporation separately from result settlement. Preparation and
    /// transport commitment alone supply no native acceptance evidence.
    pub(crate) fn record_routed_input_acceptance(
        &self,
        input: &Instruction,
        local: i64,
        native: &str,
    ) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let current = super::interaction::instruction_on(&tx, &input.id, input.human_id)?
            .context("Routed input missing")?;
        if current.phase != Phase::Submitting
            || current.local_turn != Some(local)
            || current.native_thread.as_deref() != Some(native)
            || !current_on(&tx, &current, &self.instance_id)?
        {
            return Ok(false);
        }
        let changed = tx.execute(
            "UPDATE interaction_instructions SET doc=json_set(doc,'$.native_input_accepted',json('true'))
             WHERE id=?1 AND instance_id=?2 AND phase='submitting'
             AND coalesce(json_extract(doc,'$.native_input_accepted'),0)=0
             AND EXISTS(SELECT 1 FROM turns WHERE id=?3 AND status='running' AND native_thread_id=?4)",
            params![input.id, self.instance_id, local, native],
        )?;
        if changed == 1 {
            super::topic_publications::accepted_handoff_projection_on(&tx, input, local)?;
        }
        tx.commit()?;
        Ok(changed == 1)
    }

    pub(crate) fn finish_routed_portable(
        &self,
        input: &Instruction,
        local: i64,
        outcome: &Value,
        projection_entry: Option<SessionKey>,
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
        let mut exchange_inputs = Vec::new();
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
                            (steered.phase == Phase::Steering
                                || (steered.phase == Phase::Accepted
                                    && steered.native_turn.as_deref()
                                        == Some(result_anchor.as_str())))
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
            exchange_inputs.push(current.clone());
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
                if let Some(steered) =
                    super::interaction::instruction_on(&tx, selected, input.human_id)?
                {
                    exchange_inputs.push(steered);
                }
            }
        } else if current.phase != Phase::Cancelled {
            let phase = match current.phase {
                Phase::Queued => Phase::RetainedUnsent,
                _ if !current.native_input_accepted
                    && (outcome["phase"] == "not_submitted"
                        || (limit.is_some()
                            && crate::interaction::SubscriptionLimit::refused_before_work(
                                outcome,
                            ))) =>
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
        super::topic_publications::completed_handoff_projection_on(&tx, input, local, &deliveries)?;
        if let Some(entry) = projection_entry {
            for original in exchange_inputs {
                super::topic_publications::portable_exchange_on(&tx, &original, local, entry)?;
            }
        }
        tx.commit()?;
        Ok(deliveries)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn settled_telegram_input_is_valid_only_for_its_exact_native_parent() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let key = SessionKey::new(100, Some(7));
        let source = SourceInput {
            channel: "telegram:123".into(),
            event_id: "41".into(),
            update_id: Some(41),
            human_id: 100,
            target_sessions: vec![],
            origin: crate::interaction::ReturnRoute {
                chat_id: 100,
                thread_id: 7,
                message_id: Some(42),
            },
            text: "Coordinate the design.".into(),
            telegram_files: vec![],
            tribu_source: None,
            transcription: None,
        };
        let conn = store.conn.lock().unwrap();
        let raw = json!({"update_id":41,"direct_human_text":true,"message":{
            "date":0,"message_id":42,"message_thread_id":7,
            "from":{"id":100,"is_bot":false,"first_name":"Human"},
            "chat":{"id":100,"type":"supergroup"},"text":source.text}});
        conn.execute(
            "INSERT INTO bot_state(key,value) VALUES('telegram_identity',?1),
            ('stop_input_epoch:41','initial')",
            [json!({"id":123}).to_string()],
        )
        .unwrap();
        conn.execute("INSERT INTO incoming_updates(update_id,payload_json,status,instance_id,turn_id,updated_at)
            VALUES(41,?1,'settled','fixture',46,'2026-11-28')", [raw.to_string()]).unwrap();
        assert_eq!(telegram_original_epoch(&conn, &source, key).unwrap(), None);
        assert_eq!(
            telegram_original_epoch_on(&conn, &source, key, Some((45, "native", "turn"))).unwrap(),
            None
        );
        assert_eq!(
            telegram_original_epoch_on(&conn, &source, key, Some((46, "native", "turn")))
                .unwrap()
                .as_deref(),
            Some("initial")
        );
        conn.execute(
            "UPDATE incoming_updates SET status='undetermined' WHERE update_id=41",
            [],
        )
        .unwrap();
        assert_eq!(
            telegram_original_epoch_on(&conn, &source, key, Some((46, "native", "turn"))).unwrap(),
            None
        );
        conn.execute(
            "INSERT INTO native_input_receipts VALUES(41,'native','turn','2026-11-28')",
            [],
        )
        .unwrap();
        assert_eq!(telegram_original_epoch(&conn, &source, key).unwrap(), None);
        for parent in [
            (45, "native", "turn"),
            (46, "other", "turn"),
            (46, "native", "other"),
        ] {
            assert_eq!(
                telegram_original_epoch_on(&conn, &source, key, Some(parent)).unwrap(),
                None
            );
        }
        assert_eq!(
            telegram_original_epoch_on(&conn, &source, key, Some((46, "native", "turn")))
                .unwrap()
                .as_deref(),
            Some("initial")
        );
    }

    #[test]
    fn claude_checkpoint_reads_a_direct_codex_exchange_from_the_same_owned_topic() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        store.set_session_codex_thread(key, "codex-native").unwrap();
        let conn = store.conn.lock().unwrap();
        let (prior, current) = {
            let request = TurnRequest {
                session_key: key,
                from_user_id: 100,
                prompt: "Review the project.".into(),
                runtime_instructions: None,
                attachments: vec![],
                review_mode: None,
                override_search_mode: None,
            };
            let prior =
                super::super::record_turn_started_on(&conn, session.id, &request, None).unwrap();
            conn.execute(
                "UPDATE turns SET status='completed',native_thread_id='codex-native' WHERE id=?1",
                [prior],
            )
            .unwrap();
            let current =
                super::super::record_turn_started_on(&conn, session.id, &request, None).unwrap();
            (prior, current)
        };
        let input = json!({"direct_human_text":true,"message":{"chat":{"id":100},"from":{"id":100},
            "message_thread_id":7,"text":"Review the project."}});
        conn.execute("INSERT INTO incoming_updates(update_id,payload_json,status,instance_id,turn_id,updated_at)
          VALUES(1,?1,'settled','fixture',?2,'2026-11-27')", params![input.to_string(),prior]).unwrap();
        conn.execute("INSERT INTO native_input_receipts(update_id,native_thread,native_turn,observed_at) VALUES(1,'codex-native','turn','2026-11-27')",[]).unwrap();
        conn.execute("INSERT INTO interaction_native_messages(native_thread,native_turn,item_id,local_turn,phase,text,observed_at)
          VALUES('codex-native','turn','final',?1,'final_answer','I can update it next.','2026-11-27')", [prior]).unwrap();
        let body = json!({"beingRef":"same","embodimentId":"claude"});
        assert_eq!(
            claude_history_seed_on(&conn, current, &body).unwrap(),
            Some(
                json!({"turn":prior,"human":"Review the project.","assistant":"I can update it next.","harness":"codex"})
            )
        );
        conn.execute("UPDATE incoming_updates SET payload_json=json_remove(payload_json,'$.direct_human_text')",[]).unwrap();
        assert!(
            claude_history_seed_on(&conn, current, &body)
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn claude_owned_workspace_change_preserves_the_parked_native_binding() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        store.ensure_session(key, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(key, "retained-codex-thread")
            .unwrap();
        let binding = store.conversation_request_binding(100, key).unwrap();
        let workspace = tempfile::TempDir::new().unwrap();
        assert!(
            store
                .set_owned_session_cwd(key, 101, workspace.path())
                .is_err()
        );
        store
            .set_owned_session_cwd(key, 100, workspace.path())
            .unwrap();
        assert_eq!(
            store.get_session(key).unwrap().unwrap().cwd,
            workspace.path()
        );
        assert_eq!(
            store.conversation_request_binding(100, key).unwrap(),
            binding
        );
    }

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
            let latest = record("completed");
            conn.execute(
                "INSERT INTO bot_state(key,value) VALUES(?1,?2)",
                params![
                    format!("execution_root:{latest}"),
                    json!("later-instruction").to_string()
                ],
            )
            .unwrap();
            conn.execute(
                "INSERT INTO interaction_sources(id,human_id,channel,event_id,origin_chat,origin_thread,doc,created_at)
                 VALUES('later-original',100,'telegram:100','later-original',100,7,?1,'2026-11-27')",
                [json!({"text":"Check the unrelated lighting."}).to_string()],
            ).unwrap();
            conn.execute(
                "INSERT INTO interaction_instructions(id,input_id,session_id,sequence,phase,doc,instance_id)
                 VALUES('later-instruction','later-original',?1,2,'accepted','{}','test')",
                [session.id],
            ).unwrap();
            conn.execute(
                "INSERT INTO interaction_results(id,local_turn,native_thread,native_turn,item_id,body)
                 VALUES('later-result',?1,'native-thread','gateway:claude:later-instruction','final','The room is bright.')",
                [latest],
            ).unwrap();
            let researching = record("running");
            let found = owned_history_seed_on(&conn, researching, &body, false, Some("LAYOUT"))
                .unwrap()
                .unwrap();
            assert_eq!(found["exchanges"].as_array().unwrap().len(), 1);
            assert_eq!(found["exchanges"][0]["turn"], prior);
            assert_eq!(found["exchanges"][0]["human"], "Review the layout.");
            let reordered =
                owned_history_seed_on(&conn, researching, &body, false, Some("layout UPDATE"))
                    .unwrap()
                    .unwrap();
            assert_eq!(reordered, found);
            let partial =
                owned_history_seed_on(&conn, researching, &body, false, Some("layouts UPDATE"))
                    .unwrap()
                    .unwrap();
            assert_eq!(partial, json!({"exchanges":[]}));
            conn.execute_batch("SAVEPOINT numbered_reference").unwrap();
            let native = Uuid::new_v4().to_string();
            conn.execute(
                "UPDATE turns SET native_thread_id=?1 WHERE id IN (?2,?3)",
                params![native, prior, latest],
            )
            .unwrap();
            conn.execute(
                "UPDATE interaction_results SET native_thread=?1,body='The Explorador v29 has two clips.' WHERE id='result'",
                [&native],
            ).unwrap();
            let question =
                "Contame qué clips dejamos listos en el Explorador v29 y qué quedó pendiente.";
            assert_eq!(
                numbered_history_references(question).next(),
                Some("Explorador v29")
            );
            assert!(
                numbered_history_references("Explorador v29.12345")
                    .next()
                    .is_none()
            );
            assert!(
                numbered_history_references("Explorador v29.1.2.3")
                    .next()
                    .is_none()
            );
            assert!(
                numbered_history_references(&format!("Explorador{}v29", " ".repeat(256)))
                    .next()
                    .is_none()
            );
            conn.execute("UPDATE interaction_results SET native_thread=?1,body='Explorador v290 has a different set of clips.' WHERE id='later-result'", [&native]).unwrap();
            assert_eq!(
                claude_history_for_input_on(&conn, researching, &body, question).unwrap(),
                Some(json!({"matchedReference":"Explorador v29","exchanges":[{
                    "turn":prior,"human":"Review the layout.",
                    "assistant":"The Explorador v29 has two clips.","harness":"claude","nativeThread":native}]}))
            );
            let longer = owned_history_seed_on(
                &conn,
                researching,
                &body,
                false,
                Some("clips Explorador v29"),
            )
            .unwrap()
            .unwrap();
            assert_eq!(longer["exchanges"].as_array().unwrap().len(), 1);
            assert_eq!(longer["exchanges"][0]["turn"], prior);
            conn.execute_batch("ROLLBACK TO numbered_reference; RELEASE numbered_reference")
                .unwrap();
            conn.execute(
                "INSERT INTO interaction_sources(id,human_id,channel,event_id,origin_chat,origin_thread,doc,created_at)
                 VALUES('steered-original',100,'telegram:100','steered-original',100,7,?1,'2026-11-27')",
                [json!({"text":"Wait for review."}).to_string()],
            ).unwrap();
            conn.execute(
                "INSERT INTO interaction_instructions(id,input_id,session_id,sequence,phase,doc,instance_id)
                 VALUES('steer','steered-original',?1,3,'accepted',?2,'test')",
                params![session.id,json!({"local_turn":prior,"native_turn":"gateway:claude:instruction"}).to_string()],
            ).unwrap();
            let ambiguous =
                owned_history_seed_on(&conn, researching, &body, false, Some("LAYOUT")).unwrap();
            assert_eq!(ambiguous, Some(json!({"exchanges":[]})));
            conn.execute("DELETE FROM interaction_instructions WHERE id='steer'", [])
                .unwrap();
            conn.execute(
                "DELETE FROM interaction_results WHERE id='later-result'",
                [],
            )
            .unwrap();
            (prior, researching)
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
    fn agy_continuation_stays_in_its_topic_workspace_generation_and_incarnation() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let topic = store
            .ensure_session(SessionKey::new(100, Some(7)), 100, &defaults)
            .unwrap();
        let other = store
            .ensure_session(SessionKey::new(100, Some(8)), 100, &defaults)
            .unwrap();
        let body = json!({"beingRef":"being","embodimentId":"body","incarnationId":"current"});
        let retired = json!({"beingRef":"being","embodimentId":"body","incarnationId":"retired"});
        let scope = agy_scope("/workspace/topic");
        let record = |session: i64, generation: &str, scope: Option<&str>, identity: &Value| {
            let native = Uuid::new_v4().to_string();
            let conn = store.conn.lock().unwrap();
            let local = conn.query_row(
                "INSERT INTO turns (session_id,from_user_id,prompt,status,started_at,native_thread_id,
                     execution_harness,execution_generation,execution_native_scope,execution_body)
                 VALUES (?1,100,'fixture','completed','2026-11-28',?2,'antigravity',?3,?4,?5) RETURNING id",
                params![session,&native,generation,scope,identity.to_string()], |r| r.get::<_, i64>(0),
            ).unwrap();
            (local, native)
        };
        let (_, expected) = record(topic.id, "current", Some(&scope), &body);
        record(other.id, "current", Some(&scope), &body);
        record(topic.id, "previous", Some(&scope), &body);
        record(topic.id, "current", None, &body);
        record(topic.id, "current", Some(&scope), &retired);
        let (local, _) = record(topic.id, "current", None, &body);
        assert_eq!(
            store
                .routed_agy_session(local, &body, "/workspace/topic")
                .unwrap(),
            Some(expected)
        );
        assert_eq!(
            store
                .routed_agy_session(local, &body, "/workspace/moved")
                .unwrap(),
            None
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
        let scopes = store
            .routed_claude_continuations(local, &body, false)
            .unwrap();
        assert_eq!(
            scopes
                .iter()
                .map(|c| c.session_id.as_str())
                .collect::<Vec<_>>(),
            vec![from_previous_manifest.as_str(), one.as_str()]
        );
        let (_, unfinished) = record("failed", &first, &body);
        let (next, _) = record("running", "", &body);
        let scopes = store
            .routed_claude_continuations(next, &body, false)
            .unwrap();
        assert_eq!(scopes.len(), 1);
        assert_eq!(scopes[0].session_id, from_previous_manifest);
        assert_eq!(
            store
                .routed_claude_continuations(next, &body, true)
                .unwrap()[0]
                .session_id,
            unfinished
        );
        record("failed", "resume_unavailable", &body);
        let (next, _) = record("running", "", &body);
        assert!(
            store
                .routed_claude_continuations(next, &body, false)
                .unwrap()
                .is_empty()
        );
    }
}
