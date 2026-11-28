//! A secondary topic projection never admits input or controls native execution.
use super::*;
use serde_json::json;

// One predicate for control publication, actual-send validation and client reads.
const CONTROL_NOTICE_SCOPE: &str = r#"(
    (p.kind='control' AND s.force_fresh_thread=0 AND EXISTS(
        SELECT 1 FROM interaction_goal_controls g
        WHERE g.id=json_extract(CASE WHEN p.kind='control' AND json_valid(p.source) THEN p.source ELSE '[]' END,'$[0]')
        AND g.human_id=p.human_id AND g.target_chat=s.chat_id AND g.target_topic=s.thread_id
        AND json_extract(g.doc,'$.actor.local')=p.local_turn
        AND json_extract(g.doc,'$.target_binding[1]')=s.id
        AND json_extract(g.doc,'$.target_binding[2]')=s.codex_thread_id
    )) OR (p.kind='task_control' AND s.force_fresh_thread=0 AND EXISTS(
        SELECT 1 FROM human_interactions h
        WHERE h.id=json_extract(CASE WHEN p.kind='task_control' AND json_valid(p.source) THEN p.source ELSE '[]' END,'$[0]')
        AND h.kind='task' AND h.state='cancelled' AND h.requester=p.human_id
        AND h.session_id=s.id AND h.local_turn=p.local_turn AND h.native_thread=s.codex_thread_id
        AND json_type(h.payload_json,'$.source.agentWithdrawal.actor')='object'
        AND (json_extract(h.payload_json,'$.source.agentWithdrawal.actor.session.chat_id')!=s.chat_id
            OR json_extract(h.payload_json,'$.source.agentWithdrawal.actor.session.thread_id')!=s.thread_id)
    ))
)"#;

const ENTRY_INPUT_SCOPE: &str = r#"(p.kind='entry_input' AND s.force_fresh_thread=0
    AND EXISTS(SELECT 1 FROM conversation_inputs c WHERE c.id=p.source
        AND c.session_id=p.session_id AND c.human_id=p.human_id
        AND c.native_thread=s.codex_thread_id
        AND (c.local_turn=p.local_turn OR EXISTS(SELECT 1 FROM interaction_instructions i
            JOIN interaction_sources x ON x.id=i.input_id WHERE json_extract(i.doc,'$.local_turn')=p.local_turn
            AND x.human_id=p.human_id AND x.channel='conversation' AND x.event_id=c.id))))"#;

// A progress echo is visible only through the original web return binding.
const ENTRY_PROGRESS_SCOPE: &str = r#"(p.kind='entry_progress' AND s.force_fresh_thread=0
    AND EXISTS(SELECT 1 FROM interaction_native_messages m
        JOIN conversation_inputs c ON c.id=m.presentation_input AND c.human_id=p.human_id
        JOIN sessions w ON w.id=t.session_id AND w.creator_user_id=p.human_id
        WHERE m.local_turn=p.local_turn AND m.phase='commentary'
        AND p.source=json_array(m.native_thread,m.native_turn,m.item_id)
        AND c.session_id=p.session_id AND c.native_thread=s.codex_thread_id
        AND w.codex_thread_id=m.native_thread AND w.force_fresh_thread=0))"#;

const REPORT_PARENT_SCOPE: &str = r#"((src.channel='conversation' AND EXISTS(SELECT 1 FROM conversation_inputs original
            WHERE original.id=src.event_id AND original.human_id=call.human_id
              AND original.retired=0 AND json_extract(original.doc,'$.paired_actor')=1))
          OR (src.channel LIKE 'telegram:%' AND EXISTS(
            SELECT 1 FROM incoming_updates original
            JOIN bot_state captured ON captured.key='stop_input_epoch:'||original.update_id
            JOIN bot_state bot ON bot.key='telegram_identity'
            LEFT JOIN bot_state current ON current.key='stop_admission_epoch:'||call.human_id
            JOIN turns caller_turn ON caller_turn.id=json_extract(parent.doc,'$.local_turn')
              AND caller_turn.session_id=parent.session_id AND caller_turn.from_user_id=call.human_id
            JOIN sessions caller ON caller.id=caller_turn.session_id AND caller.creator_user_id=call.human_id
              AND caller.chat_id=call.caller_chat AND caller.thread_id=call.caller_topic
            JOIN conversation_entry_generations caller_generation ON caller_generation.session_id=caller.id
            WHERE original.update_id=src.update_id AND src.event_id=cast(original.update_id AS TEXT)
              AND src.channel='telegram:'||json_extract(bot.value,'$.id')
              AND captured.value=json_extract(call.doc,'$.epoch')
              AND captured.value=coalesce(current.value,'initial')
              AND caller_turn.execution_generation=caller_generation.generation
              AND caller_turn.native_thread_id=json_extract(call.doc,'$.caller_native')
              AND caller_turn.native_thread_id=json_extract(parent.doc,'$.native_thread')
              AND ((parent.phase='accepted' AND caller_turn.status IN ('running','completed'))
                OR (parent.phase='submitting' AND caller_turn.status='running' AND original.status='handled'
                  AND parent.id=json_extract(call.doc,'$.caller_turn')))
          )))"#;

// Selected portable reports belong to the exact completed topic turn and result.
const PORTABLE_REPORT_SCOPE: &str = r#"(p.kind IN ('portable_report','portable_report_request') AND t.status='completed'
    AND t.session_id=s.id
    AND EXISTS(SELECT 1 FROM conversation_entry_generations g
      WHERE g.session_id=s.id AND g.generation=t.execution_generation)
    AND EXISTS(SELECT 1 FROM interaction_results r JOIN interaction_instructions i
      ON r.local_turn=json_extract(i.doc,'$.local_turn') AND r.native_turn=json_extract(i.doc,'$.native_turn')
      JOIN interaction_session_requests call ON call.target_instruction=i.id
      JOIN interaction_instructions parent ON parent.id=call.parent_instruction
      JOIN interaction_sources src ON src.id=parent.input_id AND src.human_id=call.human_id
      WHERE r.id=p.source AND r.local_turn=p.local_turn AND r.native_thread=t.native_thread_id
        AND i.session_id=s.id AND i.phase='accepted'
        AND call.human_id=p.human_id AND json_extract(call.doc,'$.report_to_topic')=1
        AND call.phase IN ('requested','returned')
        AND {REPORT_PARENT_SCOPE}))"#;

const REPORT_PARENT_CURRENT: &str = r#"NOT EXISTS (SELECT 1 FROM interaction_request_links old
        JOIN interaction_request_links newer ON newer.request_id=old.request_id
        JOIN interaction_instructions i ON i.id=newer.instruction_id
        JOIN interaction_sources x ON x.id=i.input_id
        JOIN original_ingress_order ingress ON ingress.event_id=x.event_id
          AND ingress.channel=CASE WHEN x.update_id IS NOT NULL THEN 'telegram' ELSE 'conversation' END
        WHERE old.instruction_id=parent.id AND ingress.id>original.id AND x.human_id=p.human_id
          AND i.phase NOT IN ('cancelled','rejected') AND json_extract(i.doc,'$.relation.kind')='amends'
          AND NOT EXISTS (SELECT 1 FROM interaction_session_authors a WHERE a.input_id=x.id))"#;

// Web reads are independent of Telegram delivery, but must apply the same
// retained permission and correction fences before disclosing a request.
const REPORT_REQUEST_CURRENT: &str = r#"EXISTS (
    SELECT 1 FROM interaction_deliveries d
    JOIN interaction_session_requests call ON call.target_instruction=d.request_id
    JOIN interaction_instructions parent ON parent.id=call.parent_instruction
    JOIN interaction_sources root ON root.id=parent.input_id
    JOIN original_ingress_order original ON original.event_id=root.event_id
      AND original.channel=CASE WHEN root.update_id IS NOT NULL THEN 'telegram' ELSE 'conversation' END
    WHERE d.result_id=p.source AND d.human_id=p.human_id AND call.human_id=p.human_id
      AND json_extract(call.doc,'$.report_to_topic')=1 AND call.phase IN ('requested','returned')
      AND json_extract(d.doc,'$.declared')=1 AND json_extract(d.doc,'$.completed')=1
      AND NOT EXISTS (
        SELECT 1 FROM json_each(coalesce(json_extract(d.doc,'$.request_ids'),json_array(d.request_id))) needed
        WHERE NOT EXISTS (SELECT 1 FROM interaction_request_links l
          JOIN interaction_instructions i ON i.id=l.instruction_id
          WHERE l.request_id=needed.value AND i.phase NOT IN ('cancelled','rejected'))
        OR EXISTS (SELECT 1 FROM interaction_request_links l
          JOIN interaction_instructions i ON i.id=l.instruction_id
          WHERE l.request_id=needed.value AND i.phase NOT IN ('cancelled','rejected')
          AND (i.phase<>'accepted' OR NOT EXISTS (SELECT 1 FROM json_each(d.doc,'$.covered') c WHERE c.value=i.id)))
      )
      AND {REPORT_PARENT_CURRENT}
  )"#;

