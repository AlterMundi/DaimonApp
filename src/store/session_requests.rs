//! Attributed, bounded local session dependencies, separate from human speech.
use super::*;
use crate::interaction::{InputReference, Instruction, RequestRelation, SourceInput};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionRequest {
    pub id: String,
    pub human: i64,
    pub caller: SessionKey,
    pub caller_native: String,
    pub caller_turn: String,
    pub parent_instruction: String,
    pub target_instruction: String,
    pub epoch: String,
    pub return_instruction: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub report_to_topic: bool,
    pub phase: String,
}

fn progress_event(request: &str, result: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("local-progress:{request}:{result}").as_bytes(),
    )
    .to_string()
}

fn local_portable_route(
    config: Option<&crate::interaction::InteractionConfig>,
    target: SessionKey,
) -> Result<Option<crate::interaction::ForegroundAdmission<'_>>> {
    let route = config.and_then(|cfg| cfg.portable_route(target));
    anyhow::ensure!(
        route.is_none_or(|(engine, worker)| engine
            .attributed_handoff_text_limit(worker.agy_cli)
            .is_some()),
        "This portable harness does not support attributed session dependencies"
    );
    Ok(route.map(|(engine, worker)| (engine, &worker.transport.source, worker.agy_cli)))
}

pub(super) fn author_on(conn: &Connection, input: &str) -> Result<Option<Value>> {
    let raw: Option<String> = conn
        .query_row(
            "SELECT doc FROM interaction_session_authors WHERE input_id=?",
            [input],
            |r| r.get(0),
        )
        .optional()?;
    raw.map(|s| Ok(serde_json::from_str(&s)?)).transpose()
}

pub(super) fn interview_target_allowed_on(
    conn: &Connection,
    human: i64,
    caller_session: i64,
    target: SessionKey,
) -> Result<bool> {
    let protected:bool=conn.query_row("SELECT EXISTS(
        SELECT 1 FROM interaction_enrollments e JOIN interaction_creations c ON c.id=e.creation_id
        JOIN json_each(c.doc,'$.context.sources') source
        WHERE e.session_id=?1 AND e.human_id=?2 AND json_extract(c.doc,'$.context.purpose')='interview'
        AND json_extract(source.value,'$.source_session')=(SELECT id FROM sessions WHERE chat_id=?3 AND thread_id=?4))",
        params![caller_session,human,target.chat_id,target.thread_id],|r|r.get(0))?;
    Ok(!protected)
}

pub(super) fn instruction_on(conn: &Connection, id: &str, human: i64) -> Result<Instruction> {
    let (raw,phase):(String,String)=conn.query_row("SELECT i.doc,i.phase FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id WHERE i.id=?1 AND s.human_id=?2",params![id,human],|r|Ok((r.get(0)?,r.get(1)?)))?;
    let mut i: Instruction = serde_json::from_str(&raw)?;
    i.phase = phase.as_str().try_into()?;
    Ok(i)
}

fn current_epoch(conn: &Connection, human: i64) -> Result<String> {
    Ok(conn
        .query_row(
            "SELECT value FROM bot_state WHERE key=?",
            [format!("stop_admission_epoch:{human}")],
            |r| r.get(0),
        )
        .optional()?
        .unwrap_or_else(|| "initial".into()))
}

pub(super) fn later_result_source_on(
    conn: &Connection,
    human: i64,
    local: i64,
    native: &str,
    request: &str,
    coverage: &crate::interaction::Coverage,
) -> Result<Option<Instruction>> {
    // A declaration selects one still-open dependency. Find the original
    // accepted helper input, never derive authority from the result text alone.
    let original: Option<String> = conn
        .query_row(
            "SELECT i.id FROM interaction_session_requests c
             JOIN interaction_request_links l ON l.instruction_id=c.target_instruction
             JOIN interaction_instructions i ON i.id=l.instruction_id
             JOIN turns later ON later.id=?2 AND later.session_id=i.session_id
             JOIN turns prior ON prior.id=json_extract(i.doc,'$.local_turn')
             JOIN conversation_entry_generations generation ON generation.session_id=later.session_id
             WHERE c.human_id=?1 AND c.phase='requested' AND l.request_id=?4
               AND i.phase='accepted' AND prior.id<later.id AND prior.status='completed'
               AND prior.session_id=later.session_id AND prior.from_user_id=?1
               AND later.from_user_id=?1 AND later.native_thread_id=?3
               AND later.execution_generation=generation.generation
               AND prior.execution_generation=later.execution_generation
               AND prior.execution_harness=later.execution_harness
               AND json_extract(i.doc,'$.native_thread')=?3
               AND (later.execution_harness='codex' OR (
                   prior.execution_native_scope=later.execution_native_scope
                   AND json_extract(prior.execution_body,'$.beingRef')=json_extract(later.execution_body,'$.beingRef')
                   AND json_extract(prior.execution_body,'$.embodimentId')=json_extract(later.execution_body,'$.embodimentId')
                   AND json_extract(prior.execution_body,'$.incarnationId')=json_extract(later.execution_body,'$.incarnationId')
               ))
               AND NOT EXISTS (
                   SELECT 1 FROM interaction_session_withdrawals w
                   WHERE w.parent_instruction=c.parent_instruction
               )",
            params![human, local, native, request],
            |row| row.get(0),
        )
        .optional()?;
    let Some(id) = original else { return Ok(None) };
    let completed = coverage
        .completed
        .iter()
        .any(|completed| completed == request);
    if !coverage.covered.contains(&id) || completed == coverage.deferred.contains(&id) {
        return Ok(None);
    }
    let input = instruction_on(conn, &id, human)?;
    let portable = input
        .target_execution
        .as_ref()
        .is_some_and(|binding| binding.harness.is_portable());
    let (current, correction) = super::routing::freshness(conn, request, &coverage.covered, true)?;
    if !current
        || correction
        || input.admission_epoch.as_deref() != Some(current_epoch(conn, human)?.as_str())
        || !super::interaction::target_execution_matches_on(
            conn,
            &input,
            (!portable).then_some(native),
        )?
        || super::stopping::fenced_on(conn, input.target)?
        || super::maintenance_writer_held_on(conn, input.target)?
    {
        return Ok(None);
    }
    Ok(Some(input))
}

fn save_epoch(conn: &Connection, i: &mut Instruction, epoch: &str) -> Result<()> {
    i.admission_epoch = Some(epoch.to_owned());
    conn.execute(
        "UPDATE interaction_instructions SET doc=?2 WHERE id=?1",
        params![i.id, serde_json::to_string(i)?],
    )?;
    Ok(())
}

pub(super) fn session_input_allowed_on(conn: &Connection, id: &str, human: i64) -> Result<bool> {
    let i = instruction_on(conn, id, human)?;
    let Some(author) = author_on(conn, &i.input_id)? else {
        return Ok(true);
    };
    if author["kind"] == "workflow_step" {
        return super::workflows::input_allowed_on(conn, &author, &i);
    }
    let call = author["local_request"]
        .as_str()
        .context("Missing local request provenance")?;
    let phase: Option<String> = conn
        .query_row(
            "SELECT phase FROM interaction_session_requests WHERE id=?1 AND human_id=?2",
            params![call, human],
            |r| r.get(0),
        )
        .optional()?;
    if author["kind"] == "session_request" && phase.as_deref() == Some("requested") {
        let parent: String = conn.query_row(
            "SELECT parent_instruction FROM interaction_session_requests WHERE id=?1 AND human_id=?2",
            params![call,human], |r| r.get(0),
        )?;
        let parent = instruction_on(conn, &parent, human)?;
        return Ok(coordination_root_on(conn, human, &parent)?.is_some());
    }
    let progress = author["dependency_status"] == "progress";
    if author["kind"] != "session_result"
        || phase.as_deref() != Some(if progress { "requested" } else { "returned" })
    {
        return Ok(false);
    }
    let raw: String = conn.query_row(
        "SELECT doc FROM interaction_session_requests WHERE id=?1 AND human_id=?2",
        params![call, human],
        |row| row.get(0),
    )?;
    let request: SessionRequest = serde_json::from_str(&raw)?;
    if progress {
        let result = author["canonical_result"]
            .as_str()
            .context("Missing progress result")?;
        let event = progress_event(&request.id, result);
        let selected: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM interaction_sources x JOIN interaction_deliveries d
              ON d.human_id=x.human_id WHERE x.id=?1 AND x.event_id=?2
              AND x.channel='local-session-result' AND d.request_id=?3 AND d.result_id=?4)",
            params![i.input_id, event, request.target_instruction, result],
            |row| row.get(0),
        )?;
        if !selected {
            return Ok(false);
        }
    } else if request.return_instruction.as_deref() != Some(i.id.as_str()) {
        return Ok(false);
    }
    for id in [&request.parent_instruction, &request.target_instruction] {
        let execution = instruction_on(conn, id, human)?;
        if execution.target_execution.is_some() && !current_return_parent_on(conn, &execution)? {
            return Ok(false);
        }
    }
    Ok(true)
}

pub(super) fn current_bound_turn_on(conn: &Connection, instruction: &Instruction) -> Result<bool> {
    Ok(conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM turns t
            JOIN sessions s ON s.id=t.session_id
            JOIN conversation_entry_generations g ON g.session_id=s.id
            WHERE t.id=?1 AND t.session_id=?2 AND t.native_thread_id=?3
              AND t.execution_generation=g.generation AND s.force_fresh_thread=0
              AND t.status IN ('running','completed'))",
        params![
            instruction.local_turn,
            instruction.target_session,
            instruction.native_thread
        ],
        |row| row.get(0),
    )? && super::interaction::target_execution_allowed_on(conn, instruction)?)
}

// A disconnected collector can fail locally after observing both the exact
// original and its final native item. These receipts authorize returning
// existing evidence only. They do not reopen the original for new work.
fn current_return_parent_on(conn: &Connection, instruction: &Instruction) -> Result<bool> {
    if current_bound_turn_on(conn, instruction)? {
        return Ok(true);
    }
    if instruction.phase != crate::interaction::TransportPhase::Accepted {
        return Ok(false);
    }
    let retained = conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM interaction_direct_parents direct
            JOIN interaction_instructions i ON i.id=direct.instruction
            JOIN interaction_sources x ON x.id=i.input_id AND x.channel LIKE 'telegram:%'
            JOIN incoming_updates u ON u.update_id=x.update_id AND u.turn_id=?2
            JOIN native_input_receipts r ON r.update_id=u.update_id
            JOIN turns t ON t.id=u.turn_id AND t.session_id=i.session_id
            JOIN sessions s ON s.id=t.session_id AND s.codex_thread_id=t.native_thread_id
            JOIN conversation_entry_generations g ON g.session_id=s.id
            JOIN users h ON h.tg_user_id=s.creator_user_id
            JOIN interaction_native_messages m ON m.local_turn=t.id
               AND m.native_thread=r.native_thread AND m.native_turn=r.native_turn
               AND m.phase='final_answer' AND length(trim(m.text))>0
            WHERE i.id=?1 AND i.phase='accepted' AND u.status='undetermined'
              AND r.native_thread=?3 AND r.native_turn=?4 AND t.native_thread_id=r.native_thread
              AND t.execution_harness='codex' AND t.status='failed'
              AND t.execution_generation=g.generation AND s.force_fresh_thread=0
              AND s.creator_user_id=?5 AND t.from_user_id=?5 AND x.human_id=?5 AND h.allowed=1
              AND NOT EXISTS(SELECT 1 FROM interaction_session_withdrawals w
                              WHERE w.parent_instruction=i.id))",
        params![
            instruction.id,
            instruction.local_turn,
            instruction.native_thread,
            instruction.native_turn,
            instruction.human_id
        ],
        |row| row.get(0),
    )?;
    Ok(retained && super::interaction::target_execution_allowed_on(conn, instruction)?)
}

