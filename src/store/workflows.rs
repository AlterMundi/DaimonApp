//! Bounded human-selected workflows extend the existing instruction/result journal.
//! This module never runs a scheduler, publishes an answer or creates human speech.
use super::*;
use crate::interaction::{Delivery, InputReference, Instruction, RequestRelation, SourceInput};
use anyhow::bail;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

mod native_returns;
pub(crate) use native_returns::{ReturnDispatch, WorkflowReturn};
pub(super) use native_returns::{
    only_on as native_only_on, publication_on as native_publication_on,
    reconcile_on as native_reconcile_on, return_sources_on as native_return_sources_on,
    source_current_on as native_source_current_on,
    transfer_collection_on as native_transfer_collection_on, visible_on as native_visible_on,
};

const MAX_RETAINED_WORKFLOWS: i64 = 256;
const MAX_WORKFLOW_DOCUMENT_BYTES: usize = 256 * 1024;
pub(crate) const WORKFLOW_CAPACITY_ERROR: &str = "Workflow journal capacity reached; retain existing history and finish or inspect current workflows";

/// Only bounded, non-sensitive admission diagnostics cross the tool boundary.
#[derive(Debug)]
struct WorkflowRejection {
    code: &'static str,
    workflow: Option<String>,
}
impl std::fmt::Display for WorkflowRejection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.code)
    }
}
impl std::error::Error for WorkflowRejection {}
fn refusal(code: &'static str, workflow: Option<String>) -> anyhow::Error {
    WorkflowRejection { code, workflow }.into()
}
pub(crate) fn rejection(error: &anyhow::Error) -> Option<Value> {
    let e = error.downcast_ref::<WorkflowRejection>()?;
    let recovery = match e.code {
        "workflow_plan_conflict" => {
            "This request_id already names an immutable plan. Inspect workflow_status and its retained instructions. Exact retries must preserve the plan; a genuinely additional authorized subtask uses a distinct stable request_id, not a replacement original or a retry of accepted/uncertain work."
        }
        "workflow_scope_already_selected" => {
            "This subtask already belongs to the referenced workflow. Inspect and continue that retained workflow; changing request_id is not permission to dispatch it again."
        }
        "workflow_original_retired" => {
            "A prior explicit withdrawal/supersession retired this original's workflow authority. Preserve existing effects and select the actual later human instruction instead."
        }
        "workflow_selected" => {
            "This original already has attributed workflow work. Inspect the retained workflow. For genuinely additional authorized work, declare a separate bounded workflow with the same input_ref and its own stable request_id and scope; do not dispatch the entire original again or replay an existing subtask."
        }
        _ => return None,
    };
    Some(
        json!({"kind":"routing_rejected","code":e.code,"workflow":e.workflow,"admitted":false,"effect":"This call made no new workflow or native submission; earlier effects remain retained.","recovery":recovery}),
    )
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowStep {
    pub id: String,
    pub owner: SessionKey,
    pub after: Option<String>,
    pub scope: String,
    pub checkpoint: String,
    pub milestone: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowPlan {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_instruction: Option<String>,
    pub request_id: String,
    pub input_ref: InputReference,
    pub expires_at: String,
    pub steps: Vec<WorkflowStep>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct PrimaryRouting {
    instruction: String,
    input_id: String,
    target_session: i64,
    target: SessionKey,
    native: String,
    binding: String,
    requests: Vec<String>,
    source_hash: String,
    epoch: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Admission {
    instruction: String,
    predecessor: Option<Value>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
struct Workflow {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    primary: Option<PrimaryRouting>,
    id: String,
    human: i64,
    entry: SessionKey,
    native: String,
    binding: String,
    epoch: String,
    source: SourceInput,
    plan: WorkflowPlan,
    phase: String,
    admissions: Vec<Option<Admission>>,
    // One current acknowledgment per step/source kind, never an event history.
    reported: Vec<Option<String>>,
    final_checkpoint: Option<String>,
    supersession: Option<Value>,
    #[serde(default)]
    native_returns: Vec<WorkflowReturn>,
    #[serde(default)]
    attention: Option<super::heartbeat::AttentionOwner>,
}
fn digest(v: &impl Serialize) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(v)?)))
}
fn token(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn load_on(conn: &Connection, human: i64, entry: SessionKey, id: &str) -> Result<Workflow> {
    let raw:String=conn.query_row("SELECT doc FROM interaction_workflows WHERE id=?1 AND human_id=?2 AND entry_chat=?3 AND entry_topic=?4",params![id,human,entry.chat_id,entry.thread_id],|r|r.get(0))?;
    Ok(serde_json::from_str(&raw)?)
}
fn document(w: &Workflow) -> Result<String> {
    let raw = serde_json::to_string(w)?;
    if raw.len() > MAX_WORKFLOW_DOCUMENT_BYTES {
        bail!("Workflow document bound exceeded; no state was changed");
    }
    Ok(raw)
}
fn save_on(conn: &Connection, w: &Workflow) -> Result<()> {
    let raw = document(w)?;
    conn.execute(
        "UPDATE interaction_workflows SET phase=?2,doc=?3 WHERE id=?1",
        params![w.id, w.phase, raw],
    )?;
    Ok(())
}
fn live_on(conn: &Connection, w: &Workflow) -> Result<bool> {
    let (session, native) = super::presentation::entry_on(conn, w.human, w.entry)?;
    if w.phase != "active"
        || native != w.native
        || super::presentation::entry_binding(conn, w.human, w.entry, session)? != w.binding
        || super::stopping::admission_epoch_on(conn, w.entry)? != w.epoch
        || super::stopping::fenced_on(conn, w.entry)?
        || super::maintenance_writer_held_on(conn, w.entry)?
        || chrono::DateTime::parse_from_rfc3339(&w.plan.expires_at)? <= Utc::now()
    {
        return Ok(false);
    }
    // Re-read the retained original instead of promoting a callback to authority.
    let (original, _) = super::dialogue::original_owned_on(
        conn,
        w.entry,
        w.human,
        &w.native,
        &w.plan.input_ref,
        &w.source.channel,
        false,
    )?;
    if original != w.source {
        return Ok(false);
    }
    if let Some(primary) = &w.primary {
        if primary_on(conn, w.human, &w.source, &primary.instruction)
            .ok()
            .as_ref()
            != Some(primary)
        {
            return Ok(false);
        }
        for step in &w.plan.steps {
            if !primary_target_allowed(conn, w.human, primary, step.owner)? {
                return Ok(false);
            }
        }
    }
    Ok(true)
}
fn owner_on(conn: &Connection, human: i64, key: SessionKey) -> Result<(i64, String)> {
    Ok(conn.query_row("SELECT s.id,s.codex_thread_id FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1 AND s.force_fresh_thread=0 AND s.codex_thread_id IS NOT NULL",params![key.chat_id,key.thread_id,human],|r|Ok((r.get(0)?,r.get(1)?)))?)
}
fn instruction_on(conn: &Connection, human: i64, id: &str) -> Result<Instruction> {
    let (raw,phase):(String,String)=conn.query_row("SELECT i.doc,i.phase FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id WHERE i.id=?1 AND s.human_id=?2",params![id,human],|r|Ok((r.get(0)?,r.get(1)?)))?;
    let mut i: Instruction = serde_json::from_str(&raw)?;
    i.phase = phase.as_str().try_into()?;
    Ok(i)
}
fn primary_on(
    conn: &Connection,
    human: i64,
    source: &SourceInput,
    id: &str,
) -> Result<PrimaryRouting> {
    anyhow::ensure!(
        Uuid::parse_str(id).is_ok_and(|u| u.to_string() == id),
        "Exact primary instruction UUID required"
    );
    let i = instruction_on(conn, human, id)?;
    let (session, native) = owner_on(conn, human, i.target)?;
    let epoch = super::stopping::admission_epoch_on(conn, i.target)?;
    let withdrawn:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM interaction_session_withdrawals WHERE parent_instruction=?1) OR EXISTS(SELECT 1 FROM interaction_session_authors WHERE input_id=?2)",params![id,i.input_id],|r|r.get(0))?;
    anyhow::ensure!(
        !withdrawn
            && i.human_id == human
            && i.target_session == session
            && i.phase == crate::interaction::TransportPhase::Accepted
            && i.native_thread.as_deref() == Some(native.as_str())
            && i.admission_epoch.as_deref() == Some(epoch.as_str())
            && !super::stopping::fenced_on(conn, i.target)?
            && !super::maintenance_writer_held_on(conn, i.target)?,
        "Primary routing is not a current accepted human instruction"
    );
    let raw: String = conn.query_row(
        "SELECT doc FROM interaction_sources WHERE id=?1 AND human_id=?2",
        params![i.input_id, human],
        |r| r.get(0),
    )?;
    let original: SourceInput = serde_json::from_str(&raw)?;
    let mut normalized = original.clone();
    normalized.target_sessions.clear();
    let mut expected = source.clone();
    expected.target_sessions.clear();
    anyhow::ensure!(
        normalized == expected,
        "Primary belongs to another human original"
    );
    Ok(PrimaryRouting {
        instruction: id.into(),
        input_id: i.input_id,
        target_session: session,
        target: i.target,
        native,
        binding: super::presentation::entry_binding(conn, human, i.target, session)?,
        requests: i.requests,
        source_hash: digest(&original)?,
        epoch,
    })
}
fn primary_target_allowed(
    conn: &Connection,
    human: i64,
    primary: &PrimaryRouting,
    target: SessionKey,
) -> Result<bool> {
    super::session_requests::interview_target_allowed_on(
        conn,
        human,
        primary.target_session,
        target,
    )
}
fn primary_view(primary: &PrimaryRouting) -> Value {
    json!({"instruction":primary.instruction,"target":primary.target,"requests":primary.requests,"meaning":"Existing primary owner and original request coverage are retained. This workflow is an additional scoped subtask, not a replay, replacement or completion of that original."})
}
pub(in crate::store) fn purpose_parents_on(
    conn: &Connection,
    human: i64,
    source: &SourceInput,
) -> Result<Value> {
    let mut q=conn.prepare("SELECT i.id FROM interaction_instructions i JOIN interaction_sources x ON x.id=i.input_id WHERE x.human_id=?1 AND x.channel=?2 AND x.event_id=?3 ORDER BY i.sequence LIMIT 6")?;
    let ids = q
        .query_map(params![human, source.channel, source.event_id], |r| {
            r.get::<_, String>(0)
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    anyhow::ensure!(
        ids.len() <= 5,
        "Original primary routing exceeds bounded selection"
    );
    Ok(json!(ids.iter().map(|id|match primary_on(conn,human,source,id){Ok(p)=>primary_view(&p),Err(_)=>json!({"instruction":id,"state":"unavailable","meaning":"Not a current accepted human primary; do not replay it"})}).collect::<Vec<_>>()))
}
fn result_on(conn: &Connection, w: &Workflow, index: usize) -> Result<Option<(Value, Delivery)>> {
    let Some(a) = &w.admissions[index] else {
        return Ok(None);
    };
    let i = instruction_on(conn, w.human, &a.instruction)?;
    // Join every covered request, not only the representative delivery request.
    let found:Option<(String,String,String,String,String)>=conn.query_row(
        "SELECT d.doc,d.result_id,z.native_thread,z.native_turn,z.item_id FROM interaction_deliveries d JOIN interaction_delivery_requests m ON m.delivery_id=d.id JOIN interaction_request_links l ON l.request_id=m.request_id JOIN interaction_results z ON z.id=d.result_id WHERE l.instruction_id=?1 AND d.human_id=?2 ORDER BY d.rowid DESC LIMIT 1",
        params![i.id,w.human],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
    let Some((raw, result, native, turn, item)) = found else {
        return Ok(None);
    };
    let d: Delivery = serde_json::from_str(&raw)?;
    let (current, correction) = super::routing::delivery_freshness(conn, &d)?;
    let owner_current =
        owner_on(conn, w.human, w.plan.steps[index].owner).is_ok_and(|(_, n)| n == native);
    let mut source = json!({"id":result,"delivery":d.id,"native_thread":native,"native_turn":turn,"item":item,"source_session":i.target_session,"instruction":i.id,"completed":d.completed,"current":current && owner_current,"correction_pending":correction});
    // The revision fences the immutable canonical body and current source/coverage.
    source["revision"] = json!(digest(&json!([source, d.covered, d.body]))?);
    Ok(Some((source, d)))
}
fn completed(source: &Value) -> bool {
    source["completed"] == true
        && source["current"] == true
        && source["correction_pending"] == false
}
fn view_on(conn: &Connection, w: &Workflow) -> Result<Value> {
    let live = live_on(conn, w).unwrap_or(false);
    let mut steps = vec![];
    let mut previous: Option<Value> = None;
    let mut all_completed = true;
    for (index, step) in w.plan.steps.iter().enumerate() {
        let result = result_on(conn, w, index)?.map(|(source, _)| source);
        let predecessor_current = index == 0 || previous.as_ref().is_some_and(completed);
        let mut phase = if predecessor_current {
            "ready"
        } else {
            "waiting"
        }
        .to_owned();
        let mut instruction = None;
        if let Some(a) = &w.admissions[index] {
            let i = instruction_on(conn, w.human, &a.instruction)?;
            phase = i.phase.as_str().to_owned();
            // An already started successor cannot be replayed after a correction.
            // Retain it and expose the mismatch for integrator reconciliation.
            if a.predecessor != previous {
                phase = "predecessor_changed".into();
            } else if result.as_ref().is_some_and(completed) {
                phase = "completed".into();
            } else if result
                .as_ref()
                .is_some_and(|r| r["correction_pending"] == true || r["current"] == false)
            {
                phase = "correction_pending".into();
            }
            instruction = Some(i.id);
        } else if !live {
            phase = "withdrawn".into();
        }
        all_completed &= phase == "completed";
        steps.push(json!({"id":step.id,"owner":step.owner,"after":step.after,"checkpoint":step.checkpoint,"milestone":step.milestone,"phase":phase,"instruction":instruction,"result":result}));
        // Successor readiness requires the whole prefix, including the source
        // revision actually consumed by every earlier step.
        previous = if phase == "completed" { result } else { None };
    }
    let phase = if w.phase != "active" {
        w.phase.as_str()
    } else if !live {
        "retired"
    } else if all_completed {
        "awaiting_integration"
    } else {
        "active"
    };
    let mut view = json!({"schema":"telecodex.workflow/v1","id":w.id,"input_ref":w.plan.input_ref,"request_id":w.plan.request_id,"entry":w.entry,"expires_at":w.plan.expires_at,"phase":phase,"steps":steps,"final_checkpoint":w.final_checkpoint,"supersession":w.supersession,"authority":"retained original human input; worker results are internal evidence","publication_grant":false});
    if let Some(primary) = &w.primary {
        view["primary_routing"] = primary_view(primary);
    }
    view["revision"] = json!(digest(&view)?);
    let mut returns = Vec::new();
    for r in &w.native_returns {
        let observation = if let Some(local) = r.collection_local {
            conn.query_row(
                "SELECT phase,detail FROM native_collections WHERE local_turn=?1",
                [local],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?
            .map(|(phase, detail)| json!({"phase":phase,"detail":detail}))
        } else {
            None
        };
        returns.push(json!({"id":r.id,"source_revision":r.envelope["revision"],"phase":r.phase,"local_turn":r.local,"collection_local_turn":r.collection_local,"native_turn":r.native_turn,"attempts":r.attempts,"max_attempts":3,"retry_after":r.retry_after,"observation":observation}));
    }
    view["native_returns"] = json!({"limit":16,"retained":returns});
    Ok(view)
}
fn attention_on(conn: &Connection, w: &Workflow) -> Result<Vec<Value>> {
    let view = view_on(conn, w)?;
    if !matches!(
        view["phase"].as_str(),
        Some("active" | "awaiting_integration")
    ) {
        return Ok(vec![]);
    }
    let mut envelopes = vec![];
    for (index, step) in w.plan.steps.iter().enumerate() {
        let source = &view["steps"][index]["result"];
        let bounded_source = if source.is_object() {
            json!({"kind":"canonical_result","id":source["id"],"delivery":source["delivery"],"revision":source["revision"],"source_session":source["source_session"],"instruction":source["instruction"],"completed":source["completed"],"current":source["current"],"correction_pending":source["correction_pending"]})
        } else {
            Value::Null
        };
        let phase = view["steps"][index]["phase"].as_str().unwrap_or("");
        let reason = if matches!(phase, "correction_pending" | "predecessor_changed") {
            Some("reconciliation_required")
        } else if phase == "completed" && index + 1 == w.plan.steps.len() {
            Some("integration_required")
        } else if phase == "completed"
            && (step.milestone.is_some()
                || w.admissions.get(index + 1).is_some_and(Option::is_none))
        {
            Some(if step.milestone.is_some() {
                "reporting_milestone"
            } else {
                "successor_ready"
            })
        } else if matches!(phase, "retained_unsent" | "uncertain" | "rejected") {
            Some("admission_attention_required")
        } else {
            None
        };
        if let Some(reason) = reason {
            let mut envelope = json!({"workflow":w.id,"step":step.id,"source":bounded_source,"reason":reason,"milestone":step.milestone,"workflow_revision":view["revision"],"expires_at":w.plan.expires_at,"internal_evidence":true,"publication_grant":false});
            envelope
                .as_object_mut()
                .unwrap()
                .remove("workflow_revision");
            envelope["slot"] = json!(index * 3);
            let revision = digest(&envelope)?;
            envelope["revision"] = json!(revision);
            envelope["workflow_revision"] = view["revision"].clone();
            if w.reported[index * 3].as_deref() != Some(&revision) {
                envelopes.push(envelope);
            }
        }
        // Only pending native questions from this exact admitted step execution.
        // These source versions are not approval/answer revisions or responders.
        if let Some(admission) = &w.admissions[index] {
            let instruction = instruction_on(conn, w.human, &admission.instruction)?;
            let mut q=conn.prepare("SELECT h.id FROM human_interactions h JOIN turns t ON t.id=h.local_turn WHERE h.requester=?1 AND h.kind='native' AND h.state='pending' AND h.local_turn=?2 AND t.status='running' AND h.native_thread=?3 AND json_extract(h.payload_json,'$.source.kind')='question' ORDER BY h.rowid LIMIT 2")?;
            let ids = q
                .query_map(
                    params![w.human, instruction.local_turn, instruction.native_thread],
                    |r| r.get::<_, String>(0),
                )?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            for (position, id) in ids.into_iter().enumerate() {
                let question = super::conversation_requests::read_scoped_on(
                    conn, w.human, w.entry, &id, true,
                )?;
                let source = json!({"kind":"native_question","id":id,"revision":question.capture_version,"revision_kind":"capture_version","source_session":instruction.target_session,"native_thread":question.item.native_thread,"local_turn":question.item.local_turn,"current":true});
                let slot = index * 3 + position + 1;
                let mut envelope = json!({"workflow":w.id,"step":step.id,"source":source,"reason":"human_decision_required","slot":slot,"expires_at":w.plan.expires_at,"internal_evidence":true,"publication_grant":false});
                let revision = digest(&envelope)?;
                envelope["revision"] = json!(revision);
                envelope["workflow_revision"] = view["revision"].clone();
                if w.reported[slot].as_deref() != Some(&revision) {
                    envelopes.push(envelope);
                }
            }
        }
    }
    Ok(envelopes)
}

fn attention_workflow_on(
    conn: &Connection,
    human: i64,
    target: SessionKey,
    instruction: &str,
) -> Result<Option<Workflow>> {
    let raw:Option<String>=conn.query_row("SELECT w.doc FROM interaction_instructions i JOIN interaction_session_authors a ON a.input_id=i.input_id JOIN interaction_workflows w ON w.id=json_extract(a.doc,'$.workflow') WHERE i.id=?1 AND w.human_id=?2 AND json_extract(a.doc,'$.kind')='workflow_step'",params![instruction,human],|r|r.get(0)).optional()?;
    let Some(raw) = raw else { return Ok(None) };
    let w: Workflow = serde_json::from_str(&raw)?;
    let Some(owner) = &w.attention else {
        return Ok(None);
    };
    anyhow::ensure!(live_on(conn, &w)?, "Attention workflow authority retired");
    let index = w
        .admissions
        .iter()
        .position(|a| a.as_ref().is_some_and(|a| a.instruction == instruction))
        .context("Instruction is not an admitted workflow step")?;
    anyhow::ensure!(
        w.plan.steps[index].owner == target,
        "Delegated target changed"
    );
    super::heartbeat::owner_current_on(conn, human, owner)?;
    Ok(Some(w))
}

pub(in crate::store) fn heartbeat_offers_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    after: i64,
) -> Result<(i64, Vec<super::heartbeat::producer::Offer>)> {
    let rows = |after| -> Result<Vec<(i64, String)>> {
        let mut q=conn.prepare("SELECT rowid,doc FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND rowid>?4 AND phase='active' AND julianday(json_extract(doc,'$.plan.expires_at'))>julianday('now') ORDER BY rowid LIMIT 4")?;
        Ok(
            q.query_map(params![human, entry.chat_id, entry.thread_id, after], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })?
            .collect::<rusqlite::Result<_>>()?,
        )
    };
    let mut selected = rows(after)?;
    if selected.is_empty() && after > 0 {
        selected = rows(0)?;
    }
    let next = selected.last().map_or(0, |r| r.0);
    let mut offers = vec![];
    for (_, raw) in selected {
        let w: Workflow = serde_json::from_str(&raw)?;
        for mut evidence in attention_on(conn, &w)? {
            let revision = evidence["revision"]
                .as_str()
                .context("Workflow offer revision missing")?
                .to_owned();
            let slot = evidence["slot"]
                .as_u64()
                .context("Workflow offer slot missing")?;
            evidence["original_input_ref"] = json!(w.plan.input_ref);
            evidence["reader"] = if evidence["source"]["kind"] == "native_question" {
                json!({"operation":"workflow_question","arguments":{"question":evidence["source"]["id"],"revision":evidence["source"]["revision"],"offset":0}})
            } else if evidence["source"].is_object() {
                json!({"operation":"workflow_result","arguments":{"workflow":w.id,"step":evidence["step"],"revision":evidence["source"]["revision"],"offset":0}})
            } else {
                json!({"operation":"workflow_status","arguments":{"workflow":w.id}})
            };
            evidence["after_incorporation"] = json!({"operation":"workflow_reported","arguments":{"workflow":w.id,"revision":revision}});
            offers.push(super::heartbeat::producer::Offer {
                key: format!("workflow:{}:{slot}", w.id),
                revision,
                evidence,
            });
        }
    }
    Ok((next, offers))
}
pub(in crate::store) fn heartbeat_offer_current_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    key: &str,
    revision: &str,
    admission: bool,
) -> Result<bool> {
    let Some(id) = key
        .strip_prefix("workflow:")
        .and_then(|s| s.rsplit_once(':'))
        .map(|(id, _)| id)
    else {
        return Ok(false);
    };
    let mut w = load_on(conn, human, entry, id)?;
    if !admission {
        if !matches!(w.phase.as_str(), "active" | "completed") {
            return Ok(false);
        }
        w.phase = "active".into();
        w.reported.fill(None);
    }
    Ok(attention_on(conn, &w)?
        .iter()
        .any(|e| e["revision"] == revision))
}

/// Explicit owner Resume advances only retained workflow authority and returns
/// that have never crossed a native submission boundary. It creates no input,
/// allocation or retry, and preserves all accepted/uncertain execution evidence.
pub(in crate::store) fn resume_attention_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    native: &str,
    generation: u64,
) -> Result<()> {
    let mut q = conn.prepare("SELECT doc FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND phase='active' AND json_extract(doc,'$.attention') IS NOT NULL ORDER BY rowid LIMIT 257")?;
    let rows = q
        .query_map(params![human, entry.chat_id, entry.thread_id], |r| {
            r.get::<_, String>(0)
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    anyhow::ensure!(
        rows.len() <= 256,
        "Retained attention workflow capacity exceeded"
    );
    for raw in rows {
        let mut w: Workflow = serde_json::from_str(&raw)?;
        let Some(owner) = w.attention.as_ref() else {
            continue;
        };
        if owner.entry != entry
            || owner.native != native
            || owner.generation > generation
            || !live_on(conn, &w)?
        {
            continue;
        }
        let Some(activation) = owner.activation.as_ref() else {
            continue;
        };
        let Some(activation) = super::heartbeat::lanes::refreshed(conn, human, entry, activation)?
        else {
            continue;
        };
        w.attention.as_mut().unwrap().generation = generation;
        w.attention.as_mut().unwrap().activation = Some(activation.clone());
        for r in &mut w.native_returns {
            if r.attention_generation.is_some()
                && matches!(r.phase.as_str(), "reserved" | "retained_unsent")
                && r.local.is_none()
                && r.native_turn.is_none()
                && r.collection_local.is_none()
            {
                r.attention_generation = Some(generation);
                r.attention_activation = Some(activation.clone());
            }
        }
        save_on(conn, &w)?;
    }
    Ok(())
}

impl Store {
    /// Only the exact claimed child, with native proof of no submission, may
    /// return to the existing known-unsent recovery lane. Never downgrade ACKs.
    pub(crate) fn heartbeat_workflow_deferred(
        &self,
        id: &str,
        human: i64,
        local: i64,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let proven: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id JOIN bot_state b ON b.key='heartbeat_execution:'||?3 WHERE i.id=?1 AND s.human_id=?2 AND i.phase='submitting' AND json_extract(i.doc,'$.local_turn')=?3 AND json_extract(i.doc,'$.native_turn') IS NULL AND json_extract(b.value,'$.owner') IS NOT NULL AND json_extract(b.value,'$.physical') IS NULL AND json_extract(b.value,'$.phase')='terminal' AND json_extract(b.value,'$.terminal_status')='not_submitted')",params![id,human,local],|r|r.get(0))?;
        anyhow::ensure!(proven, "No exact unsubmitted delegated execution proof");
        let mut i = instruction_on(&tx, human, id)?;
        i.phase = crate::interaction::TransportPhase::RetainedUnsent;
        tx.execute(
            "UPDATE interaction_instructions SET phase='retained_unsent',doc=?2 WHERE id=?1",
            params![id, serde_json::to_string(&i)?],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub(super) fn init_workflows(&self) -> Result<()> {
        self.conn.lock().expect("store mutex poisoned").execute_batch(
            "CREATE TABLE IF NOT EXISTS interaction_workflows(id TEXT PRIMARY KEY,human_id INTEGER NOT NULL,entry_chat INTEGER NOT NULL,entry_topic INTEGER NOT NULL,source_key TEXT NOT NULL,phase TEXT NOT NULL,doc TEXT NOT NULL,UNIQUE(human_id,entry_chat,entry_topic,source_key));")?;
        Ok(())
    }
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_workflow_declare(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        channel: &str,
        plan: WorkflowPlan,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<Value> {
        if !token(&plan.request_id) || plan.steps.is_empty() || plan.steps.len() > 4 {
            bail!("A workflow requires one to four predeclared steps");
        }
        let mut ids = std::collections::HashSet::new();
        for (index, step) in plan.steps.iter().enumerate() {
            if !token(&step.id)
                || !ids.insert(&step.id)
                || step.owner == entry
                || step.scope.trim().is_empty()
                || step.scope.len() > 4000
                || step.checkpoint.trim().is_empty()
                || step.checkpoint.len() > 512
                || step
                    .milestone
                    .as_ref()
                    .is_some_and(|m| m.trim().is_empty() || m.len() > 80)
                || step.after.as_ref() != index.checked_sub(1).map(|i| &plan.steps[i].id)
            {
                bail!("Invalid ordered workflow step");
            }
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, current) = super::presentation::entry_on(&tx, human, entry)?;
        if current != native {
            bail!("Workflow entry binding changed");
        }
        let (source, _) = super::dialogue::original_owned_on(
            &tx,
            entry,
            human,
            native,
            &plan.input_ref,
            channel,
            false,
        )?;
        // Preserve old per-original workflow IDs. New plans use the actual
        // caller-selected subtask identity; changing an ID never retries work.
        let mut q = tx.prepare("SELECT doc FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND json_extract(doc,'$.source.channel')=?4 AND json_extract(doc,'$.source.event_id')=?5")?;
        let existing = q
            .query_map(
                params![
                    human,
                    entry.chat_id,
                    entry.thread_id,
                    source.channel,
                    source.event_id
                ],
                |r| r.get::<_, String>(0),
            )?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        drop(q);
        let siblings = existing
            .iter()
            .map(|raw| serde_json::from_str::<Workflow>(raw))
            .collect::<serde_json::Result<Vec<_>>>()?;
        if let Some(w) = siblings
            .iter()
            .find(|w| w.plan.request_id == plan.request_id)
        {
            if w.plan != plan || w.source != source || w.native != native {
                return Err(refusal("workflow_plan_conflict", Some(w.id.clone())));
            }
            return view_on(&tx, w);
        }
        for w in &siblings {
            if matches!(w.phase.as_str(), "superseded" | "withdrawn") {
                return Err(refusal("workflow_original_retired", Some(w.id.clone())));
            }
            if w.plan.steps.iter().any(|old| {
                plan.steps
                    .iter()
                    .any(|new| old.owner == new.owner && old.scope.trim() == new.scope.trim())
            }) {
                return Err(refusal(
                    "workflow_scope_already_selected",
                    Some(w.id.clone()),
                ));
            }
        }
        super::matrix::non_workflow_unclaimed_on(
            &tx,
            human,
            &source.channel,
            &source.event_id,
            source.update_id,
        )?;
        let source_key = digest(&json!([source.channel, source.event_id, plan.request_id]))?;
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("telecodex:workflow:{human}:{session}:{source_key}").as_bytes(),
        )
        .to_string();
        let (selected,creation):(bool,bool)=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_sources WHERE human_id=?1 AND channel=?2 AND event_id=?3),EXISTS(SELECT 1 FROM interaction_creations WHERE human_id=?1 AND input_update=?4)",params![human,source.channel,source.event_id,plan.input_ref],|r|Ok((r.get(0)?,r.get(1)?)))?;
        if creation || selected && plan.parent_instruction.is_none() {
            bail!("Original already has a dispatch or creation plan");
        }
        let primary = plan
            .parent_instruction
            .as_deref()
            .map(|id| primary_on(&tx, human, &source, id))
            .transpose()?;
        for step in &plan.steps {
            if let Some(primary) = &primary {
                anyhow::ensure!(
                    primary_target_allowed(&tx, human, primary, step.owner)?,
                    "An interview cannot activate its pinned source work"
                );
            }
        }
        let retained: i64 =
            tx.query_row("SELECT count(*) FROM interaction_workflows", [], |r| {
                r.get(0)
            })?;
        if retained >= MAX_RETAINED_WORKFLOWS {
            bail!(WORKFLOW_CAPACITY_ERROR);
        }
        let expiry = chrono::DateTime::parse_from_rfc3339(&plan.expires_at)?;
        if expiry <= Utc::now() || expiry > Utc::now() + Duration::days(7) {
            bail!("Workflow lifetime must be finite and at most seven days");
        }
        let count:i64=tx.query_row("SELECT count(*) FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND phase='active' AND julianday(json_extract(doc,'$.plan.expires_at'))>julianday('now')",params![human,entry.chat_id,entry.thread_id],|r|r.get(0))?;
        if count >= 16 {
            bail!("Active workflow bound reached");
        }
        for step in &plan.steps {
            owner_on(&tx, human, step.owner)?;
        }
        let w = Workflow {
            primary,
            id: id.clone(),
            human,
            entry,
            native: native.into(),
            binding: super::presentation::entry_binding(&tx, human, entry, session)?,
            epoch: super::stopping::admission_epoch_on(&tx, entry)?,
            source,
            admissions: vec![None; plan.steps.len()],
            reported: vec![None; plan.steps.len() * 3],
            plan,
            phase: "active".into(),
            final_checkpoint: None,
            supersession: None,
            native_returns: vec![],
            attention: None,
        };
        if !live_on(&tx, &w)? || closed.is_cancelled() {
            bail!("Workflow authority is not current");
        }
        let raw = document(&w)?;
        // Reserve room for the four bounded admission references, offer slots,
        // later-original supersession reference and final integration checkpoint.
        if raw.len() > MAX_WORKFLOW_DOCUMENT_BYTES - 32 * 1024 {
            bail!("Workflow original exceeds the reserved journal document bound");
        }
        tx.execute(
            "INSERT INTO interaction_workflows VALUES(?1,?2,?3,?4,?5,'active',?6)",
            params![id, human, entry.chat_id, entry.thread_id, source_key, raw],
        )?;
        let view = view_on(&tx, &w)?;
        tx.commit()?;
        Ok(view)
    }
    pub fn interaction_workflow_status(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
    ) -> Result<Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        if owner_on(&conn, human, entry)?.1 != native {
            bail!("Entry binding changed");
        }
        view_on(&conn, &load_on(&conn, human, entry, id)?)
    }
    /// One explicit progression under the original grant. Known-unsent attention
    /// work may recover its exact instruction after native non-submission proof;
    /// queued/uncertain/native-accepted work is never replayed.
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_workflow_advance(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
        revision: &str,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<Option<Instruction>> {
        self.interaction_workflow_advance_at_turn(human, entry, native, None, id, revision, closed)
    }
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn interaction_workflow_advance_at_turn(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        physical: Option<&str>,
        id: &str,
        revision: &str,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<Option<Instruction>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let mut w = load_on(&tx, human, entry, id)?;
        if native != w.native || !live_on(&tx, &w)? || closed.is_cancelled() {
            bail!("Workflow grant retired");
        }
        let view = view_on(&tx, &w)?;
        if view["revision"].as_str() != Some(revision) {
            bail!("Workflow revision changed; inspect without replay");
        }
        let Some(index) = view["steps"].as_array().unwrap().iter().position(|s| {
            s["phase"] == "ready" || (w.attention.is_some() && s["phase"] == "retained_unsent")
        }) else {
            return Ok(None);
        };
        if let Some(physical) = physical {
            if let Some(owner) =
                super::heartbeat::owner_for_turn_on(&tx, human, entry, native, physical)?
            {
                anyhow::ensure!(
                    w.attention.as_ref().is_none_or(|prior| prior == &owner),
                    "Workflow attention owner changed"
                );
                w.attention = Some(owner);
            }
        }
        if let Some(owner) = &w.attention {
            super::heartbeat::owner_current_on(&tx, human, owner)?;
        }
        let step = &w.plan.steps[index];
        let (session, _) = owner_on(&tx, human, step.owner)?;
        if super::stopping::fenced_on(&tx, step.owner)?
            || super::maintenance_writer_held_on(&tx, step.owner)?
        {
            bail!("Workflow owner admission held");
        }
        if view["steps"][index]["phase"] == "retained_unsent" {
            let admission = w.admissions[index]
                .as_ref()
                .context("Missing retained workflow instruction")?;
            // A retained label alone cannot prove the native never received it.
            // Keep source, actor and exact local execution tied to the original
            // terminal not_submitted observation; no UUID replacement or replay.
            let proven: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id JOIN bot_state b ON b.key='heartbeat_execution:'||json_extract(i.doc,'$.local_turn') WHERE i.id=?1 AND s.human_id=?2 AND i.phase='retained_unsent' AND json_extract(i.doc,'$.native_turn') IS NULL AND json_extract(b.value,'$.source')=i.id AND json_extract(b.value,'$.owner') IS NOT NULL AND json_extract(b.value,'$.physical') IS NULL AND json_extract(b.value,'$.phase')='terminal' AND json_extract(b.value,'$.terminal_status')='not_submitted')",
                params![admission.instruction, human], |row| row.get(0),
            )?;
            anyhow::ensure!(proven, "No exact unsubmitted delegated execution proof");
            anyhow::ensure!(
                super::interaction::recover_on(
                    &tx,
                    &admission.instruction,
                    human,
                    &self.instance_id
                )?,
                "Retained workflow recovery changed"
            );
            let recovered = instruction_on(&tx, human, &admission.instruction)?;
            anyhow::ensure!(
                !closed.is_cancelled(),
                "Workflow recovery closed before commitment"
            );
            tx.commit()?;
            return Ok(Some(recovered));
        }
        let predecessor = index
            .checked_sub(1)
            .map(|i| view["steps"][i]["result"].clone());
        // Reader arguments are transport guidance, not part of the canonical
        // source descriptor/revision retained by existing admissions.
        let predecessor_reader = index.checked_sub(1).map(|i| {
            json!({"operation":"workflow_result","arguments":{
                "workflow":w.id,"step":w.plan.steps[i].id,
                "revision":view["steps"][i]["result"]["revision"],"offset":0}})
        });
        let mut text = format!(
            "Preauthorized workflow step, authored by the integrating session. This is internal session context under the retained human task, never a new human instruction or permission to transfer ownership/create helpers. Workflow: {}. Step: {}. Original input: {}. Required checkpoint: {}. Scope:\n{}\nPredecessor source (read its exact revision with workflow_result before relying on it): {}",
            w.id,
            step.id,
            w.plan.input_ref,
            step.checkpoint,
            step.scope,
            serde_json::to_string(&predecessor)?
        );
        if let Some(reader) = &predecessor_reader {
            text.push_str(&format!(
                "\nPredecessor reader (use these exact arguments): {}",
                serde_json::to_string(reader)?
            ));
        }
        if let Some(primary) = &w.primary {
            text.push_str(&format!("\nExisting primary routing, whose owner and original request coverage remain unchanged: {}",primary_view(primary)));
        }
        let source = SourceInput {
            tribu_source: None,
            transcription: None,
            channel: "local-session".into(),
            event_id: format!("workflow:{}:{}", w.id, step.id),
            update_id: None,
            human_id: human,
            target_sessions: vec![session],
            origin: w.source.origin.clone(),
            text,
        };
        let (mut i, fresh) = super::interaction::admit_on(
            &tx,
            &source,
            step.owner,
            RequestRelation::New,
            &self.instance_id,
        )?;
        if !fresh {
            bail!("Unattributed workflow instruction exists");
        }
        i.admission_epoch = Some(w.epoch.clone());
        tx.execute(
            "UPDATE interaction_instructions SET doc=?2 WHERE id=?1",
            params![i.id, serde_json::to_string(&i)?],
        )?;
        let mut author = json!({"kind":"workflow_step","session":entry,"native_thread":native,"workflow":w.id,"step":step.id,"input_ref":w.plan.input_ref,"authorized_human":human,"predecessor":predecessor});
        if let Some(reader) = predecessor_reader {
            author["predecessor_reader"] = reader;
        }
        if let Some(primary) = &w.primary {
            author["primary_routing"] = primary_view(primary);
        }
        tx.execute(
            "INSERT INTO interaction_session_authors VALUES(?1,?2)",
            params![i.input_id, author.to_string()],
        )?;
        w.admissions[index] = Some(Admission {
            instruction: i.id.clone(),
            predecessor,
        });
        save_on(&tx, &w)?;
        if closed.is_cancelled() {
            bail!("Workflow advance closed before commitment");
        }
        tx.commit()?;
        Ok(Some(i))
    }
    /// Select existing workflow provenance; this does not charge or admit a worker.
    pub(crate) fn heartbeat_workflow_delegation(
        &self,
        human: i64,
        target: SessionKey,
        instruction: &str,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(attention_workflow_on(&conn, human, target, instruction)?.is_some())
    }
    pub(crate) fn heartbeat_claim_workflow_delegate(
        &self,
        local: i64,
        human: i64,
        target: SessionKey,
        instruction: &str,
    ) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let Some(w) = attention_workflow_on(&tx, human, target, instruction)? else {
            return Ok(false);
        };
        let (_, native) = super::presentation::entry_on(&tx, human, target)?;
        let owner = w
            .attention
            .as_ref()
            .context("Missing retained attention owner")?;
        super::heartbeat::claim_delegate_on(
            &tx,
            local,
            human,
            target,
            &native,
            owner,
            instruction,
        )?;
        tx.commit()?;
        Ok(true)
    }
    /// A committed canonical result is evidence for the integrator's retained
    /// finite plan, never a new worker-authored grant. Select exactly that source
    /// before reusing the same transactional progression/admission primitive.
    pub fn interaction_workflow_return(
        &self,
        human: i64,
        delivery: &str,
    ) -> Result<Option<Instruction>> {
        let selected = {
            let conn = self.conn.lock().expect("store mutex poisoned");
            let mut q=conn.prepare("SELECT DISTINCT w.doc FROM interaction_workflows w JOIN interaction_session_authors a ON json_extract(a.doc,'$.workflow')=w.id JOIN interaction_instructions i ON i.input_id=a.input_id JOIN interaction_request_links l ON l.instruction_id=i.id JOIN interaction_delivery_requests m ON m.request_id=l.request_id JOIN interaction_deliveries d ON d.id=m.delivery_id WHERE d.id=?1 AND d.human_id=?2 AND w.human_id=?2 AND w.phase='active' AND json_extract(a.doc,'$.kind')='workflow_step' LIMIT 2")?;
            let candidates = q
                .query_map(params![delivery, human], |r| r.get::<_, String>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            if candidates.len() > 1 {
                bail!("Canonical return has ambiguous workflow ownership");
            }
            let Some(raw) = candidates.into_iter().next() else {
                return Ok(None);
            };
            let w: Workflow = serde_json::from_str(&raw)?;
            let view = view_on(&conn, &w)?;
            if view["phase"] != "active" {
                return Ok(None);
            }
            let steps = view["steps"].as_array().unwrap();
            let ready = steps.iter().enumerate().any(|(index, step)| {
                index > 0
                    && step["phase"] == "ready"
                    && steps[index - 1]["phase"] == "completed"
                    && steps[index - 1]["result"]["delivery"] == delivery
            });
            if !ready {
                return Ok(None);
            }
            (
                w.entry,
                w.native,
                w.id,
                view["revision"].as_str().unwrap().to_owned(),
            )
        };
        // Revalidation is inside the committing transaction. A concurrent human
        // correction or duplicate result callback invalidates this exact view.
        self.interaction_workflow_advance(
            human,
            selected.0,
            &selected.1,
            &selected.2,
            &selected.3,
            &tokio_util::sync::CancellationToken::new(),
        )
    }

    pub fn interaction_workflow_attention(&self, human: i64, entry: SessionKey) -> Result<Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        super::presentation::entry_on(&conn, human, entry)?;
        let mut q=conn.prepare("SELECT doc FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND phase='active' AND julianday(json_extract(doc,'$.plan.expires_at'))>julianday('now') ORDER BY rowid LIMIT 16")?;
        let mut envelopes = vec![];
        for row in q.query_map(params![human, entry.chat_id, entry.thread_id], |r| {
            r.get::<_, String>(0)
        })? {
            let workflow: Workflow = serde_json::from_str(&row?)?;
            for mut envelope in attention_on(&conn, &workflow)? {
                // Delivery metadata never changes the source revision, reserves
                // another return, or converts an ACK into human incorporation.
                if let Some(receipt) = workflow
                    .native_returns
                    .iter()
                    .rev()
                    .find(|r| r.envelope["revision"] == envelope["revision"])
                {
                    envelope["native_return"] = json!({"id":receipt.id,"phase":receipt.phase,"native_turn":receipt.native_turn,"attempts":receipt.attempts,"max_attempts":3,"retry_after":receipt.retry_after});
                }
                envelopes.push(envelope);
            }
        }
        let matrix = super::matrix::attention_on(&conn, human, entry)?;
        Ok(
            json!({"schema":"telecodex.workflow-attention/v1","matrix":matrix,"envelopes":envelopes,"bounded":true,"max_workflows":16,"max_steps":4,"max_envelopes":192,"automatic_native_return":false,"publication_grant":false}),
        )
    }
    /// An exact offer acknowledgment is not a hearing or completion receipt.
    pub fn interaction_workflow_reported(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
        revision: &str,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let mut w = load_on(&tx, human, entry, id)?;
        if native != w.native || !live_on(&tx, &w)? {
            bail!("Workflow grant retired");
        }
        if w.reported.iter().any(|r| r.as_deref() == Some(revision)) {
            return Ok(());
        }
        let envelope = attention_on(&tx, &w)?
            .into_iter()
            .find(|e| e["revision"].as_str() == Some(revision))
            .context("Attention source changed or expired")?;
        let slot = envelope["slot"].as_u64().context("Missing offer slot")? as usize;
        w.reported[slot] = Some(revision.into());
        save_on(&tx, &w)?;
        tx.commit()?;
        Ok(())
    }
    pub fn interaction_workflow_finish(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
        revision: &str,
        checkpoint: &str,
    ) -> Result<Value> {
        if checkpoint.trim().is_empty() || checkpoint.len() > 2000 {
            bail!("Integration checkpoint required");
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let mut w = load_on(&tx, human, entry, id)?;
        if native != w.native || owner_on(&tx, human, entry)?.1 != native {
            bail!("Workflow entry binding changed");
        }
        if w.phase == "completed" {
            if w.final_checkpoint.as_deref() != Some(checkpoint) {
                bail!("Final integration checkpoint is immutable");
            }
            return view_on(&tx, &w);
        }
        if !live_on(&tx, &w)? {
            bail!("Workflow grant retired");
        }
        let view = view_on(&tx, &w)?;
        if view["revision"].as_str() != Some(revision) || view["phase"] != "awaiting_integration" {
            bail!("Required workflow steps remain unfinished or changed");
        }
        w.phase = "completed".into();
        w.final_checkpoint = Some(checkpoint.into());
        save_on(&tx, &w)?;
        let view = view_on(&tx, &w)?;
        tx.commit()?;
        Ok(view)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_workflow_supersede(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        channel: &str,
        id: &str,
        revision: &str,
        input_ref: InputReference,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let mut w = load_on(&tx, human, entry, id)?;
        if native != w.native || owner_on(&tx, human, entry)?.1 != native {
            bail!("Entry binding changed");
        }
        if w.phase == "superseded"
            && w.supersession
                .as_ref()
                .is_some_and(|s| s["input_ref"] == json!(input_ref))
        {
            return view_on(&tx, &w);
        }
        if w.phase != "active" || view_on(&tx, &w)?["revision"].as_str() != Some(revision) {
            bail!("Workflow changed before supersession");
        }
        if input_ref == w.plan.input_ref {
            bail!("Supersession requires a later human original");
        }
        let (source, _) =
            super::dialogue::original_on(&tx, entry, human, native, &input_ref, channel, false)?;
        let old_order = super::dialogue::original_order_on(&tx, &w.source)?;
        let new_order = super::dialogue::original_order_on(&tx, &source)?;
        if old_order.zip(new_order).is_none_or(|(a, b)| b <= a) {
            bail!("Supersession requires observed later human input");
        }
        w.phase = "superseded".into();
        w.supersession = Some(
            json!({"input_ref":input_ref,"source_revision":digest(&source)?,"source_channel":source.channel,"source_event":source.event_id}),
        );
        save_on(&tx, &w)?;
        // Only queued, definitely unsent inputs are held. Native accepted and
        // uncertain operations remain untouched and visible in the same journal.
        tx.execute("UPDATE interaction_instructions SET phase='retained_unsent' WHERE phase='queued' AND input_id IN (SELECT input_id FROM interaction_session_authors WHERE json_extract(doc,'$.workflow')=?1)",[id])?;
        let view = view_on(&tx, &w)?;
        tx.commit()?;
        Ok(view)
    }

    pub fn interaction_workflow_question(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
        revision: &str,
        offset: usize,
    ) -> Result<Value> {
        if offset > 1_000_000 {
            bail!("Question offset outside bound");
        }
        let conn = self.conn.lock().expect("store mutex poisoned");
        if owner_on(&conn, human, entry)?.1 != native {
            bail!("Entry binding changed");
        }
        let mut q=conn.prepare("SELECT doc FROM interaction_workflows WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND phase='active' AND julianday(json_extract(doc,'$.plan.expires_at'))>julianday('now') ORDER BY rowid DESC LIMIT 16")?;
        let mut selected = None;
        for raw in q.query_map(params![human, entry.chat_id, entry.thread_id], |r| {
            r.get::<_, String>(0)
        })? {
            let mut w: Workflow = serde_json::from_str(&raw?)?;
            w.reported.fill(None);
            for envelope in attention_on(&conn, &w)? {
                if envelope["source"]["kind"] == "native_question"
                    && envelope["source"]["id"] == id
                    && envelope["source"]["revision"] == revision
                {
                    selected = Some(envelope["source"].clone());
                }
            }
        }
        let source =
            selected.context("Question version expired, reported or outside selected workflow")?;
        let question = super::conversation_requests::read_scoped_on(&conn, human, entry, id, true)?;
        if question.item.state != "pending" || question.capture_version != revision {
            bail!("Question version changed");
        }
        let index = question.item.source["conversationIndex"]
            .as_u64()
            .unwrap_or(0) as usize;
        let text = serde_json::to_string(&question.item.source["request"]["questions"][index])?;
        let length = text.chars().count();
        if offset > length {
            bail!("Question offset beyond source");
        }
        let text: String = text.chars().skip(offset).take(4000).collect();
        let end = offset + text.chars().count();
        Ok(
            json!({"schema":"telecodex.workflow-question-part/v1","source":source,"text":text,"offset":offset,"next_offset":if end<length{Some(end)}else{None},"answer_allowed":false,"meaning":"Current native question evidence. Use the existing human-selected question controls; this operation cannot answer or approve."}),
        )
    }

    /// Inspect predecessor source text on demand; helper content stays internal.
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_workflow_result(
        &self,
        human: i64,
        actor: SessionKey,
        native: &str,
        id: &str,
        step: &str,
        revision: &str,
        offset: usize,
    ) -> Result<Value> {
        if offset > 1_000_000 {
            bail!("Result offset outside bound");
        }
        let conn = self.conn.lock().expect("store mutex poisoned");
        if owner_on(&conn, human, actor)?.1 != native {
            bail!("Actor binding changed");
        }
        let raw: String = conn.query_row(
            "SELECT doc FROM interaction_workflows WHERE id=?1 AND human_id=?2",
            params![id, human],
            |r| r.get(0),
        )?;
        let w: Workflow = serde_json::from_str(&raw)?;
        let eligible = |index: usize| {
            actor == w.entry
                || w.plan
                    .steps
                    .get(index + 1)
                    .is_some_and(|s| s.owner == actor && w.admissions[index + 1].is_some())
        };
        let index = if let Some(index) = w.plan.steps.iter().position(|s| s.id == step) {
            index
        } else {
            // Older handoffs exposed only the canonical result ID. Resolve that
            // exact ID/revision inside already-authorized dependencies; never
            // search unrelated results or expand the worker's reader scope.
            let mut selected = None;
            for index in 0..w.plan.steps.len() {
                if eligible(index)
                    && let Some((source, _)) = result_on(&conn, &w, index)?
                    && source["id"].as_str() == Some(step)
                    && source["revision"].as_str() == Some(revision)
                {
                    anyhow::ensure!(selected.is_none(), "Ambiguous canonical result dependency");
                    selected = Some(index);
                }
            }
            selected.context("Unknown workflow step or canonical result dependency")?
        };
        if !eligible(index) {
            bail!("Result outside this step's selected dependency");
        }
        let (source, d) = result_on(&conn, &w, index)?.context("Canonical result unavailable")?;
        if source["revision"].as_str() != Some(revision) || !completed(&source) {
            bail!("Canonical result changed or incomplete");
        }
        let length = d.body.chars().count();
        if offset > length {
            bail!("Result offset beyond source");
        }
        let text: String = d.body.chars().skip(offset).take(4000).collect();
        let end = offset + text.chars().count();
        Ok(
            json!({"schema":"telecodex.workflow-result-part/v1","source":source,"covered":d.covered,"text":text,"offset":offset,"next_offset":if end<length{Some(end)}else{None},"internal_evidence":true,"publication_grant":false}),
        )
    }
}

pub(super) fn input_allowed_on(conn: &Connection, author: &Value, i: &Instruction) -> Result<bool> {
    let id = author["workflow"]
        .as_str()
        .context("Missing workflow provenance")?;
    let raw: String = conn.query_row(
        "SELECT doc FROM interaction_workflows WHERE id=?1 AND human_id=?2",
        params![id, i.human_id],
        |r| r.get(0),
    )?;
    let w: Workflow = serde_json::from_str(&raw)?;
    if !live_on(conn, &w)? {
        return Ok(false);
    }
    let view = view_on(conn, &w)?;
    Ok(w.admissions.iter().enumerate().any(|(index, a)| {
        a.as_ref().is_some_and(|a| a.instruction == i.id)
            && !matches!(
                view["steps"][index]["phase"].as_str(),
                Some("predecessor_changed" | "correction_pending" | "withdrawn")
            )
    }))
}
pub(super) fn withdraw_on(conn: &Connection, caller: SessionKey) -> Result<()> {
    conn.execute("UPDATE interaction_workflows SET phase='withdrawn',doc=json_set(doc,'$.phase','withdrawn') WHERE entry_chat=?1 AND entry_topic=?2 AND phase='active'",params![caller.chat_id,caller.thread_id])?;
    Ok(())
}

// Share the existing original-selection exclusion with dispatch/creation/Matrix.
pub(super) fn unclaimed_on(
    conn: &Connection,
    human: i64,
    channel: &str,
    event: &str,
    update: Option<i64>,
) -> Result<()> {
    let held:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM interaction_workflows WHERE human_id=?1 AND (json_extract(doc,'$.source.update_id')=?4 OR (json_extract(doc,'$.source.channel')=?2 AND json_extract(doc,'$.source.event_id')=?3)))",params![human,channel,event,update],|r|r.get(0))?;
    if held {
        let id: String = conn.query_row("SELECT id FROM interaction_workflows WHERE human_id=?1 AND (json_extract(doc,'$.source.update_id')=?4 OR (json_extract(doc,'$.source.channel')=?2 AND json_extract(doc,'$.source.event_id')=?3)) ORDER BY rowid LIMIT 1",params![human,channel,event,update], |r| r.get(0))?;
        return Err(refusal("workflow_selected", Some(id)));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::interaction::{ReturnRoute, TransportPhase as P};
    use crate::store::ConversationInputEvent as E;
    use tokio_util::sync::CancellationToken;

    fn session(s: &Store, topic: i64) -> SessionRecord {
        let key = SessionKey::new(100, Some(topic));
        s.ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(key, &format!("native-{topic}"))
            .unwrap();
        s.get_session(key).unwrap().unwrap()
    }
    fn turn(s: &Store, session: &SessionRecord, text: &str) -> i64 {
        let local = s
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: session.key,
                    from_user_id: 100,
                    prompt: text.into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        s.record_turn_native_thread(local, session.codex_thread_id.as_deref().unwrap())
            .unwrap();
        local
    }
    fn original(s: &Store, entry: &SessionRecord, text: &str) -> InputReference {
        let id = Uuid::now_v7().to_string();
        let binding = s.conversation_request_binding(100, entry.key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        s.conversation_input_capture(100, entry.key, &binding, &id, text)
            .unwrap();
        s.conversation_input_event(100, &id, E::Queue).unwrap();
        let local = turn(s, entry, text);
        s.conversation_input_event(
            100,
            &id,
            E::Begin {
                local_turn: local,
                steer: false,
            },
        )
        .unwrap();
        s.conversation_input_event(100, &id, E::Accepted { local_turn: local })
            .unwrap();
        InputReference::Conversation(id)
    }
    fn setup() -> (tempfile::NamedTempFile, Store, SessionRecord, WorkflowPlan) {
        let f = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(f.path(), &[100], &super::super::tests::defaults()).unwrap();
        let entry = session(&s, 1);
        let a = session(&s, 7);
        let b = session(&s, 8);
        let plan = WorkflowPlan {
            parent_instruction: None,
            request_id: "selected-work".into(),
            input_ref: original(
                &s,
                &entry,
                "A produces a checkpoint, B consumes it; return here after verification and report the first checkpoint.",
            ),
            expires_at: (Utc::now() + Duration::hours(2)).to_rfc3339(),
            steps: vec![
                WorkflowStep {
                    id: "produce".into(),
                    owner: a.key,
                    after: None,
                    scope: "Produce the selected checkpoint".into(),
                    checkpoint: "Current canonical checkpoint".into(),
                    milestone: Some("Checkpoint ready".into()),
                },
                WorkflowStep {
                    id: "consume".into(),
                    owner: b.key,
                    after: Some("produce".into()),
                    scope: "Consume the exact first checkpoint and verify the selected outcome"
                        .into(),
                    checkpoint: "Receiving verification".into(),
                    milestone: None,
                },
            ],
        };
        super::heartbeat::enable_test_lanes(&s, 100, entry.key);
        (f, s, entry, plan)
    }
    fn declare(s: &Store, e: &SessionRecord, p: WorkflowPlan) -> Value {
        s.interaction_workflow_declare(
            100,
            e.key,
            "native-1",
            "conversation",
            p,
            &CancellationToken::new(),
        )
        .unwrap()
    }
    fn status(s: &Store, e: &SessionRecord, id: &str) -> Value {
        s.interaction_workflow_status(100, e.key, "native-1", id)
            .unwrap()
    }
    fn advance(s: &Store, e: &SessionRecord, v: &Value) -> Option<Instruction> {
        s.interaction_workflow_advance(
            100,
            e.key,
            "native-1",
            v["id"].as_str().unwrap(),
            v["revision"].as_str().unwrap(),
            &CancellationToken::new(),
        )
        .unwrap()
    }
    fn accept(s: &Store, i: &Instruction) -> i64 {
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.interaction_transport(
            &i.id,
            100,
            local,
            P::Accepted,
            Some(&format!("turn-{local}")),
        )
        .unwrap();
        local
    }
    fn answer(
        s: &Store,
        i: &Instruction,
        local: i64,
        item: &str,
        covered: Vec<String>,
        body: &str,
    ) -> Delivery {
        let text = format!(
            "{body}\n<daimon-result>{}</daimon-result>",
            json!({"requests":i.requests,"covered":covered,"completed":i.requests})
        );
        s.interaction_record_result(
            &i.id,
            100,
            local,
            i.native_thread.as_deref().unwrap(),
            &format!("turn-{local}"),
            item,
            &text,
            true,
        )
        .unwrap()
        .remove(0)
    }
    fn routed_result(
        s: &Store,
        entry: &SessionRecord,
        reference: &InputReference,
    ) -> (Instruction, Delivery) {
        let (mut source, _) = s
            .interaction_entry_original(entry.key, 100, "native-1", reference, "conversation")
            .unwrap();
        source.target_sessions = vec![
            s.get_session(SessionKey::new(100, Some(7)))
                .unwrap()
                .unwrap()
                .id,
        ];
        let (instruction, _) = s
            .interaction_admit(&source, SessionKey::new(100, Some(7)), RequestRelation::New)
            .unwrap();
        let local = accept(s, &instruction);
        let instruction = s
            .interaction_instruction(&instruction.id, 100)
            .unwrap()
            .unwrap();
        let delivery = answer(
            s,
            &instruction,
            local,
            "ordinary-source",
            vec![instruction.id.clone()],
            &"Result α\n".repeat(400),
        );
        (instruction, delivery)
    }
    fn selected_primary(s: &Store, e: &SessionRecord, reference: &InputReference) -> Instruction {
        let (mut source, _) = s
            .interaction_entry_original(e.key, 100, "native-1", reference, "conversation")
            .unwrap();
        let target = s
            .get_session(SessionKey::new(100, Some(7)))
            .unwrap()
            .unwrap();
        source.target_sessions = vec![target.id];
        let (primary, _) = s
            .interaction_admit(&source, target.key, RequestRelation::New)
            .unwrap();
        s.interaction_bind_epoch(&primary.id, 100, "initial")
            .unwrap();
        accept(s, &primary);
        s.interaction_instruction(&primary.id, 100)
            .unwrap()
            .unwrap()
    }
    #[test]
    fn selected_human_primary_can_link_an_additional_workflow_without_replay_or_transfer() {
        let (_f, s, e, mut plan) = setup();
        let primary = selected_primary(&s, &e, &plan.input_ref);
        plan.request_id = "additional-evidence-check".into();
        plan.steps.truncate(1);
        plan.steps[0].owner = SessionKey::new(100, Some(8));
        plan.steps[0].scope =
            "Check the additional selected peer evidence; keep primary implementation ownership."
                .into();
        let before = serde_json::to_value(
            s.interaction_instruction(&primary.id, 100)
                .unwrap()
                .unwrap(),
        )
        .unwrap();
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                plan.clone(),
                &CancellationToken::new()
            )
            .is_err()
        );
        plan.parent_instruction = Some(Uuid::now_v7().to_string());
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                plan.clone(),
                &CancellationToken::new()
            )
            .is_err()
        );
        plan.parent_instruction = Some(primary.id.clone());
        let view = declare(&s, &e, plan.clone());
        assert_eq!(view["primary_routing"]["instruction"], primary.id);
        assert_eq!(
            view["primary_routing"]["target"],
            serde_json::to_value(primary.target).unwrap()
        );
        assert_eq!(declare(&s, &e, plan.clone())["id"], view["id"]);
        let mut changed = plan;
        changed.steps[0].scope.push_str(" changed");
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                changed,
                &CancellationToken::new()
            )
            .is_err()
        );
        let child = advance(&s, &e, &view).unwrap();
        assert!(
            child
                .text
                .contains("whose owner and original request coverage remain unchanged")
        );
        assert!(
            child
                .requests
                .iter()
                .all(|id| !primary.requests.contains(id))
        );
        accept(&s, &child);
        assert_eq!(
            s.interaction_author(&child.id, 100).unwrap().unwrap()["primary_routing"]["instruction"],
            primary.id
        );
        assert_eq!(
            serde_json::to_value(
                s.interaction_instruction(&primary.id, 100)
                    .unwrap()
                    .unwrap()
            )
            .unwrap(),
            before
        );
        s.interaction_withdraw_session_requests(primary.target)
            .unwrap();
        assert!(!s.interaction_session_input_allowed(&child.id, 100).unwrap());
        assert_eq!(
            status(&s, &e, view["id"].as_str().unwrap())["phase"],
            "retired"
        );
        assert_eq!(
            s.interaction_instruction(&child.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::Accepted
        );
        assert_eq!(
            serde_json::to_value(
                s.interaction_instruction(&primary.id, 100)
                    .unwrap()
                    .unwrap()
            )
            .unwrap(),
            before
        );
    }
    #[test]
    fn linked_primary_rejects_another_original_session_authorship_and_rebound_owner() {
        let (_f, s, e, mut plan) = setup();
        let primary = selected_primary(&s, &e, &plan.input_ref);
        let different = original(&s, &e, "A different actual human original.");
        plan.parent_instruction = Some(primary.id.clone());
        plan.input_ref = different;
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                plan.clone(),
                &CancellationToken::new()
            )
            .is_err()
        );
        let (_f, s, e, mut plan) = setup();
        let primary = selected_primary(&s, &e, &plan.input_ref);
        plan.parent_instruction = Some(primary.id.clone());
        let view = declare(&s, &e, plan);
        s.set_session_codex_thread(primary.target, "replacement-native")
            .unwrap();
        s.set_session_codex_thread(primary.target, "native-7")
            .unwrap();
        assert_eq!(
            status(&s, &e, view["id"].as_str().unwrap())["phase"],
            "retired"
        );
        let (_f, s, e, mut plan) = setup();
        let primary = selected_primary(&s, &e, &plan.input_ref);
        s.conn
            .lock()
            .unwrap()
            .execute(
                "INSERT INTO interaction_session_authors(input_id,doc) VALUES(?1,?2)",
                params![
                    primary.input_id,
                    json!({"kind":"session_request","authorized_human":100}).to_string()
                ],
            )
            .unwrap();
        plan.parent_instruction = Some(primary.id);
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                plan,
                &CancellationToken::new()
            )
            .is_err()
        );
    }
    #[test]
    fn heartbeat_generation_fences_native_admission_without_erasing_history_or_ack() {
        let (_file, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        // The existing ordinary policy is independent of the default-paused gate.
        s.workflow_native_validate(&selected.id).unwrap();
        s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        {
            // Test-owned server receipt, not a new public tagging or funding API.
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.returns[0].attention_generation',2,'$.returns[0].attention_activation',json('{\"lane\":\"messaging\",\"generation\":1}')) WHERE id=?1",[&delivery.id]).unwrap();
        }
        let local = turn(&s, &entry, "");
        assert!(s.workflow_native_link(&selected.id, local).is_err());
        assert!(s.workflow_native_submitting(&selected.id).is_err());
        assert!(s.workflow_native_validate(&selected.id).is_err());
        s.heartbeat_control(
            100,
            entry.key,
            crate::store::HeartbeatCommand::ConfigureResources {
                generation: 1,
                contract: crate::store::heartbeat::test_contract(),
            },
        )
        .unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            crate::store::HeartbeatCommand::Resume { generation: 1 },
        )
        .unwrap();
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_validate(&selected.id).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        assert!(s.workflow_native_validate(&selected.id).is_err());
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        let revision = packet["evidence"]["revision"].as_str().unwrap();
        s.native_routed_source(100, entry.key, "native-1", &selected.id, revision, 0)
            .unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            crate::store::HeartbeatCommand::Resume { generation: 3 },
        )
        .unwrap();
        // Resume permits only a new generation; a previously submitting intent
        // never becomes eligible or known-unsent solely because pause occurred.
        assert!(s.workflow_native_validate(&selected.id).is_err());
        s.workflow_native_outcome(&selected.id, "accepted", Some("exact-late-physical"))
            .unwrap();
        let conn = s.conn.lock().unwrap();
        let raw: String = conn
            .query_row(
                "SELECT native_return FROM interaction_deliveries WHERE id=?1",
                [&delivery.id],
                |r| r.get(0),
            )
            .unwrap();
        let retained: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(retained["returns"][0]["phase"], "accepted");
        assert_eq!(retained["returns"][0]["native_turn"], "exact-late-physical");
        assert_eq!(retained["returns"][0]["attention_generation"], 2);
    }

    #[test]
    fn ordinary_routed_result_returns_exact_source_without_declaring_workflow() {
        let (_f, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        assert_eq!(selected.name, "conversation_attention");
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        assert_eq!(packet["schema"], "telecodex.native-attention/v1");
        assert_eq!(packet["original_input_ref"], json!(plan.input_ref));
        assert!(packet.get("workflow").is_none());
        assert!(packet["evidence"]["source"].get("text").is_none());
        assert_eq!(packet["source_text_complete"], false);
        let revision = packet["evidence"]["revision"].as_str().unwrap();
        let part = s
            .native_routed_source(100, entry.key, "native-1", &selected.id, revision, 0)
            .unwrap();
        assert_eq!(part["text"].as_str().unwrap().chars().count(), 1600);
        assert_eq!(part["next_offset"], 1600);
        assert!(
            s.native_routed_source(100, entry.key, "wrong-native", &selected.id, revision, 0)
                .is_err()
        );
        assert!(
            s.native_routed_source(
                100,
                entry.key,
                "native-1",
                &selected.id,
                "wrong-revision",
                0
            )
            .is_err()
        );
        assert!(
            s.native_routed_result_reserve(100, entry.key, &delivery.id)
                .unwrap()
                .is_none()
        );
        s.native_routed_reported(100, entry.key, "native-1", &selected.id, revision)
            .unwrap();
        assert!(s.workflow_native_dispatch(&selected.id).is_err());
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_workflows", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_sources", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            1
        );
    }
    #[test]
    fn heartbeat_pause_preserves_exact_canonical_report_and_source_reader_scope() {
        let (_file, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        {
            // Only the server-owned fixture marks this retained source; peer
            // text and requesting models cannot mint an attention generation.
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.returns[0].attention_generation',2,'$.returns[0].attention_activation',json('{\"lane\":\"messaging\",\"generation\":1}')) WHERE id=?1", [&delivery.id]).unwrap();
        }
        s.heartbeat_control(
            100,
            entry.key,
            crate::store::HeartbeatCommand::ConfigureResources {
                generation: 1,
                contract: crate::store::heartbeat::test_contract(),
            },
        )
        .unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            crate::store::HeartbeatCommand::Resume { generation: 1 },
        )
        .unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        assert!(
            !s.heartbeat_native_started(local, "heartbeat-report-physical")
                .unwrap()
        );
        s.workflow_native_outcome_attempt(
            &selected.id,
            1,
            "accepted",
            Some("heartbeat-report-physical"),
        )
        .unwrap();
        s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        s.heartbeat_executions(100, entry.key, true).unwrap();
        assert!(s.workflow_native_validate(&selected.id).is_err());
        let report = "The selected result was reviewed; further heartbeat work is paused.";
        assert!(
            s.record_native_message(
                local,
                "native-1",
                "heartbeat-report-physical",
                "paused-report",
                Some("commentary"),
                report
            )
            .unwrap()
        );
        s.heartbeat_native_terminal(local, "heartbeat-report-physical", "interrupted")
            .unwrap();
        assert!(
            !s.record_native_message(
                local,
                "native-1",
                "heartbeat-report-physical",
                "paused-report",
                Some("commentary"),
                report
            )
            .unwrap()
        );
        let list = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        let reports: Vec<_> = list["items"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|v| v["preview"] == report)
            .collect();
        assert_eq!(
            reports.len(),
            1,
            "Exact native item is presented once across pause/terminal observation"
        );
        assert_eq!(reports[0]["kind"], "integrator_progress");
        assert_eq!(reports[0]["native_returns"], json!([selected.id]));
        assert_eq!(
            reports[0]["current"], true,
            "Pause fences new inference, not retained human-authorized reports"
        );
        assert!(
            s.interaction_presentation_list(101, entry.key, 0, 0)
                .is_err()
        );
        // Existing canonical source retirement remains separate: an old report
        // stays in history but cannot become a fresh voice offer after expiry.
        let conn = s.conn.lock().unwrap();
        conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.expires_at','2000-01-01T00:00:00Z') WHERE id=?1",[&delivery.id]).unwrap();
        drop(conn);
        let list = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        let item = list["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["preview"] == report)
            .unwrap();
        assert_eq!(item["current"], false);
    }

    #[test]
    fn ordinary_return_reuses_exact_attempt_and_source_publication_fences() {
        let (_f, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.workflow_native_outcome_attempt(
            &selected.id,
            1,
            "accepted",
            Some("ordinary-attention-physical"),
        )
        .unwrap();
        s.record_native_message(
            local,
            "native-1",
            "ordinary-attention-physical",
            "offer",
            Some("final_answer"),
            "The result is ready; shall we review it?",
        )
        .unwrap();
        let list = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        let item = list["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["preview"] == "The result is ready; shall we review it?")
            .unwrap();
        assert_eq!(item["native_returns"], json!([selected.id]));
        assert!(item.get("workflow_returns").is_none());
        assert_eq!(item["current"], true);
        assert!(
            s.native_returns_recover_unsent(100, entry.key, false, true)
                .unwrap()
                .is_empty()
        );
        // Expiry invalidates callback publication without inventing another input.
        let conn = s.conn.lock().unwrap();
        conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.expires_at','2000-01-01T00:00:00Z') WHERE id=?1", [&delivery.id]).unwrap();
        drop(conn);
        assert!(s.workflow_native_dispatch(&selected.id).is_err());
        let list = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        let item = list["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["preview"] == "The result is ready; shall we review it?")
            .unwrap();
        assert_eq!(item["current"], false);
    }
    #[test]
    fn ordinary_question_return_reads_exact_question_and_never_answers_it() {
        let (_f, s, entry, plan) = setup();
        let (mut source, _) = s
            .interaction_entry_original(entry.key, 100, "native-1", &plan.input_ref, "conversation")
            .unwrap();
        source.target_sessions = vec![
            s.get_session(SessionKey::new(100, Some(7)))
                .unwrap()
                .unwrap()
                .id,
        ];
        let (instruction, _) = s
            .interaction_admit(&source, SessionKey::new(100, Some(7)), RequestRelation::New)
            .unwrap();
        let local = accept(&s, &instruction);
        let question = HumanInteraction {
            id: "c".repeat(32),
            kind: "native".into(),
            state: "pending".into(),
            requester: 100,
            native_thread: "native-7".into(),
            local_turn: local,
            title: "Receiving choice".into(),
            action: "Answer".into(),
            blocking: true,
            source: json!({"kind":"question","conversationIndex":0,"request":{"questions":[{"id":"choice","question":"Which receiving target?","options":[]}]}}),
        };
        s.save_interaction(instruction.target, &question, Some("ordinary-question"))
            .unwrap();
        let selected = s
            .native_routed_questions_reserve(100, entry.key, local)
            .unwrap()
            .remove(0);
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        assert_eq!(packet["source_text_complete"], false);
        let revision = packet["evidence"]["revision"].as_str().unwrap();
        let part = s
            .native_routed_source(100, entry.key, "native-1", &selected.id, revision, 0)
            .unwrap();
        assert!(
            part["text"]
                .as_str()
                .unwrap()
                .contains("Which receiving target?")
        );
        assert_eq!(part["answer_allowed"], false);
        s.native_routed_reported(100, entry.key, "native-1", &selected.id, revision)
            .unwrap();
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row(
                "SELECT state FROM human_interactions WHERE id=?1",
                [&question.id],
                |r| r.get::<_, String>(0)
            )
            .unwrap(),
            "pending"
        );
        drop(conn);
        assert!(
            s.native_routed_questions_reserve(100, entry.key, local)
                .unwrap()
                .is_empty()
        );
        s.transition_interaction(instruction.target, 100, &question.id, "pending", "expired")
            .unwrap();
        assert!(
            s.native_routed_source(100, entry.key, "native-1", &selected.id, revision, 0)
                .is_err()
        );
        let direct = session(&s, 8);
        let direct_local = turn(&s, &direct, "Direct topic work");
        let mut direct_question = question.clone();
        direct_question.id = "d".repeat(32);
        direct_question.native_thread = "native-8".into();
        direct_question.local_turn = direct_local;
        s.save_interaction(direct.key, &direct_question, Some("direct-only-question"))
            .unwrap();
        assert!(
            s.native_routed_questions_reserve(100, entry.key, direct_local)
                .unwrap()
                .is_empty()
        );
    }
    #[test]
    fn ordinary_return_restart_preserves_unsent_uncertainty_and_finite_retry() {
        let (file, s, entry, plan) = setup();
        let (instruction, first) = routed_result(&s, &entry, &plan.input_ref);
        let unsent = s
            .native_routed_result_reserve(100, entry.key, &first.id)
            .unwrap()
            .unwrap();
        let second = answer(
            &s,
            &instruction,
            instruction.local_turn.unwrap(),
            "second-ordinary-source",
            vec![instruction.id.clone()],
            "Another exact result",
        );
        let unknown = s
            .native_routed_result_reserve(100, entry.key, &second.id)
            .unwrap()
            .unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link(&unknown.id, local).unwrap();
        s.workflow_native_submitting(&unknown.id).unwrap();
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let conn = s.conn.lock().unwrap();
        let unknown_doc: String = conn
            .query_row(
                "SELECT native_return FROM interaction_deliveries WHERE id=?1",
                [&second.id],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&unknown_doc).unwrap()["returns"][0]["phase"],
            "uncertain"
        );
        conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.returns[0].retry_after',?2) WHERE id=?1", params![first.id,Utc::now().timestamp()-1]).unwrap();
        drop(conn);
        assert!(
            s.native_returns_recover_unsent(100, entry.key, false, false)
                .unwrap()
                .is_empty()
        );
        let retry = s
            .native_returns_recover_unsent(100, entry.key, false, true)
            .unwrap()
            .remove(0);
        assert_eq!(retry.id, unsent.id);
        assert_eq!(retry.attempts, 2);
        assert_eq!(
            serde_json::from_str::<Value>(&retry.output).unwrap()["evidence"],
            serde_json::from_str::<Value>(&unsent.output).unwrap()["evidence"]
        );
        s.workflow_native_outcome_attempt(&retry.id, 1, "accepted", Some("stale-attempt"))
            .unwrap();
        assert_eq!(s.workflow_native_dispatch(&retry.id).unwrap().attempts, 2);
        assert!(s.workflow_native_dispatch(&unknown.id).is_err());
        s.workflow_native_outcome_attempt(&retry.id, 2, "retained_unsent", None)
            .unwrap();
        let conn = s.conn.lock().unwrap();
        conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.returns[0].retry_after',?2) WHERE id=?1", params![first.id,Utc::now().timestamp()-1]).unwrap();
        drop(conn);
        let last = s
            .native_returns_recover_unsent(100, entry.key, false, true)
            .unwrap()
            .remove(0);
        assert_eq!(last.id, unsent.id);
        assert_eq!(last.attempts, 3);
        s.workflow_native_outcome_attempt(&last.id, 3, "retained_unsent", None)
            .unwrap();
        assert!(
            s.native_returns_recover_unsent(100, entry.key, false, true)
                .unwrap()
                .is_empty()
        );
        assert!(s.workflow_native_dispatch(&unknown.id).is_err());
    }
    #[test]
    fn ordinary_return_correction_retires_old_source_without_replaying_work() {
        let (_file, s, entry, plan) = setup();
        let (instruction, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        let correction = original(
            &s,
            &entry,
            "Change the selected requirement before announcing the result.",
        );
        let (mut source, _) = s
            .interaction_entry_original(entry.key, 100, "native-1", &correction, "conversation")
            .unwrap();
        source.target_sessions = vec![instruction.target_session];
        let (amended, _) = s
            .interaction_admit(
                &source,
                instruction.target,
                RequestRelation::Amends(instruction.requests.clone()),
            )
            .unwrap();
        accept(&s, &amended);
        assert!(s.workflow_native_dispatch(&selected.id).is_err());
        assert!(
            s.native_routed_result_reserve(100, entry.key, &delivery.id)
                .unwrap()
                .is_none()
        );
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        assert!(
            s.native_routed_source(
                100,
                entry.key,
                "native-1",
                &selected.id,
                packet["evidence"]["revision"].as_str().unwrap(),
                0
            )
            .is_err()
        );
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_instructions", [], |r| r
                .get::<_, i64>(
                0
            ))
            .unwrap(),
            2
        );
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_workflows", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
    #[test]
    fn ordinary_callback_replacement_keeps_expired_source_fenced_and_human_input_usable() {
        let (file, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let returned = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        let old = turn(&s, &entry, "");
        s.workflow_native_link(&returned.id, old).unwrap();
        s.native_collection_submitting(old, None).unwrap();
        s.native_collection_started(old, "callback-physical")
            .unwrap();
        s.workflow_native_submitting(&returned.id).unwrap();
        s.workflow_native_outcome(&returned.id, "accepted", Some("callback-physical"))
            .unwrap();
        assert!(s.workflow_native_visible(old).unwrap());
        {
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.expires_at','2000-01-01T00:00:00Z') WHERE id=?1",[&delivery.id]).unwrap();
        }
        assert!(!s.workflow_native_visible(old).unwrap());
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let successor = turn(
            &s,
            &entry,
            "Owner-local collector attachment; no new native input.",
        );
        s.topic_direct_register(successor, 100, entry.key).unwrap();
        s.record_collector_attachment(successor, entry.key, 100, "native-1", "callback-physical")
            .unwrap();
        s.native_collection_started(successor, "callback-physical")
            .unwrap();
        s.record_native_message(
            successor,
            "native-1",
            "callback-physical",
            "late-expired-offer",
            Some("final_answer"),
            "Stale callback must stay internal after collector replacement.",
        )
        .unwrap();
        let page = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        assert!(
            !page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|i| i["native_item"] == "late-expired-offer"),
            "Replacing a collector must not erase the exact callback source fence"
        );
        // A real later human input in the same execution keeps ordinary rights.
        let binding = s.conversation_request_binding(100, entry.key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        let id = Uuid::now_v7().to_string();
        s.conversation_input_capture(
            100,
            entry.key,
            &binding,
            &id,
            "My later actual human question",
        )
        .unwrap();
        s.conversation_input_event(100, &id, E::Queue).unwrap();
        s.conversation_input_event(
            100,
            &id,
            E::Begin {
                local_turn: successor,
                steer: true,
            },
        )
        .unwrap();
        s.conversation_input_event(
            100,
            &id,
            E::Accepted {
                local_turn: successor,
            },
        )
        .unwrap();
        s.record_native_message(
            successor,
            "native-1",
            "callback-physical",
            "real-human-answer",
            Some("final_answer"),
            "The later actual human answer remains visible.",
        )
        .unwrap();
        let page = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        assert!(
            page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|i| i["native_item"] == "real-human-answer")
        );
    }
    fn replacement_collector(s: &Store, entry: &SessionRecord, physical: &str) -> i64 {
        let local = turn(
            s,
            entry,
            "Owner-local collector attachment; no new native input.",
        );
        s.topic_direct_register(local, 100, entry.key).unwrap();
        s.record_collector_attachment(local, entry.key, 100, "native-1", physical)
            .unwrap();
        s.native_collection_started(local, physical).unwrap();
        local
    }
    #[test]
    fn replacement_collector_retains_unknown_sibling_and_the_exact_source_set() {
        let (_file, s, entry, plan) = setup();
        let (instruction, first) = routed_result(&s, &entry, &plan.input_ref);
        let second = answer(
            &s,
            &instruction,
            instruction.local_turn.unwrap(),
            "another-source",
            vec![instruction.id.clone()],
            "Another current result",
        );
        let a = s
            .native_routed_result_reserve(100, entry.key, &first.id)
            .unwrap()
            .unwrap();
        let b = s
            .native_routed_result_reserve(100, entry.key, &second.id)
            .unwrap()
            .unwrap();
        let old = turn(&s, &entry, "");
        s.native_collection_started(old, "mixed-physical").unwrap();
        for id in [&a.id, &b.id] {
            s.workflow_native_link(id, old).unwrap();
            s.workflow_native_submitting(id).unwrap();
        }
        s.workflow_native_outcome(&a.id, "accepted", Some("mixed-physical"))
            .unwrap();
        s.workflow_native_outcome(&b.id, "uncertain", None).unwrap();
        let next = replacement_collector(&s, &entry, "mixed-physical");
        assert!(
            !s.workflow_native_visible(next).unwrap(),
            "An unknown sibling cannot borrow the accepted source's publication"
        );
        s.workflow_native_outcome(&b.id, "accepted", Some("mixed-physical"))
            .unwrap();
        s.record_native_message(
            next,
            "native-1",
            "mixed-physical",
            "recovered-offer",
            Some("final_answer"),
            "Both exact sources are now confirmed.",
        )
        .unwrap();
        let page = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        let item = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["native_item"] == "recovered-offer")
            .unwrap();
        let ids = item["native_returns"].as_array().unwrap();
        assert_eq!(ids.len(), 2);
        assert!(ids.contains(&json!(a.id)) && ids.contains(&json!(b.id)));
        assert!(
            !s.workflow_native_visible(old).unwrap(),
            "The earlier local cannot borrow the successor's grant"
        );
        let newer = replacement_collector(&s, &entry, "mixed-physical");
        assert!(s.workflow_native_visible(newer).unwrap());
        assert!(!s.workflow_native_visible(next).unwrap());
        let other = replacement_collector(&s, &entry, "different-physical");
        let conn = s.conn.lock().unwrap();
        assert!(
            !conn
                .query_row(
                    "SELECT EXISTS(SELECT 1 FROM bot_state WHERE key=?1)",
                    [format!("workflow_return_local:{other}")],
                    |r| r.get::<_, bool>(0)
                )
                .unwrap(),
            "Another physical turn cannot inherit these source bindings"
        );
    }
    #[test]
    fn replacement_collector_preserves_real_human_execution_publication() {
        let (_file, s, entry, plan) = setup();
        let (_, delivery) = routed_result(&s, &entry, &plan.input_ref);
        let selected = s
            .native_routed_result_reserve(100, entry.key, &delivery.id)
            .unwrap()
            .unwrap();
        let InputReference::Conversation(id) = &plan.input_ref else {
            unreachable!()
        };
        let old = {
            let conn = s.conn.lock().unwrap();
            conn.query_row(
                "SELECT local_turn FROM conversation_inputs WHERE id=?1",
                [id],
                |r| r.get::<_, i64>(0),
            )
            .unwrap()
        };
        s.native_collection_started(old, "human-physical").unwrap();
        s.workflow_native_link(&selected.id, old).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("human-physical"))
            .unwrap();
        {
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE interaction_deliveries SET native_return=json_set(native_return,'$.expires_at','2000-01-01T00:00:00Z') WHERE id=?1",[delivery.id]).unwrap();
        }
        let next = replacement_collector(&s, &entry, "human-physical");
        assert!(s.workflow_native_visible(next).unwrap());
        s.record_native_message(
            next,
            "native-1",
            "human-physical",
            "real-original-answer",
            Some("final_answer"),
            "The actual human execution keeps its publication.",
        )
        .unwrap();
        let page = s
            .interaction_presentation_list(100, entry.key, 0, 0)
            .unwrap();
        assert!(
            page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|i| i["native_item"] == "real-original-answer")
        );
    }
    #[test]
    fn declared_callback_replacement_cannot_publish_an_expired_workflow() {
        let (_file, s, entry, plan) = setup();
        let workflow = declare(&s, &entry, plan);
        let instruction = advance(&s, &entry, &workflow).unwrap();
        let worker = accept(&s, &instruction);
        answer(
            &s,
            &instruction,
            worker,
            "workflow-source",
            vec![instruction.id.clone()],
            "Declared evidence",
        );
        let selected = s.workflow_native_reserve(100, entry.key).unwrap().remove(0);
        let old = turn(&s, &entry, "");
        s.native_collection_started(old, "declared-physical")
            .unwrap();
        s.workflow_native_link(&selected.id, old).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("declared-physical"))
            .unwrap();
        {
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE interaction_workflows SET doc=json_set(doc,'$.plan.expires_at','2000-01-01T00:00:00Z') WHERE id=?1",[workflow["id"].as_str().unwrap()]).unwrap();
        }
        let next = replacement_collector(&s, &entry, "declared-physical");
        assert!(!s.workflow_native_visible(next).unwrap());
    }
    #[test]
    fn incremental_subtasks_preserve_legacy_plan_receipts_and_original_authority() {
        let (file, store, entry, mut first_plan) = setup();
        first_plan.steps.truncate(1);
        let first = declare(&store, &entry, first_plan.clone());
        // Reproduce a pre-change workflow identity before any admission.
        let legacy = "legacy-original-workflow";
        {
            let conn = store.conn.lock().unwrap();
            let mut w = load_on(&conn, 100, entry.key, first["id"].as_str().unwrap()).unwrap();
            w.id = legacy.into();
            conn.execute("UPDATE interaction_workflows SET id=?1,doc=?2,source_key='legacy-source' WHERE id=?3",params![legacy,document(&w).unwrap(),first["id"].as_str().unwrap()]).unwrap();
        }
        let legacy_view = declare(&store, &entry, first_plan.clone());
        assert_eq!(legacy_view["id"], legacy);
        let original_instruction = advance(&store, &entry, &legacy_view).unwrap();
        let worker = accept(&store, &original_instruction);
        let mut next = first_plan.clone();
        next.request_id = "additional-attributed-handoff".into();
        next.steps[0].id = "deliver-context".into();
        next.steps[0].owner = SessionKey::new(100, Some(8));
        next.steps[0].scope = "Session A reports its checkpoint; deliver this attributed context to B under the same human request".into();
        next.steps[0].checkpoint = "B incorporates the selected attributed evidence".into();
        // Additional work is not a mutation, retry or replay of the first plan.
        let added = declare(&store, &entry, next.clone());
        assert_ne!(added["id"], legacy);
        assert_eq!(declare(&store, &entry, next.clone()), added);
        let second_instruction = advance(&store, &entry, &added).unwrap();
        assert!(
            store
                .interaction_author(&second_instruction.id, 100)
                .unwrap()
                .is_some()
        );
        assert_eq!(second_instruction.target, SessionKey::new(100, Some(8)));
        assert!(
            advance(
                &store,
                &entry,
                &status(&store, &entry, added["id"].as_str().unwrap())
            )
            .is_none()
        );
        assert_eq!(
            store
                .interaction_instruction(&original_instruction.id, 100)
                .unwrap()
                .unwrap()
                .local_turn,
            Some(worker)
        );
        let mut conflict = next.clone();
        conflict.steps[0].scope = "Mutating the frozen selected work is refused".into();
        let error = store
            .interaction_workflow_declare(
                100,
                entry.key,
                "native-1",
                "conversation",
                conflict,
                &CancellationToken::new(),
            )
            .unwrap_err();
        assert_eq!(rejection(&error).unwrap()["code"], "workflow_plan_conflict");
        let mut duplicate = next.clone();
        duplicate.request_id = "not-a-retry-loophole".into();
        duplicate.steps[0].checkpoint = "Different reporting expectation is not new work".into();
        let error = store
            .interaction_workflow_declare(
                100,
                entry.key,
                "native-1",
                "conversation",
                duplicate,
                &CancellationToken::new(),
            )
            .unwrap_err();
        assert_eq!(
            rejection(&error).unwrap()["code"],
            "workflow_scope_already_selected"
        );
        let error = store
            .interaction_entry_original(entry.key, 100, "native-1", &next.input_ref, "conversation")
            .unwrap_err();
        assert_eq!(rejection(&error).unwrap()["code"], "workflow_selected");
        assert!(rejection(&anyhow!("private arbitrary diagnostic")).is_none());
        drop(store);
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(declare(&store, &entry, first_plan)["id"], legacy);
        assert_eq!(declare(&store, &entry, next.clone())["id"], added["id"]);
        assert_eq!(
            store
                .interaction_instruction(&original_instruction.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::Accepted
        );
        // A retired original cannot gain another plan by changing request_id.
        withdraw_on(&store.conn.lock().unwrap(), entry.key).unwrap();
        next.request_id = "after-withdrawal".into();
        next.steps[0].scope = "Different work still cannot revive retired authority".into();
        let error = store
            .interaction_workflow_declare(
                100,
                entry.key,
                "native-1",
                "conversation",
                next,
                &CancellationToken::new(),
            )
            .unwrap_err();
        assert_eq!(
            rejection(&error).unwrap()["code"],
            "workflow_original_retired"
        );
    }

    #[test]
    fn workflow_retains_ownership_exact_scope_milestones_and_final_integration() {
        let (_f, s, e, plan) = setup();
        let initial = declare(&s, &e, plan.clone());
        let id = initial["id"].as_str().unwrap();
        assert_eq!(declare(&s, &e, plan.clone()), initial);
        let mut changed = plan.clone();
        changed.steps[0].scope = "Different work".into();
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                changed,
                &CancellationToken::new()
            )
            .is_err()
        );
        // A selected workflow cannot also dispatch the whole original separately.
        assert!(
            s.interaction_entry_original(e.key, 100, "native-1", &plan.input_ref, "conversation")
                .is_err()
        );
        let first = advance(&s, &e, &initial).unwrap();
        assert!(s.interaction_session_input_allowed(&first.id, 100).unwrap());
        let author = s.interaction_author(&first.id, 100).unwrap().unwrap();
        assert_eq!(author["kind"], "workflow_step");
        assert_eq!(author["input_ref"], json!(plan.input_ref));
        assert!(
            s.interaction_workflow_advance(
                100,
                e.key,
                "native-1",
                id,
                initial["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .is_err()
        );
        assert!(advance(&s, &e, &status(&s, &e, id)).is_none());
        let local = accept(&s, &first);
        assert!(
            s.interaction_session_request(
                first.target,
                100,
                "native-7",
                &format!("turn-{local}"),
                &first.id,
                "recursive",
                plan.steps[1].owner,
                "Unplanned helper chain",
                &CancellationToken::new()
            )
            .is_err()
        );
        let d = answer(
            &s,
            &first,
            local,
            "first",
            vec![first.id.clone()],
            &"Canonical checkpoint α\n".repeat(250),
        );
        assert_eq!(d.internal, Some(true));
        let ready = status(&s, &e, id);
        assert_eq!(ready["steps"][0]["phase"], "completed");
        assert_eq!(ready["steps"][1]["phase"], "ready");
        assert_eq!(ready["phase"], "active");
        assert!(
            s.interaction_workflow_finish(
                100,
                e.key,
                "native-1",
                id,
                ready["revision"].as_str().unwrap(),
                "Too early"
            )
            .is_err()
        );
        let attention = s.interaction_workflow_attention(100, e.key).unwrap();
        assert_eq!(attention["envelopes"].as_array().unwrap().len(), 1);
        let event = &attention["envelopes"][0];
        assert_eq!(event["reason"], "reporting_milestone");
        assert!(event["source"]["text"].is_null());
        s.interaction_workflow_reported(
            100,
            e.key,
            "native-1",
            id,
            event["revision"].as_str().unwrap(),
        )
        .unwrap();
        let second = advance(&s, &e, &ready).unwrap();
        // Advancing another step cannot replay a previously reported milestone.
        assert!(
            s.interaction_workflow_attention(100, e.key).unwrap()["envelopes"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        let source = &ready["steps"][0]["result"];
        let part = s
            .interaction_workflow_result(
                100,
                second.target,
                "native-8",
                id,
                "produce",
                source["revision"].as_str().unwrap(),
                0,
            )
            .unwrap();
        assert_eq!(part["text"].as_str().unwrap().chars().count(), 4000);
        assert_eq!(part["next_offset"], 4000);
        assert!(
            s.interaction_workflow_result(
                100,
                first.target,
                "native-7",
                id,
                "produce",
                source["revision"].as_str().unwrap(),
                0
            )
            .is_err()
        );
        let local = accept(&s, &second);
        answer(
            &s,
            &second,
            local,
            "verified",
            vec![second.id.clone()],
            "Receiving verified",
        );
        let final_view = status(&s, &e, id);
        assert_eq!(final_view["phase"], "awaiting_integration");
        let final_event = s.interaction_workflow_attention(100, e.key).unwrap();
        assert_eq!(
            final_event["envelopes"][0]["reason"],
            "integration_required"
        );
        let done = s
            .interaction_workflow_finish(
                100,
                e.key,
                "native-1",
                id,
                final_view["revision"].as_str().unwrap(),
                "Integrated receiving verification",
            )
            .unwrap();
        assert_eq!(done["phase"], "completed");
        assert_eq!(
            s.interaction_workflow_finish(
                100,
                e.key,
                "native-1",
                id,
                final_view["revision"].as_str().unwrap(),
                "Integrated receiving verification"
            )
            .unwrap(),
            done
        );
        assert!(
            s.interaction_workflow_attention(100, e.key).unwrap()["envelopes"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM interaction_public_deliveries",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            0
        );
    }
    #[test]
    fn native_return_publication_uses_original_reporting_scope_and_preserves_history() {
        let (_f, s, e, plan) = setup();
        let initial = declare(&s, &e, plan);
        assert!(s.workflow_native_reserve(100, e.key).unwrap().is_empty());
        let first = advance(&s, &e, &initial).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "checkpoint",
            vec![first.id.clone()],
            "Selected reporting checkpoint",
        );
        let before = status(&s, &e, initial["id"].as_str().unwrap());
        let selected = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        assert!(selected.output.contains("Attributed internal"));
        let reserved_attention = s.interaction_workflow_attention(100, e.key).unwrap();
        let reserved_event = &reserved_attention["envelopes"][0];
        assert_eq!(reserved_event["native_return"]["id"], selected.id);
        assert_eq!(reserved_event["native_return"]["phase"], "reserved");
        let source_revision = reserved_event["revision"].clone();
        assert_eq!(
            status(&s, &e, initial["id"].as_str().unwrap())["revision"],
            before["revision"]
        );
        assert!(s.workflow_native_reserve(100, e.key).unwrap().is_empty());
        let local = turn(&s, &e, "");
        s.workflow_native_link(&selected.id, local).unwrap();
        s.native_collection_submitting(local, None).unwrap();
        s.native_collection_started(local, "return-turn").unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        assert!(!s.workflow_native_visible(local).unwrap());
        s.workflow_native_outcome(&selected.id, "accepted", Some("return-turn"))
            .unwrap();
        s.workflow_native_outcome(&selected.id, "uncertain", None)
            .unwrap();
        let accepted_attention = s.interaction_workflow_attention(100, e.key).unwrap();
        let accepted_event = &accepted_attention["envelopes"][0];
        assert_eq!(accepted_event["native_return"]["phase"], "accepted");
        assert_eq!(
            accepted_event["native_return"]["native_turn"],
            "return-turn"
        );
        assert_eq!(accepted_event["revision"], source_revision);
        assert!(s.workflow_native_visible(local).unwrap());
        assert!(s.conversation_turn_return(local).unwrap());
        assert!(
            s.start_response_draft(100, e.key, local, "native-1", "return-turn")
                .unwrap()
        );
        assert!(
            s.interaction_response_draft(
                100,
                e.key,
                local,
                "native-1",
                "return-turn",
                "draft",
                "",
                true,
                false
            )
            .unwrap()
        );
        assert!(
            s.interaction_response_draft(
                100,
                e.key,
                local,
                "native-1",
                "return-turn",
                "draft",
                "Selected milestone. More current draft text",
                false,
                false
            )
            .unwrap()
        );
        let prefix = "Selected milestone. ";
        let live = format!(
            "live:return-turn:draft:0:{}:{:x}",
            prefix.chars().count(),
            Sha256::digest(prefix.as_bytes())
        );
        let binding = s.interaction_presentation_list(100, e.key, 0, 0).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        let revision = format!(
            "{:x}",
            Sha256::digest(format!("{binding}:{live}").as_bytes())
        );
        s.interaction_live_speech_part(100, e.key, &live, &revision, 0)
            .expect("Current accepted workflow draft prefix is readable");
        s.record_native_message(
            local,
            "native-1",
            "return-turn",
            "reported",
            Some("final_answer"),
            "The selected milestone is ready.",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let reported = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|item| item["preview"] == "The selected milestone is ready.")
            .unwrap();
        assert_eq!(reported["current"], true);
        s.interaction_withdraw_session_requests(e.key).unwrap();
        assert!(!s.workflow_native_visible(local).unwrap());
        assert!(
            s.interaction_live_speech_part(100, e.key, &live, &revision, 0)
                .is_err()
        );
        assert!(
            s.interaction_presentation_list(100, e.key, 0, 0).unwrap()["response_draft"].is_null()
        );
        assert!(
            !s.start_response_draft(100, e.key, local, "native-1", "return-turn")
                .unwrap()
        );
        s.record_native_message(
            local,
            "native-1",
            "return-turn",
            "stale",
            Some("final_answer"),
            "A stale callback cannot obtain publication.",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let items = page["items"].as_array().unwrap();
        assert!(
            items
                .iter()
                .any(|item| item["preview"] == "The selected milestone is ready."
                    && item["current"] == false)
        );
        assert!(
            !items
                .iter()
                .any(|item| item["preview"] == "A stale callback cannot obtain publication.")
        );
        // A genuinely later human input on the same writer retains ordinary
        // publication even though this earlier internal return is now retired.
        let id = Uuid::now_v7().to_string();
        let binding = s.conversation_request_binding(100, e.key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        s.conversation_input_capture(100, e.key, &binding, &id, "My later actual human question")
            .unwrap();
        s.conversation_input_event(100, &id, E::Queue).unwrap();
        s.conversation_input_event(
            100,
            &id,
            E::Begin {
                local_turn: local,
                steer: true,
            },
        )
        .unwrap();
        s.conversation_input_event(100, &id, E::Accepted { local_turn: local })
            .unwrap();
        assert!(s.workflow_native_visible(local).unwrap());
        s.record_native_message(
            local,
            "native-1",
            "return-turn",
            "human",
            Some("final_answer"),
            "The ordinary human answer remains visible.",
        )
        .unwrap();
        assert!(
            s.interaction_presentation_list(100, e.key, 0, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|i| i["preview"] == "The ordinary human answer remains visible.")
        );
    }
    fn make_return_due(s: &Store, e: &SessionRecord, workflow: &str) {
        let conn = s.conn.lock().unwrap();
        let mut w = load_on(&conn, 100, e.key, workflow).unwrap();
        for r in &mut w.native_returns {
            r.retry_after = Some(Utc::now().timestamp() - 1);
        }
        save_on(&conn, &w).unwrap();
    }
    #[test]
    fn known_unsent_return_recovers_same_source_with_finite_attempts() {
        let (f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let workflow = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "source",
            vec![first.id.clone()],
            "Ready",
        );
        let original = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let old = turn(&s, &e, "");
        s.workflow_native_link(&original.id, old).unwrap();
        s.workflow_native_outcome_attempt(&original.id, 1, "retained_unsent", None)
            .unwrap();
        assert!(
            s.workflow_native_recover_unsent(100, e.key)
                .unwrap()
                .is_empty()
        );
        for attempt in 2..=3 {
            make_return_due(&s, &e, workflow);
            let retry = s
                .workflow_native_recover_unsent(100, e.key)
                .unwrap()
                .remove(0);
            assert_eq!(retry.id, original.id);
            assert_eq!(retry.attempts, attempt);
            assert_eq!(
                serde_json::from_str::<Value>(&retry.output).unwrap()["evidence"],
                serde_json::from_str::<Value>(&original.output).unwrap()["evidence"]
            );
            assert!(
                s.workflow_native_recover_unsent(100, e.key)
                    .unwrap()
                    .is_empty()
            );
            // A late ACK/error for the earlier attempt cannot mutate this claim.
            s.workflow_native_outcome_attempt(
                &retry.id,
                attempt - 1,
                "accepted",
                Some("stale-ack"),
            )
            .unwrap();
            s.workflow_native_outcome_attempt(&retry.id, attempt - 1, "uncertain", None)
                .unwrap();
            assert_eq!(
                s.workflow_native_dispatch(&retry.id).unwrap().attempts,
                attempt
            );
            let current = turn(&s, &e, "");
            s.workflow_native_link(&retry.id, current).unwrap();
            s.workflow_native_submitting(&retry.id).unwrap();
            assert!(!s.workflow_native_visible(old).unwrap());
            s.workflow_native_outcome_attempt(&retry.id, attempt, "retained_unsent", None)
                .unwrap();
        }
        make_return_due(&s, &e, workflow);
        assert!(
            s.workflow_native_recover_unsent(100, e.key)
                .unwrap()
                .is_empty()
        );
        let workflow = workflow.to_owned();
        drop(s);
        let s = Store::open(f.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert!(
            s.workflow_native_recover_unsent(100, e.key)
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            status(&s, &e, &workflow)["native_returns"]["retained"][0]["attempts"],
            3
        );
    }
    #[test]
    fn return_recovery_excludes_uncertain_rejected_accepted_and_changed_sources() {
        for outcome in ["uncertain", "rejected", "accepted", "changed"] {
            let (_f, s, e, plan) = setup();
            let v = declare(&s, &e, plan);
            let workflow = v["id"].as_str().unwrap();
            let first = advance(&s, &e, &v).unwrap();
            let worker = accept(&s, &first);
            answer(
                &s,
                &first,
                worker,
                "source",
                vec![first.id.clone()],
                "Ready",
            );
            let r = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
            let local = turn(&s, &e, "");
            s.workflow_native_link(&r.id, local).unwrap();
            s.workflow_native_submitting(&r.id).unwrap();
            if outcome == "changed" {
                s.workflow_native_outcome_attempt(&r.id, 1, "retained_unsent", None)
                    .unwrap();
                answer(
                    &s,
                    &first,
                    worker,
                    "new-source",
                    vec![first.id.clone()],
                    "Corrected",
                );
            } else {
                s.workflow_native_outcome_attempt(
                    &r.id,
                    1,
                    outcome,
                    (outcome == "accepted").then_some("actual-ack"),
                )
                .unwrap();
            }
            make_return_due(&s, &e, workflow);
            assert!(
                s.workflow_native_recover_unsent(100, e.key)
                    .unwrap()
                    .is_empty(),
                "{outcome}"
            );
        }
    }
    #[test]
    fn native_return_restart_keeps_known_unsent_uncertainty_and_ack_separate() {
        let (f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "a",
            vec![first.id.clone()],
            "First checkpoint",
        );
        let a = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        // Failure before a native submitting observation remains known unsent.
        s.workflow_native_outcome(&a.id, "uncertain", None).unwrap();
        answer(
            &s,
            &first,
            worker,
            "b",
            vec![first.id.clone()],
            "Revised checkpoint",
        );
        let b = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let local = turn(&s, &e, "");
        s.workflow_native_link(&b.id, local).unwrap();
        s.workflow_native_submitting(&b.id).unwrap();
        answer(
            &s,
            &first,
            worker,
            "c",
            vec![first.id.clone()],
            "Current checkpoint",
        );
        let c = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let local = turn(&s, &e, "");
        s.workflow_native_link(&c.id, local).unwrap();
        s.workflow_native_submitting(&c.id).unwrap();
        s.workflow_native_outcome(&c.id, "accepted", Some("accepted-native"))
            .unwrap();
        let id = id.to_owned();
        drop(s);
        let s = Store::open(f.path(), &[100], &super::super::tests::defaults()).unwrap();
        let view = status(&s, &e, &id);
        let rows = view["native_returns"]["retained"].as_array().unwrap();
        assert_eq!(
            rows.iter().find(|r| r["id"] == a.id).unwrap()["phase"],
            "retained_unsent"
        );
        assert_eq!(
            rows.iter().find(|r| r["id"] == b.id).unwrap()["phase"],
            "uncertain"
        );
        assert_eq!(
            rows.iter().find(|r| r["id"] == c.id).unwrap()["phase"],
            "accepted"
        );
        assert!(s.workflow_native_reserve(100, e.key).unwrap().is_empty());
        assert!(s.workflow_native_validate(&b.id).is_err());
    }
    #[test]
    fn detached_ack_reconciles_only_a_distinct_exact_collection_and_late_final() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "source",
            vec![first.id.clone()],
            "Selected checkpoint",
        );
        let dispatch = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let old = turn(&s, &e, "Actual human execution");
        s.native_collection_started(old, "old-physical").unwrap();
        s.workflow_native_link(&dispatch.id, old).unwrap();
        s.workflow_native_submitting(&dispatch.id).unwrap();
        s.workflow_native_outcome(&dispatch.id, "accepted_uncollected", Some("new-physical"))
            .unwrap();
        s.workflow_native_outcome(
            &dispatch.id,
            "accepted_uncollected",
            Some("another-physical"),
        )
        .unwrap();
        let selected = s.native_collection_next().unwrap().unwrap();
        assert_ne!(selected.local, old);
        assert_eq!(selected.anchor, "new-physical");
        let observation = s
            .workflow_native_collection(selected.local)
            .unwrap()
            .unwrap();
        assert!(observation.live);
        assert_eq!(observation.physical, "new-physical");
        assert!(!s.workflow_native_visible(selected.local).unwrap());
        let active = json!({"id":"new-physical","status":"inProgress","items":[]});
        s.native_collection_observed(&selected, &[active], false)
            .unwrap();
        assert!(
            s.native_collection_observed(
                &selected,
                &[json!({"id":"old-physical","status":"completed","items":[]})],
                false
            )
            .is_err()
        );
        assert!(
            s.native_collection_observed(
                &selected,
                &[json!({"id":"new-physical","status":"completed","items":[]})],
                false
            )
            .is_err()
        );
        let final_turn = json!({"id":"new-physical","status":"completed","items":[{"id":"actual-native-item","type":"agentMessage","phase":"final_answer","text":"Late selected workflow report"}]});
        s.native_collection_observed(&selected, &[final_turn], false)
            .unwrap();
        let view = status(&s, &e, v["id"].as_str().unwrap());
        let receipt = &view["native_returns"]["retained"][0];
        assert_eq!(receipt["phase"], "accepted_reconciled");
        assert_eq!(receipt["native_turn"], "new-physical");
        assert_eq!(receipt["local_turn"], old);
        assert_eq!(receipt["collection_local_turn"], selected.local);
        let conn = s.conn.lock().unwrap();
        let old_state:(String,String)=conn.query_row("SELECT t.status,n.anchor FROM turns t JOIN native_collections n ON n.local_turn=t.id WHERE t.id=?1",[old],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
        assert_eq!(old_state, ("running".into(), "old-physical".into()));
        drop(conn);
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        assert!(
            page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["preview"] == "Late selected workflow report"
                    && item["local_turn"] == selected.local
                    && item["current"] == true)
        );
        assert_ne!(
            view["phase"], "completed",
            "A collected helper report cannot finish integration"
        );
    }
    #[test]
    fn detached_observation_retires_at_original_scope_without_erasing_ack() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "source",
            vec![first.id.clone()],
            "Selected checkpoint",
        );
        let dispatch = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let old = turn(&s, &e, "Actual human execution");
        s.workflow_native_link(&dispatch.id, old).unwrap();
        s.workflow_native_submitting(&dispatch.id).unwrap();
        s.workflow_native_outcome(&dispatch.id, "accepted_uncollected", Some("new-physical"))
            .unwrap();
        let selected = s.native_collection_next().unwrap().unwrap();
        s.interaction_withdraw_session_requests(e.key).unwrap();
        assert!(
            !s.workflow_native_collection(selected.local)
                .unwrap()
                .unwrap()
                .live
        );
        assert!(s.native_collection_next().unwrap().is_none());
        let view = status(&s, &e, v["id"].as_str().unwrap());
        assert_eq!(
            view["native_returns"]["retained"][0]["phase"],
            "accepted_uncollected"
        );
        assert_eq!(
            view["native_returns"]["retained"][0]["native_turn"],
            "new-physical"
        );
    }
    #[test]
    fn detached_siblings_share_exact_collection_and_wait_for_unknown_target() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan.clone());
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "first",
            vec![first.id.clone()],
            "First selected checkpoint",
        );
        let a = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let mut next = plan;
        next.request_id = "second-workflow".into();
        next.input_ref = original(&s, &e, "Another finite selected human workflow");
        let second_view = declare(&s, &e, next);
        let second = advance(&s, &e, &second_view).unwrap();
        let second_worker = accept(&s, &second);
        answer(
            &s,
            &second,
            second_worker,
            "second",
            vec![second.id.clone()],
            "Second selected checkpoint",
        );
        let b = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let old = turn(&s, &e, "Actual human owner");
        s.native_collection_started(old, "old-physical").unwrap();
        for id in [&a.id, &b.id] {
            s.workflow_native_link(id, old).unwrap();
            s.workflow_native_submitting(id).unwrap();
        }
        s.workflow_native_outcome(&a.id, "accepted_uncollected", Some("shared-physical"))
            .unwrap();
        let selected = s.native_collection_next().unwrap().unwrap();
        let final_turn = json!({"id":"shared-physical","status":"completed","items":[{"id":"shared-item","type":"agentMessage","phase":"final_answer","text":"Both current checkpoints"}]});
        assert!(
            s.native_collection_observed(&selected, std::slice::from_ref(&final_turn), false)
                .is_err(),
            "Unknown sibling target must not borrow the first source grant"
        );
        assert_eq!(
            status(&s, &e, v["id"].as_str().unwrap())["native_returns"]["retained"][0]["phase"],
            "accepted_uncollected"
        );
        s.workflow_native_outcome(&b.id, "accepted_uncollected", Some("shared-physical"))
            .unwrap();
        let second_receipt = status(&s, &e, second_view["id"].as_str().unwrap());
        assert_eq!(
            second_receipt["native_returns"]["retained"][0]["collection_local_turn"],
            selected.local
        );
        s.native_collection_observed(&selected, &[final_turn], false)
            .unwrap();
        for view in [&v, &second_view] {
            assert_eq!(
                status(&s, &e, view["id"].as_str().unwrap())["native_returns"]["retained"][0]["phase"],
                "accepted_reconciled"
            );
        }
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let report = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["preview"] == "Both current checkpoints")
            .unwrap();
        assert_eq!(report["workflow_returns"].as_array().unwrap().len(), 2);
        assert_eq!(report["local_turn"], selected.local);
        let conn = s.conn.lock().unwrap();
        let anchor: String = conn
            .query_row(
                "SELECT anchor FROM native_collections WHERE local_turn=?1",
                [old],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(anchor, "old-physical");
    }
    #[test]
    fn human_turn_freezes_return_association_without_changing_presentation_lifetime() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "result",
            vec![first.id.clone()],
            "Two useful ideas",
        );
        let selected = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let local = turn(&s, &e, "An independently admitted human correction");
        s.record_native_message(
            local,
            "native-1",
            "human-physical",
            "before",
            Some("commentary"),
            "Ordinary progress before the return",
        )
        .unwrap();
        s.workflow_native_link(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("human-physical"))
            .unwrap();
        s.record_native_message(
            local,
            "native-1",
            "human-physical",
            "useful",
            Some("commentary"),
            "The worker returned two useful ideas",
        )
        .unwrap();
        // Reobserving an old item after the return cannot widen its association.
        s.record_native_message(
            local,
            "native-1",
            "human-physical",
            "before",
            Some("commentary"),
            "Ordinary progress before the return",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let rows = page["items"].as_array().unwrap();
        let before = rows
            .iter()
            .find(|i| i["preview"] == "Ordinary progress before the return")
            .unwrap();
        assert!(before["native_returns"].is_null());
        let useful = rows
            .iter()
            .find(|i| i["preview"] == "The worker returned two useful ideas")
            .unwrap();
        assert_eq!(useful["kind"], "integrator_progress");
        assert_eq!(useful["native_returns"], json!([selected.id]));
        assert!(
            useful["current"].is_null(),
            "Association is not a new publication restriction"
        );
        let part = s
            .interaction_presentation_part(
                100,
                e.key,
                useful["id"].as_str().unwrap(),
                useful["revision"].as_str().unwrap(),
                0,
            )
            .unwrap();
        assert_eq!(part["native_returns"], useful["native_returns"]);
        answer(
            &s,
            &first,
            worker,
            "corrected",
            vec![first.id.clone()],
            "Corrected ideas",
        );
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let retained = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["preview"] == "The worker returned two useful ideas")
            .unwrap();
        assert!(
            retained["native_returns"].is_null(),
            "Stale evidence is no longer a returning voice offer"
        );
        assert!(
            s.workflow_native_visible(local).unwrap(),
            "The ordinary human lifetime remains visible"
        );
    }

    #[test]
    fn callback_publication_fences_every_accepted_source_in_its_frozen_set() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan.clone());
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "first",
            vec![first.id.clone()],
            "First selected checkpoint",
        );
        let a = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let mut next = plan;
        next.request_id = "second-workflow".into();
        next.input_ref = original(&s, &e, "Another finite selected human workflow");
        let second_view = declare(&s, &e, next);
        let second = advance(&s, &e, &second_view).unwrap();
        let second_worker = accept(&s, &second);
        answer(
            &s,
            &second,
            second_worker,
            "second",
            vec![second.id.clone()],
            "Second selected checkpoint",
        );
        let b = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let local = turn(&s, &e, "");
        s.workflow_native_link(&a.id, local).unwrap();
        s.workflow_native_submitting(&a.id).unwrap();
        s.workflow_native_outcome(&a.id, "accepted", Some("callback"))
            .unwrap();
        s.workflow_native_link(&b.id, local).unwrap();
        assert!(
            s.workflow_native_visible(local).unwrap(),
            "Known unsent sibling cannot poison accepted context"
        );
        s.workflow_native_submitting(&b.id).unwrap();
        assert!(
            !s.workflow_native_visible(local).unwrap(),
            "An unresolved possible input has no causal publication proof"
        );
        s.workflow_native_outcome(&b.id, "accepted", Some("callback"))
            .unwrap();
        assert!(s.workflow_native_visible(local).unwrap());
        s.record_native_message(
            local,
            "native-1",
            "callback",
            "mixed",
            Some("final_answer"),
            "Two current selected checkpoints",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let mixed = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["preview"] == "Two current selected checkpoints")
            .unwrap();
        assert_eq!(mixed["workflow_returns"].as_array().unwrap().len(), 2);
        answer(
            &s,
            &first,
            worker,
            "corrected",
            vec![first.id.clone()],
            "Corrected first source",
        );
        assert!(
            !s.workflow_native_visible(local).unwrap(),
            "Current second source cannot publish a stale first source"
        );
        s.record_native_message(
            local,
            "native-1",
            "callback",
            "stale-mixed",
            Some("final_answer"),
            "Stale mixed output cannot publish",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        assert!(
            page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(
                    |i| i["preview"] == "Two current selected checkpoints" && i["current"] == false
                )
        );
        assert!(
            !page["items"]
                .as_array()
                .unwrap()
                .iter()
                .any(|i| i["preview"] == "Stale mixed output cannot publish")
        );
        let corrected = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        s.workflow_native_link(&corrected.id, local).unwrap();
        s.workflow_native_submitting(&corrected.id).unwrap();
        s.workflow_native_outcome(&corrected.id, "accepted", Some("callback"))
            .unwrap();
        assert!(
            !s.workflow_native_visible(local).unwrap(),
            "ACK does not declare integration of the corrected source"
        );
        let offer: Value = serde_json::from_str(&corrected.output).unwrap();
        s.interaction_workflow_reported(
            100,
            e.key,
            "native-1",
            v["id"].as_str().unwrap(),
            offer["evidence"]["revision"].as_str().unwrap(),
        )
        .unwrap();
        assert!(
            s.workflow_native_visible(local).unwrap(),
            "Explicit current same-slot incorporation supersedes the old source"
        );
        s.record_native_message(
            local,
            "native-1",
            "callback",
            "current-mixed",
            Some("final_answer"),
            "Current explicitly incorporated checkpoints",
        )
        .unwrap();
        let page = s.interaction_presentation_list(100, e.key, 0, 0).unwrap();
        let current = page["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["preview"] == "Current explicitly incorporated checkpoints")
            .unwrap();
        assert_eq!(current["workflow_returns"].as_array().unwrap().len(), 2);
        assert!(
            !current["workflow_returns"]
                .as_array()
                .unwrap()
                .contains(&json!(a.id))
        );
    }
    #[test]
    fn native_return_count_is_bounded_and_source_corrections_fence_submission() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let worker = accept(&s, &first);
        answer(
            &s,
            &first,
            worker,
            "initial",
            vec![first.id.clone()],
            "Checkpoint before correction",
        );
        let stale = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        answer(
            &s,
            &first,
            worker,
            "changed",
            vec![first.id.clone()],
            "Current corrected checkpoint",
        );
        assert!(s.workflow_native_validate(&stale.id).is_err());
        for index in 0..16 {
            answer(
                &s,
                &first,
                worker,
                &format!("revision-{index}"),
                vec![first.id.clone()],
                &format!("Named milestone revision{index}"),
            );
            let selected = s.workflow_native_reserve(100, e.key).unwrap();
            assert_eq!(selected.len(), usize::from(index < 15));
        }
        let view = status(&s, &e, id);
        assert_eq!(
            view["native_returns"]["retained"].as_array().unwrap().len(),
            16
        );
        // At the model-return limit, evidence remains visible and ordinary
        // preauthorized successor progression is still usable without inference.
        assert!(
            !s.interaction_workflow_attention(100, e.key).unwrap()["envelopes"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert!(advance(&s, &e, &view).is_some());
    }

    #[test]
    fn historical_rows_and_documents_are_bounded_without_erasing_identity_or_effects() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan.clone());
        let id = v["id"].as_str().unwrap();
        {
            let mut conn = s.conn.lock().unwrap();
            let tx = conn.transaction().unwrap();
            let w = load_on(&tx, 100, e.key, id).unwrap();
            let mut oversized = w.clone();
            oversized.source.text = "x".repeat(MAX_WORKFLOW_DOCUMENT_BYTES);
            assert!(save_on(&tx, &oversized).is_err());
            assert_eq!(load_on(&tx, 100, e.key, id).unwrap().source, w.source);
            // Retained historical rows, not active work, exhaust the bound.
            for index in 1..MAX_RETAINED_WORKFLOWS {
                let mut old = w.clone();
                old.id = format!("historical-{index}");
                old.phase = "completed".into();
                tx.execute(
                    "INSERT INTO interaction_workflows VALUES(?1,100,100,1,?2,'completed',?3)",
                    params![
                        old.id,
                        format!("historical-source-{index}"),
                        document(&old).unwrap()
                    ],
                )
                .unwrap();
            }
            tx.commit().unwrap();
        }
        let later = original(&s, &e, "Another independently selected workflow");
        let mut next = plan.clone();
        next.input_ref = later;
        let error = s
            .interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                next,
                &CancellationToken::new(),
            )
            .unwrap_err();
        assert_eq!(error.to_string(), WORKFLOW_CAPACITY_ERROR);
        // Capacity does not disable an exact retained retry or current progress.
        assert_eq!(declare(&s, &e, plan), v);
        assert!(advance(&s, &e, &v).is_some());
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_workflows", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            MAX_RETAINED_WORKFLOWS
        );
        assert!(
            conn.query_row(
                "SELECT sum(length(CAST(doc AS BLOB))) FROM interaction_workflows",
                [],
                |r| r.get::<_, usize>(0)
            )
            .unwrap()
                <= MAX_RETAINED_WORKFLOWS as usize * MAX_WORKFLOW_DOCUMENT_BYTES
        );
    }

    #[test]
    fn generated_predecessor_reader_and_legacy_result_id_keep_the_selected_scope() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let local = accept(&s, &first);
        let d = answer(
            &s,
            &first,
            local,
            "complete",
            vec![first.id.clone()],
            "Exact predecessor 🦉; not a new human request",
        );
        let second = s.interaction_workflow_return(100, &d.id).unwrap().unwrap();
        let source = status(&s, &e, id)["steps"][0]["result"].clone();
        let author = s.interaction_author(&second.id, 100).unwrap().unwrap();
        let reader: Value = serde_json::from_str(
            second
                .text
                .lines()
                .find_map(|line| {
                    line.strip_prefix("Predecessor reader (use these exact arguments): ")
                })
                .unwrap(),
        )
        .unwrap();
        assert_eq!(reader, author["predecessor_reader"]);
        assert_eq!(author["predecessor"], source);
        assert!(source.get("predecessor_reader").is_none());
        assert_eq!(reader["operation"], "workflow_result");
        let args = &reader["arguments"];
        let part = s
            .interaction_workflow_result(
                100,
                second.target,
                "native-8",
                args["workflow"].as_str().unwrap(),
                args["step"].as_str().unwrap(),
                args["revision"].as_str().unwrap(),
                args["offset"].as_u64().unwrap() as usize,
            )
            .unwrap();
        assert!(
            part["text"]
                .as_str()
                .unwrap()
                .contains("Exact predecessor 🦉")
        );
        // Simulate an already-admitted older packet, without altering its source
        // or workflow/admission. Its retained result ID is enough for this read.
        let mut old_author = author.clone();
        old_author
            .as_object_mut()
            .unwrap()
            .remove("predecessor_reader");
        s.conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE interaction_session_authors SET doc=?2 WHERE input_id=?1",
                params![second.input_id, old_author.to_string()],
            )
            .unwrap();
        let result_id = source["id"].as_str().unwrap();
        let revision = source["revision"].as_str().unwrap();
        assert_eq!(
            s.interaction_workflow_result(
                100,
                second.target,
                "native-8",
                id,
                result_id,
                revision,
                0
            )
            .unwrap(),
            part
        );
        assert_eq!(
            s.interaction_workflow_result(100, e.key, "native-1", id, result_id, revision, 0)
                .unwrap(),
            part
        );
        for (human, actor, native, workflow, result, selected_revision) in [
            (101, second.target, "native-8", id, result_id, revision),
            (100, first.target, "native-7", id, result_id, revision),
            (100, second.target, "old-native-8", id, result_id, revision),
            (
                100,
                second.target,
                "native-8",
                "another-workflow",
                result_id,
                revision,
            ),
            (
                100,
                second.target,
                "native-8",
                id,
                "another-result",
                revision,
            ),
            (
                100,
                second.target,
                "native-8",
                id,
                result_id,
                "another-revision",
            ),
        ] {
            assert!(
                s.interaction_workflow_result(
                    human,
                    actor,
                    native,
                    workflow,
                    result,
                    selected_revision,
                    0
                )
                .is_err()
            );
        }
        assert_eq!(status(&s, &e, id)["steps"][0]["result"], source);
        assert!(s.interaction_workflow_return(100, &d.id).unwrap().is_none());
    }

    #[test]
    fn committed_result_advances_only_the_current_predeclared_successor_once() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let local = accept(&s, &first);
        let partial = answer(
            &s,
            &first,
            local,
            "partial",
            vec![],
            "Coverage is incomplete",
        );
        assert!(
            s.interaction_workflow_return(100, &partial.id)
                .unwrap()
                .is_none()
        );
        let d = answer(
            &s,
            &first,
            local,
            "complete",
            vec![first.id.clone()],
            "Canonical predecessor",
        );
        let second = s.interaction_workflow_return(100, &d.id).unwrap().unwrap();
        assert_eq!(second.target, SessionKey::new(100, Some(8)));
        let author = s.interaction_author(&second.id, 100).unwrap().unwrap();
        assert_eq!(
            author["predecessor"]["id"],
            status(&s, &e, id)["steps"][0]["result"]["id"]
        );
        assert!(s.interaction_workflow_return(100, &d.id).unwrap().is_none());
        let before = status(&s, &e, id);
        assert_eq!(before["steps"][1]["phase"], "queued");
        // A reserved successor cannot be recreated to repair a lost dispatch.
        assert!(s.interaction_workflow_return(100, &d.id).unwrap().is_none());
        assert_eq!(status(&s, &e, id), before);
        let local = accept(&s, &second);
        let done = answer(
            &s,
            &second,
            local,
            "verified",
            vec![second.id.clone()],
            "Receiving checkpoint",
        );
        assert!(
            s.interaction_workflow_return(100, &done.id)
                .unwrap()
                .is_none()
        );
        assert_eq!(status(&s, &e, id)["phase"], "awaiting_integration");
    }

    #[test]
    fn corrections_invalidate_consumed_predecessor_without_replaying_successor() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let local = accept(&s, &first);
        answer(&s, &first, local, "partial", vec![], "Uncovered result");
        assert_ne!(status(&s, &e, id)["steps"][1]["phase"], "ready");
        answer(
            &s,
            &first,
            local,
            "current",
            vec![first.id.clone()],
            "Covered checkpoint",
        );
        let ready = status(&s, &e, id);
        let second = advance(&s, &e, &ready).unwrap();
        let second_local = accept(&s, &second);
        let amendment = s
            .interaction_admit(
                &SourceInput {
                    tribu_source: None,
                    transcription: None,
                    channel: "fixture-correction".into(),
                    event_id: "later-correction".into(),
                    update_id: None,
                    human_id: 100,
                    target_sessions: vec![first.target_session],
                    origin: ReturnRoute {
                        chat_id: 100,
                        thread_id: 1,
                        message_id: Some(12),
                    },
                    text: "Correct the checkpoint".into(),
                },
                first.target,
                RequestRelation::Amends(first.requests.clone()),
            )
            .unwrap()
            .0;
        s.interaction_bind_epoch(&amendment.id, 100, "initial")
            .unwrap();
        let amended = accept(&s, &amendment);
        let v = status(&s, &e, id);
        assert_eq!(v["steps"][0]["phase"], "correction_pending");
        assert_eq!(v["steps"][1]["phase"], "predecessor_changed");
        assert!(
            !s.interaction_session_input_allowed(&second.id, 100)
                .unwrap()
        );
        assert!(advance(&s, &e, &v).is_none());
        answer(
            &s,
            &amendment,
            amended,
            "amended",
            vec![first.id.clone(), amendment.id.clone()],
            "Corrected checkpoint",
        );
        let v = status(&s, &e, id);
        assert_eq!(v["steps"][0]["phase"], "completed");
        assert_eq!(v["steps"][1]["phase"], "predecessor_changed");
        answer(
            &s,
            &second,
            second_local,
            "old-consumption",
            vec![second.id.clone()],
            "Consumed earlier checkpoint",
        );
        assert_ne!(status(&s, &e, id)["phase"], "awaiting_integration");
        let a = s.interaction_workflow_attention(100, e.key).unwrap();
        assert!(
            a["envelopes"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v["reason"] == "reconciliation_required")
        );
    }
    #[test]
    fn restart_atomic_admission_and_uncertain_native_input_are_never_replayed() {
        let (f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap().to_owned();
        s.conn.lock().unwrap().execute_batch("CREATE TRIGGER synthetic_author_failure BEFORE INSERT ON interaction_session_authors BEGIN SELECT RAISE(ABORT,'synthetic author failure'); END;").unwrap();
        assert!(
            s.interaction_workflow_advance(
                100,
                e.key,
                "native-1",
                &id,
                v["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .is_err()
        );
        assert_eq!(status(&s, &e, &id), v);
        s.conn
            .lock()
            .unwrap()
            .execute_batch("DROP TRIGGER synthetic_author_failure;")
            .unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let target = s.get_session(first.target).unwrap().unwrap();
        let local = turn(&s, &target, &first.text);
        s.interaction_transport(&first.id, 100, local, P::Submitting, None)
            .unwrap();
        drop(s);
        let s = Store::open(f.path(), &[100], &super::super::tests::defaults()).unwrap();
        let v = status(&s, &e, &id);
        assert_eq!(v["steps"][0]["phase"], "uncertain");
        assert!(advance(&s, &e, &v).is_none());
        let conn = s.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_instructions", [], |r| r
                .get::<_, i64>(
                0
            ))
            .unwrap(),
            1
        );
    }
    #[test]
    fn pending_question_offers_are_scoped_versioned_and_expire_without_deciding() {
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let first = advance(&s, &e, &v).unwrap();
        let local = accept(&s, &first);
        let question = HumanInteraction {
            id: "a".repeat(32),
            kind: "native".into(),
            state: "pending".into(),
            requester: 100,
            native_thread: "native-7".into(),
            local_turn: local,
            title: "Selected missing decision".into(),
            action: "Answer".into(),
            blocking: true,
            source: json!({"kind":"question","conversationIndex":0,"request":{"questions":[{"id":"decision","question":"Which receiving target?","options":[]}]}}),
        };
        s.save_interaction(first.target, &question, Some("selected-question"))
            .unwrap();
        let mut unrelated = question.clone();
        unrelated.id = "b".repeat(32);
        unrelated.native_thread = "native-8".into();
        unrelated.local_turn = turn(
            &s,
            &s.get_session(SessionKey::new(100, Some(8)))
                .unwrap()
                .unwrap(),
            "Unrelated direct work",
        );
        s.save_interaction(
            SessionKey::new(100, Some(8)),
            &unrelated,
            Some("direct-question"),
        )
        .unwrap();
        let a = s.interaction_workflow_attention(100, e.key).unwrap();
        let events = a["envelopes"].as_array().unwrap();
        assert_eq!(events.len(), 1);
        let event = &events[0];
        assert_eq!(event["source"]["id"], question.id);
        assert_eq!(event["reason"], "human_decision_required");
        let revision = event["source"]["revision"].as_str().unwrap();
        let native_return = s.workflow_native_reserve(100, e.key).unwrap().remove(0);
        let part = s
            .interaction_workflow_question(100, e.key, "native-1", &question.id, revision, 0)
            .unwrap();
        assert!(
            part["text"]
                .as_str()
                .unwrap()
                .contains("Which receiving target?")
        );
        assert_eq!(part["answer_allowed"], false);
        s.transition_interaction(first.target, 100, &question.id, "pending", "expired")
            .unwrap();
        assert!(
            s.interaction_workflow_attention(100, e.key).unwrap()["envelopes"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert!(
            s.interaction_workflow_question(100, e.key, "native-1", &question.id, revision, 0)
                .is_err()
        );
        assert!(s.workflow_native_validate(&native_return.id).is_err());
        assert!(
            s.interaction_workflow_reported(
                100,
                e.key,
                "native-1",
                v["id"].as_str().unwrap(),
                event["revision"].as_str().unwrap()
            )
            .is_err()
        );
    }
    #[test]
    fn bounded_grants_supersession_withdrawal_and_binding_retirement_preserve_active_effects() {
        let (_f, s, e, plan) = setup();
        let mut oversized = plan.clone();
        oversized.steps.resize(5, plan.steps[0].clone());
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                oversized,
                &CancellationToken::new()
            )
            .is_err()
        );
        let mut expired = plan.clone();
        expired.expires_at = (Utc::now() - Duration::seconds(1)).to_rfc3339();
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                expired,
                &CancellationToken::new()
            )
            .is_err()
        );
        let mut excessive = plan.clone();
        excessive.expires_at = (Utc::now() + Duration::days(8)).to_rfc3339();
        assert!(
            s.interaction_workflow_declare(
                100,
                e.key,
                "native-1",
                "conversation",
                excessive,
                &CancellationToken::new()
            )
            .is_err()
        );
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        let first = advance(&s, &e, &v).unwrap();
        let local = accept(&s, &first);
        let correction = original(
            &s,
            &e,
            "Supersede this plan; preserve the active checkpoint",
        );
        let current = status(&s, &e, id);
        let superseded = s
            .interaction_workflow_supersede(
                100,
                e.key,
                "native-1",
                "conversation",
                id,
                current["revision"].as_str().unwrap(),
                correction.clone(),
            )
            .unwrap();
        assert_eq!(superseded["phase"], "superseded");
        assert_eq!(superseded["steps"][0]["phase"], "accepted");
        assert_eq!(superseded["steps"][1]["phase"], "withdrawn");
        assert!(!s.interaction_session_input_allowed(&first.id, 100).unwrap());
        answer(
            &s,
            &first,
            local,
            "retained-after-supersession",
            vec![first.id.clone()],
            "Completed effect retained",
        );
        assert_eq!(
            s.interaction_instruction(&first.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::Accepted
        );
        assert_eq!(
            s.interaction_workflow_supersede(
                100,
                e.key,
                "native-1",
                "conversation",
                id,
                current["revision"].as_str().unwrap(),
                correction
            )
            .unwrap()["phase"],
            "superseded"
        );
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let id = v["id"].as_str().unwrap();
        s.set_session_codex_thread(e.key, "replacement").unwrap();
        s.set_session_codex_thread(e.key, "native-1").unwrap();
        assert_eq!(status(&s, &e, id)["phase"], "retired");
        assert!(
            s.interaction_workflow_advance(
                100,
                e.key,
                "native-1",
                id,
                v["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .is_err()
        );
        let (_f, s, e, plan) = setup();
        let v = declare(&s, &e, plan);
        let first = advance(&s, &e, &v).unwrap();
        s.interaction_withdraw_session_requests(e.key).unwrap();
        assert_eq!(
            status(&s, &e, v["id"].as_str().unwrap())["phase"],
            "withdrawn"
        );
        assert!(!s.interaction_session_input_allowed(&first.id, 100).unwrap());
    }
    fn producer_configure(s: &Store, entry: &SessionRecord, max_checks: u32) {
        producer_configure_reports(s, entry, max_checks, vec![]);
    }
    fn producer_configure_reports(
        s: &Store,
        entry: &SessionRecord,
        max_checks: u32,
        reports: Vec<crate::store::HeartbeatReportSource>,
    ) {
        use crate::store::{HeartbeatCommand as H, HeartbeatProducerContract};
        let selected_lane = if reports.is_empty() {
            super::heartbeat::HeartbeatLane::WorkflowReturns
        } else {
            super::heartbeat::HeartbeatLane::Reports
        };
        for lane in super::heartbeat::HeartbeatLane::IMPLEMENTED {
            if lane != selected_lane {
                s.heartbeat_control(100, entry.key, H::PauseLane { lane })
                    .unwrap();
            }
        }
        s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        let resources = crate::store::heartbeat::test_contract();
        let expiry = resources.expires_at_unix_ms;
        s.heartbeat_control(
            100,
            entry.key,
            H::ConfigureResources {
                generation: 1,
                contract: resources,
            },
        )
        .unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            H::ConfigureProducer {
                generation: 1,
                contract: HeartbeatProducerContract {
                    purpose: None,
                    matrix_inbox: None,
                    interval_seconds: 30,
                    max_checks,
                    expires_at_unix_ms: expiry,
                    matrix_replies: true,
                    workflows: true,
                    session_progress: false,
                    reports,
                },
            },
        )
        .unwrap();
        s.heartbeat_control(100, entry.key, H::Resume { generation: 1 })
            .unwrap();
    }
    fn producer_edit(s: &Store, entry: &SessionRecord, edit: impl FnOnce(&mut Value)) {
        let conn = s.conn.lock().unwrap();
        let key = format!("heartbeat_producer:100:{}", entry.id);
        let raw: String = conn
            .query_row("SELECT value FROM bot_state WHERE key=?1", [&key], |r| {
                r.get(0)
            })
            .unwrap();
        let mut value: Value = serde_json::from_str(&raw).unwrap();
        edit(&mut value);
        conn.execute(
            "UPDATE bot_state SET value=?2 WHERE key=?1",
            params![key, value.to_string()],
        )
        .unwrap();
    }
    fn producer_work(s: &Store, entry: &SessionRecord, plan: WorkflowPlan) -> Value {
        let view = declare(s, entry, plan);
        let i = advance(s, entry, &view).unwrap();
        let local = accept(s, &i);
        answer(
            s,
            &i,
            local,
            "producer-checkpoint",
            vec![i.id.clone()],
            "Selected checkpoint for the heartbeat.",
        );
        view
    }

    #[test]
    fn heartbeat_owned_report_selective_read_pause_and_changed_source() {
        use crate::store::{HeartbeatCommand as H, HeartbeatReportSource};
        let (_file, s, entry, _) = setup();
        let mut file = tempfile::NamedTempFile::new().unwrap();
        use std::io::Write;
        file.write_all(
            br#"{"clock":1,"offers":[{"publisher":"Eko","revision":"r1"}],"private":"excluded"}"#,
        )
        .unwrap();
        producer_configure_reports(
            &s,
            &entry,
            8,
            vec![HeartbeatReportSource {
                id: "learning".into(),
                path: file.path().to_path_buf(),
                pointers: vec!["/offers".into()],
            }],
        );
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        let source_revision = packet["evidence"]["offers"][0]["revision"]
            .as_str()
            .unwrap();
        assert!(!selected.output.contains(file.path().to_str().unwrap()));
        assert!(!selected.output.contains("Eko")); // only metadata in the offered batch
        let read = s
            .heartbeat_source(
                100,
                entry.key,
                "native-1",
                &selected.id,
                "learning",
                source_revision,
                0,
            )
            .unwrap();
        assert!(read["text"].as_str().unwrap().contains("Eko"));
        assert!(!read["text"].as_str().unwrap().contains("private"));
        assert!(
            s.heartbeat_source(
                101,
                entry.key,
                "native-1",
                &selected.id,
                "learning",
                source_revision,
                0
            )
            .is_err()
        );
        assert!(
            s.heartbeat_source(
                100,
                entry.key,
                "wrong-native",
                &selected.id,
                "learning",
                source_revision,
                0
            )
            .is_err()
        );
        assert!(
            s.heartbeat_source(
                100,
                entry.key,
                "native-1",
                &selected.id,
                "other-report",
                source_revision,
                0
            )
            .is_err()
        );
        let paused = s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        let before = paused["producer"]["checks"].clone();
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["producer"]["checks"],
            before
        );
        // Reading an exact retained report remains possible during pause.
        std::fs::write(
            file.path(),
            br#"{"clock":2,"offers":[{"publisher":"Eko","revision":"r1"}]}"#,
        )
        .unwrap();
        s.heartbeat_source(
            100,
            entry.key,
            "native-1",
            &selected.id,
            "learning",
            source_revision,
            0,
        )
        .unwrap();
        std::fs::write(
            file.path(),
            br#"{"offers":[{"publisher":"Eko","revision":"r2"}]}"#,
        )
        .unwrap();
        assert!(
            s.heartbeat_source(
                100,
                entry.key,
                "native-1",
                &selected.id,
                "learning",
                source_revision,
                0
            )
            .is_err()
        );
        s.heartbeat_control(
            100,
            entry.key,
            H::Resume {
                generation: paused["generation"].as_u64().unwrap(),
            },
        )
        .unwrap();
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        let next = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        assert_ne!(next.id, selected.id);
        let conn = s.conn.lock().unwrap();
        let (parent, index) = crate::store::heartbeat::producer::load_return(&conn, &selected.id)
            .unwrap()
            .unwrap();
        assert_eq!(parent.native_returns[index].phase, "retired_unsent");
    }

    #[test]
    fn heartbeat_reviewed_report_unchanged_is_quiet_after_restart() {
        use crate::store::{HeartbeatCommand as H, HeartbeatReportSource};
        let (db, s, entry, _) = setup();
        let file = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(file.path(), br#"{"state":"pending","steps":9}"#).unwrap();
        producer_configure_reports(
            &s,
            &entry,
            8,
            vec![HeartbeatReportSource {
                id: "memory".into(),
                path: file.path().to_path_buf(),
                pointers: vec!["/state".into(), "/steps".into()],
            }],
        );
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.heartbeat_native_started(local, "report-physical")
            .unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("report-physical"))
            .unwrap();
        s.heartbeat_reported(
            100,
            entry.key,
            "native-1",
            &selected.id,
            packet["evidence"]["revision"].as_str().unwrap(),
        )
        .unwrap();
        s.heartbeat_native_terminal(local, "report-physical", "completed")
            .unwrap();
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        drop(s);
        let s = Store::open(db.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["resources"]["reserved_provider_attempts"],
            3
        );
    }

    #[test]
    fn heartbeat_producer_no_news_is_model_free_durable_and_finite() {
        use crate::store::HeartbeatCommand as H;
        let (file, s, entry, _) = setup();
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        producer_configure(&s, &entry, 2);
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["checks"], 1);
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
        s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["producer"]["checks"],
            1
        );
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        s.heartbeat_control(100, entry.key, H::Resume { generation: 3 })
            .unwrap();
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["checks"], 2);
        assert_eq!(status["producer"]["state"], "check_capacity");
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
    }

    #[test]
    fn heartbeat_operating_purpose_is_actual_human_original_and_hash_fenced() {
        use crate::store::{HeartbeatCommand as H, HeartbeatProducerContract, HeartbeatPurpose};
        let (_file, s, e, plan) = setup();
        producer_work(&s, &e, plan.clone());
        s.heartbeat_control(100, e.key, H::Pause).unwrap();
        let resources = crate::store::heartbeat::test_contract();
        let expiry = resources.expires_at_unix_ms;
        s.heartbeat_control(
            100,
            e.key,
            H::ConfigureResources {
                generation: 1,
                contract: resources,
            },
        )
        .unwrap();
        let mut contract = HeartbeatProducerContract {
            purpose: Some(HeartbeatPurpose {
                input_ref: InputReference::Conversation(Uuid::now_v7().to_string()),
                channel: "conversation".into(),
            }),
            interval_seconds: 30,
            max_checks: 4,
            expires_at_unix_ms: expiry,
            matrix_replies: false,
            matrix_inbox: None,
            workflows: true,
            session_progress: false,
            reports: vec![],
        };
        assert!(
            s.heartbeat_control(
                100,
                e.key,
                H::ConfigureProducer {
                    generation: 1,
                    contract: contract.clone()
                }
            )
            .is_err()
        );
        contract.purpose.as_mut().unwrap().input_ref = plan.input_ref.clone();
        s.heartbeat_control(
            100,
            e.key,
            H::ConfigureProducer {
                generation: 1,
                contract,
            },
        )
        .unwrap();
        s.heartbeat_control(100, e.key, H::Resume { generation: 1 })
            .unwrap();
        let r = s.heartbeat_produce(100, e.key).unwrap().unwrap();
        let output: Value = serde_json::from_str(&r.output).unwrap();
        let purpose = &output["evidence"]["operating_purpose"];
        assert_eq!(
            purpose["input_ref"],
            serde_json::to_value(&plan.input_ref).unwrap()
        );
        let revision = purpose["revision"].as_str().unwrap();
        let exact = s
            .heartbeat_source(100, e.key, "native-1", &r.id, "purpose:human", revision, 0)
            .unwrap();
        assert_eq!(exact["retained_human_original"], true);
        assert_eq!(exact["new_human_input"], false);
        assert!(
            exact["text"]
                .as_str()
                .unwrap()
                .contains("A produces a checkpoint")
        );
        assert!(
            s.heartbeat_source(
                100,
                e.key,
                "native-1",
                &r.id,
                "purpose:human",
                "changed-revision",
                0
            )
            .is_err()
        );
        assert!(
            s.heartbeat_source(101, e.key, "native-1", &r.id, "purpose:human", revision, 0)
                .is_err()
        );
        s.heartbeat_control(100, e.key, H::Pause).unwrap();
        assert!(
            s.heartbeat_source(100, e.key, "native-1", &r.id, "purpose:human", revision, 0)
                .is_ok()
        );
        // Deliberate fixture corruption must not silently rebind the purpose.
        s.conn.lock().unwrap().execute("UPDATE conversation_inputs SET doc=json_set(doc,'$.text','Changed source bytes') WHERE id=?1",[plan.input_ref.event()]).unwrap();
        let status = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(status["producer"]["state"], "purpose_retired");
        assert_eq!(status["producer"]["checks"], 1);
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
        assert!(
            s.heartbeat_source(100, e.key, "native-1", &r.id, "purpose:human", revision, 0)
                .is_err()
        );
    }

    #[test]
    fn heartbeat_producer_batches_existing_sources_and_reviews_once_with_fresh_ownership() {
        use crate::store::HeartbeatCommand as H;
        let (_file, s, entry, plan) = setup();
        let view = producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        assert_eq!(selected.name, "heartbeat_attention");
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        assert_eq!(packet["schema"], "daimon.heartbeat-batch/v1");
        let revision = packet["evidence"]["revision"].as_str().unwrap();
        assert_eq!(
            packet["evidence"]["offers"][0]["evidence"]["reader"]["operation"],
            "workflow_result"
        );
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["resources"]["reserved_provider_attempts"],
            0
        );
        assert!(
            s.heartbeat_reported(100, entry.key, "native-1", &selected.id, revision)
                .is_err()
        );
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.heartbeat_native_started(local, "heartbeat-batch-physical")
            .unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("heartbeat-batch-physical"))
            .unwrap();
        assert!(super::native_visible_on(&s.conn.lock().unwrap(), local).unwrap());
        assert!(
            s.heartbeat_reported(101, entry.key, "native-1", &selected.id, revision)
                .is_err()
        );
        s.heartbeat_reported(100, entry.key, "native-1", &selected.id, revision)
            .unwrap();
        s.heartbeat_reported(100, entry.key, "native-1", &selected.id, revision)
            .unwrap();
        s.heartbeat_native_terminal(local, "heartbeat-batch-physical", "completed")
            .unwrap();
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["cursor_entries"], 1);
        assert_eq!(status["producer"]["retained_returns"], 1);
        assert_eq!(status["resources"]["reserved_provider_attempts"], 3);
        // Batch review is distinct from original source incorporation and task completion.
        assert_eq!(
            s.interaction_workflow_attention(100, entry.key).unwrap()["envelopes"][0]["workflow"],
            view["id"]
        );
        assert_eq!(status["producer"]["checks"], 2);
    }

    #[test]
    fn heartbeat_producer_accepted_narration_survives_consumed_offers() {
        let (_file, s, entry, plan) = setup();
        let view = producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.heartbeat_native_started(local, "heartbeat-action")
            .unwrap();
        s.workflow_native_outcome(&selected.id, "accepted", Some("heartbeat-action"))
            .unwrap();
        // Advancing the ready successor changes the original offer set. It
        // must not hide narration of the action just performed.
        let current = status(&s, &entry, view["id"].as_str().unwrap());
        assert!(
            s.interaction_workflow_advance_at_turn(
                100,
                entry.key,
                "native-1",
                Some("heartbeat-action"),
                view["id"].as_str().unwrap(),
                current["revision"].as_str().unwrap(),
                &CancellationToken::new(),
            )
            .unwrap()
            .is_some()
        );
        // Source incorporation remains separate from batch review.
        let offer = &packet["evidence"]["offers"][0];
        s.interaction_workflow_reported(
            100,
            entry.key,
            "native-1",
            view["id"].as_str().unwrap(),
            offer["revision"].as_str().unwrap(),
        )
        .unwrap();
        {
            let conn = s.conn.lock().unwrap();
            assert!(native_visible_on(&conn, local).unwrap());
            assert!(native_publication_on(&conn, local).unwrap().is_some());
            assert!(native_source_current_on(&conn, &selected.id).unwrap());
            let (p, index) = super::super::heartbeat::producer::load_return(&conn, &selected.id)
                .unwrap()
                .unwrap();
            assert!(
                !super::super::heartbeat::producer::current(
                    &conn,
                    &p,
                    &p.native_returns[index],
                    true
                )
                .unwrap()
            );
        }
        // Pause blocks new inference, not already accepted narration. Retiring
        // the original native binding still withdraws its publication authority.
        s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        assert!(native_visible_on(&s.conn.lock().unwrap(), local).unwrap());
        s.set_session_codex_thread(entry.key, "replacement-native")
            .unwrap();
        assert!(!native_visible_on(&s.conn.lock().unwrap(), local).unwrap());
    }

    #[test]
    fn heartbeat_producer_retires_independently_incorporated_unsent_source() {
        let (_file, s, entry, plan) = setup();
        let view = producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        let packet: Value = serde_json::from_str(&selected.output).unwrap();
        s.interaction_workflow_reported(
            100,
            entry.key,
            "native-1",
            view["id"].as_str().unwrap(),
            packet["evidence"]["offers"][0]["revision"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        assert!(s.workflow_native_validate(&selected.id).is_err());
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        producer_edit(&s, &entry, |v| {
            assert_eq!(v["native_returns"][0]["phase"], "retired_unsent");
            assert_eq!(v["native_returns"][0]["reported_revision"], Value::Null);
        });
        assert_eq!(
            s.heartbeat_control(100, entry.key, crate::store::HeartbeatCommand::Status)
                .unwrap()["producer"]["pending"],
            false
        );
    }

    #[test]
    fn heartbeat_producer_pause_resume_preserves_pending_identity_and_account() {
        use crate::store::HeartbeatCommand as H;
        let (_file, s, entry, plan) = setup();
        producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        assert!(s.workflow_native_validate(&selected.id).is_err());
        s.heartbeat_control(100, entry.key, H::Resume { generation: 3 })
            .unwrap();
        let current = s.workflow_native_dispatch(&selected.id).unwrap();
        assert_eq!(current.id, selected.id);
        assert_eq!(current.attention_generation, Some(4));
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["producer"]["checks"],
            1
        );
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        s.heartbeat_native_not_submitted(local).unwrap();
        s.workflow_native_outcome(&selected.id, "retained_unsent", None)
            .unwrap();
        s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        s.heartbeat_control(100, entry.key, H::Resume { generation: 5 })
            .unwrap();
        producer_edit(&s, &entry, |v| {
            v["native_returns"][0]["retry_after"] = json!(0)
        });
        assert!(
            s.native_returns_recover_unsent(100, entry.key, false, false)
                .unwrap()
                .is_empty()
        );
        let retry = s.heartbeat_returns_recover_unsent(100, entry.key).unwrap();
        assert_eq!(retry.len(), 1);
        assert_eq!(retry[0].id, selected.id);
        assert_eq!(retry[0].attention_generation, Some(6));
        assert_eq!(retry[0].attempts, 2);
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["resources"]["reserved_provider_attempts"],
            3
        );
    }

    #[test]
    fn heartbeat_producer_restart_preserves_uncertain_submission_without_retry() {
        use crate::store::HeartbeatCommand as H;
        let (file, s, entry, plan) = setup();
        producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        let local = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&selected.id, local).unwrap();
        s.workflow_native_submitting(&selected.id).unwrap();
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        assert!(
            s.heartbeat_returns_recover_unsent(100, entry.key)
                .unwrap()
                .is_empty()
        );
        producer_edit(&s, &entry, |v| {
            assert_eq!(v["native_returns"][0]["phase"], "uncertain")
        });
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["checks"], 1);
        assert_eq!(status["resources"]["reserved_provider_attempts"], 3);
    }

    #[test]
    fn heartbeat_producer_retires_only_known_unsent_stale_offers() {
        use crate::store::HeartbeatCommand as H;
        let (_file, s, entry, plan) = setup();
        let view = producer_work(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        let selected = s.heartbeat_produce(100, entry.key).unwrap().unwrap();
        {
            let conn = s.conn.lock().unwrap();
            let mut w = load_on(&conn, 100, entry.key, view["id"].as_str().unwrap()).unwrap();
            w.phase = "withdrawn".into();
            save_on(&conn, &w).unwrap();
        }
        assert!(s.workflow_native_validate(&selected.id).is_err());
        producer_edit(&s, &entry, |v| v["next_check_ms"] = json!(0));
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        producer_edit(&s, &entry, |v| {
            assert_eq!(v["native_returns"][0]["phase"], "retired_unsent");
            assert_eq!(v["native_returns"][0]["reported_revision"], Value::Null);
        });
        assert!(
            s.heartbeat_returns_recover_unsent(100, entry.key)
                .unwrap()
                .is_empty()
        );
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["pending"], false);
        assert_eq!(status["producer"]["cursor_entries"], 0);
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
    }

    #[test]
    fn heartbeat_producer_failed_source_read_keeps_cadence_and_expiry() {
        use crate::store::HeartbeatCommand as H;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        producer_configure(&s, &entry, 8);
        {
            let conn = s.conn.lock().unwrap();
            conn.execute(
                "UPDATE interaction_workflows SET doc='{' WHERE id=?1",
                [view["id"].as_str().unwrap()],
            )
            .unwrap();
        }
        assert!(s.heartbeat_produce(100, entry.key).is_err());
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["producer"]["checks"],
            1
        );
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        producer_edit(&s, &entry, |v| {
            v["contract"]["expires_at_unix_ms"] = json!(0);
            v["next_check_ms"] = json!(0)
        });
        assert!(s.heartbeat_produce(100, entry.key).unwrap().is_none());
        let status = s.heartbeat_control(100, entry.key, H::Status).unwrap();
        assert_eq!(status["producer"]["state"], "expired");
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
    }

    fn attention_parent(s: &Store, entry: &SessionRecord) -> i64 {
        use crate::store::HeartbeatCommand;
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        s.heartbeat_control(
            100,
            entry.key,
            HeartbeatCommand::ConfigureResources {
                generation: 1,
                contract: crate::store::heartbeat::test_contract(),
            },
        )
        .unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 1 })
            .unwrap();
        let local = turn(s, entry, "");
        {
            let mut conn = s.conn.lock().unwrap();
            let tx = conn.transaction().unwrap();
            crate::store::heartbeat::execution_claim_on(
                &tx,
                local,
                100,
                entry.key,
                "native-1",
                2,
                "attention-source",
                &super::heartbeat::lanes::Activation {
                    lane: super::heartbeat::HeartbeatLane::Messaging,
                    generation: 1,
                },
            )
            .unwrap();
            tx.commit().unwrap();
        }
        s.heartbeat_native_started(local, "attention-parent-physical")
            .unwrap();
        local
    }
    fn attention_advance(s: &Store, e: &SessionRecord, v: &Value) -> Result<Option<Instruction>> {
        s.interaction_workflow_advance_at_turn(
            100,
            e.key,
            "native-1",
            Some("attention-parent-physical"),
            v["id"].as_str().unwrap(),
            v["revision"].as_str().unwrap(),
            &CancellationToken::new(),
        )
    }
    #[test]
    fn heartbeat_resume_recovers_queued_workflow_without_refilling_or_replaying_submitted_returns()
    {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        let parent = attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let worker = accept(&s, &i);
        answer(
            &s,
            &i,
            worker,
            "checkpoint",
            vec![i.id.clone()],
            "Checkpoint ready",
        );
        let reserved = s.workflow_native_reserve(100, entry.key).unwrap();
        assert!(!reserved.is_empty());
        let id = view["id"].as_str().unwrap();
        {
            let conn = s.conn.lock().unwrap();
            let mut w = load_on(&conn, 100, entry.key, id).unwrap();
            let template = w.native_returns[0].clone();
            w.native_returns.clear();
            for (position, phase) in [
                "reserved",
                "retained_unsent",
                "submitting",
                "accepted",
                "uncertain",
                "retained_unsent",
            ]
            .iter()
            .enumerate()
            {
                let mut r = template.clone();
                r.id = format!("resume-receipt-{position}");
                r.phase = (*phase).into();
                if position >= 2 {
                    r.local = Some(parent);
                }
                if position >= 3 && position != 5 {
                    r.native_turn = Some(format!("exact-physical-{position}"));
                }
                w.native_returns.push(r);
            }
            save_on(&conn, &w).unwrap();
        }
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert!(
            s.heartbeat_workflow_delegation(100, i.target, &i.id)
                .is_err()
        );
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 3 })
            .unwrap();
        let conn = s.conn.lock().unwrap();
        let w = load_on(&conn, 100, entry.key, id).unwrap();
        assert_eq!(w.attention.as_ref().unwrap().generation, 4);
        assert_eq!(
            w.native_returns
                .iter()
                .map(|r| r.attention_generation)
                .collect::<Vec<_>>(),
            vec![Some(4), Some(4), Some(2), Some(2), Some(2), Some(2)]
        );
        assert_eq!(w.native_returns[2].phase, "submitting");
        assert_eq!(
            w.native_returns[3].native_turn.as_deref(),
            Some("exact-physical-3")
        );
        assert_eq!(w.native_returns[4].phase, "uncertain");
        assert_eq!(w.native_returns[5].local, Some(parent));
        let record: String = conn
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [format!("heartbeat_execution:{parent}")],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&record).unwrap()["generation"],
            2
        );
        drop(conn);
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            3
        );
        // An ordinary control read cannot change the explicit Resume selection.
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap();
        assert!(
            s.heartbeat_workflow_delegation(100, i.target, &i.id)
                .unwrap()
        );
    }

    #[test]
    fn heartbeat_resume_admits_the_same_queued_step_with_a_new_conserved_allocation() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert!(
            s.heartbeat_workflow_delegation(100, i.target, &i.id)
                .is_err()
        );
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 3 })
            .unwrap();
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::Queued
        );
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        assert!(
            s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
                .unwrap()
        );
        assert_eq!(
            s.heartbeat_inference_allowance(local, 100, i.target)
                .unwrap()
                .unwrap()
                .max_provider_attempts,
            3
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            6
        );
        // The retained instruction identity/scope is unchanged, not replayed as
        // another workflow leg or silently assigned a new independent account.
        assert_eq!(
            s.interaction_instruction(&i.id, 100).unwrap().unwrap().text,
            i.text
        );
    }

    #[test]
    fn heartbeat_workflow_recovery_refuses_label_only_and_paused_authority() {
        use crate::store::HeartbeatCommand as H;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let mut i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
            .unwrap();
        // A retained marker alone is not the exact native non-submission proof.
        i = s.interaction_instruction(&i.id, 100).unwrap().unwrap();
        i.phase = P::RetainedUnsent;
        s.conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE interaction_instructions SET phase='retained_unsent',doc=?2 WHERE id=?1",
                params![i.id, serde_json::to_string(&i).unwrap()],
            )
            .unwrap();
        let current = status(&s, &entry, view["id"].as_str().unwrap());
        assert!(
            s.interaction_workflow_advance(
                100,
                entry.key,
                "native-1",
                view["id"].as_str().unwrap(),
                current["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .unwrap_err()
            .to_string()
            .contains("unsubmitted")
        );
        s.heartbeat_native_not_submitted(local).unwrap();
        s.heartbeat_control(100, entry.key, H::Pause).unwrap();
        assert!(
            s.interaction_workflow_advance(
                100,
                entry.key,
                "native-1",
                view["id"].as_str().unwrap(),
                current["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .is_err()
        );
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::RetainedUnsent
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, H::Status).unwrap()["resources"]["reserved_provider_attempts"],
            6
        );
    }

    #[test]
    fn heartbeat_busy_child_requires_exact_unsent_proof_and_preserves_the_account() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let target = s.get_session(i.target).unwrap().unwrap();
        let first = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, first, P::Submitting, None)
            .unwrap();
        s.heartbeat_claim_workflow_delegate(first, 100, i.target, &i.id)
            .unwrap();
        assert!(s.heartbeat_workflow_deferred(&i.id, 100, first).is_err());
        s.heartbeat_native_not_submitted(first).unwrap();
        assert!(s.heartbeat_workflow_deferred(&i.id, 101, first).is_err());
        s.heartbeat_workflow_deferred(&i.id, 100, first).unwrap();
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            P::RetainedUnsent
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            6
        );
        let current = status(&s, &entry, view["id"].as_str().unwrap());
        assert!(
            s.interaction_workflow_advance(
                100,
                entry.key,
                "wrong-native",
                view["id"].as_str().unwrap(),
                current["revision"].as_str().unwrap(),
                &CancellationToken::new()
            )
            .is_err()
        );
        let recovered = advance(&s, &entry, &current).unwrap();
        assert_eq!(recovered.id, i.id);
        assert_eq!(recovered.text, i.text);
        let queued = status(&s, &entry, view["id"].as_str().unwrap());
        assert!(advance(&s, &entry, &queued).is_none());
        let second = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, second, P::Submitting, None)
            .unwrap();
        s.heartbeat_claim_workflow_delegate(second, 100, i.target, &i.id)
            .unwrap();
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            9
        );
        s.heartbeat_native_started(second, "accepted-child")
            .unwrap();
        s.interaction_transport(&i.id, 100, second, P::Accepted, Some("accepted-child"))
            .unwrap();
        assert!(s.heartbeat_native_not_submitted(second).is_err());
        assert!(s.heartbeat_workflow_deferred(&i.id, 100, second).is_err());
        assert!(!s.interaction_recover(&i.id, 100).unwrap());
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .native_turn
                .as_deref(),
            Some("accepted-child")
        );
    }

    #[test]
    fn heartbeat_resume_keeps_retired_native_workflow_ownership_stale() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        s.set_session_codex_thread(entry.key, "replacement-native")
            .unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 3 })
            .unwrap();
        assert!(
            s.heartbeat_workflow_delegation(100, i.target, &i.id)
                .is_err()
        );
        let conn = s.conn.lock().unwrap();
        let w = load_on(&conn, 100, entry.key, view["id"].as_str().unwrap()).unwrap();
        assert_eq!(w.attention.as_ref().unwrap().generation, 2);
        assert_eq!(w.attention.as_ref().unwrap().native, "native-1");
    }

    #[test]
    fn heartbeat_lane_pause_propagates_to_children_and_preserves_human_handover() {
        use crate::store::heartbeat::{HeartbeatCommand as H, HeartbeatLane as L};
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        assert!(
            s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
                .unwrap()
        );
        s.heartbeat_control(100, entry.key, H::PauseLane { lane: L::Reports })
            .unwrap();
        let rows = s
            .heartbeat_executions_scoped(100, entry.key, true, Some(L::Reports))
            .unwrap();
        assert_eq!(rows.iter().filter(|r| r["phase"] == "owned").count(), 2);
        assert!(
            s.heartbeat_inference_allowance(local, 100, i.target)
                .unwrap()
                .is_some()
        );
        s.heartbeat_native_started(local, "child-physical").unwrap();
        s.heartbeat_external_input(local).unwrap();
        s.heartbeat_control(100, entry.key, H::PauseLane { lane: L::Messaging })
            .unwrap();
        let rows = s
            .heartbeat_executions_scoped(100, entry.key, true, Some(L::Messaging))
            .unwrap();
        assert_eq!(rows.iter().filter(|r| r["phase"] == "stopping").count(), 1);
        assert_eq!(
            rows.iter().filter(|r| r["phase"] == "transferred").count(),
            1
        );
    }

    #[test]
    fn heartbeat_workflow_delegate_charges_original_account_and_pause_selects_children() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        let _parent = attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        assert!(
            s.heartbeat_workflow_delegation(100, i.target, &i.id)
                .unwrap()
        );
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        assert!(
            s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
                .unwrap()
        );
        let allocation = s
            .heartbeat_inference_allowance(local, 100, i.target)
            .unwrap()
            .unwrap();
        assert_eq!(allocation.max_provider_attempts, 3);
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            6
        );
        assert_eq!(
            s.heartbeat_control(100, i.target, HeartbeatCommand::Status)
                .unwrap()["resources"]["state"],
            "not_configured"
        );
        assert!(
            s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
                .is_err()
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            6
        );
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert!(
            s.heartbeat_inference_allowance(local, 100, i.target)
                .is_err()
        );
        let records = s.heartbeat_executions(100, entry.key, true).unwrap();
        assert_eq!(records.len(), 2);
        assert!(records.iter().all(|r| r["phase"] == "stopping"));
        assert!(records.iter().any(|r| r["native"] == "native-7"));
        assert!(
            s.heartbeat_native_started(local, "late-worker-physical")
                .unwrap()
        );
    }
    #[test]
    fn heartbeat_workflow_delegate_pause_before_claim_keeps_parent_charge_only() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert!(
            s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
                .is_err()
        );
        assert!(
            s.heartbeat_inference_allowance(local, 100, i.target)
                .unwrap()
                .is_none()
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            3
        );
        assert_eq!(
            s.heartbeat_executions(100, entry.key, false).unwrap().len(),
            1
        );
    }
    #[test]
    fn heartbeat_workflow_result_return_keeps_the_same_attention_account() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        let view = declare(&s, &entry, plan);
        let parent = attention_parent(&s, &entry);
        let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
        let target = s.get_session(i.target).unwrap().unwrap();
        let local = turn(&s, &target, &i.text);
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id)
            .unwrap();
        let physical = format!("turn-{local}");
        s.heartbeat_native_started(local, &physical).unwrap();
        s.interaction_transport(&i.id, 100, local, P::Accepted, Some(&physical))
            .unwrap();
        let i = s.interaction_instruction(&i.id, 100).unwrap().unwrap();
        answer(
            &s,
            &i,
            local,
            "bounded-worker-result",
            vec![i.id.clone()],
            "Verified checkpoint",
        );
        s.heartbeat_native_terminal(parent, "attention-parent-physical", "completed")
            .unwrap();
        s.heartbeat_native_terminal(local, &physical, "completed")
            .unwrap();
        let returns = s.workflow_native_reserve(100, entry.key).unwrap();
        assert!(!returns.is_empty());
        assert!(
            returns.iter().all(|r| r.attention_generation == Some(2)),
            "worker results must not create an unmetered integrator wakeup"
        );
        let reflection = turn(&s, &entry, "");
        s.workflow_native_link_fresh(&returns[0].id, reflection)
            .unwrap();
        assert_eq!(
            s.heartbeat_inference_allowance(reflection, 100, entry.key)
                .unwrap()
                .unwrap()
                .max_provider_attempts,
            3
        );
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            9
        );
    }
    #[test]
    fn heartbeat_workflow_delegate_capacity_retains_every_owned_cancellation_target() {
        use crate::store::HeartbeatCommand;
        let (_file, s, entry, plan) = setup();
        attention_parent(&s, &entry);
        for index in 0..16 {
            let mut next = plan.clone();
            next.request_id = format!("attention-step-{index}");
            for step in &mut next.steps {
                step.scope
                    .push_str(&format!(" Selected test subtask {index}."));
            }
            let view = declare(&s, &entry, next);
            let i = attention_advance(&s, &entry, &view).unwrap().unwrap();
            let target = s.get_session(i.target).unwrap().unwrap();
            let local = turn(&s, &target, &i.text);
            s.interaction_transport(&i.id, 100, local, P::Submitting, None)
                .unwrap();
            let claimed = s.heartbeat_claim_workflow_delegate(local, 100, i.target, &i.id);
            if index < 15 {
                assert!(claimed.unwrap())
            } else {
                assert!(claimed.is_err())
            }
        }
        assert_eq!(
            s.heartbeat_control(100, entry.key, HeartbeatCommand::Status)
                .unwrap()["resources"]["reserved_provider_attempts"],
            48
        );
        s.heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        let records = s.heartbeat_executions(100, entry.key, true).unwrap();
        assert_eq!(records.len(), 16);
        assert!(records.iter().all(|r| r["phase"] == "stopping"));
    }
    #[test]
    fn finite_review_selection_keeps_parent_counters_and_exact_human_purpose() {
        use crate::store::{
            HeartbeatCommand as H, HeartbeatProducerContract, HeartbeatPurpose,
            HeartbeatReviewContract,
        };
        let (file, s, e, plan) = setup();
        s.heartbeat_control(100, e.key, H::Pause).unwrap();
        let resources = crate::store::heartbeat::test_contract();
        s.heartbeat_control(
            100,
            e.key,
            H::ConfigureResources {
                generation: 1,
                contract: resources.clone(),
            },
        )
        .unwrap();
        s.heartbeat_control(
            100,
            e.key,
            H::ConfigureProducer {
                generation: 1,
                contract: HeartbeatProducerContract {
                    purpose: None,
                    interval_seconds: 30,
                    max_checks: 4,
                    expires_at_unix_ms: resources.expires_at_unix_ms,
                    matrix_replies: true,
                    matrix_inbox: None,
                    workflows: false,
                    session_progress: false,
                    reports: vec![],
                },
            },
        )
        .unwrap();
        let report = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(
            report.path(),
            r#"{"milestone":"fixture checkpoint","clock":1}"#,
        )
        .unwrap();
        let contract = HeartbeatReviewContract {
            purpose: HeartbeatPurpose {
                input_ref: plan.input_ref,
                channel: "conversation".into(),
            },
            interval_seconds: 900,
            max_checks: 96,
            expires_at_unix_ms: resources.expires_at_unix_ms,
            reports: vec![crate::store::HeartbeatReportSource {
                id: "children".into(),
                path: report.path().to_owned(),
                pointers: vec!["/milestone".into()],
            }],
        };
        s.heartbeat_control(
            100,
            e.key,
            H::PauseLane {
                lane: crate::store::heartbeat::lanes::HeartbeatLane::Reports,
            },
        )
        .unwrap();
        for lane in [
            crate::store::heartbeat::lanes::HeartbeatLane::Messaging,
            crate::store::heartbeat::lanes::HeartbeatLane::WorkflowReturns,
            crate::store::heartbeat::lanes::HeartbeatLane::SessionProgress,
        ] {
            s.heartbeat_control(100, e.key, H::PauseLane { lane })
                .unwrap();
        }
        let before = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert!(
            s.heartbeat_select_review(100, e.key, 2, contract.clone())
                .is_err()
        );
        s.heartbeat_select_review(100, e.key, 1, contract.clone())
            .unwrap();
        let after = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(before["resources"], after["resources"]);
        for key in [
            "checks",
            "next_check_ms",
            "cursor_entries",
            "retained_returns",
        ] {
            assert_eq!(before["producer"][key], after["producer"][key]);
        }
        assert_eq!(before["lanes"], after["lanes"]);
        assert!(s.heartbeat_select_review(100, e.key, 1, contract).is_err());
        s.heartbeat_control(
            100,
            e.key,
            H::ResumeLane {
                lane: crate::store::heartbeat::lanes::HeartbeatLane::Reports,
                generation: after["lanes"]["reports"]["generation"].as_u64().unwrap(),
            },
        )
        .unwrap();
        s.heartbeat_control(100, e.key, H::Resume { generation: 1 })
            .unwrap();
        let check = s.heartbeat_begin_check(100, e.key).unwrap().unwrap();
        assert!(
            s.heartbeat_finish_observation(&check, None, false)
                .unwrap()
                .is_none()
        );
        let waiting = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(waiting["producer"]["pending"], true);
        assert_eq!(waiting["resources"]["reserved_provider_attempts"], 0);
        let mut retained = s.heartbeat_returns_recover_unsent(100, e.key).unwrap();
        assert_eq!(retained.len(), 1);
        let r = retained.remove(0);
        assert_eq!(
            r.attempts, 2,
            "Existing finite known-unsent recovery accounting is preserved"
        );
        let packet: Value = serde_json::from_str(&r.output).unwrap();
        let revision = packet["evidence"]["operating_purpose"]["revision"]
            .as_str()
            .unwrap();
        let purpose = s
            .heartbeat_source(100, e.key, "native-1", &r.id, "purpose:human", revision, 0)
            .unwrap();
        assert!(purpose["retained_human_original"].as_bool().unwrap());
        assert!(
            purpose["text"]
                .as_str()
                .unwrap()
                .contains("A produces a checkpoint")
        );
        assert!(s.heartbeat_produce(100, e.key).unwrap().is_none());
        let after = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(after["producer"]["finite_review"]["checks"], 1);
        assert_eq!(after["resources"]["reserved_provider_attempts"], 0);
        assert_eq!(after["producer"]["pending"], true);
        {
            let conn = s.conn.lock().unwrap();
            conn.execute("UPDATE bot_state SET value=json_set(value,'$.review.contract.expires_at_unix_ms',?2) WHERE key=?1",
                params![format!("heartbeat_producer:100:{}", e.id), Utc::now().timestamp_millis()-1]).unwrap();
        }
        let expired = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(expired["producer"]["finite_review"]["state"], "expired");
        assert_eq!(
            expired["producer"]["contract"]["expires_at_unix_ms"],
            resources.expires_at_unix_ms
        );
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let restarted = s.heartbeat_control(100, e.key, H::Status).unwrap();
        assert_eq!(restarted["producer"]["finite_review"]["state"], "expired");
        assert_eq!(restarted["resources"], expired["resources"]);
        assert_eq!(
            restarted["producer"]["retained_returns"],
            expired["producer"]["retained_returns"]
        );
    }
}