// The transport receives one derived view of an ordinary completed exchange.
const PORTABLE_EXCHANGE_SCOPE: &str = r#"(p.kind IN ('portable_topic_exchange','portable_entry_exchange','portable_topic_original','portable_entry_original')
    AND t.status='completed' AND t.execution_harness<>'codex' AND t.private_handoff=0
    AND EXISTS(
      SELECT 1 FROM interaction_results r
      JOIN interaction_instructions i ON json_extract(i.doc,'$.local_turn')=t.id
        AND json_extract(i.doc,'$.native_turn')=r.native_turn AND i.phase='accepted'
      JOIN interaction_sources x ON x.id=i.input_id AND x.human_id=p.human_id
      JOIN sessions w ON w.id=t.session_id AND w.id=i.session_id AND w.creator_user_id=p.human_id
      JOIN conversation_entry_generations g ON g.session_id=w.id AND g.generation=t.execution_generation
      WHERE r.id=p.source AND r.local_turn=t.id AND r.native_thread=t.native_thread_id
        AND r.item_id='final' AND w.chat_id=s.chat_id AND x.origin_chat=w.chat_id
        AND NOT EXISTS(SELECT 1 FROM interaction_session_authors a WHERE a.input_id=x.id)
        AND json_type(x.doc,'$.tribu_source') IS NOT 'object'
        AND ((p.kind IN ('portable_topic_exchange','portable_topic_original') AND s.id=w.id AND x.channel='conversation'
              AND EXISTS(SELECT 1 FROM conversation_inputs c WHERE c.id=x.event_id
                AND c.human_id=p.human_id AND c.retired=0 AND json_extract(c.doc,'$.paired_actor')=1))
          OR (p.kind IN ('portable_entry_exchange','portable_entry_original') AND s.id<>w.id AND x.channel LIKE 'telegram:%'
              AND x.origin_thread=w.thread_id))))"#;

pub(super) fn portable_exchange_on(
    conn: &Connection,
    input: &crate::interaction::Instruction,
    local: i64,
    entry: SessionKey,
) -> Result<()> {
    let source = super::routing::source_on(conn, &input.id, input.human_id)?;
    if source.tribu_source.is_some()
        || super::session_requests::author_on(conn, &input.input_id)?.is_some()
        || input.target == entry
    {
        return Ok(());
    }
    let (target, kind, label) = match source.channel.as_str() {
        "conversation" => (input.target, "portable_topic_exchange", "Conversation"),
        channel
            if channel.starts_with("telegram:")
                && source.origin.thread_id == input.target.thread_id =>
        {
            (entry, "portable_entry_exchange", "Telegram")
        }
        _ => return Ok(()),
    };
    conn.execute(
        "WITH projection(position,kind) AS (VALUES (0,replace(?2,'_exchange','_original')),(1,?2))
         INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
         SELECT t.id,s.id,?1,projection.kind,r.id,
           CASE WHEN ?2='portable_entry_exchange' THEN '#'||coalesce(nullif(trim(w.session_title),''),'t'||w.thread_id)||' · update'||char(10)||char(10) ELSE '' END
           ||CASE WHEN projection.position=0 THEN 'You · '||?3||char(10)||?4 ELSE r.body END,'ready',''
         FROM projection CROSS JOIN turns t JOIN sessions s ON s.chat_id=?7 AND s.thread_id=?8 AND s.creator_user_id=?1
         JOIN interaction_results r ON r.local_turn=t.id
         JOIN interaction_instructions current ON current.id=?5 AND json_extract(current.doc,'$.native_turn')=r.native_turn
         JOIN sessions w ON w.id=t.session_id
         WHERE t.id=?6 AND t.from_user_id=?1 AND t.private_handoff=0 AND r.item_id='final' AND length(trim(r.body))>0
           AND EXISTS(SELECT 1 FROM users u WHERE u.tg_user_id=?1 AND u.allowed=1)
           AND (projection.position<>0 OR length(trim(?4))>0)
           AND NOT EXISTS(SELECT 1 FROM interaction_public_deliveries d WHERE d.result_id=r.id AND d.human_id=?1
             AND json_extract(d.doc,'$.origin.chat_id')=s.chat_id AND json_extract(d.doc,'$.origin.thread_id')=s.thread_id
             AND (?2='portable_entry_exchange' OR json_type(d.doc,'$.origin.message_id')='integer'))
         ORDER BY projection.position",
        params![input.human_id, kind, label, source.text, input.id, local, target.chat_id, target.thread_id],
    )?;
    Ok(())
}

fn portable_report_delivery_current(
    conn: &Connection,
    delivery: &crate::interaction::Delivery,
    parent: &str,
    human: i64,
) -> Result<bool> {
    let (current, correction) = super::routing::delivery_freshness(conn, delivery)?;
    if !delivery.completed || !current || correction {
        return Ok(false);
    }
    let source = super::routing::source_on(conn, parent, human)?;
    let Some(capture) = super::dialogue::original_order_on(conn, &source)? else {
        return Ok(false);
    };
    conn.query_row(
        "SELECT NOT EXISTS(SELECT 1 FROM interaction_request_links old
           JOIN interaction_request_links newer ON newer.request_id=old.request_id
           JOIN interaction_instructions i ON i.id=newer.instruction_id
           JOIN interaction_sources s ON s.id=i.input_id
           JOIN original_ingress_order o ON o.event_id=s.event_id
              AND o.channel=CASE WHEN s.update_id IS NOT NULL THEN 'telegram' ELSE 'conversation' END
           WHERE old.instruction_id=?1 AND o.id>?2 AND s.human_id=?3
             AND i.phase NOT IN ('cancelled','rejected')
             AND json_extract(i.doc,'$.relation.kind')='amends'
             AND NOT EXISTS(SELECT 1 FROM interaction_session_authors a WHERE a.input_id=s.id))",
        params![parent,capture,human], |r| r.get(0)
    ).map_err(Into::into)
}

pub(super) fn accepted_handoff_projection_on(
    conn: &Connection,
    input: &crate::interaction::Instruction,
    local: i64,
) -> Result<()> {
    conn.execute(
        "INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
         SELECT ?1,i.session_id,call.human_id,'portable_handoff_input',i.id,'Handoff from #'||
           coalesce(nullif(trim(caller.session_title),''),'t'||caller.thread_id)||char(10)||char(10)||
           json_extract(source.doc,'$.text'),'ready',''
         FROM interaction_session_requests call
         JOIN sessions caller ON caller.chat_id=call.caller_chat AND caller.thread_id=call.caller_topic
           AND caller.creator_user_id=call.human_id
         JOIN interaction_instructions i ON i.id=call.target_instruction
         JOIN interaction_sources source ON source.id=i.input_id AND source.channel='local-session'
         WHERE i.id=?2 AND call.human_id=?3 AND call.phase='requested'
           AND json_extract(call.doc,'$.report_to_topic')=1
           AND length(trim(json_extract(source.doc,'$.text')))>0",
        params![local, input.id, input.human_id],
    )?;
    Ok(())
}

pub(super) fn completed_handoff_projection_on(
    conn: &Connection,
    input: &crate::interaction::Instruction,
    local: i64,
    deliveries: &[crate::interaction::Delivery],
) -> Result<()> {
    let Some(delivery) = deliveries.iter().find(|d| d.requests().contains(&input.id)) else {
        return Ok(());
    };
    let parent: Option<String> = conn
        .query_row(
            "SELECT parent_instruction FROM interaction_session_requests
         WHERE target_instruction=?1 AND human_id=?2 AND phase='requested'
           AND json_extract(doc,'$.report_to_topic')=1",
            params![input.id, input.human_id],
            |r| r.get(0),
        )
        .optional()?;
    let Some(parent) = parent else {
        return Ok(());
    };
    if !super::session_requests::paired_request_parent_on(conn, input)?
        || !portable_report_delivery_current(conn, delivery, &parent, input.human_id)?
    {
        return Ok(());
    }
    // Fence the early lease if no part reached Telegram. The completion
    // format can then drain it, including after a rollback.
    conn.execute(
        "UPDATE topic_publications SET phase='retired'
         WHERE kind='portable_handoff_input' AND source=?2 AND local_turn=?1 AND human_id=?3
           AND NOT EXISTS (SELECT 1 FROM topic_publication_parts part
             WHERE part.publication=topic_publications.id AND part.phase<>'ready')",
        params![local, input.id, input.human_id],
    )?;
    conn.execute(
        "WITH projection(position,kind) AS (VALUES (0,'portable_report_request'),(1,'portable_report'))
         INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
         SELECT ?1,i.session_id,call.human_id,projection.kind,r.id,
           CASE WHEN projection.position=0 THEN 'Handoff from #'||
             coalesce(nullif(trim(caller.session_title),''),'t'||caller.thread_id)||char(10)||char(10)||
             json_extract(source.doc,'$.text') ELSE r.body END,
           CASE WHEN projection.position=0 AND EXISTS(SELECT 1 FROM topic_publications early
             JOIN topic_publication_parts part ON part.publication=early.id AND part.phase<>'ready'
             WHERE early.kind='portable_handoff_input' AND early.source=i.id AND early.local_turn=?1)
             THEN 'not_selected' ELSE 'ready' END,''
         FROM projection CROSS JOIN interaction_session_requests call
         JOIN sessions caller ON caller.chat_id=call.caller_chat AND caller.thread_id=call.caller_topic
           AND caller.creator_user_id=call.human_id
         JOIN interaction_instructions i ON i.id=call.target_instruction
         JOIN interaction_sources source ON source.id=i.input_id AND source.channel='local-session'
         JOIN interaction_deliveries d ON d.id=?4 AND d.request_id=i.id AND d.human_id=call.human_id
         JOIN interaction_results r ON r.id=d.result_id AND r.local_turn=?1
           AND r.native_turn=json_extract(i.doc,'$.native_turn')
         WHERE i.id=?2 AND call.human_id=?3 AND call.phase='requested'
           AND json_extract(call.doc,'$.report_to_topic')=1
           AND length(trim(r.body))>0
         ORDER BY projection.position",
        params![local,input.id,input.human_id,delivery.id],
    )?;
    Ok(())
}