type RelayedTelegramOriginal = (SourceInput, crate::telegram::Message, Value);

/// Resolve the exact direct human original behind one pending, accepted first hop.
pub(super) fn relayed_telegram_original_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    expected_origin: Option<SessionKey>,
    reference: &InputReference,
) -> Result<Option<RelayedTelegramOriginal>> {
    let Some(update) = reference.update() else {
        return Ok(None);
    };
    let mut stmt = conn.prepare(
        "SELECT r.id,p.id,i.id,x.channel
         FROM interaction_direct_parents direct
         JOIN interaction_instructions p ON p.id=direct.instruction
         JOIN interaction_sources x ON x.id=p.input_id
         JOIN interaction_session_requests r ON r.parent_instruction=p.id AND r.human_id=x.human_id
         JOIN interaction_instructions i ON i.id=r.target_instruction
         JOIN interaction_session_authors a ON a.input_id=i.input_id
         JOIN sessions e ON e.id=i.session_id
         JOIN native_input_receipts n ON n.update_id=x.update_id
           AND n.native_thread=json_extract(p.doc,'$.native_thread')
           AND n.native_turn=json_extract(p.doc,'$.native_turn')
         WHERE x.update_id=?1 AND x.human_id=?2 AND x.channel LIKE 'telegram:%'
           AND x.origin_chat=?3 AND NOT (x.origin_chat=?5 AND x.origin_thread=?6)
           AND (?4 IS NULL OR x.origin_thread=?4)
           AND r.caller_chat=x.origin_chat AND r.caller_topic=x.origin_thread
           AND e.chat_id=?5 AND e.thread_id=?6 AND e.creator_user_id=?2
           AND p.phase='accepted' AND i.phase='accepted' AND r.phase='requested'
           AND json_extract(a.doc,'$.kind')='session_request'
           AND json_extract(a.doc,'$.local_request')=r.id
           AND json_extract(a.doc,'$.parent_instruction')=p.id
           AND json_extract(a.doc,'$.authorized_human')=?2
           AND json_extract(a.doc,'$.human_parent.input_ref')=?1
           AND NOT EXISTS(SELECT 1 FROM interaction_session_withdrawals w WHERE w.parent_instruction=p.id)
         ORDER BY r.id LIMIT 2",
    )?;
    let candidates = stmt
        .query_map(
            params![
                update,
                human,
                expected_origin.map_or(entry.chat_id, |origin| origin.chat_id),
                expected_origin.map(|origin| origin.thread_id),
                entry.chat_id,
                entry.thread_id
            ],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                ))
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let [(request, parent, received, channel)] = candidates.as_slice() else {
        return Ok(None);
    };
    let original = super::session_requests::instruction_on(conn, parent, human)?;
    let relay = super::session_requests::instruction_on(conn, received, human)?;
    if expected_origin.map_or(original.target.chat_id != entry.chat_id, |origin| {
        original.target != origin
    }) || relay.target != entry
        || original.admission_epoch != relay.admission_epoch
        || super::stopping::fenced_on(conn, original.target)?
        || super::stopping::fenced_on(conn, entry)?
        || super::maintenance_writer_held_on(conn, original.target)?
        || super::maintenance_writer_held_on(conn, entry)?
        || !super::session_requests::current_bound_turn_on(conn, &original)?
        || !super::session_requests::current_bound_turn_on(conn, &relay)?
    {
        return Ok(None);
    }
    let (source, message) = super::dialogue::original_owned_on(
        conn,
        original.target,
        human,
        original
            .native_thread
            .as_deref()
            .context("Relay original native binding missing")?,
        reference,
        channel,
        false,
    )?;
    let message = message.context("Relay original is not a Telegram message")?;
    if message
        .from
        .as_ref()
        .is_none_or(|u| u.is_bot || u.id != human)
        || author_on(conn, &relay.input_id)?
            .is_none_or(|author| author["human_parent"]["origin"] != json!(source.origin))
    {
        anyhow::bail!("Actual human input required");
    }
    Ok(Some((
        source,
        message,
        json!({"request":request,"parent":parent,"received":received}),
    )))
}

pub(super) fn controller_parent_eligible_on(
    conn: &Connection,
    human: i64,
    parent: &Instruction,
) -> Result<bool> {
    let Some(author) = author_on(conn, &parent.input_id)? else {
        return Ok(true);
    };
    if author["kind"] == "session_result" {
        return paired_result_parent_on(conn, parent);
    }
    Ok(coordination_root_on(conn, human, parent)?.is_some()
        && paired_request_parent_on(conn, parent)?)
}

// One local helper may coordinate onward under its original human instruction.
fn coordination_root_on(
    conn: &Connection,
    human: i64,
    parent: &Instruction,
) -> Result<Option<Instruction>> {
    coordination_root_with(conn, human, parent, current_bound_turn_on)
}

fn coordination_root_with(
    conn: &Connection,
    human: i64,
    parent: &Instruction,
    root_allowed: fn(&Connection, &Instruction) -> Result<bool>,
) -> Result<Option<Instruction>> {
    let Some(author) = author_on(conn, &parent.input_id)? else {
        return Ok(Some(parent.clone()));
    };
    if author["kind"] != "session_request" {
        return Ok(None);
    }
    let root: Option<String> = conn
        .query_row(
            "SELECT parent_instruction FROM interaction_session_requests
         WHERE target_instruction=?1 AND human_id=?2 AND phase='requested'
         AND NOT EXISTS (SELECT 1 FROM interaction_session_withdrawals
                         WHERE parent_instruction=interaction_session_requests.parent_instruction)",
            params![parent.id, human],
            |r| r.get(0),
        )
        .optional()?;
    let Some(root) = root else { return Ok(None) };
    let root = instruction_on(conn, &root, human)?;
    Ok((author_on(conn, &root.input_id)?.is_none()
        && root.admission_epoch == parent.admission_epoch
        && root_allowed(conn, &root)?
        && current_bound_turn_on(conn, parent)?)
    .then_some(root))
}

// Paired tools can be inherited only from the retained human source.
pub(super) fn paired_request_parent_on(conn: &Connection, child: &Instruction) -> Result<bool> {
    let human = child.human_id;
    let parent: Option<String> = conn
        .query_row(
            "SELECT parent_instruction FROM interaction_session_requests
         WHERE target_instruction=?1 AND human_id=?2 AND phase='requested'
         AND NOT EXISTS(SELECT 1 FROM interaction_session_withdrawals
                        WHERE parent_instruction=interaction_session_requests.parent_instruction)",
            params![child.id, human],
            |row| row.get(0),
        )
        .optional()?;
    let Some(parent) = parent else {
        return Ok(false);
    };
    let immediate = instruction_on(conn, &parent, human)?;
    let Some(parent) = coordination_root_on(conn, human, &immediate)? else {
        return Ok(false);
    };
    paired_source_on(conn, &parent, child)
}

pub(super) fn paired_result_parent_on(conn: &Connection, child: &Instruction) -> Result<bool> {
    if !session_input_allowed_on(conn, &child.id, child.human_id)? {
        return Ok(false);
    }
    let author = author_on(conn, &child.input_id)?.context("Missing result provenance")?;
    let parent: Option<String> = conn
        .query_row(
            "SELECT parent_instruction FROM interaction_session_requests WHERE human_id=?1 AND id=?2",
            params![child.human_id, author["local_request"].as_str()],
            |row| row.get(0),
        )
        .optional()?;
    let Some(parent) = parent else {
        return Ok(false);
    };
    let parent = instruction_on(conn, &parent, child.human_id)?;
    if parent.target != child.target
        || !parent.target_execution.as_ref().is_some_and(|selection| {
            use crate::execution::Harness;
            matches!(selection.harness, Harness::Claude | Harness::Antigravity)
                && child.target_execution.as_ref() == Some(selection)
        })
    {
        return Ok(false);
    }
    let Some(root) = coordination_root_on(conn, child.human_id, &parent)? else {
        return Ok(false);
    };
    paired_source_on(conn, &root, child)
}

fn paired_source_on(conn: &Connection, parent: &Instruction, child: &Instruction) -> Result<bool> {
    if parent.admission_epoch != child.admission_epoch {
        return Ok(false);
    }
    let human = child.human_id;
    let source = super::routing::source_on(conn, &parent.id, human)?;
    paired_original_on(conn, parent, &source)
}

fn paired_original_on(
    conn: &Connection,
    parent: &Instruction,
    source: &SourceInput,
) -> Result<bool> {
    if source.channel == "conversation" {
        let original =
            super::conversation_inputs::read_on(conn, &source.event_id, parent.human_id)?;
        return Ok(original.paired_actor
            && original.tribu_source.is_none()
            && source.tribu_source.is_none()
            && super::conversation_inputs::eligible_binding_on(conn, &original).is_ok());
    }
    if source.channel.starts_with("telegram:") {
        return Ok(super::routed_portable::telegram_original_epoch_for_parent(
            conn, source, parent,
        )?
        .is_some_and(|epoch| Some(epoch) == parent.admission_epoch));
    }
    Ok(false)
}

fn session_requests_on(
    conn: &Connection,
    caller: SessionKey,
    human: i64,
    request_id: Option<&str>,
) -> Result<Vec<SessionRequest>> {
    let mut q=conn.prepare("SELECT doc,phase FROM interaction_session_requests WHERE human_id=?1 AND caller_chat=?2 AND caller_topic=?3 AND (?4 IS NULL OR id=?4) ORDER BY rowid DESC LIMIT 16")?;
    q.query_map(
        params![human, caller.chat_id, caller.thread_id, request_id],
        |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
    )?
    .map(|r| {
        let (raw, phase) = r?;
        let mut call: SessionRequest = serde_json::from_str(&raw)?;
        call.phase = phase;
        Ok(call)
    })
    .collect()
}

pub(super) fn withdraw_local_requests_on(conn: &Connection, caller: SessionKey) -> Result<()> {
    conn.execute("UPDATE interaction_session_requests SET phase='withdrawn' WHERE caller_chat=?1 AND caller_topic=?2 AND (phase='requested' OR (phase='returned' AND EXISTS(SELECT 1 FROM interaction_instructions i WHERE i.id=json_extract(interaction_session_requests.doc,'$.return_instruction') AND i.phase IN ('queued','submitting','steering'))))",params![caller.chat_id,caller.thread_id])?;
    conn.execute("UPDATE interaction_instructions SET phase='retained_unsent' WHERE phase='queued' AND input_id IN (SELECT a.input_id FROM interaction_session_authors a JOIN interaction_session_requests c ON json_extract(a.doc,'$.local_request')=c.id WHERE c.caller_chat=?1 AND c.caller_topic=?2 AND c.phase='withdrawn' AND json_extract(a.doc,'$.kind')='session_result')",params![caller.chat_id,caller.thread_id])?;
    Ok(())
}