#[derive(Debug)]
pub struct TopicPublication {
    pub id: i64,
    pub local_turn: i64,
    pub direct: bool,
    pub target: SessionKey,
    pub body: String,
    pub kind: String,
    pub source: String,
}

/// A control receipt belongs to its retained target, not the integrator turn
/// that authored it. It never registers that turn as target conversation input.
pub(super) fn goal_control_on(conn: &Connection, id: &str, phase: &str) -> Result<()> {
    let (doc, human, receipt): (String, i64, Option<String>) = conn.query_row(
        "SELECT doc,human_id,result FROM interaction_goal_controls WHERE id=?",
        [id],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    )?;
    let doc: serde_json::Value = serde_json::from_str(&doc)?;
    if let Some(raw) = receipt {
        let result: serde_json::Value = serde_json::from_str(&raw)?;
        super::goal_controls::record_attempt_on(
            conn,
            id,
            &json!({"attempt":doc["attempt"],"phase":phase,"result":result}),
            &json!({"author":doc["actor"],"executor":doc["execution_actor"]}),
        )?;
    }
    if doc["recovery"].is_object() {
        // Preserve the exact receipt in shared recovery state. Routine attempts
        // must not send one Telegram control notice each.
        return super::goal_retries::settle_on(conn, id, phase);
    }
    let action = match doc["plan"]["action"].as_str() {
        Some("start") => "start",
        Some("edit") => "edit",
        Some("pause") => "pause",
        Some("resume") => "resume",
        Some("clear") => "clear",
        Some("replace") => "replace",
        _ => return Err(anyhow!("Invalid retained goal action")),
    };
    let outcome = match phase {
        "submitted" => "Submitted; execution is not yet confirmed.",
        "acknowledged" => "Native session acknowledged the goal change.",
        "rejected" => "Rejected; the requested change was not accepted.",
        "known_unsent" | "retained_unsent" => "Not submitted; the goal change was not sent.",
        "partial" => "Partly applied; inspect the result before continuing.",
        "uncertain" => "Outcome unknown; the action will not be replayed automatically.",
        _ => return Err(anyhow!("Invalid goal publication outcome")),
    };
    let author = if doc["delegation"].is_object() {
        "Daimon action"
    } else {
        "Integrator action"
    };
    let body = format!("↪ {author} · goal {action}\n{outcome}");
    let source = json!([id, doc["attempt"], phase]).to_string();
    conn.execute("INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
        VALUES(?1,?2,?3,'control',?4,?5,'ready','')",
        params![doc["actor"]["local"].as_i64(),doc["target_binding"][1].as_i64(),human,source,body])?;
    Ok(())
}

/// Only a cross-session live retirement is a routed action. Ordinary task
/// declarations and same-session withdrawals do not become router traffic.
pub(super) fn task_withdrawal_on(conn: &Connection, id: &str) -> Result<()> {
    let (local,session,human,raw,chat,topic): (Option<i64>,i64,i64,String,i64,i64) = conn.query_row(
        "SELECT h.local_turn,h.session_id,h.requester,h.payload_json,s.chat_id,s.thread_id FROM human_interactions h JOIN sessions s ON s.id=h.session_id WHERE h.id=? AND h.kind='task' AND h.state='cancelled'",
        [id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?)))?;
    let doc: serde_json::Value = serde_json::from_str(&raw)?;
    let actor = &doc["source"]["agentWithdrawal"]["actor"];
    let Ok(origin) = serde_json::from_value::<SessionKey>(actor["session"].clone()) else {
        return Ok(());
    };
    let Some(local) = local else {
        return Ok(());
    };
    if origin == SessionKey::new(chat, Some(topic)) {
        return Ok(());
    }
    let title = doc["title"]
        .as_str()
        .unwrap_or("Pending request")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(120)
        .collect::<String>();
    let body = format!("↪ Integrator action · request withdrawn\n{title}\nNo longer needed.");
    conn.execute("INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id) VALUES(?1,?2,?3,'task_control',?4,?5,'ready','')",
        params![local,session,human,json!([id]).to_string(),body])?;
    Ok(())
}

pub(super) fn enqueue_on(
    conn: &Connection,
    local: i64,
    kind: &str,
    source: &str,
    body: &str,
) -> Result<()> {
    if body.trim().is_empty() {
        return Ok(());
    }
    conn.execute("INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
        SELECT p.local_turn,t.session_id,p.human_id,?2,?3,?4,'ready',?5
        FROM topic_projection_turns p JOIN turns t ON t.id=p.local_turn WHERE p.local_turn=?1",
        params![local,kind,source,body,""])?;
    Ok(())
}

pub(super) fn native_on(
    conn: &Connection,
    local: i64,
    thread: &str,
    turn: &str,
    item: &str,
    text: &str,
) -> Result<()> {
    if !super::workflows::native_visible_on(conn, local)? {
        return Ok(());
    }
    let legacy:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM native_recovery_baseline WHERE native_thread=?1 AND native_turn=?2 AND item_id=?3)",params![thread,turn,item],|r|r.get(0))?;
    let internal: bool = conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM interaction_native_messages
         WHERE native_thread=?1 AND native_turn=?2 AND item_id=?3 AND internal_handoff=1)",
        params![thread, turn, item],
        |row| row.get(0),
    )?;
    if legacy || internal {
        return Ok(());
    }
    enqueue_on(
        conn,
        local,
        "native",
        &json!([thread, turn, item]).to_string(),
        crate::interaction::visible_answer(text),
    )?;
    let entry: Option<(i64, i64, String)> = conn
        .query_row(
            "SELECT c.session_id,c.human_id,COALESCE(NULLIF(w.session_title,''),'Session')
         FROM interaction_native_messages m JOIN conversation_inputs c ON c.id=m.presentation_input
         JOIN turns t ON t.id=m.local_turn JOIN sessions w ON w.id=t.session_id
         WHERE m.local_turn=?1 AND m.native_thread=?2 AND m.native_turn=?3 AND m.item_id=?4
         AND m.phase='commentary' AND c.session_id!=t.session_id AND c.human_id=t.from_user_id
         AND EXISTS(SELECT 1 FROM bot_state b JOIN sessions e ON e.id=c.session_id
             WHERE b.key='telegram_entry_projection' AND b.value=json_array(c.human_id,e.chat_id,e.thread_id))",
            params![local, thread, turn, item],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    if let Some((entry, human, title)) = entry {
        let body = format!(
            "#{title} · update\n\n{}",
            crate::interaction::visible_answer(text)
        );
        conn.execute("INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
            VALUES(?1,?2,?3,'entry_progress',?4,?5,'ready','')",params![local,entry,human,json!([thread,turn,item]).to_string(),body])?;
    }
    Ok(())
}

fn conversation_echo_on(
    conn: &Connection,
    input: &super::conversation_inputs::ConversationInput,
    local: i64,
) -> Result<()> {
    let selected: bool = conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM bot_state WHERE key='telegram_entry_projection' AND value=?1)",
        [json!([input.human, input.entry.chat_id, input.entry.thread_id]).to_string()],
        |r| r.get(0),
    )?;
    if !selected {
        return Ok(());
    }
    let author = if input.voice.is_some() {
        "Your voice transcript"
    } else {
        "You · app"
    };
    conn.execute("INSERT OR IGNORE INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id)
        VALUES(?1,?2,?3,'entry_input',?4,?5,'ready','')",params![local,input.session,input.human,input.id,format!("{author}\n\n{}",input.text)])?;
    Ok(())
}

pub(super) fn conversation_accepted_on(
    conn: &Connection,
    input: &super::conversation_inputs::ConversationInput,
) -> Result<()> {
    if let Some(local) = input.local_turn {
        conversation_echo_on(conn, input, local)?;
    }
    Ok(())
}

pub(super) fn accepted_on(
    conn: &Connection,
    input: &crate::interaction::Instruction,
) -> Result<()> {
    if super::session_requests::author_on(conn, &input.input_id)?.is_some() {
        return Ok(());
    }
    if input.origin.chat_id == input.target.chat_id
        && input.origin.thread_id == input.target.thread_id
    {
        return Ok(());
    }
    let Some(local) = input.local_turn else {
        return Ok(());
    };
    let source: String = conn.query_row(
        "SELECT doc FROM interaction_sources WHERE id=?",
        [&input.input_id],
        |r| r.get(0),
    )?;
    let source: crate::interaction::SourceInput = serde_json::from_str(&source)?;
    let author = if matches!(
        source.channel.as_str(),
        "local-session" | "local-session-result"
    ) {
        "Session message"
    } else if source.transcription.is_some() {
        "Human voice transcript"
    } else {
        "Human message"
    };
    // Original input is source data, including any protocol-looking quotation.
    let body = format!("↪ {author} · via integrator\n\n{}", input.text);
    enqueue_on(conn, local, "input", &input.id, &body)?;
    if source.channel == "conversation"
        && let Ok(original) =
            super::conversation_inputs::read_on(conn, &source.event_id, source.human_id)
        && original.entry == SessionKey::new(source.origin.chat_id, Some(source.origin.thread_id))
        && !original.retired
    {
        conversation_echo_on(conn, &original, local)?;
    }
    Ok(())
}

impl Store {
    pub fn topic_projection_entry_selection(
        &self,
        config: Option<&crate::interaction::InteractionConfig>,
    ) -> Result<()> {
        let selected = config
            .filter(|c| c.telegram_entry_projection)
            .map(|c| json!([c.human_id, c.chat_id, c.topic_id]))
            .unwrap_or(serde_json::Value::Null);
        self.save_bot_state("telegram_entry_projection", &selected.to_string())
    }

    /// Foreground presentation only: reads retained outcomes, never native input.
    pub fn thread_control_notices(
        &self,
        human: i64,
        native: &str,
        after: Option<i64>,
    ) -> Result<serde_json::Value> {
        if native.is_empty()
            || native.len() > 128
            || native.chars().any(char::is_whitespace)
            || native.chars().any(char::is_control)
            || after.is_some_and(|n| n < 0)
        {
            return Err(anyhow!("Invalid notice scope or cursor"));
        }
        let conn = self.conn.lock().expect("store mutex poisoned");
        let known: bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE u.allowed=1 AND s.creator_user_id=?1 AND s.codex_thread_id=?2 AND s.force_fresh_thread=0)",params![human,native],|r|r.get(0))?;
        let mut items = Vec::new();
        if known {
            // Legacy publication source IDs are opaque strings. Parse only the
            // typed control source, including when SQLite reorders predicates.
            let order = if after.is_some() { "ASC" } else { "DESC" };
            let mut query = conn.prepare(&format!(
                "SELECT p.id,p.body FROM topic_publications p
                JOIN sessions s ON s.id=p.session_id WHERE p.kind IN ('control','task_control') AND p.human_id=?1 AND s.creator_user_id=?1
                AND s.codex_thread_id=?2 AND s.force_fresh_thread=0 AND {CONTROL_NOTICE_SCOPE}
                AND p.id>?3 ORDER BY p.id {order} LIMIT 33"
            ))?;
            items = query.query_map(params![human,native,after.unwrap_or(0)],|r| {
                let sequence: i64 = r.get(0)?;
                Ok(json!({"id":format!("publication:{sequence}"),"sequence":sequence,"source":"interaction","text":r.get::<_,String>(1)?}))
            })?.collect::<rusqlite::Result<Vec<_>>>()?;
        }
        let more = items.len() > 32;
        items.truncate(32);
        if after.is_none() {
            items.reverse();
        }
        let cursor = items
            .last()
            .and_then(|v| v["sequence"].as_i64())
            .unwrap_or(after.unwrap_or(0));
        Ok(
            json!({"schema":"telecodex.thread-notices/v1","native_thread":native,"available":known,
            "history":after.is_none(),"history_truncated":after.is_none() && more,
            "cursor":cursor,"has_more":after.is_some() && more,"items":items}),
        )
    }

    pub(super) fn init_topic_publications(&self) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute_batch("CREATE TABLE IF NOT EXISTS topic_projection_turns(local_turn INTEGER PRIMARY KEY REFERENCES turns(id),human_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS topic_publications(id INTEGER PRIMARY KEY AUTOINCREMENT,local_turn INTEGER NOT NULL REFERENCES turns(id),session_id INTEGER NOT NULL REFERENCES sessions(id),human_id INTEGER NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,body TEXT NOT NULL,phase TEXT NOT NULL,instance_id TEXT NOT NULL,UNIQUE(kind,source,session_id));
            CREATE INDEX IF NOT EXISTS topic_publications_pending ON topic_publications(session_id,phase,id);
            CREATE TABLE IF NOT EXISTS topic_publication_parts(publication INTEGER NOT NULL REFERENCES topic_publications(id),part INTEGER NOT NULL,body TEXT NOT NULL,phase TEXT NOT NULL,message_id INTEGER,PRIMARY KEY(publication,part));")?;
        conn.execute_batch("CREATE INDEX IF NOT EXISTS topic_publication_control_feed ON topic_publications(session_id,id) WHERE kind IN ('control','task_control');")?;
        conn.execute_batch("CREATE TABLE IF NOT EXISTS direct_topic_turns(local_turn INTEGER PRIMARY KEY REFERENCES topic_projection_turns(local_turn));")?;
        conn.execute("UPDATE topic_publications SET phase=CASE WHEN EXISTS(SELECT 1 FROM topic_publication_parts p WHERE p.publication=topic_publications.id AND p.phase IN ('sending','uncertain')) THEN 'uncertain' ELSE 'ready' END WHERE phase='publishing' AND instance_id!=?",[&self.instance_id])?;
        conn.execute("UPDATE topic_publication_parts SET phase='uncertain' WHERE phase='sending' AND publication IN (SELECT id FROM topic_publications WHERE phase='uncertain')",[])?;
        Ok(())
    }

    pub(super) fn init_report_request_view(&self) -> Result<()> {
        let report_scope =
            PORTABLE_REPORT_SCOPE.replace("{REPORT_PARENT_SCOPE}", REPORT_PARENT_SCOPE);
        let request_current =
            REPORT_REQUEST_CURRENT.replace("{REPORT_PARENT_CURRENT}", REPORT_PARENT_CURRENT);
        let definition = format!(
            "CREATE VIEW visible_portable_report_requests AS
             SELECT p.id,p.source,p.session_id,p.local_turn,p.human_id,p.body
             FROM topic_publications p JOIN turns t ON t.id=p.local_turn JOIN sessions s ON s.id=p.session_id
             JOIN users u ON u.tg_user_id=p.human_id
             WHERE p.kind='portable_report_request'
               AND u.allowed=1 AND s.creator_user_id=p.human_id AND t.from_user_id=p.human_id
               AND {report_scope} AND {request_current}"
        );
        let early = format!(
            "CREATE VIEW visible_portable_handoff_inputs AS
             SELECT p.id,p.source,p.session_id,p.local_turn,p.human_id,p.body
             FROM topic_publications p JOIN turns t ON t.id=p.local_turn
             JOIN sessions s ON s.id=p.session_id JOIN users u ON u.tg_user_id=p.human_id
             JOIN conversation_entry_generations g ON g.session_id=s.id AND g.generation=t.execution_generation
             JOIN interaction_instructions i ON i.id=p.source AND i.session_id=s.id
               AND json_extract(i.doc,'$.local_turn')=t.id
               AND json_extract(i.doc,'$.native_thread')=t.native_thread_id
             JOIN interaction_session_requests call ON call.target_instruction=i.id AND call.human_id=p.human_id
             LEFT JOIN bot_state epoch ON epoch.key='stop_admission_epoch:'||p.human_id
             JOIN interaction_instructions parent ON parent.id=call.parent_instruction
             JOIN interaction_sources src ON src.id=parent.input_id AND src.human_id=call.human_id
             JOIN original_ingress_order original ON original.event_id=src.event_id
               AND original.channel=CASE WHEN src.update_id IS NOT NULL THEN 'telegram' ELSE 'conversation' END
             WHERE p.kind='portable_handoff_input' AND t.session_id=s.id
               AND u.allowed=1 AND s.creator_user_id=p.human_id AND t.from_user_id=p.human_id
               AND i.phase IN ('submitting','accepted','uncertain')
               AND t.status IN ('running','completed','failed')
               AND NOT EXISTS(SELECT 1 FROM bot_state stop WHERE stop.key='stopped_turn:'||t.id)
               AND json_extract(i.doc,'$.native_input_accepted')=1
               AND json_extract(call.doc,'$.epoch')=coalesce(epoch.value,'initial')
               AND json_extract(call.doc,'$.report_to_topic')=1 AND call.phase IN ('requested','returned')
               AND NOT EXISTS(SELECT 1 FROM interaction_session_withdrawals w WHERE w.parent_instruction=parent.id)
               AND {REPORT_PARENT_SCOPE} AND {REPORT_PARENT_CURRENT}",
        );
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        for (name, definition) in [
            ("visible_portable_report_requests", definition),
            ("visible_portable_handoff_inputs", early),
        ] {
            let existing: Option<String> = tx
                .query_row(
                    "SELECT sql FROM sqlite_schema WHERE type='view' AND name=?1",
                    [name],
                    |row| row.get(0),
                )
                .optional()?;
            if existing.as_deref() != Some(definition.as_str()) {
                tx.execute_batch(&format!("DROP VIEW IF EXISTS {name}"))?;
                tx.execute_batch(&definition)?;
            }
        }
        tx.commit()?;
        Ok(())
    }

    pub fn topic_projection_register(&self, local: i64, human: i64, key: SessionKey) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let valid: bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id JOIN users u ON u.tg_user_id=s.creator_user_id WHERE t.id=?1 AND t.from_user_id=?2 AND s.creator_user_id=?2 AND u.allowed=1 AND s.chat_id=?3 AND s.thread_id=?4)",params![local,human,key.chat_id,key.thread_id],|r|r.get(0))?;
        if !valid {
            return Err(anyhow!("Topic projection ownership changed"));
        }
        conn.execute(
            "INSERT OR IGNORE INTO topic_projection_turns(local_turn,human_id) VALUES(?1,?2)",
            params![local, human],
        )?;
        Ok(())
    }

    pub fn topic_direct_register(&self, local: i64, human: i64, key: SessionKey) -> Result<()> {
        self.topic_projection_register(local, human, key)?;
        self.conn.lock().expect("store mutex poisoned").execute(
            "INSERT OR IGNORE INTO direct_topic_turns(local_turn) VALUES(?)",
            [local],
        )?;
        Ok(())
    }

    pub fn topic_publication_owner(&self, key: SessionKey) -> Result<Option<i64>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.query_row("SELECT s.creator_user_id FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND u.allowed=1",params![key.chat_id,key.thread_id],|r|r.get(0)).optional()?)
    }

    pub fn topic_publication_notice(&self, local: i64, text: &str) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        enqueue_on(&conn, local, "notice", &format!("collector:{local}"), text)
    }

    pub fn topic_projection_active(&self, local: i64) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM topic_projection_turns WHERE local_turn=?)",
            [local],
            |r| r.get(0),
        )?)
    }

    pub fn topic_publication_targets(&self) -> Result<Vec<SessionKey>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut query=conn.prepare("SELECT DISTINCT s.chat_id,s.thread_id FROM topic_publications p JOIN sessions s ON s.id=p.session_id WHERE p.phase='ready' LIMIT 512")?;
        Ok(query
            .query_map([], |r| Ok(SessionKey::new(r.get(0)?, Some(r.get(1)?))))?
            .collect::<rusqlite::Result<_>>()?)
    }

    /// SQLite serializes the queue per destination, independent of its producer.
    pub fn topic_publication_claim(
        &self,
        key: SessionKey,
        human: i64,
    ) -> Result<Option<TopicPublication>> {
        self.topic_publication_claim_lane(key, human, false)
    }
    pub fn topic_publication_claim_files(
        &self,
        key: SessionKey,
        human: i64,
    ) -> Result<Option<TopicPublication>> {
        self.topic_publication_claim_lane(key, human, true)
    }
    fn topic_publication_claim_lane(
        &self,
        key: SessionKey,
        human: i64,
        files: bool,
    ) -> Result<Option<TopicPublication>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let report_scope =
            PORTABLE_REPORT_SCOPE.replace("{REPORT_PARENT_SCOPE}", REPORT_PARENT_SCOPE);
        let busy: bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM topic_publications p JOIN sessions s ON s.id=p.session_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND p.phase='publishing' AND (p.kind='artifact')=?3)",params![key.chat_id,key.thread_id,files],|r|r.get(0))?;
        if busy {
            return Ok(None);
        }
        loop {
            let row:Option<(i64,String,bool,String,String,i64,bool)>=tx.query_row(&format!("SELECT p.id,p.body,COALESCE((u.allowed=1 AND s.creator_user_id=p.human_id AND t.from_user_id=p.human_id AND (((p.kind NOT IN ('artifact','control','task_control','portable_report','portable_report_request','portable_handoff_input','portable_topic_exchange','portable_entry_exchange','portable_topic_original','portable_entry_original') AND s.codex_thread_id=t.native_thread_id AND s.force_fresh_thread=0) OR {CONTROL_NOTICE_SCOPE} OR {ENTRY_PROGRESS_SCOPE} OR {ENTRY_INPUT_SCOPE} OR (p.kind='portable_handoff_input' AND EXISTS(SELECT 1 FROM visible_portable_handoff_inputs h WHERE h.id=p.id)) OR ({report_scope} AND (p.kind='portable_report' OR EXISTS(SELECT 1 FROM visible_portable_report_requests h WHERE h.id=p.id))) OR {PORTABLE_EXCHANGE_SCOPE} OR (p.kind='notice' AND t.native_thread_id IS NULL)) OR (p.kind='artifact' AND EXISTS(SELECT 1 FROM interaction_artifacts a JOIN interaction_artifact_blobs b ON b.sha256=a.sha256 WHERE a.id=p.source AND a.source_local=p.local_turn AND a.source_session=p.session_id AND a.human_id=p.human_id AND a.phase='ready' AND b.present=1 AND julianday(a.expires_at)>julianday('now'))))),0),p.kind,p.source,p.local_turn,(p.kind NOT IN ('control','task_control','entry_progress','entry_input') AND EXISTS(SELECT 1 FROM direct_topic_turns pt WHERE pt.local_turn=p.local_turn)) FROM topic_publications p JOIN sessions s ON s.id=p.session_id JOIN turns t ON t.id=p.local_turn JOIN users u ON u.tg_user_id=p.human_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND p.human_id=?3 AND p.phase='ready' AND (p.kind='artifact')=?4 ORDER BY p.id LIMIT 1"),params![key.chat_id,key.thread_id,human,files],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?))).optional()?;
            let Some((id, body, valid, kind, source, local_turn, direct)) = row else {
                tx.commit()?;
                return Ok(None);
            };
            tx.execute(
                "UPDATE topic_publications SET phase=?2,instance_id=?3 WHERE id=?1",
                params![
                    id,
                    if valid { "publishing" } else { "retired" },
                    &self.instance_id
                ],
            )?;
            if valid {
                tx.commit()?;
                return Ok(Some(TopicPublication {
                    id,
                    local_turn,
                    direct,
                    target: key,
                    body,
                    kind,
                    source,
                }));
            }
        }
    }

    pub fn topic_file_caption(&self, id: i64) -> Result<String> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (name,text):(String,String)=conn.query_row("SELECT a.name,m.text FROM topic_publications p JOIN interaction_artifacts a ON a.id=p.source JOIN interaction_native_messages m ON m.local_turn=a.source_local AND m.native_thread=a.native_thread AND m.native_turn=a.native_turn AND m.item_id=a.native_item WHERE p.id=?1 AND p.kind='artifact'",[id],|r|Ok((r.get(0)?,r.get(1)?)))?;
        Ok(format!(
            "File · {}\n{}",
            name,
            crate::interaction::visible_answer(&text)
                .chars()
                .take(240)
                .collect::<String>()
        ))
    }

    pub fn topic_publication_parts(
        &self,
        id: i64,
        chunks: &[String],
    ) -> Result<Vec<(i64, String)>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let own:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM topic_publications WHERE id=?1 AND phase='publishing' AND instance_id=?2)",params![id,&self.instance_id],|r|r.get(0))?;
        if !own {
            return Err(anyhow!("Topic publication lease changed"));
        }
        let count: i64 = tx.query_row(
            "SELECT COUNT(*) FROM topic_publication_parts WHERE publication=?",
            [id],
            |r| r.get(0),
        )?;
        if count == 0 {
            if chunks.is_empty() {
                return Err(anyhow!("Invalid topic publication parts"));
            }
            for (part, body) in chunks.iter().enumerate() {
                tx.execute(
                    "INSERT INTO topic_publication_parts VALUES(?1,?2,?3,'ready',NULL)",
                    params![id, part as i64, body],
                )?;
            }
        }
        let parts = {
            let mut q=tx.prepare("SELECT part,body FROM topic_publication_parts WHERE publication=? AND phase='ready' ORDER BY part")?;
            q.query_map([id], |r| Ok((r.get(0)?, r.get(1)?)))?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        tx.commit()?;
        Ok(parts)
    }

    /// A disabled secondary projection cannot hold the destination's direct
    /// output lane. The retained notice remains readable without a send claim.
    pub fn topic_publication_not_selected(&self, id: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let changed = conn.execute("UPDATE topic_publications SET phase='not_selected' WHERE id=?1 AND phase='publishing' AND instance_id=?2 AND NOT EXISTS(SELECT 1 FROM topic_publication_parts WHERE publication=?1 AND phase IN ('sending','uncertain'))",params![id,self.instance_id])?;
        if changed != 1 {
            return Err(anyhow!(
                "Publication selection changed or delivery is uncertain"
            ));
        }
        Ok(())
    }

    /// Called after Telegram cooldown, immediately before one network attempt.
    pub fn topic_publication_reserve(&self, id: i64, part: i64) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let report: Option<(String, Option<String>, Option<String>, i64)> = tx
            .query_row(
                "SELECT p.kind,d.doc,call.parent_instruction,p.human_id
             FROM topic_publications p
             LEFT JOIN interaction_deliveries d ON p.kind='portable_report'
                  AND d.result_id=p.source AND d.human_id=p.human_id
             LEFT JOIN interaction_session_requests call ON call.target_instruction=d.request_id
             WHERE p.id=?1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()?;
        if let Some((kind, raw, parent, human)) = report
            && kind == "portable_report"
        {
            let Some((raw, parent)) = raw.zip(parent) else {
                return Ok(false);
            };
            let delivery: crate::interaction::Delivery = serde_json::from_str(&raw)?;
            if !portable_report_delivery_current(&tx, &delivery, &parent, human)? {
                return Ok(false);
            }
        }
        let exchange: Option<(String, i64)> = tx
            .query_row(
                "SELECT source,human_id FROM topic_publications
             WHERE id=?1 AND kind IN ('portable_topic_exchange','portable_entry_exchange')",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((result, human)) = exchange {
            let mut query = tx.prepare(
                "SELECT doc FROM interaction_public_deliveries WHERE result_id=?1 AND human_id=?2",
            )?;
            let mut rows = query.query(params![result, human])?;
            let mut eligible = false;
            while let Some(row) = rows.next()? {
                let raw: String = row.get(0)?;
                let delivery: crate::interaction::Delivery = serde_json::from_str(&raw)?;
                if super::routing::delivery_freshness(&tx, &delivery)?.1 {
                    return Ok(false);
                }
                eligible = true;
            }
            if !eligible {
                return Ok(false);
            }
        }
        let report_scope =
            PORTABLE_REPORT_SCOPE.replace("{REPORT_PARENT_SCOPE}", REPORT_PARENT_SCOPE);
        let changed = tx.execute(&format!("UPDATE topic_publication_parts SET phase='sending' WHERE publication=?1 AND part=?2 AND phase='ready' AND EXISTS(SELECT 1 FROM topic_publications p JOIN turns t ON t.id=p.local_turn JOIN sessions s ON s.id=p.session_id JOIN users u ON u.tg_user_id=p.human_id WHERE p.id=?1 AND p.phase='publishing' AND p.instance_id=?3 AND u.allowed=1 AND s.creator_user_id=p.human_id AND t.from_user_id=p.human_id AND (((p.kind NOT IN ('artifact','control','task_control','portable_report','portable_report_request','portable_handoff_input','portable_topic_exchange','portable_entry_exchange','portable_topic_original','portable_entry_original') AND s.codex_thread_id=t.native_thread_id AND s.force_fresh_thread=0) OR {CONTROL_NOTICE_SCOPE} OR {ENTRY_PROGRESS_SCOPE} OR {ENTRY_INPUT_SCOPE} OR (p.kind='portable_handoff_input' AND EXISTS(SELECT 1 FROM visible_portable_handoff_inputs h WHERE h.id=p.id)) OR ({report_scope} AND (p.kind='portable_report' OR EXISTS(SELECT 1 FROM visible_portable_report_requests h WHERE h.id=p.id))) OR {PORTABLE_EXCHANGE_SCOPE} OR (p.kind='notice' AND t.native_thread_id IS NULL)) OR (p.kind='artifact' AND EXISTS(SELECT 1 FROM interaction_artifacts a JOIN interaction_artifact_blobs b ON b.sha256=a.sha256 WHERE a.id=p.source AND a.source_local=p.local_turn AND a.source_session=p.session_id AND a.human_id=p.human_id AND a.phase='ready' AND b.present=1 AND julianday(a.expires_at)>julianday('now')))))"),params![id,part,&self.instance_id])?==1;
        tx.commit()?;
        Ok(changed)
    }

    pub fn topic_publication_receipt(
        &self,
        id: i64,
        part: i64,
        message: Option<i64>,
        rejected: bool,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let changed=tx.execute("UPDATE topic_publication_parts SET phase=?3,message_id=?4 WHERE publication=?1 AND part=?2 AND phase='sending' AND EXISTS(SELECT 1 FROM topic_publications p WHERE p.id=?1 AND p.phase='publishing' AND p.instance_id=?5)",params![id,part,if message.is_some(){"sent"}else if rejected{"rejected"}else{"uncertain"},message,&self.instance_id])?;
        if changed != 1 {
            return Err(anyhow!("Topic publication receipt ownership changed"));
        }
        if let Some(message) = message {
            let exchange: Option<(String, i64, i64, i64, i64)> = tx
                .query_row(
                    "SELECT p.source,p.human_id,t.session_id,s.chat_id,s.thread_id
                 FROM topic_publications p JOIN turns t ON t.id=p.local_turn
                 JOIN sessions s ON s.id=p.session_id WHERE p.id=?1
                   AND p.kind IN ('portable_topic_exchange','portable_entry_exchange')",
                    [id],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
                )
                .optional()?;
            if let Some((result, human, session, chat, topic)) = exchange {
                let mut query = tx.prepare(
                    "SELECT request_id FROM interaction_public_deliveries
                     WHERE result_id=?1 AND human_id=?2
                     UNION SELECT member.request_id FROM interaction_public_deliveries d
                     JOIN interaction_delivery_requests member ON member.delivery_id=d.id
                     WHERE d.result_id=?1 AND d.human_id=?2 ORDER BY request_id",
                )?;
                let requests = query
                    .query_map(params![result, human], |r| r.get(0))?
                    .collect::<rusqlite::Result<Vec<String>>>()?;
                if !requests.is_empty() {
                    super::routing::bind_message(
                        &tx,
                        &crate::interaction::ReturnRoute {
                            chat_id: chat,
                            thread_id: topic,
                            message_id: Some(message),
                        },
                        human,
                        session,
                        &requests,
                    )?;
                }
            }
            tx.execute("INSERT OR IGNORE INTO handoff_messages(chat_id,thread_id,message_id,turn_id,text) SELECT s.chat_id,s.thread_id,?3,p.local_turn,x.body FROM topic_publications p JOIN sessions s ON s.id=p.session_id JOIN topic_publication_parts x ON x.publication=p.id WHERE p.id=?1 AND x.part=?2",params![id,part,message])?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn topic_publication_finish(&self, id: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute("UPDATE topic_publications SET phase=CASE WHEN EXISTS(SELECT 1 FROM topic_publication_parts p WHERE p.publication=?1 AND p.phase IN ('sending','uncertain')) THEN 'uncertain' WHEN EXISTS(SELECT 1 FROM topic_publication_parts p WHERE p.publication=?1 AND p.phase='rejected') THEN 'rejected' WHEN NOT EXISTS(SELECT 1 FROM topic_publication_parts p WHERE p.publication=?1 AND p.phase!='sent') THEN 'sent' ELSE 'retired' END WHERE id=?1 AND phase='publishing' AND instance_id=?2",params![id,&self.instance_id])?;
        Ok(())
    }

    pub fn topic_publication_release(&self, id: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute("UPDATE topic_publications SET phase=CASE WHEN EXISTS(SELECT 1 FROM topic_publication_parts p WHERE p.publication=?1 AND p.phase IN ('sending','uncertain')) THEN 'uncertain' ELSE 'ready' END WHERE id=?1 AND phase='publishing' AND instance_id=?2",params![id,&self.instance_id])?;
        Ok(())
    }

    pub fn topic_publication_retry(&self, id: i64, part: i64) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let changed=tx.execute("UPDATE topic_publication_parts SET phase='ready' WHERE publication=?1 AND part=?2 AND phase='sending' AND EXISTS(SELECT 1 FROM topic_publications p WHERE p.id=?1 AND p.phase='publishing' AND p.instance_id=?3)",params![id,part,&self.instance_id])?;
        if changed != 1 {
            return Err(anyhow!("Topic retry lease changed"));
        }
        // A cooldown proves this attempt was not sent. If the answer settled
        // during the attempt, switch back to its compatible request row only
        // when there is no acknowledged or uncertain prefix.
        let fallback = tx.execute(
            "UPDATE topic_publications AS final SET phase='ready'
             WHERE final.kind='portable_report_request' AND final.phase='not_selected'
               AND EXISTS (SELECT 1 FROM topic_publications early
                 JOIN interaction_deliveries d ON d.request_id=early.source
                   AND d.result_id=final.source AND d.human_id=final.human_id
                 WHERE early.id=?1 AND early.kind='portable_handoff_input'
                   AND early.local_turn=final.local_turn AND early.session_id=final.session_id
                   AND early.human_id=final.human_id)
               AND NOT EXISTS(SELECT 1 FROM topic_publication_parts part
                 WHERE part.publication=?1 AND part.phase<>'ready')",
            [id],
        )?;
        tx.execute(
            "UPDATE topic_publications SET phase=?3 WHERE id=?1 AND instance_id=?2",
            params![
                id,
                &self.instance_id,
                if fallback == 1 { "retired" } else { "ready" }
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn topic_publication_inventory(&self, human: i64) -> Result<serde_json::Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut query=conn.prepare("SELECT p.id,s.chat_id,s.thread_id,p.kind,p.phase,p.body,(SELECT COUNT(*) FROM topic_publication_parts x WHERE x.publication=p.id AND x.phase='sent') FROM topic_publications p JOIN sessions s ON s.id=p.session_id JOIN users u ON u.tg_user_id=p.human_id WHERE p.human_id=? AND s.creator_user_id=p.human_id AND u.allowed=1 ORDER BY p.id DESC LIMIT 256")?;
        let items=query.query_map([human],|r|{let body:String=r.get(5)?;Ok(json!({"id":r.get::<_,i64>(0)?,"chat":r.get::<_,i64>(1)?,"topic":r.get::<_,i64>(2)?,"kind":r.get::<_,String>(3)?,"phase":r.get::<_,String>(4)?,"preview":body.chars().take(300).collect::<String>(),"acknowledged_parts":r.get::<_,i64>(6)?}))})?.collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(json!({"schema":"telecodex.topic-publications/v1","items":items,"bounded":256}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn execution(store: &Store) -> (i64, SessionKey) {
        let key = SessionKey::new(100, Some(7));
        let session = store
            .ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        store.set_session_codex_thread(key, "native").unwrap();
        let local = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: "Work".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store.record_turn_native_thread(local, "native").unwrap();
        store.topic_projection_register(local, 100, key).unwrap();
        (local, key)
    }
    fn store(path: &Path) -> Store {
        Store::open(path, &[100, 101], &super::super::tests::defaults()).unwrap()
    }
    fn control(store: &Store, target: SessionKey) -> i64 {
        let entry = SessionKey::new(100, Some(9));
        let session = store
            .ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "integrator-native")
            .unwrap();
        let local = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Pause that goal".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(local, "integrator-native")
            .unwrap();
        let selected = store.get_session(target).unwrap().unwrap();
        let doc = json!({"actor":{"local":local},"target_binding":["binding",selected.id,"native"],
            "plan":{"action":"pause"},"attempt":"attempt-1"});
        store.conn.lock().unwrap().execute("INSERT INTO interaction_goal_controls(id,human_id,entry_chat,entry_topic,target_chat,target_topic,phase,doc,instance_id) VALUES('control-1',100,100,9,?1,?2,'claimed',?3,?4)",
            params![target.chat_id,target.thread_id,doc.to_string(),store.instance_id]).unwrap();
        local
    }
    #[test]
    fn control_receipt_projects_once_without_target_turn_or_input() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (_, key) = execution(&s);
        let local = control(&s, key);
        // An ordinary direct origin does not turn a secondary control notice
        // into direct target output or bypass projection/surface checks.
        s.topic_direct_register(local, 100, SessionKey::new(100, Some(9)))
            .unwrap();
        let receipt = json!({"goal":{"status":"paused"}});
        assert!(
            s.goal_control_finish(
                100,
                SessionKey::new(100, Some(9)),
                "control-1",
                "attempt-1",
                "acknowledged",
                &receipt
            )
            .unwrap()
        );
        assert!(
            !s.goal_control_finish(
                100,
                SessionKey::new(100, Some(9)),
                "control-1",
                "attempt-1",
                "acknowledged",
                &receipt
            )
            .unwrap()
        );
        assert!(s.topic_publication_claim(key, 101).unwrap().is_none());
        let p = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert_eq!(p.local_turn, local);
        assert_eq!(p.kind, "control");
        assert!(!p.direct);
        assert!(p.body.contains("goal pause"));
        assert!(!p.body.contains("attempt-1"));
        // Direct registration belongs only to the origin. No target input was added.
        assert!(s.topic_projection_active(local).unwrap());
        let snapshot = s.thread_control_notices(100, "native", None).unwrap();
        assert_eq!(snapshot["schema"], "telecodex.thread-notices/v1");
        assert_eq!(snapshot["items"].as_array().unwrap().len(), 1);
        assert_eq!(snapshot["items"][0]["text"], p.body);
        let cursor = snapshot["cursor"].as_i64().unwrap();
        assert!(snapshot["history"].as_bool().unwrap());
        assert!(
            s.thread_control_notices(100, "native", Some(cursor))
                .unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            s.thread_control_notices(101, "native", None).unwrap()["available"],
            false
        );
        assert_eq!(
            s.thread_control_notices(100, "other-native", None).unwrap()["available"],
            false
        );
        assert!(s.thread_control_notices(100, "native", Some(-1)).is_err());
        s.topic_publication_parts(p.id, std::slice::from_ref(&p.body))
            .unwrap();
        assert!(s.topic_publication_reserve(p.id, 0).unwrap());
        s.topic_publication_receipt(p.id, 0, Some(10), false)
            .unwrap();
        s.topic_publication_finish(p.id).unwrap();
        assert!(s.topic_publication_claim(key, 100).unwrap().is_none());
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT COUNT(*) FROM turns", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            2
        );
        assert_eq!(
            conn.query_row("SELECT COUNT(*) FROM interaction_instructions", [], |r| r
                .get::<_, i64>(
                0
            ))
            .unwrap(),
            0
        );
    }
    #[test]
    fn failed_control_publication_retention_rolls_back_receipt() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (_, key) = execution(&s);
        control(&s, key);
        s.conn.lock().unwrap().execute_batch("CREATE TRIGGER reject_control_notice BEFORE INSERT ON topic_publications WHEN NEW.kind='control' BEGIN SELECT RAISE(ABORT,'test publication retention failure'); END;").unwrap();
        assert!(
            s.goal_control_finish(
                100,
                SessionKey::new(100, Some(9)),
                "control-1",
                "attempt-1",
                "acknowledged",
                &json!({})
            )
            .is_err()
        );
        assert_eq!(
            s.conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT phase FROM interaction_goal_controls WHERE id='control-1'",
                    [],
                    |r| r.get::<_, String>(0)
                )
                .unwrap(),
            "claimed"
        );
    }
    #[test]
    fn unselected_secondary_notice_does_not_hold_the_direct_output_lane() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (target_local, key) = execution(&s);
        control(&s, key);
        s.topic_direct_register(target_local, 100, key).unwrap();
        s.goal_control_finish(
            100,
            SessionKey::new(100, Some(9)),
            "control-1",
            "attempt-1",
            "acknowledged",
            &json!({}),
        )
        .unwrap();
        {
            let conn = s.conn.lock().unwrap();
            enqueue_on(
                &conn,
                target_local,
                "native",
                "ordinary-answer",
                "An ordinary direct reply",
            )
            .unwrap();
        }
        let secondary = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert!(!secondary.direct);
        assert_eq!(secondary.kind, "control");
        s.topic_publication_not_selected(secondary.id).unwrap();
        let direct = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert!(direct.direct);
        assert_eq!(direct.body, "An ordinary direct reply");
        // Selection for Telegram is independent of whether the local UI may read it.
        assert_eq!(
            s.thread_control_notices(100, "native", None).unwrap()["items"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        let ledger = s.topic_publication_inventory(100).unwrap();
        let notice = ledger["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["id"] == secondary.id)
            .unwrap();
        assert_eq!(notice["phase"], "not_selected");
        assert_eq!(notice["acknowledged_parts"], 0);
    }
    #[test]
    fn actual_collector_retirement_and_restart_publish_outcomes_without_retry() {
        for submitted in [false, true] {
            for restart in [false, true] {
                let file = tempfile::NamedTempFile::new().unwrap();
                let s = store(file.path());
                let (_, key) = execution(&s);
                control(&s, key);
                if submitted {
                    s.conn.lock().unwrap().execute("UPDATE interaction_goal_controls SET phase='submitted' WHERE id='control-1'",[]).unwrap();
                }
                let s = if restart {
                    drop(s);
                    store(file.path())
                } else {
                    s.goal_control_retire_execution(
                        100,
                        SessionKey::new(100, Some(9)),
                        "control-1",
                        "attempt-1",
                    )
                    .unwrap();
                    s
                };
                let notice = s.topic_publication_claim(key, 100).unwrap().unwrap();
                assert!(notice.body.contains(if submitted {
                    "Outcome unknown"
                } else {
                    "Not submitted"
                }));
                assert!(!notice.direct);
                let conn = s.conn.lock().unwrap();
                assert_eq!(
                    conn.query_row("SELECT COUNT(*) FROM turns", [], |r| r.get::<_, i64>(0))
                        .unwrap(),
                    2
                );
                assert_eq!(
                    conn.query_row("SELECT COUNT(*) FROM interaction_instructions", [], |r| r
                        .get::<_, i64>(
                        0
                    ))
                    .unwrap(),
                    0
                );
                assert_eq!(
                    conn.query_row(
                        "SELECT COUNT(*) FROM topic_publications WHERE kind='control'",
                        [],
                        |r| r.get::<_, i64>(0)
                    )
                    .unwrap(),
                    1
                );
            }
        }
    }
    #[test]
    fn control_notice_observes_binding_and_revocation_at_actual_send() {
        for revoke in [false, true] {
            let file = tempfile::NamedTempFile::new().unwrap();
            let s = store(file.path());
            let (_, key) = execution(&s);
            control(&s, key);
            s.goal_control_finish(
                100,
                SessionKey::new(100, Some(9)),
                "control-1",
                "attempt-1",
                "uncertain",
                &json!({}),
            )
            .unwrap();
            let p = s.topic_publication_claim(key, 100).unwrap().unwrap();
            assert!(p.body.contains("Outcome unknown"));
            s.topic_publication_parts(p.id, std::slice::from_ref(&p.body))
                .unwrap();
            if revoke {
                s.conn
                    .lock()
                    .unwrap()
                    .execute("UPDATE users SET allowed=0 WHERE tg_user_id=100", [])
                    .unwrap();
            } else {
                s.set_session_codex_thread(key, "replacement").unwrap();
            }
            assert!(!s.topic_publication_reserve(p.id, 0).unwrap());
            let feed = s.thread_control_notices(100, "native", None).unwrap();
            assert_eq!(feed["available"], false);
            assert!(feed["items"].as_array().unwrap().is_empty());
        }
    }
    #[test]
    fn notice_snapshot_bounds_history_and_delta_cursor_does_not_skip_backlog() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (_, key) = execution(&s);
        control(&s, key);
        s.goal_control_finish(
            100,
            SessionKey::new(100, Some(9)),
            "control-1",
            "attempt-1",
            "acknowledged",
            &json!({}),
        )
        .unwrap();
        {
            let conn = s.conn.lock().unwrap();
            for n in 2..=40 {
                let id = format!("control-{n}");
                conn.execute("INSERT INTO interaction_goal_controls SELECT ?1,human_id,entry_chat,entry_topic,target_chat,target_topic,phase,doc,result,instance_id FROM interaction_goal_controls WHERE id='control-1'",[&id]).unwrap();
                conn.execute("INSERT INTO topic_publications(local_turn,session_id,human_id,kind,source,body,phase,instance_id) SELECT local_turn,session_id,human_id,kind,json_array(?1,'attempt-1','acknowledged'),body,'ready','' FROM topic_publications WHERE kind='control' AND json_extract(source,'$[0]')='control-1'",[&id]).unwrap();
            }
        }
        let snapshot = s.thread_control_notices(100, "native", None).unwrap();
        assert_eq!(snapshot["items"].as_array().unwrap().len(), 32);
        assert_eq!(snapshot["history_truncated"], true);
        assert_eq!(snapshot["cursor"], 40);
        assert_eq!(snapshot["items"][0]["sequence"], 9);
        let first = s.thread_control_notices(100, "native", Some(0)).unwrap();
        assert_eq!(first["has_more"], true);
        assert_eq!(first["cursor"], 32);
        let second = s.thread_control_notices(100, "native", Some(32)).unwrap();
        assert_eq!(second["has_more"], false);
        assert_eq!(second["items"].as_array().unwrap().len(), 8);
        assert_eq!(second["items"][0]["sequence"], 33);
    }
    #[test]
    fn pre_native_failure_notice_needs_owner_scope_but_no_native_receipt() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        // Preparation can fail before ThreadStarted even for an already-bound
        // session. A notice does not claim native output or input acceptance.
        s.conn
            .lock()
            .unwrap()
            .execute("UPDATE turns SET native_thread_id=NULL WHERE id=?", [local])
            .unwrap();
        s.topic_direct_register(local, 100, key).unwrap();
        s.topic_publication_notice(local, "Native preparation unavailable")
            .unwrap();
        assert!(s.topic_publication_claim(key, 101).unwrap().is_none());
        let p = s.topic_publication_claim(key, 100).unwrap().unwrap();
        s.topic_publication_parts(p.id, &[p.body]).unwrap();
        s.conn
            .lock()
            .unwrap()
            .execute("UPDATE users SET allowed=0 WHERE tg_user_id=100", [])
            .unwrap();
        assert!(!s.topic_publication_reserve(p.id, 0).unwrap());
        s.conn
            .lock()
            .unwrap()
            .execute("UPDATE users SET allowed=1 WHERE tg_user_id=100", [])
            .unwrap();
        assert!(s.topic_publication_reserve(p.id, 0).unwrap());
        s.topic_publication_receipt(p.id, 0, Some(900), false)
            .unwrap();
        s.topic_publication_finish(p.id).unwrap();
    }
    #[test]
    fn topic_publication_identity_order_parts_and_unknown_ack_survive_restart() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        let text = "Answer\n<daimon-result>{\"requests\":[],\"covered\":[]}</daimon-result>";
        for _ in 0..2 {
            s.record_native_message(local, "native", "turn", "A", Some("final_answer"), text)
                .unwrap();
        }
        s.record_native_message(
            local,
            "native",
            "turn",
            "B",
            Some("commentary"),
            "Another item",
        )
        .unwrap();
        let a = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert_eq!(a.body, "Answer");
        assert!(s.topic_publication_claim(key, 100).unwrap().is_none());
        let parts = s
            .topic_publication_parts(a.id, &["One".into(), "Two".into()])
            .unwrap();
        assert_eq!(parts.len(), 2);
        assert!(s.topic_publication_reserve(a.id, 0).unwrap());
        s.topic_publication_receipt(a.id, 0, Some(901), false)
            .unwrap();
        assert!(s.topic_publication_reserve(a.id, 1).unwrap());
        drop(s); // Accepted send with no receipt: never replay its second part.
        let s = store(file.path());
        let b = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert_ne!(a.id, b.id);
        let inventory = s.topic_publication_inventory(100).unwrap();
        let rows = inventory["items"].as_array().unwrap();
        let old = rows.iter().find(|row| row["id"] == a.id).unwrap();
        assert_eq!(old["phase"], "uncertain");
        assert_eq!(old["acknowledged_parts"], 1);
        assert!(
            s.topic_publication_inventory(101).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert!(!s.topic_publication_reserve(a.id, 1).unwrap());
    }

    #[test]
    fn topic_receipt_without_reply_mapping_commit_stays_uncertain() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        s.record_native_message(
            local,
            "native",
            "turn",
            "result",
            Some("final_answer"),
            "Retained answer",
        )
        .unwrap();
        let publication = s.topic_publication_claim(key, 100).unwrap().unwrap();
        s.topic_publication_parts(publication.id, &[publication.body])
            .unwrap();
        assert!(s.topic_publication_reserve(publication.id, 0).unwrap());
        s.conn
            .lock()
            .unwrap()
            .execute_batch(
                "CREATE TRIGGER fixture_mapping_failure BEFORE INSERT ON handoff_messages
             BEGIN SELECT RAISE(ABORT, 'synthetic reply mapping write failure'); END;",
            )
            .unwrap();
        assert!(
            s.topic_publication_receipt(publication.id, 0, Some(901), false)
                .is_err()
        );
        drop(s);

        let s = store(file.path());
        let inventory = s.topic_publication_inventory(100).unwrap();
        let item = &inventory["items"][0];
        assert_eq!(item["id"], publication.id);
        assert_eq!(item["phase"], "uncertain");
        assert_eq!(item["acknowledged_parts"], 0);
        assert!(s.topic_publication_claim(key, 100).unwrap().is_none());
    }
    #[test]
    fn topic_publication_known_unsent_and_acknowledged_prefix_resume_without_reformat() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        s.record_native_message(local, "native", "turn", "A", None, "Whole answer")
            .unwrap();
        let a = s.topic_publication_claim(key, 100).unwrap().unwrap();
        s.topic_publication_parts(a.id, &["First".into(), "Second".into()])
            .unwrap();
        assert!(s.topic_publication_reserve(a.id, 0).unwrap());
        s.topic_publication_receipt(a.id, 0, Some(900), false)
            .unwrap();
        drop(s); // No attempt for part 1; continuing publication is not work replay.
        let s = store(file.path());
        let restored = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert_eq!(restored.id, a.id);
        assert_eq!(
            s.topic_publication_parts(a.id, &["Changed renderer".into()])
                .unwrap(),
            vec![(1, "Second".into())]
        );
        assert!(s.topic_publication_reserve(a.id, 1).unwrap());
        s.topic_publication_retry(a.id, 1).unwrap(); // An explicit rejection can retry.
        let retry = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert_eq!(retry.id, a.id);
        assert!(s.topic_publication_reserve(a.id, 1).unwrap());
        s.topic_publication_receipt(a.id, 1, Some(901), false)
            .unwrap();
        s.topic_publication_finish(a.id).unwrap();
        assert!(s.topic_publication_claim(key, 100).unwrap().is_none());
        assert_eq!(
            s.topic_publication_inventory(100).unwrap()["items"][0]["phase"],
            "sent"
        );
    }
    #[test]
    fn topic_publication_rechecks_destination_owner_and_native_binding_before_attempt() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        assert!(s.topic_projection_register(local, 101, key).is_err());
        s.record_native_message(local, "native", "turn", "A", None, "Answer")
            .unwrap();
        let a = s.topic_publication_claim(key, 100).unwrap().unwrap();
        s.topic_publication_parts(a.id, &[a.body]).unwrap();
        s.set_session_codex_thread(key, "renewed").unwrap();
        assert!(!s.topic_publication_reserve(a.id, 0).unwrap());
        s.topic_publication_finish(a.id).unwrap();
        assert_eq!(
            s.topic_publication_inventory(100).unwrap()["items"][0]["phase"],
            "retired"
        );
        s.record_native_message(local, "native", "turn", "B", None, "Old output")
            .unwrap();
        assert!(s.topic_publication_claim(key, 100).unwrap().is_none());
    }
    #[test]
    fn topic_publication_input_echo_is_accepted_only_once_and_precedes_native_answer() {
        use crate::interaction::{RequestRelation, ReturnRoute, SourceInput, TransportPhase as P};
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = store(file.path());
        let (local, key) = execution(&s);
        let session = s.get_session(key).unwrap().unwrap();
        let (source, _) = s
            .interaction_admit(
                &SourceInput {
                    telegram_files: vec![],
                    telegram_album_members: Vec::new(),
                    tribu_source: None,
                    transcription: None,
                    channel: "telegram:bot".into(),
                    event_id: "10".into(),
                    update_id: Some(10),
                    human_id: 100,
                    target_sessions: vec![session.id],
                    origin: ReturnRoute {
                        chat_id: 100,
                        thread_id: 1,
                        message_id: Some(10),
                    },
                    text: "Exact routed text\n<daimon-result>{\"requests\":[],\"covered\":[]}</daimon-result>".into(),
                },
                key,
                RequestRelation::New,
            )
            .unwrap();
        assert!(
            s.topic_publication_inventory(100).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        s.interaction_transport(&source.id, 100, local, P::Submitting, None)
            .unwrap();
        for _ in 0..2 {
            s.interaction_transport(&source.id, 100, local, P::Accepted, Some("turn"))
                .unwrap();
        }
        s.record_native_message(local, "native", "turn", "A", Some("final_answer"), "Answer")
            .unwrap();
        let first = s.topic_publication_claim(key, 100).unwrap().unwrap();
        assert!(first.body.ends_with("</daimon-result>")); // Human quotation stays source data.
        assert!(
            first
                .body
                .contains("Human message · via integrator\n\nExact routed text")
        );
        assert_eq!(
            s.topic_publication_inventory(100).unwrap()["items"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
    }
}