impl Store {
    pub(super) fn init_session_requests(&self) -> Result<()> {
        self.conn.lock().expect("store mutex poisoned").execute_batch(
            "CREATE TABLE IF NOT EXISTS interaction_session_requests(id TEXT PRIMARY KEY,human_id INTEGER NOT NULL,caller_chat INTEGER NOT NULL,caller_topic INTEGER NOT NULL,parent_instruction TEXT NOT NULL,target_instruction TEXT NOT NULL UNIQUE,phase TEXT NOT NULL,doc TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS interaction_session_authors(input_id TEXT PRIMARY KEY REFERENCES interaction_sources(id),doc TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS interaction_session_withdrawals(parent_instruction TEXT PRIMARY KEY);
             CREATE TABLE IF NOT EXISTS interaction_direct_parents(instruction TEXT PRIMARY KEY REFERENCES interaction_instructions(id) ON DELETE CASCADE);"
        )?;
        Ok(())
    }

    /// Retain the accepted Telegram input and its eligible coordination parent
    /// within the same journal transaction. The ordinary input receipt survives
    /// ineligible provenance and isolated coordination metadata failures.
    pub(crate) fn native_direct_input_receipt(
        &self,
        caller: SessionKey,
        human: i64,
        local: i64,
        physical: &str,
        client: &str,
        bot: i64,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let mut tx = conn.transaction()?;
        super::native_recovery::input_receipt_on(&tx, local, Some(client), physical)?;
        self.retain_direct_parent(&mut tx, caller, human, local, physical, client, bot)?;
        tx.commit()?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn retain_direct_parent(
        &self,
        tx: &mut rusqlite::Transaction<'_>,
        caller: SessionKey,
        human: i64,
        local: i64,
        physical: &str,
        client: &str,
        bot: i64,
    ) -> Result<()> {
        let savepoint = tx.savepoint()?;
        match self.record_direct_parent_on(&savepoint, caller, human, local, physical, client, bot)
        {
            Ok(()) => savepoint.commit()?,
            Err(error) => {
                tracing::warn!(%error, local, "Could not retain direct dependency parent");
                savepoint.finish()?;
            }
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn record_direct_parent_on(
        &self,
        tx: &Connection,
        caller: SessionKey,
        human: i64,
        local: i64,
        physical: &str,
        client: &str,
        bot: i64,
    ) -> Result<()> {
        use crate::interaction::{ReturnRoute, TransportPhase};

        let binding: Option<(i64, String)> = tx
            .query_row(
                "SELECT s.id,s.codex_thread_id FROM sessions s
                JOIN users u ON u.tg_user_id=s.creator_user_id
                JOIN turns t ON t.session_id=s.id
                WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3
                AND u.allowed=1 AND s.force_fresh_thread=0 AND t.id=?4
                AND t.from_user_id=?3 AND t.native_thread_id=s.codex_thread_id
                AND t.status='running' AND t.completed_at IS NULL AND (t.review_json IS NULL OR t.review_json='null')",
                params![caller.chat_id, caller.thread_id, human, local],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((session, native)) = binding else {
            return Ok(());
        };
        if physical.is_empty()
            || super::stopping::fenced_on(tx, caller)?
            || super::maintenance_writer_held_on(tx, caller)?
        {
            return Ok(());
        }
        let epoch = current_epoch(tx, human)?;
        let mut source = SourceInput {
            telegram_files: vec![],
            telegram_album_members: Vec::new(),
            tribu_source: None,
            transcription: None,
            channel: "conversation".into(),
            event_id: String::new(),
            update_id: None,
            human_id: human,
            target_sessions: vec![session],
            origin: ReturnRoute {
                chat_id: caller.chat_id,
                thread_id: caller.thread_id,
                message_id: None,
            },
            text: String::new(),
        };
        let telegram_prefix = format!("telegram:{}:{human}:", caller.chat_id);
        if let Some(update) = client
            .strip_prefix(&telegram_prefix)
            .and_then(|id| id.parse::<i64>().ok())
        {
            let raw: Option<String> = tx
                .query_row(
                    "SELECT i.payload_json FROM incoming_updates i
                    JOIN native_input_receipts n ON n.update_id=i.update_id
                    JOIN bot_state e ON e.key='stop_input_epoch:'||i.update_id
                    WHERE i.update_id=?1 AND i.turn_id=?2 AND n.native_thread=?3
                    AND n.native_turn=?4 AND e.value=?5",
                    params![update, local, native, physical, epoch],
                    |r| r.get(0),
                )
                .optional()?;
            let Some(raw) = raw else { return Ok(()) };
            let original: crate::telegram::Update = serde_json::from_str(&raw)?;
            let Some(message) = original.message.as_ref() else {
                return Ok(());
            };
            if message.chat.id != caller.chat_id
                || message.message_thread_id.unwrap_or_default() != caller.thread_id
                || message
                    .from
                    .as_ref()
                    .is_none_or(|user| user.id != human || user.is_bot)
                || !(original.direct_human_text
                    || (original.direct_human_attachment && message.voice.is_some()))
            {
                return Ok(());
            }
            let Ok((text, transcription)) = super::voice::content_on(tx, &original, human) else {
                // Attachment-only direct messages have no text authority.
                return Ok(());
            };
            source.channel = format!("telegram:{bot}");
            source.event_id = update.to_string();
            source.update_id = Some(update);
            source.origin.message_id = Some(message.message_id);
            source.text = text;
            source.transcription = transcription;
        } else if let Some(id) = client.strip_prefix("conversation:") {
            let input = super::conversation_inputs::read_on(tx, id, human)?;
            if input.entry != caller
                || input.session != session
                || input.native != native
                || input.local_turn != Some(local)
                || input.phase != "accepted"
                || input.routing.is_some()
                || input.foreground_dialogue.is_some()
                || input.tribu_source.is_some()
                || !input.paired_actor
            {
                return Ok(());
            }
            super::conversation_inputs::eligible_on(tx, &input)?;
            source.event_id = input.id;
            source.text = input.text;
            source.transcription = input.voice.and_then(|voice| voice.transcription);
        } else {
            return Ok(());
        }
        if source.text.trim().is_empty() {
            return Ok(());
        }
        let (mut parent, fresh) =
            super::interaction::retain_direct_parent_on(tx, &source, caller, &self.instance_id)?;
        if fresh {
            parent.phase = TransportPhase::Accepted;
            parent.local_turn = Some(local);
            parent.native_turn = Some(physical.into());
            save_epoch(tx, &mut parent, &epoch)?;
            tx.execute(
                "UPDATE interaction_instructions SET phase='accepted' WHERE id=?1",
                [&parent.id],
            )?;
            tx.execute(
                "INSERT INTO interaction_direct_parents VALUES(?1)",
                [&parent.id],
            )?;
        }
        Ok(())
    }

    pub fn interaction_dependency_inputs(
        &self,
        local: i64,
        human: i64,
    ) -> Result<Vec<Instruction>> {
        self.turn_inputs(local, human, true)
    }

    pub fn interaction_author(&self, instruction: &str, human: i64) -> Result<Option<Value>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let i = instruction_on(&conn, instruction, human)?;
        author_on(&conn, &i.input_id)
    }

    /// The caller's accepted human instruction is the causal grant. One level,
    /// at most four dependencies per original instruction, and no self-addressing.
    #[allow(clippy::too_many_arguments)]
    #[cfg(test)]
    pub fn interaction_session_request(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
        turn: &str,
        parent: &str,
        client: &str,
        target: SessionKey,
        text: &str,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<(SessionRequest, Instruction, bool)> {
        self.interaction_session_request_scoped(
            caller, human, native, turn, parent, client, target, text, closed, None, None, false,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn interaction_session_request_scoped(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
        turn: &str,
        parent: &str,
        client: &str,
        target: SessionKey,
        text: &str,
        closed: &tokio_util::sync::CancellationToken,
        portable_local: Option<i64>,
        config: Option<&crate::interaction::InteractionConfig>,
        report_to_topic: bool,
    ) -> Result<(SessionRequest, Instruction, bool)> {
        if caller == target
            || text.trim().is_empty()
            || text.len() > 16000
            || client.is_empty()
            || client.len() > 64
            || !client
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err(anyhow!("Invalid local session request"));
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let p = instruction_on(&tx, parent, human)?;
        let caller_owned = if let Some(local) = portable_local {
            let root = instruction_on(&tx, turn, human)?;
            let matches_root = p.id == root.id
                || (p.phase == crate::interaction::TransportPhase::Accepted
                    && p.local_turn == Some(local)
                    && p.native_turn.as_deref() == Some(format!("gateway:claude:{turn}").as_str())
                    && p.target_execution == root.target_execution
                    && super::routed_portable::controller_parent_eligible_steer_on(
                        &tx,
                        &p,
                        &self.instance_id,
                    )?);
            matches_root
                && super::routed_portable::controller_parent_on(
                    &tx,
                    &root,
                    caller,
                    human,
                    native,
                    turn,
                    local,
                    &self.instance_id,
                )?
        } else {
            p.phase == crate::interaction::TransportPhase::Accepted
                && p.native_turn.as_deref() == Some(turn)
                && tx.query_row("SELECT EXISTS(SELECT 1 FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id JOIN turns t ON t.session_id=s.id WHERE s.id=?1 AND s.chat_id=?2 AND s.thread_id=?3 AND s.creator_user_id=?4 AND u.allowed=1 AND s.codex_thread_id=?5 AND t.id=?6 AND t.native_thread_id=?5 AND t.status='running')",params![p.target_session,caller.chat_id,caller.thread_id,human,native,p.local_turn],|r|r.get(0))?
        };
        let withdrawn:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_session_withdrawals WHERE parent_instruction=?)",[parent],|r|r.get(0))?;
        if !caller_owned
            || withdrawn
            || p.target != caller
            || p.native_thread.as_deref() != Some(native)
        {
            return Err(anyhow!(
                "Local request has no current accepted human parent"
            ));
        }
        let root = coordination_root_on(&tx, human, &p)?
            .context("Local coordination needs a current human original or its first helper")?;
        let onward = root.id != p.id;
        anyhow::ensure!(
            !onward || (target != root.target && !report_to_topic),
            "An onward handoff cannot target its origin or publish to a topic"
        );
        // An interview receives historical evidence, not authority to resume or
        // steer the work it is explaining. Enforce this at durable admission,
        // independently of the interview model's output or role prompt.
        if !interview_target_allowed_on(&tx, human, p.target_session, target)?
            || (onward && !interview_target_allowed_on(&tx, human, root.target_session, target)?)
        {
            return Err(anyhow!(
                "An interview cannot activate its pinned source work"
            ));
        }
        let epoch = p
            .admission_epoch
            .as_deref()
            .context("Parent admission generation unavailable")?;
        if current_epoch(&tx, human)? != epoch || closed.is_cancelled() {
            return Err(anyhow!("Parent admission retired or closed"));
        }
        let route = local_portable_route(config, target)?;
        anyhow::ensure!(
            route
                .and_then(|(engine, _, agy_cli)| engine.attributed_handoff_text_limit(agy_cli))
                .is_none_or(|limit| text.len() <= limit),
            "The selected handoff is too large for its receiving adapter"
        );
        let target_id: i64 = tx.query_row(
            "SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1
             AND (?4 OR s.codex_thread_id IS NOT NULL)",
            params![target.chat_id, target.thread_id, human, route.is_some()],
            |r| r.get(0),
        )?;
        let raw: String = tx.query_row(
            "SELECT doc FROM interaction_sources WHERE id=?",
            [&p.input_id],
            |r| r.get(0),
        )?;
        let original: SourceInput = serde_json::from_str(&raw)?;
        if route.is_some_and(|(_, _, agy_cli)| agy_cli) {
            let root_source = super::routing::source_on(&tx, &root.id, human)?;
            anyhow::ensure!(
                paired_original_on(&tx, &root, &root_source)?,
                "Antigravity handoffs require a paired human original"
            );
        }
        if report_to_topic {
            anyhow::ensure!(
                route.is_some()
                    && caller.chat_id == target.chat_id
                    && paired_original_on(&tx, &p, &original)?,
                "A selected topic report requires a paired local request and a supported receiving adapter"
            );
        }
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "local-session-request:{}:{parent}:{client}",
                p.target_session
            )
            .as_bytes(),
        )
        .to_string();
        let source = SourceInput {
            telegram_files: vec![],
            telegram_album_members: Vec::new(),
            tribu_source: None,
            transcription: None,
            channel: "local-session".into(),
            event_id: id.clone(),
            update_id: None,
            human_id: human,
            target_sessions: vec![target_id],
            origin: original.origin.clone(),
            text: text.to_owned(),
        };
        let existing: Option<(String, String)> = tx
            .query_row(
                "SELECT doc,phase FROM interaction_session_requests WHERE id=? AND human_id=?",
                params![id, human],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let count: i64 = tx.query_row(
            "SELECT count(*) FROM interaction_session_requests
             WHERE parent_instruction=?1 OR parent_instruction IN (
                 SELECT target_instruction FROM interaction_session_requests WHERE parent_instruction=?1)",
            [&root.id],
            |r| r.get(0),
        )?;
        if existing.is_none() && count >= 4 {
            return Err(anyhow!("Human parent dependency budget exhausted"));
        }
        let (mut i, fresh) = super::interaction::admit_local_session_on(
            &tx,
            &source,
            target,
            RequestRelation::New,
            &self.instance_id,
            route,
            epoch,
        )?;
        if let Some((raw, phase)) = existing {
            let mut call: SessionRequest = serde_json::from_str(&raw)?;
            call.phase = phase;
            if call.caller_native != native
                || call.caller_turn != turn
                || call.target_instruction != i.id
                || call.report_to_topic != report_to_topic
            {
                return Err(anyhow!("Local request identity is immutable"));
            }
            tx.commit()?;
            return Ok((call, i, false));
        }
        if !fresh {
            return Err(anyhow!(
                "Unattributed local source cannot become a session request"
            ));
        }
        save_epoch(&tx, &mut i, epoch)?;
        let call = SessionRequest {
            id: id.clone(),
            human,
            caller,
            caller_native: native.into(),
            caller_turn: turn.into(),
            parent_instruction: parent.into(),
            target_instruction: i.id.clone(),
            epoch: epoch.into(),
            return_instruction: None,
            report_to_topic,
            phase: "requested".into(),
        };
        let mut author = json!({"kind":"session_request","session":caller,"native_thread":native,"native_turn":turn,"parent_instruction":parent,"local_request":id,"authorized_human":human, "human_parent":{"channel":original.channel,"input_ref":super::dialogue::source_reference(&original),"origin":original.origin}});
        if report_to_topic {
            author["report_to_topic"] = json!(true);
        }
        if route.is_some() {
            crate::interaction::portable_handoff_packet(&i, &author)?;
        }
        tx.execute(
            "INSERT INTO interaction_session_authors VALUES(?1,?2)",
            params![i.input_id, author.to_string()],
        )?;
        tx.execute(
            "INSERT INTO interaction_session_requests VALUES(?1,?2,?3,?4,?5,?6,'requested',?7)",
            params![
                id,
                human,
                caller.chat_id,
                caller.thread_id,
                parent,
                i.id,
                serde_json::to_string(&call)?
            ],
        )?;
        if closed.is_cancelled() {
            return Err(anyhow!("Local request closed before commit"));
        }
        tx.commit()?;
        Ok((call, i, true))
    }

    pub fn interaction_session_requests(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
    ) -> Result<Vec<SessionRequest>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let owned:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1 AND s.codex_thread_id=?4)",params![caller.chat_id,caller.thread_id,human,native],|r|r.get(0))?;
        if !owned {
            return Err(anyhow!("Local caller binding changed"));
        }
        session_requests_on(&conn, caller, human, None)
    }

    pub(crate) fn routed_portable_session_requests(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
        parent: &str,
        local: i64,
        request_id: Option<&str>,
    ) -> Result<Vec<SessionRequest>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let input = instruction_on(&conn, parent, human)?;
        anyhow::ensure!(
            super::routed_portable::controller_parent_on(
                &conn,
                &input,
                caller,
                human,
                native,
                parent,
                local,
                &self.instance_id
            )?,
            "Portable caller binding changed"
        );
        session_requests_on(&conn, caller, human, request_id)
    }

    pub(crate) fn interaction_session_parent_eligible(&self, id: &str, human: i64) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let parent = instruction_on(&conn, id, human)?;
        Ok(coordination_root_on(&conn, human, &parent)?.is_some())
    }

    pub fn interaction_session_input_allowed(&self, id: &str, human: i64) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        session_input_allowed_on(&conn, id, human)
    }

    /// Requeue an admitted, known-unsent handoff without changing its source,
    /// destination, dependency budget or original admission generation.
    pub(crate) fn interaction_session_recover_unsent(
        &self,
        human: i64,
        id: &str,
    ) -> Result<(Instruction, bool)> {
        use crate::interaction::TransportPhase as Phase;

        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let (raw, phase): (String, String) = tx
            .query_row(
                "SELECT doc,phase FROM interaction_session_requests WHERE id=?1 AND human_id=?2",
                params![id, human],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .context("Owned local handoff unavailable")?;
        let call: SessionRequest = serde_json::from_str(&raw)?;
        let mut helper = instruction_on(&tx, &call.target_instruction, human)?;
        if helper.phase != Phase::RetainedUnsent || phase != "requested" {
            return Ok((helper, false));
        }

        let parent = instruction_on(&tx, &call.parent_instruction, human)?;
        let viable: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns t
                JOIN sessions s ON s.id=t.session_id
                JOIN users u ON u.tg_user_id=s.creator_user_id
                JOIN conversation_entry_generations g ON g.session_id=s.id
                WHERE t.id=?1 AND t.session_id=?2 AND t.native_thread_id=?3
                  AND t.status IN ('running','completed') AND t.execution_generation=g.generation
                  AND u.tg_user_id=?4 AND u.allowed=1 AND s.force_fresh_thread=0)",
            params![
                parent.local_turn,
                parent.target_session,
                call.caller_native,
                human
            ],
            |row| row.get(0),
        )?;
        anyhow::ensure!(
            viable
                && parent.phase == Phase::Accepted
                && parent.target == call.caller
                && parent.admission_epoch.as_deref() == Some(&call.epoch)
                && helper.admission_epoch.as_deref() == Some(&call.epoch)
                && current_epoch(&tx, human)? == call.epoch
                && !super::stopping::fenced_on(&tx, call.caller)?
                && !super::stopping::fenced_on(&tx, helper.target)?
                && !super::maintenance_writer_held_on(&tx, helper.target)?
                && super::interaction::target_execution_allowed_on(&tx, &parent)?
                && super::interaction::target_execution_allowed_on(&tx, &helper)?
                && coordination_root_on(&tx, human, &parent)?.is_some()
                && session_input_allowed_on(&tx, &helper.id, human)?
                && helper.local_turn.is_none()
                && helper.native_turn.is_none(),
            "The original local handoff is no longer eligible for recovery"
        );
        helper.phase = Phase::Queued;
        tx.execute(
            "UPDATE interaction_instructions SET phase='queued',doc=?2,instance_id=?3 WHERE id=?1",
            params![helper.id, serde_json::to_string(&helper)?, self.instance_id],
        )?;
        tx.commit()?;
        Ok((helper, true))
    }

    /// Withdraw future dependency continuations synchronously with scoped controls.
    pub fn interaction_withdraw_session_requests(&self, caller: SessionKey) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        super::workflows::withdraw_on(&tx, caller)?;
        tx.execute("INSERT OR IGNORE INTO interaction_session_withdrawals SELECT i.id FROM interaction_instructions i JOIN sessions s ON s.id=i.session_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND i.phase='accepted'",params![caller.chat_id,caller.thread_id])?;
        withdraw_local_requests_on(&tx, caller)?;
        tx.commit()?;
        Ok(())
    }

    pub fn interaction_session_selected(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
        id: &str,
    ) -> Result<SessionRequest> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (raw,phase):(String,String)=conn.query_row("SELECT c.doc,c.phase FROM interaction_session_requests c JOIN sessions s ON s.chat_id=c.caller_chat AND s.thread_id=c.caller_topic JOIN users u ON u.tg_user_id=s.creator_user_id WHERE c.id=?1 AND c.human_id=?2 AND s.creator_user_id=?2 AND u.allowed=1 AND s.chat_id=?3 AND s.thread_id=?4 AND s.codex_thread_id=?5",params![id,human,caller.chat_id,caller.thread_id,native],|r|Ok((r.get(0)?,r.get(1)?)))?;
        let mut call: SessionRequest = serde_json::from_str(&raw)?;
        call.phase = phase;
        Ok(call)
    }

    /// Explicit recovery selects retained evidence, never another helper turn.
    pub fn interaction_session_recover(
        &self,
        caller: SessionKey,
        human: i64,
        native: &str,
        id: &str,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<Option<Instruction>> {
        let selected = self.interaction_session_selected(caller, human, native, id)?;
        self.recover_selected_session_result(&selected, closed, None)
    }

    pub(crate) fn recover_selected_session_result(
        &self,
        selected: &SessionRequest,
        closed: &tokio_util::sync::CancellationToken,
        config: Option<&crate::interaction::InteractionConfig>,
    ) -> Result<Option<Instruction>> {
        if closed.is_cancelled() {
            return Err(anyhow!("Explicit local return request closed"));
        }
        let deliveries = {
            let conn = self.conn.lock().expect("store mutex poisoned");
            let mut q=conn.prepare("SELECT d.id FROM interaction_session_requests c JOIN interaction_deliveries d ON d.request_id=c.target_instruction WHERE c.id=?1 AND c.human_id=?2 AND c.phase='requested' ORDER BY d.rowid DESC LIMIT 16")?;
            q.query_map(params![selected.id, selected.human], |r| {
                r.get::<_, String>(0)
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?
        };
        for delivery in deliveries {
            if let Some(i) = self.session_return(&delivery, selected.human, Some(closed), config)? {
                return Ok(Some(i));
            }
        }
        Ok(None)
    }

    /// A current worker-declared completed canonical result can become one
    /// attributed context input to the original logical caller, never human speech.
    #[cfg(test)]
    pub fn interaction_session_return(
        &self,
        delivery: &str,
        human: i64,
    ) -> Result<Option<Instruction>> {
        self.session_return(delivery, human, None, None)
    }

    pub(crate) fn interaction_session_return_scoped(
        &self,
        delivery: &str,
        human: i64,
        config: &crate::interaction::InteractionConfig,
    ) -> Result<Option<Instruction>> {
        self.session_return(delivery, human, None, Some(config))
    }

    fn session_return(
        &self,
        delivery: &str,
        human: i64,
        closed: Option<&tokio_util::sync::CancellationToken>,
        config: Option<&crate::interaction::InteractionConfig>,
    ) -> Result<Option<Instruction>> {
        if closed.is_some_and(|c| c.is_cancelled()) {
            return Err(anyhow!("Explicit local return request closed"));
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let found:Option<(String,String,String,String)>=tx.query_row("SELECT c.doc,c.phase,d.doc,d.result_id FROM interaction_session_requests c JOIN interaction_deliveries d ON d.request_id=c.target_instruction WHERE d.id=?1 AND c.human_id=?2 AND d.human_id=?2",params![delivery,human],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
        let Some((raw, phase, raw_delivery, result_id)) = found else {
            return Ok(None);
        };
        if phase != "requested" {
            return Ok(None);
        }
        let mut call: SessionRequest = serde_json::from_str(&raw)?;
        let d: crate::interaction::Delivery = serde_json::from_str(&raw_delivery)?;
        let (current, correction) = super::routing::delivery_freshness(&tx, &d)?;
        if !current || correction || current_epoch(&tx, human)? != call.epoch {
            return Ok(None);
        }
        let progress = !d.completed;
        let event = if progress {
            let deferred: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM interaction_results r
                  JOIN json_each(r.claim,'$.deferred') f ON f.value=?2
                  WHERE r.id=?1)",
                params![result_id, call.target_instruction],
                |row| row.get(0),
            )?;
            if !deferred || !d.covered.contains(&call.target_instruction) {
                return Ok(None);
            }
            let event = progress_event(&call.id, &result_id);
            if tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_sources WHERE channel='local-session-result' AND event_id=?1)",
                [&event], |row| row.get::<_,bool>(0))? { return Ok(None); }
            event
        } else {
            call.id.clone()
        };
        let parent = instruction_on(&tx, &call.parent_instruction, human)?;
        let viable: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns WHERE id=?1 AND status IN ('running','completed'))",
            [parent.local_turn],
            |r| r.get(0),
        )?;
        let exposes_portable = parent.phase == crate::interaction::TransportPhase::Submitting
            && parent
                .target_execution
                .as_ref()
                .is_some_and(|binding| binding.harness.is_portable());
        if (!viable && !current_return_parent_on(&tx, &parent)?)
            || (parent.phase != crate::interaction::TransportPhase::Accepted && !exposes_portable)
        {
            return Ok(None);
        }
        if coordination_root_with(&tx, human, &parent, current_return_parent_on)?.is_none() {
            return Ok(None);
        }
        let helper = instruction_on(&tx, &call.target_instruction, human)?;
        if helper.target_execution.is_some() && !current_bound_turn_on(&tx, &helper)? {
            return Ok(None);
        }
        let route = local_portable_route(config, call.caller)?;
        let result_text = if let Some(limit) =
            route.and_then(|(engine, _, agy_cli)| engine.attributed_handoff_text_limit(agy_cli))
        {
            let end = d
                .body
                .char_indices()
                .find(|(index, ch)| index + ch.len_utf8() > limit)
                .map_or(d.body.len(), |(index, _)| index);
            d.body[..end].to_owned()
        } else {
            d.body.chars().take(16000).collect()
        };
        let status = if progress {
            "Worker reported progress and left this dependency open."
        } else {
            "Worker-declared current completed coverage."
        };
        let text = format!(
            "Selected local session dependency returned. This is session-authored evidence, not a new human instruction or independent proof of completion. Local request: {}. Helper instruction: {}. Canonical result: {}. {status}\n\n{}",
            call.id, helper.id, result_id, result_text
        );
        let source = SourceInput {
            telegram_files: vec![],
            telegram_album_members: Vec::new(),
            tribu_source: None,
            transcription: None,
            channel: "local-session-result".into(),
            event_id: event,
            update_id: None,
            human_id: human,
            target_sessions: vec![parent.target_session],
            origin: parent.origin.clone(),
            text,
        };
        let (mut i, fresh) = super::interaction::admit_local_session_on(
            &tx,
            &source,
            call.caller,
            RequestRelation::Context(parent.requests),
            &self.instance_id,
            route,
            &call.epoch,
        )?;
        if !fresh {
            return Err(anyhow!("Unattributed local result source"));
        }
        save_epoch(&tx, &mut i, &call.epoch)?;
        let (result_native, result_turn): (String, String) = tx.query_row(
            "SELECT native_thread,native_turn FROM interaction_results WHERE id=?",
            [&result_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        let mut author = json!({"kind":"session_result","session":helper.target,"native_thread":result_native,"native_turn":result_turn,"parent_instruction":call.parent_instruction,"local_request":call.id,"canonical_result":result_id,"authorized_human":human});
        if progress {
            author["dependency_status"] = json!("progress");
        }
        if route.is_some() {
            crate::interaction::portable_handoff_packet(&i, &author)?;
        }
        tx.execute(
            "INSERT INTO interaction_session_authors VALUES(?1,?2)",
            params![i.input_id, author.to_string()],
        )?;
        if !progress {
            call.return_instruction = Some(i.id.clone());
            call.phase = "returned".into();
            tx.execute(
                "UPDATE interaction_session_requests SET phase='returned',doc=?2 WHERE id=?1",
                params![call.id, serde_json::to_string(&call)?],
            )?;
        }
        if closed.is_some_and(|c| c.is_cancelled()) {
            return Err(anyhow!(
                "Explicit local return request closed before commit"
            ));
        }
        tx.commit()?;
        Ok(Some(i))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::interaction::{ReturnRoute, TransportPhase as P};
    fn setup(s: &Store, topic: i64) -> SessionRecord {
        let key = SessionKey::new(100, Some(topic));
        s.ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(key, &format!("native-{topic}"))
            .unwrap();
        s.get_session(key).unwrap().unwrap()
    }
    fn accept(s: &Store, target: &SessionRecord, i: &Instruction, turn: &str) -> i64 {
        let local = s
            .record_turn_started(
                target.id,
                &TurnRequest {
                    session_key: target.key,
                    from_user_id: 100,
                    prompt: i.text.clone(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        s.record_turn_native_thread(local, target.codex_thread_id.as_deref().unwrap())
            .unwrap();
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.interaction_transport(&i.id, 100, local, P::Accepted, Some(turn))
            .unwrap();
        local
    }
    fn parent(s: &Store, a: &SessionRecord) -> Instruction {
        let i = s
            .interaction_admit(
                &SourceInput {
                    telegram_files: vec![],
                    telegram_album_members: Vec::new(),
                    tribu_source: None,
                    transcription: None,
                    channel: "fixture".into(),
                    event_id: "human-parent".into(),
                    update_id: None,
                    human_id: 100,
                    target_sessions: vec![a.id],
                    origin: ReturnRoute {
                        chat_id: 100,
                        thread_id: 1,
                        message_id: Some(10),
                    },
                    text: "Human task".into(),
                },
                a.key,
                RequestRelation::New,
            )
            .unwrap()
            .0;
        s.interaction_bind_epoch(&i.id, 100, "initial").unwrap();
        accept(s, a, &i, "parent-turn");
        s.interaction_instruction(&i.id, 100).unwrap().unwrap()
    }
    fn result(s: &Store, b: &SessionRecord, i: &Instruction) -> crate::interaction::Delivery {
        let helper_turn = format!("helper-turn-{}", i.id);
        let local = accept(s, b, i, &helper_turn);
        let text = format!(
            "Selected dependency answer\n<daimon-result>{}</daimon-result>",
            json!({"requests":i.requests,"covered":[i.id],"completed":i.requests})
        );
        s.interaction_record_result(
            &i.id,
            100,
            local,
            b.codex_thread_id.as_deref().unwrap(),
            &helper_turn,
            "answer",
            &text,
            true,
        )
        .unwrap()
        .remove(0)
    }
    #[test]
    fn attributed_dependency_can_target_a_portable_topic_without_telegram() {
        for paired in [false, true] {
            check_portable_dependency(paired, false, false, None, false);
        }
    }

    #[test]
    fn a_later_claude_turn_must_keep_the_original_native_scope_to_return() {
        check_portable_dependency(false, true, false, None, false);
    }

    #[test]
    fn paired_claude_recovers_a_completed_canonical_dependency_once() {
        check_portable_dependency(true, false, true, None, false);
    }

    #[test]
    fn selected_report_accepts_an_exact_settled_telegram_parent() {
        check_portable_dependency(true, false, false, Some(41), false);
    }

    #[test]
    fn a_known_unsent_early_report_uses_the_completion_format_after_cooldown() {
        check_portable_dependency(true, false, false, None, true);
    }

    fn check_portable_dependency(
        paired: bool,
        later: bool,
        recover_onward: bool,
        update: Option<i64>,
        cooldown: bool,
    ) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let caller = setup(&store, 7);
        let target = store
            .ensure_session(
                SessionKey::new(100, Some(8)),
                100,
                &super::super::tests::defaults(),
            )
            .unwrap();
        let event = update.map_or_else(|| Uuid::now_v7().to_string(), |id| id.to_string());
        let binding = store
            .interaction_presentation_list(100, caller.key, 0, 0)
            .unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        if update.is_none() {
            store
                .conversation_input_capture_files(
                    100,
                    caller.key,
                    &binding,
                    &event,
                    "Human task",
                    None,
                    None,
                    None,
                    vec![],
                    paired,
                )
                .unwrap();
        }
        let (instruction, _) = store
            .interaction_admit(
                &SourceInput {
                    telegram_files: vec![],
                    telegram_album_members: Vec::new(),
                    tribu_source: None,
                    transcription: None,
                    channel: if update.is_some() {
                        "telegram:55"
                    } else {
                        "conversation"
                    }
                    .into(),
                    event_id: event.clone(),
                    update_id: update,
                    human_id: 100,
                    target_sessions: vec![caller.id],
                    origin: ReturnRoute {
                        chat_id: 100,
                        thread_id: 7,
                        message_id: update.map(|_| 10),
                    },
                    text: "Human task".into(),
                },
                caller.key,
                RequestRelation::New,
            )
            .unwrap();
        store
            .interaction_bind_epoch(&instruction.id, 100, "initial")
            .unwrap();
        let parent_local = accept(&store, &caller, &instruction, "parent-turn");
        if let Some(update) = update {
            let raw = json!({"update_id":update,"direct_human_text":true,"message":{
                "date":0,"message_id":10,"message_thread_id":7,
                "from":{"id":100,"is_bot":false,"first_name":"Human"},
                "chat":{"id":100,"type":"supergroup"},"text":"Human task"
            }});
            store
                .save_bot_state("telegram_identity", r#"{"id":55}"#)
                .unwrap();
            store
                .save_bot_state(&format!("stop_input_epoch:{update}"), "initial")
                .unwrap();
            let conn = store.conn.lock().unwrap();
            conn.execute("INSERT INTO incoming_updates(update_id,payload_json,status,instance_id,turn_id,updated_at)
                VALUES(?1,?2,'settled','fixture',?3,'2026-11-28')", params![update,raw.to_string(),parent_local+1]).unwrap();
            conn.execute("INSERT OR IGNORE INTO original_ingress_order(channel,event_id) VALUES('telegram',?1)", [&event]).unwrap();
        }
        let profile: crate::interaction::InteractionConfig = serde_json::from_value(json!({
            "human_id":100,"chat_id":100,"topic_id":7,
            "targets":[{"topic_id":8,"name":"Design","harness":"claude"}],
            "claude_foreground":{"interaction_direct":true,"worker_command":["/fixture/claude"],
                "transport":{"command":["/fixture/matrix"],"timeout_seconds":5,
                    "source":{"kind":"body","being_ref":"fixture","embodiment_id":"fixture"}}}
        }))
        .unwrap();
        assert_eq!(
            store.interaction_target_labels(&profile).unwrap()[0]["visible_handoff"],
            true
        );
        let send = |id, text, report_to_topic| {
            store.interaction_session_request_scoped(
                caller.key,
                100,
                "native-7",
                "parent-turn",
                &instruction.id,
                id,
                target.key,
                text,
                &Default::default(),
                None,
                Some(&profile),
                report_to_topic,
            )
        };
        let oversized = "任".repeat(
            crate::interaction::ForegroundEngine::Claude
                .attributed_handoff_text_limit(false)
                .unwrap()
                / 3
                + 1,
        );
        assert!(send("oversized", &oversized, false).is_err());
        if !paired {
            assert!(send("companion", "Must stay private", true).is_err());
        }
        if let Some(update) = update {
            assert!(send("wrong-turn", "Must stay private", true).is_err());
            store
                .conn
                .lock()
                .unwrap()
                .execute(
                    "UPDATE incoming_updates SET turn_id=?1 WHERE update_id=?2",
                    params![parent_local, update],
                )
                .unwrap();
        }
        let (_, delivered, fresh) = send("context", "A scoped context handoff", paired).unwrap();
        let authorship = store
            .interaction_author(&delivered.id, 100)
            .unwrap()
            .unwrap();
        let packet = crate::interaction::portable_handoff_packet(&delivered, &authorship).unwrap();
        assert!(packet.contains("A scoped context handoff"));
        assert!(packet.contains("session_request"));
        let conn = store.conn.lock().unwrap();
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM interaction_session_requests",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
            1
        );
        drop(conn);
        assert!(fresh);
        assert_eq!(
            delivered.target_execution.as_ref().unwrap().harness,
            crate::execution::Harness::Claude
        );
        assert_eq!(delivered.admission_epoch.as_deref(), Some("initial"));
        assert_eq!(
            store
                .interaction_author(&delivered.id, 100)
                .unwrap()
                .unwrap()["kind"],
            "session_request"
        );
        let begin = |input: &Instruction| {
            store
                .begin_routed_portable(
                    input,
                    &TurnRequest {
                        session_key: target.key,
                        from_user_id: 100,
                        prompt: input.text.clone(),
                        runtime_instructions: None,
                        attachments: vec![],
                        review_mode: None,
                        override_search_mode: None,
                    },
                )
                .unwrap()
        };
        let (local, host_access) = begin(&delivered);
        assert_eq!(host_access, paired);
        let native = Uuid::now_v7().to_string();
        let prepared = json!({"native_session_id": native, "native_session_scope": "a".repeat(64)});
        let body = json!({"beingRef":"fixture","embodimentId":"fixture","incarnationId":"fixture"});
        assert!(
            store
                .expose_routed_portable(&delivered, local, &body, &prepared, paired, None)
                .unwrap()
        );
        let early_handoff = paired && !recover_onward;
        let visible_early = || {
            store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT count(*) FROM visible_portable_handoff_inputs WHERE source=?",
                    [&delivered.id],
                    |row| row.get::<_, i64>(0),
                )
                .unwrap()
        };
        assert_eq!(visible_early(), 0);
        let early_sent = early_handoff && update.is_some();
        let mut early_claim = None;
        if early_handoff {
            assert!(
                !store
                    .record_routed_input_acceptance(&delivered, local, "another-session")
                    .unwrap()
            );
            assert!(
                store
                    .record_routed_input_acceptance(&delivered, local, &native)
                    .unwrap()
            );
            let observed = store
                .interaction_instruction(&delivered.id, 100)
                .unwrap()
                .unwrap();
            assert!(observed.native_input_accepted);
            assert_eq!(observed.phase, P::Submitting);
            assert_eq!(visible_early(), 1);
            assert!(
                !store
                    .record_routed_input_acceptance(&delivered, local, &native)
                    .unwrap()
            );
            let handoff = store
                .topic_publication_claim(target.key, 100)
                .unwrap()
                .unwrap();
            assert_eq!(handoff.kind, "portable_handoff_input");
            assert_eq!(handoff.source, delivered.id);
            assert!(handoff.body.starts_with("Handoff from #"));
            assert!(handoff.body.ends_with("A scoped context handoff"));
            store
                .topic_publication_parts(handoff.id, &[handoff.body])
                .unwrap();
            store
                .conn
                .lock()
                .unwrap()
                .execute(
                    "INSERT INTO interaction_session_withdrawals VALUES(?)",
                    [&instruction.id],
                )
                .unwrap();
            assert_eq!(visible_early(), 0);
            assert!(!store.topic_publication_reserve(handoff.id, 0).unwrap());
            store
                .conn
                .lock()
                .unwrap()
                .execute(
                    "DELETE FROM interaction_session_withdrawals WHERE parent_instruction=?",
                    [&instruction.id],
                )
                .unwrap();
            store
                .save_bot_state("stop_admission_epoch:100", "later")
                .unwrap();
            assert_eq!(visible_early(), 0);
            assert!(!store.topic_publication_reserve(handoff.id, 0).unwrap());
            store
                .save_bot_state("stop_admission_epoch:100", "initial")
                .unwrap();
            assert_eq!(visible_early(), 1);
            if early_sent || cooldown {
                assert!(store.topic_publication_reserve(handoff.id, 0).unwrap());
            }
            if early_sent {
                store
                    .topic_publication_receipt(handoff.id, 0, Some(42), false)
                    .unwrap();
                store.topic_publication_finish(handoff.id).unwrap();
            }
            early_claim = Some(handoff.id);
        }
        assert_eq!(
            store
                .routed_portable_session_requests(
                    target.key,
                    100,
                    &native,
                    &delivered.id,
                    local,
                    None
                )
                .is_ok(),
            paired
        );
        let onward_owner = setup(&store, 9);
        let onward = store.interaction_session_request_scoped(
            target.key,
            100,
            &native,
            &delivered.id,
            &delivered.id,
            "onward",
            onward_owner.key,
            "A second scoped lookup",
            &Default::default(),
            Some(local),
            Some(&profile),
            false,
        );
        assert_eq!(onward.is_ok(), paired);
        if recover_onward {
            let (call, helper, _) = onward.unwrap();
            assert!(
                store
                    .routed_portable_session_requests(
                        target.key,
                        100,
                        "another-native-session",
                        &delivered.id,
                        local,
                        Some(&call.id),
                    )
                    .is_err()
            );
            let chosen = store
                .routed_portable_session_requests(
                    target.key,
                    100,
                    &native,
                    &delivered.id,
                    local,
                    Some(&call.id),
                )
                .unwrap()
                .pop()
                .unwrap();
            let closed = tokio_util::sync::CancellationToken::new();
            assert!(
                store
                    .recover_selected_session_result(&chosen, &closed, Some(&profile))
                    .unwrap()
                    .is_none()
            );
            result(&store, &onward_owner, &helper);
            let resumed = store
                .recover_selected_session_result(&chosen, &closed, Some(&profile))
                .unwrap()
                .unwrap();
            assert_eq!(resumed.target, target.key);
            assert_eq!(
                resumed.target_execution.as_ref().unwrap().harness,
                crate::execution::Harness::Claude
            );
            assert_eq!(
                store.interaction_author(&resumed.id, 100).unwrap().unwrap()["kind"],
                "session_result"
            );
            assert!(
                store
                    .recover_selected_session_result(&chosen, &closed, Some(&profile))
                    .unwrap()
                    .is_none()
            );
            return;
        }
        let text = format!(
            "Worked on the rig\n<daimon-result>{}</daimon-result>",
            json!({"requests":delivered.requests, "covered":[delivered.id], "completed":delivered.requests})
        );
        if later {
            let partial = format!(
                "Work remains open\n<daimon-result>{}</daimon-result>",
                json!({"requests":delivered.requests, "covered":[delivered.id], "completed":[]})
            );
            let partial = store
                .finish_routed_portable(
                    &delivered,
                    local,
                    &json!({"phase":"completed","sessionId":native,"text":partial}),
                    None,
                    None,
                )
                .unwrap();
            assert!(!partial[0].completed);
            assert!(
                store
                    .interaction_session_return(&partial[0].id, 100)
                    .unwrap()
                    .is_none()
            );
            for (key, scope, allowed) in [("wrong-scope", "b", false), ("same-scope", "a", true)] {
                let (_, next, _) = send(key, "Continue existing work", false).unwrap();
                let (next_local, _) = begin(&next);
                let selected =
                    json!({"native_session_id":native, "native_session_scope":scope.repeat(64)});
                assert!(
                    store
                        .expose_routed_portable(&next, next_local, &body, &selected, false, None)
                        .unwrap()
                );
                let deliveries = store
                    .finish_routed_portable(
                        &next,
                        next_local,
                        &json!({"phase":"completed","sessionId":native,"text":text}),
                        None,
                        None,
                    )
                    .unwrap();
                assert_eq!(deliveries.len(), usize::from(allowed));
                if let Some(delivery) = deliveries.first() {
                    assert_eq!(delivery.internal, Some(true));
                    assert_eq!(delivery.request_id, delivered.id);
                    assert!(
                        store
                            .interaction_session_return(&delivery.id, 100)
                            .unwrap()
                            .is_some()
                    );
                    assert!(
                        store
                            .interaction_session_return(&delivery.id, 100)
                            .unwrap()
                            .is_none()
                    );
                }
            }
            return;
        }
        let deliveries = store
            .finish_routed_portable(
                &delivered,
                local,
                &json!({"phase":"completed", "sessionId":native, "text":text}),
                None,
                None,
            )
            .unwrap();
        assert_eq!(deliveries[0].internal, Some(true));
        assert_eq!(
            store
                .interaction_instruction(&delivered.id, 100)
                .unwrap()
                .unwrap()
                .native_input_accepted,
            paired
        );
        let handoff: Option<(i64, String)> = store.conn.lock().unwrap().query_row(
            "SELECT id,source FROM topic_publications WHERE local_turn=?1 AND kind='portable_report_request'",
            [local],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ).optional().unwrap();
        assert_eq!(handoff.is_some(), paired);
        if let Some((handoff_id, result_source)) = handoff {
            let visible_handoffs = || {
                store
                    .conn
                    .lock()
                    .unwrap()
                    .query_row(
                        "SELECT count(*) FROM visible_portable_report_requests WHERE id=?",
                        [handoff_id],
                        |row| row.get::<_, i64>(0),
                    )
                    .unwrap()
            };
            assert_eq!(visible_handoffs(), 1);
            if let Some(update) = update {
                let generation: String = store
                    .conn
                    .lock()
                    .unwrap()
                    .query_row(
                        "SELECT generation FROM conversation_entry_generations WHERE session_id=?",
                        [caller.id],
                        |row| row.get(0),
                    )
                    .unwrap();
                for (current, visible) in [("later-generation", 0), (generation.as_str(), 1)] {
                    store.conn.lock().unwrap().execute(
                        "UPDATE conversation_entry_generations SET generation=?1 WHERE session_id=?2",
                        params![current, caller.id],
                    ).unwrap();
                    assert_eq!(visible_handoffs(), visible);
                }
                let conn = store.conn.lock().unwrap();
                conn.execute(
                    "UPDATE sessions SET force_fresh_thread=1 WHERE id=?",
                    [caller.id],
                )
                .unwrap();
                drop(conn);
                assert_eq!(visible_handoffs(), 0);
                let conn = store.conn.lock().unwrap();
                conn.execute("UPDATE turns SET execution_generation=(SELECT generation FROM conversation_entry_generations WHERE session_id=?1) WHERE id=?2", params![caller.id,parent_local]).unwrap();
                drop(conn);
                assert_eq!(visible_handoffs(), 1);
                let conn = store.conn.lock().unwrap();
                conn.execute(
                    "UPDATE sessions SET force_fresh_thread=0 WHERE id=?",
                    [caller.id],
                )
                .unwrap();
                conn.execute(
                    "UPDATE interaction_instructions SET phase='submitting' WHERE id=?",
                    [&instruction.id],
                )
                .unwrap();
                conn.execute(
                    "UPDATE interaction_session_requests SET doc=json_set(doc,'$.caller_turn',?1)
                              WHERE target_instruction=?2",
                    params![instruction.id, delivered.id],
                )
                .unwrap();
                conn.execute(
                    "UPDATE incoming_updates SET status='handled' WHERE update_id=?",
                    [update],
                )
                .unwrap();
                drop(conn);
                assert_eq!(visible_handoffs(), 1);
                let conn = store.conn.lock().unwrap();
                conn.execute(
                    "UPDATE interaction_instructions SET phase='accepted' WHERE id=?",
                    [&instruction.id],
                )
                .unwrap();
                conn.execute("UPDATE interaction_session_requests SET doc=json_set(doc,'$.caller_turn','parent-turn')
                              WHERE target_instruction=?", [&delivered.id]).unwrap();
                conn.execute(
                    "UPDATE incoming_updates SET status='settled' WHERE update_id=?",
                    [update],
                )
                .unwrap();
            }
            for (retired, expected) in [(1, 0), (0, 1)] {
                if update.is_some() {
                    store
                        .save_bot_state(
                            "stop_admission_epoch:100",
                            if retired == 1 { "later" } else { "initial" },
                        )
                        .unwrap();
                } else {
                    store
                        .conn
                        .lock()
                        .unwrap()
                        .execute(
                            "UPDATE conversation_inputs SET retired=?1 WHERE id=?2",
                            params![retired, event],
                        )
                        .unwrap();
                }
                assert_eq!(visible_handoffs(), expected);
            }
            if !early_sent {
                if let Some(early) = early_claim {
                    if cooldown {
                        store.topic_publication_retry(early, 0).unwrap();
                    }
                    assert!(!store.topic_publication_reserve(early, 0).unwrap());
                }
                let handoff = store
                    .topic_publication_claim(target.key, 100)
                    .unwrap()
                    .unwrap();
                assert_eq!(handoff.id, handoff_id);
                assert_eq!(handoff.kind, "portable_report_request");
                assert!(handoff.body.ends_with("A scoped context handoff"));
                store
                    .topic_publication_parts(handoff.id, &[handoff.body])
                    .unwrap();
                assert!(store.topic_publication_reserve(handoff.id, 0).unwrap());
                store
                    .topic_publication_receipt(handoff.id, 0, Some(42), false)
                    .unwrap();
                store.topic_publication_finish(handoff.id).unwrap();
            }
            let report = store
                .topic_publication_claim(target.key, 100)
                .unwrap()
                .unwrap();
            assert_eq!(report.kind, "portable_report");
            assert_eq!(report.source, result_source);
            assert_eq!(report.body, "Worked on the rig");
            store
                .topic_publication_parts(report.id, &[report.body, "Second part".into()])
                .unwrap();
            assert!(store.topic_publication_reserve(report.id, 0).unwrap());
            store
                .topic_publication_receipt(report.id, 0, None, false)
                .unwrap();
            let (_, stale, _) = send("superseded", "Report before correction", true).unwrap();
            let (stale_local, _) = begin(&stale);
            assert!(
                store
                    .expose_routed_portable(&stale, stale_local, &json!({}), &prepared, true, None)
                    .unwrap()
            );

            let correction = Uuid::now_v7().to_string();
            let binding = store
                .interaction_presentation_list(100, caller.key, 0, 0)
                .unwrap()["binding"]
                .as_str()
                .unwrap()
                .to_owned();
            store
                .conversation_input_capture_files(
                    100,
                    caller.key,
                    &binding,
                    &correction,
                    "New human correction",
                    None,
                    None,
                    None,
                    vec![],
                    true,
                )
                .unwrap();
            let mut source = store.interaction_source(&instruction.id, 100).unwrap();
            source.channel = "conversation".into();
            source.event_id = correction;
            source.update_id = None;
            source.origin.message_id = None;
            source.text = "New human correction".into();
            store
                .interaction_admit(
                    &source,
                    caller.key,
                    RequestRelation::Amends(instruction.requests.clone()),
                )
                .unwrap();
            assert_eq!(visible_handoffs(), 0);

            let stale_text = format!(
                "Superseded work\n<daimon-result>{}</daimon-result>",
                json!({
                    "requests":stale.requests, "covered":[stale.id], "completed":stale.requests,
                })
            );
            let result = store
                .finish_routed_portable(
                    &stale,
                    stale_local,
                    &json!({"phase":"completed","sessionId":native,"text":stale_text}),
                    None,
                    None,
                )
                .unwrap();
            assert_eq!(result[0].internal, Some(true));
            assert!(!store.topic_publication_reserve(report.id, 1).unwrap());
            store.topic_publication_finish(report.id).unwrap();
            assert!(
                store
                    .topic_publication_claim(target.key, 100)
                    .unwrap()
                    .is_none()
            );
        }
        if paired {
            let (_, delivered, _) = send("revoked", "Retire before exposure", true).unwrap();
            let (local, _) = begin(&delivered);
            if let Some(update) = update {
                store
                    .save_bot_state(&format!("stop_input_epoch:{update}"), "revoked")
                    .unwrap();
            } else {
                store
                    .conn
                    .lock()
                    .unwrap()
                    .execute(
                        "UPDATE conversation_inputs SET retired=1 WHERE id=?1",
                        [&event],
                    )
                    .unwrap();
            }
            assert!(!store.expose_routed_portable(
                &delivered,
                local,
                &json!({}),
                &json!({"native_session_id": Uuid::now_v7().to_string(), "native_session_scope": "a".repeat(64)}),
                true,
                None,
            ).unwrap());
        }
        assert!(
            store
                .interaction_author(&delivered.id, 100)
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn owner_recovers_only_the_known_unsent_admitted_handoff() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let s = Store::open(file.path(), &[100], &defaults).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let p = parent(&s, &a);
        let (call, helper, _) = s
            .interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                "recover-me",
                b.key,
                "A retained handoff",
                &tokio_util::sync::CancellationToken::new(),
            )
            .unwrap();
        // Emulate the existing writer rollover: transport changes, original stays frozen.
        s.conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE interaction_instructions SET phase='retained_unsent' WHERE id=?1",
                [&helper.id],
            )
            .unwrap();
        assert!(s.interaction_session_recover_unsent(101, &call.id).is_err());
        let (recovered, changed) = s.interaction_session_recover_unsent(100, &call.id).unwrap();
        assert!(changed);
        assert_eq!(recovered.id, helper.id);
        assert_eq!(recovered.input_id, helper.input_id);
        assert_eq!(recovered.admission_epoch, helper.admission_epoch);
        assert_eq!(recovered.phase, P::Queued);
        assert!(
            !s.interaction_session_recover_unsent(100, &call.id)
                .unwrap()
                .1
        );

        for phase in ["uncertain", "cancelled", "accepted"] {
            s.conn
                .lock()
                .unwrap()
                .execute(
                    "UPDATE interaction_instructions SET phase=?2 WHERE id=?1",
                    params![helper.id, phase],
                )
                .unwrap();
            assert!(
                !s.interaction_session_recover_unsent(100, &call.id)
                    .unwrap()
                    .1
            );
        }

        s.conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE interaction_instructions SET phase='retained_unsent' WHERE id=?1",
                [&helper.id],
            )
            .unwrap();
        s.conn
            .lock()
            .unwrap()
            .execute(
                "INSERT INTO bot_state(key,value) VALUES('stop_admission_epoch:100','later')",
                [],
            )
            .unwrap();
        assert!(s.interaction_session_recover_unsent(100, &call.id).is_err());
        s.conn
            .lock()
            .unwrap()
            .execute(
                "DELETE FROM bot_state WHERE key='stop_admission_epoch:100'",
                [],
            )
            .unwrap();
        s.clear_session_conversation(a.key).unwrap();
        assert!(
            !s.interaction_session_recover_unsent(100, &call.id)
                .unwrap()
                .1
        );
    }

    #[test]
    fn same_owner_coordination_can_continue_once_and_return_through_both_topics() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let c = setup(&s, 9);
        let p = parent(&s, &a);
        let closed = tokio_util::sync::CancellationToken::new();
        let send =
            |caller: &SessionRecord, turn: &str, parent: &Instruction, client: &str, target| {
                s.interaction_session_request(
                    caller.key,
                    100,
                    caller.codex_thread_id.as_deref().unwrap(),
                    turn,
                    &parent.id,
                    client,
                    target,
                    "Attributed coordination",
                    &closed,
                )
            };
        let (_, first, _) = send(&a, "parent-turn", &p, "first", b.key).unwrap();
        accept(&s, &b, &first, "first-turn");
        assert!(send(&b, "first-turn", &first, "cycle", a.key).is_err());
        let (_, second, _) = send(&b, "first-turn", &first, "onward", c.key).unwrap();
        assert_eq!(
            s.interaction_author(&second.id, 100).unwrap().unwrap()["parent_instruction"],
            first.id
        );
        for client in ["third", "fourth"] {
            assert!(send(&b, "first-turn", &first, client, c.key).is_ok());
        }
        assert!(send(&a, "parent-turn", &p, "exhausted", c.key).is_err());

        let delivery = result(&s, &c, &second);
        let second_turn = format!("helper-turn-{}", second.id);
        assert!(send(&c, &second_turn, &second, "too-deep", a.key).is_err());
        let returned = s
            .interaction_session_return(&delivery.id, 100)
            .unwrap()
            .unwrap();
        assert_eq!(returned.target, b.key);
        assert_eq!(returned.requests, first.requests);

        let local = accept(&s, &b, &returned, "return-turn");
        let text = format!(
            "Coordinated result\n<daimon-result>{}</daimon-result>",
            json!({"requests":first.requests,"covered":[first.id,returned.id],"completed":first.requests})
        );
        let delivery = s
            .interaction_record_result(
                &returned.id,
                100,
                local,
                "native-8",
                "return-turn",
                "coordinated-result",
                &text,
                false,
            )
            .unwrap()
            .remove(0);
        let final_return = s
            .interaction_session_return(&delivery.id, 100)
            .unwrap()
            .unwrap();
        assert_eq!(final_return.target, a.key);
        assert_eq!(final_return.requests, p.requests);
    }

    #[test]
    fn codex_dependency_return_does_not_inherit_a_paired_claude_controller() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let caller = setup(&store, 7);
        let helper = setup(&store, 8);
        let parent = parent(&store, &caller);
        let (_, child, _) = store
            .interaction_session_request(
                caller.key,
                100,
                "native-7",
                "parent-turn",
                &parent.id,
                "question",
                helper.key,
                "Check this result.",
                &Default::default(),
            )
            .unwrap();
        let reply = result(&store, &helper, &child);
        let profile = serde_json::from_value(json!({
            "human_id":100,"chat_id":100,"topic_id":1,
            "targets":[{"topic_id":7,"name":"Design","harness":"claude"}],
            "claude_foreground":{"interaction_direct":true,"worker_command":["/fixture/claude"],
                "transport":{"command":["/fixture/matrix"],"timeout_seconds":5,
                    "source":{"kind":"body","being_ref":"fixture","embodiment_id":"fixture"}}}
        }))
        .unwrap();
        let returned = store
            .interaction_session_return_scoped(&reply.id, 100, &profile)
            .unwrap()
            .unwrap();
        assert_eq!(
            returned.target_execution.as_ref().unwrap().harness,
            crate::execution::Harness::Claude,
        );
        let conn = store.conn.lock().unwrap();
        assert!(session_input_allowed_on(&conn, &returned.id, 100).unwrap());
        assert!(!paired_result_parent_on(&conn, &returned).unwrap());
        assert!(!controller_parent_eligible_on(&conn, 100, &returned).unwrap());
    }

    #[test]
    fn local_dependency_is_attributed_idempotent_bounded_and_returns_to_logical_caller() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let p = parent(&s, &a);
        let closed = tokio_util::sync::CancellationToken::new();
        let send = |client: &str, text: &str| {
            s.interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                client,
                b.key,
                text,
                &closed,
            )
        };
        let (call, i, fresh) =
            send("selected-question", "A bounded session-authored question").unwrap();
        assert!(fresh);
        assert_eq!(
            s.interaction_author(&i.id, 100).unwrap().unwrap()["kind"],
            "session_request"
        );
        assert!(
            !send("selected-question", "A bounded session-authored question")
                .unwrap()
                .2
        );
        assert!(send("selected-question", "Changed question").is_err());
        assert!(
            s.interaction_session_request(
                a.key,
                100,
                "native-7",
                "foreign-turn",
                &p.id,
                "foreign",
                b.key,
                "Text",
                &closed
            )
            .is_err()
        );
        assert!(
            s.interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                "self",
                a.key,
                "Text",
                &closed
            )
            .is_err()
        );
        for client in ["second", "third", "fourth"] {
            send(client, "Another selected dependency").unwrap();
        }
        assert!(send("fifth", "No unbounded fanout").is_err());
        let d = result(&s, &b, &i);
        assert!(
            s.interaction_session_request(
                b.key,
                100,
                "native-8",
                &format!("helper-turn-{}", i.id),
                &i.id,
                "recursive",
                a.key,
                "Must not recurse",
                &closed
            )
            .is_err()
        );
        s.record_turn_finished(p.local_turn.unwrap(), "completed", None)
            .unwrap();
        s.set_session_codex_thread(a.key, "renewed-native-7")
            .unwrap();
        let returned = s.interaction_session_return(&d.id, 100).unwrap().unwrap();
        assert_eq!(returned.target, a.key);
        assert_eq!(returned.native_thread.as_deref(), Some("renewed-native-7"));
        assert_eq!(returned.requests, p.requests);
        assert_eq!(returned.origin, p.origin);
        assert_eq!(returned.admission_epoch.as_deref(), Some("initial"));
        let author = s.interaction_author(&returned.id, 100).unwrap().unwrap();
        assert_eq!(author["kind"], "session_result");
        assert_eq!(author["native_turn"], format!("helper-turn-{}", i.id));
        assert_eq!(author["local_request"], call.id);
        assert!(s.interaction_session_return(&d.id, 100).unwrap().is_none());
        s.interaction_withdraw_session_requests(a.key).unwrap();
        assert_eq!(
            s.interaction_instruction(&returned.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::RetainedUnsent
        );
        assert!(
            s.interaction_session_requests(a.key, 101, "renewed-native-7")
                .is_err()
        );
    }
    #[test]
    fn dependency_author_and_admission_commit_atomically_and_retired_or_withdrawn_calls_do_not_return()
     {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let p = parent(&s, &a);
        let closed = tokio_util::sync::CancellationToken::new();
        let send = |client: &str| {
            s.interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                client,
                b.key,
                "Selected question",
                &closed,
            )
        };
        s.conn.lock().unwrap().execute_batch("CREATE TRIGGER fail_author BEFORE INSERT ON interaction_session_authors BEGIN SELECT RAISE(ABORT,'synthetic author write failure'); END;").unwrap();
        assert!(send("atomic").is_err());
        assert_eq!(s.interaction_recent(100, b.key).unwrap().len(), 0);
        s.conn
            .lock()
            .unwrap()
            .execute_batch("DROP TRIGGER fail_author;")
            .unwrap();
        let (_, i, _) = send("withdraw").unwrap();
        let d = result(&s, &b, &i);
        s.interaction_withdraw_session_requests(a.key).unwrap();
        assert!(s.interaction_session_return(&d.id, 100).unwrap().is_none());
        assert!(send("new-id-after-withdrawal").is_err());
    }
    #[test]
    fn retired_dependency_cannot_return_or_create_a_new_grant() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let p = parent(&s, &a);
        let closed = tokio_util::sync::CancellationToken::new();
        let send = |client: &str| {
            s.interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                client,
                b.key,
                "Selected question",
                &closed,
            )
        };
        let (_, i, _) = send("retire").unwrap();
        let d = result(&s, &b, &i);
        s.save_bot_state("stop_admission_epoch:100", "synthetic-retired-generation")
            .unwrap();
        assert!(s.interaction_session_return(&d.id, 100).unwrap().is_none());
        assert!(send("new-after-retire").is_err());
    }
    #[test]
    fn onward_result_survives_loss_of_the_original_collector() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let c = setup(&s, 9);
        let original: crate::telegram::Update = serde_json::from_value(json!({
            "update_id": 10, "direct_human_text": true,
            "message": {"message_id":10, "message_thread_id":7,
                "from":{"id":100,"is_bot":false,"first_name":"Human"},
                "chat":{"id":100,"type":"private"}, "text":"Coordinate the current task."}
        }))
        .unwrap();
        s.admit_update(&original).unwrap();
        let local = s
            .record_turn_started(
                a.id,
                &TurnRequest {
                    session_key: a.key,
                    from_user_id: 100,
                    prompt: "Coordinate the current task.".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        s.record_turn_native_thread(local, "native-7").unwrap();
        s.begin_update(10).unwrap();
        s.begin_update_steer(10, local).unwrap();
        s.native_direct_input_receipt(a.key, 100, local, "paired-turn", "telegram:100:100:10", 55)
            .unwrap();
        s.accept_update_steer(10).unwrap();
        let parent_id: String = s
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT instruction FROM interaction_direct_parents",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let open = tokio_util::sync::CancellationToken::new();
        let (_, hop, _) = s
            .interaction_session_request(
                a.key,
                100,
                "native-7",
                "paired-turn",
                &parent_id,
                "first-hop",
                b.key,
                "Coordinate the task.",
                &open,
            )
            .unwrap();
        accept(&s, &b, &hop, "first-hop-turn");
        let (call, helper, _) = s
            .interaction_session_request(
                b.key,
                100,
                "native-8",
                "first-hop-turn",
                &hop.id,
                "onward-hop",
                c.key,
                "Check the result.",
                &open,
            )
            .unwrap();
        let delivery = result(&s, &c, &helper);
        s.record_turn_finished(local, "failed", None).unwrap();
        s.finish_update_turn(10, false).unwrap();
        s.record_native_message(
            local,
            "native-7",
            "other-turn",
            "unrelated-final",
            Some("final_answer"),
            "Different native turn.",
        )
        .unwrap();
        assert!(
            s.interaction_session_return(&delivery.id, 100)
                .unwrap()
                .is_none()
        );
        s.record_native_message(
            local,
            "native-7",
            "paired-turn",
            "paired-final",
            Some("final_answer"),
            "The accepted original reached a final answer.",
        )
        .unwrap();
        let returned = s
            .interaction_session_return(&delivery.id, 100)
            .unwrap()
            .unwrap();
        assert_eq!(returned.target, b.key);
        assert_eq!(
            s.interaction_session_selected(b.key, 100, "native-8", &call.id)
                .unwrap()
                .phase,
            "returned"
        );
        assert!(
            s.interaction_session_input_allowed(&returned.id, 100)
                .unwrap()
        );
        assert!(
            s.interaction_session_return(&delivery.id, 100)
                .unwrap()
                .is_none()
        );
        assert!(
            s.interaction_session_request(
                b.key,
                100,
                "native-8",
                "first-hop-turn",
                &hop.id,
                "new-hop",
                c.key,
                "Do new work.",
                &open,
            )
            .is_err()
        );
    }

    #[test]
    fn completed_canonical_dependency_recovers_after_restart_without_replaying_helper() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let s = Store::open(file.path(), &[100], &defaults).unwrap();
        let a = setup(&s, 7);
        let b = setup(&s, 8);
        let p = parent(&s, &a);
        let closed = tokio_util::sync::CancellationToken::new();
        let (call, i, _) = s
            .interaction_session_request(
                a.key,
                100,
                "native-7",
                "parent-turn",
                &p.id,
                "recover",
                b.key,
                "Selected question",
                &closed,
            )
            .unwrap();
        let _d = result(&s, &b, &i);
        let helper = s.interaction_instruction(&i.id, 100).unwrap().unwrap();
        s.record_turn_finished(p.local_turn.unwrap(), "completed", None)
            .unwrap();
        s.record_turn_finished(helper.local_turn.unwrap(), "completed", None)
            .unwrap();
        drop(s);
        // Canonical item+delivery committed, return admission had not run.
        let s = Store::open(file.path(), &[100], &defaults).unwrap();
        assert_eq!(
            s.interaction_session_requests(a.key, 100, "native-7")
                .unwrap()[0]
                .phase,
            "requested"
        );
        {
            let conn = s.conn.lock().unwrap();
            for n in 0..17 {
                let mut later = call.clone();
                later.id = format!("retained-later-{n}");
                later.target_instruction = format!("historical-helper-{n}");
                conn.execute("INSERT INTO interaction_session_requests VALUES(?1,100,100,7,?2,?3,'withdrawn',?4)",params![later.id,p.id,later.target_instruction,serde_json::to_string(&later).unwrap()]).unwrap();
            }
        }
        assert!(
            !s.interaction_session_requests(a.key, 100, "native-7")
                .unwrap()
                .iter()
                .any(|c| c.id == call.id)
        );
        let cancelled = tokio_util::sync::CancellationToken::new();
        cancelled.cancel();
        assert!(
            s.interaction_session_recover(a.key, 100, "native-7", &call.id, &cancelled)
                .is_err()
        );
        assert_eq!(
            s.interaction_session_selected(a.key, 100, "native-7", &call.id)
                .unwrap()
                .phase,
            "requested"
        );
        let returned = s
            .interaction_session_recover(a.key, 100, "native-7", &call.id, &closed)
            .unwrap()
            .unwrap();
        assert_eq!(returned.requests, p.requests);
        assert!(
            s.interaction_session_recover(a.key, 100, "native-7", &call.id, &closed)
                .unwrap()
                .is_none()
        );
        let conn = s.conn.lock().unwrap();
        let count: i64 = conn
            .query_row("SELECT count(*) FROM interaction_results", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1);
        let turns: i64 = conn
            .query_row("SELECT count(*) FROM turns", [], |r| r.get(0))
            .unwrap();
        assert_eq!(turns, 2);
    }
}
