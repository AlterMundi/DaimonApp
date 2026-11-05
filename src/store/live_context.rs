//! Temporary, bounded language projection. Retention, incorporation and semantic
//! checkpointing are separate; none of them submits an original as work.
use super::*;
use anyhow::bail;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

const MAX_DOCUMENT: usize = 2 * 1024 * 1024;
const MAX_TOTAL: usize = 64 * 1024 * 1024;
const MAX_DIALOGUES: usize = 64;
const MAX_SOURCES: usize = 4096;
const PAGE: usize = 8000;
const INLINE: usize = 16000;
const MAX_PIN: usize = 49152;
const MAX_ROLLOVER_SEED: usize = 24576;
const CONTINUATION_TRIGGER: usize = 16384;
const CONTINUATION_TARGET: usize = 8192;
const CONTINUATION_GROWTH: usize = 4096;
const MAX_CONTINUATION_REQUESTS: u32 = 32;

#[derive(Debug, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum LiveContextCommand {
    Open {
        dialogue: String,
        binding: String,
        generation: String,
        resume: Option<ResumeSource>,
    },
    Append {
        dialogue: String,
        generation: String,
        source: String,
        role: String,
        text: String,
        interrupted: bool,
    },
    Close {
        dialogue: String,
        generation: String,
    },
    Sync {
        dialogue: String,
        generation: String,
        #[serde(default)]
        assistant: Vec<LiveAssistantSource>,
        #[serde(default)]
        prepare_continuation: bool,
    },
    CheckpointNeeded {
        dialogue: String,
        generation: String,
        reason: String,
        tokens: Option<u64>,
        usage_kind: String,
        #[serde(default)]
        request_id: Option<String>,
    },
    Read {
        dialogue: String,
        full: bool,
    },
    Part {
        dialogue: String,
        revision: String,
        offset: usize,
    },
    Incorporate {
        dialogue: String,
        revision: String,
    },
    Checkpoint {
        dialogue: String,
        revision: String,
        through: u64,
        text: String,
        #[serde(default)]
        request_revision: Option<String>,
    },
    Guide {
        dialogue: String,
        generation: String,
        id: String,
        basis: u64,
        mode: String,
        text: String,
        #[serde(default)]
        supersedes: Option<String>,
    },
    GuideStatus {
        dialogue: String,
        id: String,
    },
    Guidance {
        dialogue: String,
        generation: String,
    },
    GuidanceBegin {
        dialogue: String,
        generation: String,
        id: String,
    },
    GuidanceOutcome {
        dialogue: String,
        generation: String,
        id: String,
        outcome: String,
    },
    RolloverRead {
        dialogue: String,
        generation: String,
    },
    ResumeRead {
        dialogue: String,
        generation: String,
    },
    PinRead {
        dialogue: String,
        generation: String,
    },
    RolloverCommit {
        dialogue: String,
        generation: String,
        next_generation: String,
        revision: String,
    },
    RolloverStatus {
        dialogue: String,
        generation: String,
        next_generation: String,
        revision: String,
    },
    RolloverAbort {
        dialogue: String,
        generation: String,
        next_generation: String,
        revision: String,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LiveAssistantSource {
    source: String,
    text: String,
    interrupted: bool,
    #[serde(default)]
    audio_without_transcript: Option<AudioWithoutTranscript>,
    #[serde(default)]
    derived_caption: Option<DerivedCaption>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AudioWithoutTranscript {
    pcm_sha256: String,
    generated_bytes: u64,
}

impl AudioWithoutTranscript {
    fn validate(&self) -> Result<()> {
        if self.pcm_sha256.len() != 64
            || !self
                .pcm_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || self.generated_bytes == 0
            || self.generated_bytes > 300 * 48000
            || self.generated_bytes % 2 != 0
        {
            bail!("Select bounded generated audio without a transcript");
        }
        Ok(())
    }
}

/// A file-ASR draft derives from one retained audio observation, never from a
/// human original or a claim that a device played intelligible words.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DerivedCaption {
    parent_source: String,
    pcm_sha256: String,
    generated_bytes: u64,
    asr_result_sha256: String,
    draft: bool,
}

#[derive(Clone, Serialize, Deserialize)]
struct CaptionParent {
    audio: AudioWithoutTranscript,
    interrupted: bool,
    derived_source: Option<String>,
}

#[derive(Default)]
struct SourceEvidence {
    audio_without_transcript: Option<AudioWithoutTranscript>,
    derived_caption: Option<DerivedCaption>,
}

#[derive(Clone, Serialize, Deserialize)]
struct Event {
    sequence: u64,
    source: String,
    role: String,
    text: String,
    interrupted: bool,
    /// Arrival sequence is not human capture chronology.
    capture_order: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    audio_without_transcript: Option<AudioWithoutTranscript>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    derived_caption: Option<DerivedCaption>,
    revision: String,
}

#[derive(Clone, Serialize, Deserialize)]
struct Checkpoint {
    through: u64,
    text: String,
    revision: String,
}

#[derive(Serialize, Deserialize)]
struct Frozen {
    from: u64,
    through: u64,
    revision: String,
    body: String,
    supplied: usize,
    full: bool,
    #[serde(default)]
    checkpoint_generation: Option<String>,
    #[serde(default)]
    checkpoint_request_revision: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
struct CheckpointRequest {
    generation: String,
    reason: String,
    tokens: Option<u64>,
    usage_kind: String,
    requested_through: u64,
    acknowledged: bool,
    #[serde(default)]
    request_id: Option<String>,
    #[serde(default)]
    revision: Option<String>,
    #[serde(default)]
    committed: bool,
}

#[derive(Default, Serialize, Deserialize)]
struct ContinuationCadence {
    requests: u32,
    activity: Option<String>,
    rearm_bytes: usize,
}

#[derive(Serialize, Deserialize)]
struct CheckpointRead {
    request_revision: Option<String>,
    through: u64,
}

#[derive(Clone, Serialize, Deserialize)]
struct Guidance {
    id: String,
    generation: String,
    basis: u64,
    mode: String,
    text: String,
    supersedes: Option<String>,
    phase: String,
    sender_instance: Option<String>,
    #[serde(default)]
    incorporated_revision: Option<String>,
    #[serde(default)]
    checkpointed_text_hash: Option<String>,
}

fn guidance_context(g: &Guidance) -> Value {
    json!({"id":g.id,"generation":g.generation,"basis":g.basis,"mode":g.mode,
        "text":g.text,"phase":g.phase})
}

#[derive(Serialize, Deserialize)]
struct RolloverReceipt {
    previous: String,
    next: String,
    revision: String,
    through: u64,
    #[serde(default = "yes")]
    committed: bool,
}

fn yes() -> bool {
    true
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ResumeSource {
    dialogue: String,
    generation: String,
    revision: String,
}

#[derive(Serialize, Deserialize)]
struct Projection {
    dialogue: String,
    human: i64,
    entry: SessionKey,
    session: i64,
    native: String,
    binding: String,
    epoch: String,
    generation: String,
    closed: bool,
    high: u64,
    incorporated: u64,
    checkpoint: Checkpoint,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    resume_source: Option<ResumeSource>,
    /// Compact semantic receipts survive text retirement; they prevent canonical
    /// catch-up from reintroducing sources represented by a checkpoint.
    sources: BTreeMap<String, (u64, String)>,
    events: Vec<Event>,
    #[serde(default)]
    caption_parents: BTreeMap<String, CaptionParent>,
    range: Option<Frozen>,
    #[serde(default)]
    full_incorporated_revision: Option<String>,
    #[serde(default)]
    native_returns: Vec<super::workflows::WorkflowReturn>,
    #[serde(default)]
    guidance: Vec<Guidance>,
    #[serde(default)]
    rollover: Option<RolloverReceipt>,
    #[serde(default)]
    generations: Vec<String>,
    #[serde(default)]
    checkpoint_request: Option<CheckpointRequest>,
    #[serde(default)]
    continuation: ContinuationCadence,
    #[serde(default)]
    checkpoint_read: Option<CheckpointRead>,
}

fn hash(value: &impl Serialize) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(value)?)))
}
fn uuid(value: &str) -> Result<()> {
    if Uuid::parse_str(value).is_err() || Uuid::parse_str(value)?.to_string() != value {
        bail!("Select one canonical Live identifier");
    }
    Ok(())
}
fn bounded(text: &str, max: usize) -> Result<()> {
    if text.is_empty() || text.len() > max || text.contains('\0') {
        bail!("Live language exceeds its retained bound");
    }
    Ok(())
}
fn retain_event(
    p: &mut Projection,
    source: String,
    role: String,
    text: String,
    interrupted: bool,
    capture_order: Option<i64>,
    evidence: Option<SourceEvidence>,
) -> Result<Value> {
    let SourceEvidence {
        audio_without_transcript,
        derived_caption,
    } = evidence.unwrap_or_default();
    // Preserve existing source revisions; only the new observation extends
    // identity. Playback reports are still neither language nor hearing.
    let revision = if let Some(caption) = &derived_caption {
        hash(&json!([source, role, text, interrupted, capture_order, {"derived_caption":caption}]))?
    } else if let Some(audio) = &audio_without_transcript {
        hash(&json!([
            source,
            role,
            text,
            interrupted,
            capture_order,
            audio
        ]))?
    } else {
        hash(&json!([source, role, text, interrupted, capture_order]))?
    };
    if let Some((sequence, old)) = p.sources.get(&source) {
        if *old != revision {
            bail!("Finalized Live source cannot be rewritten");
        }
        return Ok(json!({"sequence":sequence,"revision":revision,"fresh":false}));
    }
    if (p.closed && derived_caption.is_none()) || p.sources.len() >= MAX_SOURCES {
        bail!("Live producer closed or source bound reached");
    }
    if let Some(audio) = &audio_without_transcript {
        p.caption_parents.insert(
            source.clone(),
            CaptionParent {
                audio: audio.clone(),
                interrupted,
                derived_source: None,
            },
        );
    }
    if let Some(caption) = &derived_caption {
        p.caption_parents
            .get_mut(&caption.parent_source)
            .context("Missing retained caption parent")?
            .derived_source = Some(source.clone());
    }
    p.high += 1;
    p.sources.insert(source.clone(), (p.high, revision.clone()));
    p.events.push(Event {
        sequence: p.high,
        source,
        role,
        text,
        interrupted,
        capture_order,
        audio_without_transcript,
        derived_caption,
        revision: revision.clone(),
    });
    Ok(json!({"sequence":p.high,"revision":revision,"fresh":true}))
}
fn load(conn: &Connection, dialogue: &str, human: i64, entry: SessionKey) -> Result<Projection> {
    uuid(dialogue)?;
    let raw: String = conn
        .query_row(
            "SELECT doc FROM live_context WHERE dialogue=?1 AND human=?2 AND chat=?3 AND topic=?4",
            params![dialogue, human, entry.chat_id, entry.thread_id],
            |r| r.get(0),
        )
        .context("Owned Live context unavailable")?;
    let p: Projection = serde_json::from_str(&raw)?;
    let (session, native) = super::presentation::entry_on(conn, human, entry)?;
    if p.session != session
        || p.native != native
        || p.binding != super::presentation::entry_binding(conn, human, entry, session)?
        || p.epoch != super::stopping::admission_epoch_on(conn, entry)?
        || super::stopping::fenced_on(conn, entry)?
    {
        bail!("Live context owner or native generation retired");
    }
    Ok(p)
}
fn save(conn: &Connection, p: &Projection) -> Result<()> {
    let raw = serde_json::to_string(p)?;
    // Reserve space for an exact full reader before accepting more sources.
    // Otherwise an append could fill the document so Sol could no longer read
    // and acknowledge it, even though no original had been lost.
    let body = snapshot(p, true)?;
    let mut reserved = serde_json::to_value(p)?;
    reserved["range"] = serde_json::to_value(Frozen {
        from: p.checkpoint.through + 1,
        through: p.high,
        revision: hash(&body)?,
        body,
        supplied: 0,
        full: true,
        checkpoint_generation: p.checkpoint_request.as_ref().map(|q| q.generation.clone()),
        checkpoint_request_revision: p
            .checkpoint_request
            .as_ref()
            .and_then(|q| q.revision.clone()),
    })?;
    let reserved_bytes = serde_json::to_vec(&reserved)?.len().max(raw.len());
    let (count, total, previous): (usize, usize, usize) = conn.query_row(
        "SELECT count(*),coalesce(sum(reserved_bytes),0),coalesce(sum(CASE WHEN dialogue=?1 THEN reserved_bytes ELSE 0 END),0) FROM live_context",
        [&p.dialogue], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
    if reserved_bytes > MAX_DOCUMENT
        || total - previous + reserved_bytes > MAX_TOTAL
        || count + usize::from(previous == 0) > MAX_DIALOGUES
    {
        bail!("Live context retention full; preserve originals and review before continuing");
    }
    conn.execute("INSERT INTO live_context(dialogue,human,chat,topic,doc,reserved_bytes) VALUES(?1,?2,?3,?4,?5,?6) ON CONFLICT(dialogue) DO UPDATE SET doc=excluded.doc,reserved_bytes=excluded.reserved_bytes",
        params![p.dialogue,p.human,p.entry.chat_id,p.entry.thread_id,raw,reserved_bytes])?;
    Ok(())
}
fn snapshot_content(p: &Projection, full: bool) -> Value {
    let from = if full {
        p.checkpoint.through + 1
    } else {
        p.incorporated + 1
    };
    let events: Vec<_> = p.events.iter().filter(|e| e.sequence >= from).collect();
    let guidance = full.then(|| {
        p.guidance
            .iter()
            .filter(|g| g.checkpointed_text_hash.is_none())
            .map(guidance_context)
            .collect::<Vec<_>>()
    });
    json!({"dialogue":p.dialogue,"from":from,"through":p.high,
        "checkpoint":if full {Some(&p.checkpoint)}else{None},"events":events,"guidance":guidance,
        "checkpoint_request":p.checkpoint_request,
        "policy":"Attributed context, not work admission, hearing or new authority. Interrupted assistant text may be unsaid. Audio without a transcript has no known words; do not invent its language or assume intelligibility, silence or hearing. A derived_caption is an approximate file-ASR draft of assistant-generated audio, not a replacement original, human request, verified exact language, intelligibility or hearing."})
}
fn snapshot(p: &Projection, full: bool) -> Result<String> {
    Ok(serde_json::to_string(&snapshot_content(p, full))?)
}

/// Measure the same complete envelope used by reconnect, without requiring a
/// closed producer, acquiring a reader, or acknowledging any source.
fn continuation_content(p: &Projection) -> Value {
    let mut content = snapshot_content(p, true);
    content
        .as_object_mut()
        .unwrap()
        .remove("checkpoint_request");
    content["kind"] = json!("internal_live_reconnect_context");
    content["generation"] = json!(p.generation);
    content["policy"] = json!(
        "Attributed prior conversation, not a new human turn, tool call, work admission, memory write or permission to replay effects. Interrupted assistant text may be unsaid. Audio without transcript has no known words; captions remain approximate. Pending work continues independently; never execute this context."
    );
    content
}
/// Copy language once rather than serializing a previous serialized envelope
/// inside the next checkpoint. This is lossless formatting, not a semantic
/// checkpoint or acknowledgment. Native source/revision fencing stays unchanged.
fn inherited_language(content: &Value) -> Result<String> {
    let inherited = content["checkpoint"]["text"].as_str().unwrap_or_default();
    let has_delta = ["events", "guidance"].iter().any(|key| {
        content[*key]
            .as_array()
            .is_some_and(|items| !items.is_empty())
    });
    if !has_delta && !inherited.is_empty() {
        return Ok(inherited.to_owned());
    }
    let mut delta = content.clone();
    delta["checkpoint"].as_object_mut().unwrap().remove("text");
    let encoded = serde_json::to_string(&delta)?;
    Ok(if inherited.is_empty() {
        encoded
    } else {
        format!("{inherited}\n\n{encoded}")
    })
}

fn continuation_activity(p: &Projection) -> String {
    // Source receipts survive compaction. Guidance identity/text survives its
    // disposition and retirement. ACKs, transport/playback and summary rewrites
    // therefore cannot masquerade as fresh conversational activity.
    hash(&json!([
        p.sources,
        p.guidance
            .iter()
            .map(|g| json!([
                g.id,
                g.checkpointed_text_hash
                    .clone()
                    .unwrap_or_else(|| hash(&g.text).unwrap())
            ]))
            .collect::<Vec<_>>()
    ]))
    .unwrap()
}
fn continuation_status(p: &Projection) -> Value {
    let content = continuation_content(p);
    let bytes = content.to_string().len();
    let activity = continuation_activity(p);
    let available = p.checkpoint_request.as_ref().is_none_or(|q| q.committed);
    json!({"bytes":bytes,"revision":hash(&content).unwrap(),"through":p.high,
        "complete":true,"activity_revision":activity,"requests":p.continuation.requests,
        "max_requests":MAX_CONTINUATION_REQUESTS,"target_bytes":CONTINUATION_TARGET,
        "eligible":!p.closed && available && p.continuation.requests < MAX_CONTINUATION_REQUESTS
            && bytes >= CONTINUATION_TRIGGER
            && p.continuation.activity.as_ref()!=Some(&activity)
            && (p.continuation.activity.is_none()
                || bytes >= p.continuation.rearm_bytes.saturating_add(CONTINUATION_GROWTH))})
}
fn view(p: &Projection) -> Value {
    json!({"schema":"telecodex.live-context/v1","dialogue":p.dialogue,
        "entry_binding":[p.human,p.entry,p.session,p.native],"generation":p.generation,
        "high":p.high,"incorporated":p.incorporated,"checkpointed":p.checkpoint.through,
        "checkpoint_revision":p.checkpoint.revision,"closed":p.closed,
        "checkpoint_request":p.checkpoint_request,
        "continuation":continuation_status(p),
        "rollover":p.rollover,
        "rollover_meaning":"Owner-reported projection generation transition; not provider readiness, application, audio playback or work replay.",
        "work_admission":"not_requested"})
}

fn rollover_content(p: &Projection) -> Value {
    json!({"kind":"internal_integrator_checkpoint","dialogue":p.dialogue,
        "generation":p.generation,"checkpoint":p.checkpoint,
        "guidance":p.guidance.iter().filter(|g|g.checkpointed_text_hash.is_none()).map(|g|json!({"id":g.id,"basis":g.basis,
            "text":g.text,"mode":g.mode,"phase":g.phase})).collect::<Vec<_>>(),
        "policy":"Attributed continuity from Sol, not new human speech, tool calls, work admission, durable-memory writes or permission to replay effects. Preserve unresolved effect uncertainty; sent guidance is not applied or heard. Do not speak or execute this checkpoint."})
}

fn resume_snapshot(conn: &Connection, p: &Projection, generation: &str) -> Result<Value> {
    if !p.closed || generation != p.generation {
        bail!("Select the exact closed Live generation for reconnect");
    }
    if human_context_missing(conn, p)? {
        bail!("Live reconnect must catch up canonical human context first");
    }
    let content = continuation_content(p);
    Ok(content)
}
fn resume_content(conn: &Connection, p: &Projection, generation: &str) -> Result<Value> {
    let content = resume_snapshot(conn, p, generation)?;
    if serde_json::to_vec(&content)?.len() > MAX_ROLLOVER_SEED {
        bail!("Live reconnect needs semantic compaction before its complete seed can fit");
    }
    Ok(content)
}

fn rollover_basis(conn: &Connection, p: &Projection) -> Result<Value> {
    if p.closed
        || p.checkpoint.text.is_empty()
        || p.checkpoint.through != p.high
        || p.incorporated != p.high
        || p.range.is_some()
        || p.checkpoint_request
            .as_ref()
            .is_some_and(|r| !r.acknowledged)
        || p.guidance
            .iter()
            .any(|g| matches!(g.phase.as_str(), "pending" | "submitting"))
    {
        bail!("Live rollover needs a complete incorporated checkpoint and settled guidance");
    }
    if human_context_missing(conn, p)? {
        bail!("Live rollover must catch up canonical human context first");
    }
    let content = rollover_content(p);
    if serde_json::to_vec(&content)?.len() > MAX_ROLLOVER_SEED {
        bail!("Live rollover continuity exceeds its provider setup reserve");
    }
    Ok(json!({"revision":hash(&content)?,"through":p.high,"content":content}))
}
fn human_context_missing(conn: &Connection, p: &Projection) -> Result<bool> {
    Ok(conn.query_row("SELECT EXISTS(SELECT 1 FROM conversation_inputs c WHERE c.human_id=?1 AND c.session_id=?2 AND c.native_thread=?3 AND c.retired=0 AND json_extract(c.doc,'$.foreground_dialogue')=?4 AND length(json_extract(c.doc,'$.text'))>0 AND NOT EXISTS(SELECT 1 FROM json_each(?5) s WHERE s.key=c.id))",
        params![p.human,p.session,p.native,p.dialogue,serde_json::to_string(&p.sources)?],|r|r.get(0))?)
}
fn freeze(p: &mut Projection, full: bool) -> Result<Value> {
    if p.range.as_ref().is_some_and(|r| r.full != full) {
        bail!("Finish the selected frozen Live range first");
    }
    if p.range.is_none() {
        let from = if full {
            p.checkpoint.through + 1
        } else {
            p.incorporated + 1
        };
        let body = snapshot(p, full)?;
        let revision = hash(&body)?;
        p.range = Some(Frozen {
            from,
            through: p.high,
            revision,
            body,
            supplied: 0,
            full,
            checkpoint_generation: p.checkpoint_request.as_ref().map(|q| q.generation.clone()),
            checkpoint_request_revision: p
                .checkpoint_request
                .as_ref()
                .and_then(|q| q.revision.clone()),
        });
    }
    let mut result = view(p);
    let r = p.range.as_mut().unwrap();
    result["range"] = if r.body.len() <= INLINE {
        r.supplied = r.body.chars().count();
        json!({"from":r.from,"through":r.through,"revision":r.revision,"full":r.full,
                        "content":serde_json::from_str::<Value>(&r.body)?,"complete":true})
    } else {
        json!({"from":r.from,"through":r.through,"revision":r.revision,"full":r.full,
                    "complete":false,"characters":r.body.chars().count(),"offset":0})
    };
    result["range"]["checkpoint_generation"] = json!(r.checkpoint_generation);
    result["range"]["checkpoint_request_revision"] = json!(r.checkpoint_request_revision);
    reader_actions(&mut result, r)?;
    Ok(result)
}

fn reader_actions(result: &mut Value, r: &Frozen) -> Result<()> {
    result["after_incorporation"] = json!({"operation":"live_context","arguments":{
        "action":"incorporate","dialogue":result["dialogue"],"revision":r.revision}});
    if r.full && r.supplied == r.body.chars().count() {
        let frozen: Value = serde_json::from_str(&r.body)?;
        result["checkpoint_writer"] = json!({"operation":"live_context","arguments":{
            "action":"checkpoint","dialogue":result["dialogue"],
            "revision":frozen["checkpoint"]["revision"],"through":r.through,
            "request_revision":r.checkpoint_request_revision}});
        result["checkpoint_writer_notes"] = json!({
            "required_text_field":"text",
            "pressure_seed_max_bytes":MAX_ROLLOVER_SEED,
            "continuation_target_bytes":CONTINUATION_TARGET,
            "meaning":"After invoking after_incorporation, add your compact semantic checkpoint in arguments.text and call this exact template. Keep arguments.revision and through unchanged. For a complete pressure or closed reconnect checkpoint, the serialized checkpoint envelope must fit pressure_seed_max_bytes, including JSON escaping and metadata. If rejected for capacity, shorten text and retry this unchanged revision; exact context has not been retired. Guidance and complete provider setup have separate readiness/capacity gates. This is semantic continuity, not work admission or a memory-write receipt."});
    }
    Ok(())
}

fn page(p: &mut Projection, revision: &str, offset: usize) -> Result<Value> {
    let mut result = view(p);
    let r = p.range.as_mut().context("No frozen Live range")?;
    if r.revision != revision || offset > r.supplied {
        bail!("Live range changed or unread page gap");
    }
    // Character offsets avoid splitting multibyte language. The JSON string is
    // reconstructed before interpreting sources; a chunk is never a preview.
    let size = r.body.chars().count();
    if offset > size {
        bail!("Live context offset exceeds selected range");
    }
    let text: String = r.body.chars().skip(offset).take(PAGE).collect();
    let next = offset + text.chars().count();
    r.supplied = r.supplied.max(next);
    result["range"] = json!({"from":r.from,"through":r.through,"revision":r.revision,
        "full":r.full,"offset":offset,"text":text,"next":next,"more":next<size,
        "checkpoint_generation":r.checkpoint_generation,
        "checkpoint_request_revision":r.checkpoint_request_revision,
        "encoding":"JSON; concatenate exact pages before interpreting"});
    reader_actions(&mut result, r)?;
    Ok(result)
}

fn request_checkpoint(
    p: &mut Projection,
    generation: String,
    reason: String,
    tokens: Option<u64>,
    usage_kind: String,
    request_id: Option<String>,
) -> Result<bool> {
    let reconnect = reason == "reconnect";
    let continuation = reason == "continuation";
    if let Some(id) = &request_id {
        uuid(id)?;
    }
    if (p.closed != reconnect)
        || (reconnect || continuation) != request_id.is_some()
        || generation != p.generation
        || !matches!(
            reason.as_str(),
            "tokens"
                | "lifetime"
                | "tools"
                | "text"
                | "guidance"
                | "unknown_usage"
                | "reconnect"
                | "continuation"
        )
        || !matches!(usage_kind.as_str(), "observed" | "conservative" | "unknown")
        || tokens.is_some_and(|n| n > i32::MAX as u64)
        || ((usage_kind == "unknown") != tokens.is_none())
    {
        bail!("Select bounded current Live checkpoint pressure");
    }
    // One outstanding semantic operation. Physical pressure coalesces
    // while it runs; after commit it can request a complete handover.
    // Closed reconnect upgrades prior active pressure as before.
    if p.checkpoint_request.as_ref().is_some_and(|q| {
        if reconnect {
            q.reason == "reconnect" && (!q.acknowledged || q.request_id == request_id)
        } else {
            !q.committed || (!continuation && q.reason != "continuation")
        }
    }) {
        return Ok(false);
    }
    if continuation {
        let status = continuation_status(p);
        if status["eligible"] != true {
            return Ok(false);
        }
        p.continuation.requests += 1;
        p.continuation.activity = Some(continuation_activity(p));
        p.continuation.rearm_bytes = status["bytes"].as_u64().unwrap() as usize;
    }
    let revision = if request_id.is_some() {
        Some(hash(&json!([
            generation,
            request_id,
            p.high,
            p.checkpoint.revision
        ]))?)
    } else {
        None
    };
    p.checkpoint_request = Some(CheckpointRequest {
        generation,
        reason,
        tokens,
        usage_kind,
        requested_through: p.high,
        acknowledged: false,
        committed: false,
        request_id,
        revision,
    });
    Ok(true)
}

impl Store {
    pub(super) fn init_live_context(&self) -> Result<()> {
        self.conn
            .lock()
            .expect("store mutex poisoned")
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS live_context(dialogue TEXT PRIMARY KEY,
             human INTEGER NOT NULL,chat INTEGER NOT NULL,topic INTEGER NOT NULL,doc TEXT NOT NULL,
             reserved_bytes INTEGER NOT NULL);
             CREATE INDEX IF NOT EXISTS live_context_owner ON live_context(human,chat,topic);",
            )?;
        let conn = self.conn.lock().expect("store mutex poisoned");
        let rows = {
            let mut q = conn.prepare("SELECT doc FROM live_context ORDER BY rowid LIMIT 64")?;
            q.query_map([], |r| r.get::<_, String>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        for raw in rows {
            let mut p: Projection = serde_json::from_str(&raw)?;
            let mut changed = false;
            for guide in &mut p.guidance {
                if guide.phase == "submitting"
                    && guide.sender_instance.as_deref() != Some(&self.instance_id)
                {
                    guide.phase = "uncertain".into();
                    changed = true;
                }
            }
            if changed {
                save(&conn, &p)?;
            }
        }
        Ok(())
    }

    /// Owner-local producer operations and integrating-only semantic operations
    /// are separated by the caller, after its existing authentication checks.
    pub(crate) fn live_context(
        &self,
        human: i64,
        entry: SessionKey,
        command: LiveContextCommand,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        if let LiveContextCommand::Open {
            dialogue,
            binding,
            generation,
            resume,
        } = &command
        {
            uuid(dialogue)?;
            uuid(generation)?;
            let (session, native) = super::presentation::entry_on(&tx, human, entry)?;
            if native.is_empty()
                || *binding != super::presentation::entry_binding(&tx, human, entry, session)?
                || super::stopping::fenced_on(&tx, entry)?
            {
                bail!("Live producer binding unavailable");
            }
            let exists: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM live_context WHERE dialogue=?1)",
                [dialogue],
                |r| r.get(0),
            )?;
            if exists {
                let p = load(&tx, dialogue, human, entry)?;
                if p.generation != *generation
                    || resume
                        .as_ref()
                        .is_some_and(|r| p.resume_source.as_ref() != Some(r))
                {
                    bail!("Live producer generation differs");
                }
                return Ok(view(&p));
            }
            let seed = if let Some(source) = resume {
                if source.dialogue == *dialogue {
                    bail!("Reconnect requires a distinct visit");
                }
                let previous = load(&tx, &source.dialogue, human, entry)?;
                let content = resume_content(&tx, &previous, &source.generation)?;
                if hash(&content)? != source.revision {
                    bail!("Reconnect source changed before opening");
                }
                Some(inherited_language(&content)?)
            } else {
                None
            };
            let p = Projection {
                dialogue: dialogue.clone(),
                human,
                entry,
                session,
                native,
                binding: binding.clone(),
                epoch: super::stopping::admission_epoch_on(&tx, entry)?,
                generation: generation.clone(),
                closed: false,
                high: 0,
                incorporated: 0,
                checkpoint: Checkpoint {
                    through: 0,
                    text: seed.clone().unwrap_or_default(),
                    revision: if seed.is_some() {
                        hash(&json!([dialogue, 0, seed]))?
                    } else {
                        hash(&json!([dialogue, 0]))?
                    },
                },
                resume_source: resume.clone(),
                sources: BTreeMap::new(),
                events: vec![],
                caption_parents: BTreeMap::new(),
                range: None,
                full_incorporated_revision: None,
                native_returns: vec![],
                guidance: vec![],
                rollover: None,
                generations: vec![generation.clone()],
                checkpoint_request: None,
                continuation: ContinuationCadence::default(),
                checkpoint_read: None,
            };
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(view(&p));
        }
        let dialogue = match &command {
            LiveContextCommand::Open { .. } => unreachable!(),
            LiveContextCommand::Append { dialogue, .. }
            | LiveContextCommand::Close { dialogue, .. }
            | LiveContextCommand::Sync { dialogue, .. }
            | LiveContextCommand::CheckpointNeeded { dialogue, .. }
            | LiveContextCommand::Read { dialogue, .. }
            | LiveContextCommand::Part { dialogue, .. }
            | LiveContextCommand::Incorporate { dialogue, .. }
            | LiveContextCommand::Checkpoint { dialogue, .. } => dialogue,
            LiveContextCommand::Guide { dialogue, .. }
            | LiveContextCommand::GuideStatus { dialogue, .. }
            | LiveContextCommand::Guidance { dialogue, .. }
            | LiveContextCommand::GuidanceBegin { dialogue, .. }
            | LiveContextCommand::GuidanceOutcome { dialogue, .. }
            | LiveContextCommand::RolloverRead { dialogue, .. }
            | LiveContextCommand::ResumeRead { dialogue, .. }
            | LiveContextCommand::PinRead { dialogue, .. }
            | LiveContextCommand::RolloverCommit { dialogue, .. }
            | LiveContextCommand::RolloverStatus { dialogue, .. }
            | LiveContextCommand::RolloverAbort { dialogue, .. } => dialogue,
        };
        let mut p = load(&tx, dialogue, human, entry)?;
        let abort = matches!(&command, LiveContextCommand::RolloverAbort { .. });
        let result = match command {
            LiveContextCommand::Open { .. } => unreachable!(),
            LiveContextCommand::ResumeRead { generation, .. } => {
                // A copy cannot acquire/replace the integrator's shared range.
                let content = resume_snapshot(&tx, &p, &generation)?;
                let bytes = serde_json::to_vec(&content)?.len();
                let mut result = view(&p);
                if bytes > MAX_ROLLOVER_SEED {
                    // Read-only refusal with enough information for one explicit
                    // reconnect to request semantic preparation. Never clip or ACK.
                    result["resume_requirement"] = json!({"kind":"semantic_checkpoint",
                        "generation":generation,"through":p.high,"bytes":bytes,
                        "max_bytes":MAX_ROLLOVER_SEED});
                } else {
                    result["resume"] = json!({"revision":hash(&content)?,"through":p.high,
                        "checkpointed":p.checkpoint.through,"bytes":bytes,"content":content});
                }
                tx.commit()?;
                return Ok(result);
            }
            LiveContextCommand::PinRead { generation, .. } => {
                if p.closed || generation != p.generation {
                    bail!("Select the current active Live pin generation");
                }
                if human_context_missing(&tx, &p)? {
                    bail!("Live pin must catch up canonical human context first");
                }
                // A provider pin is a frozen COPY, not Sol's semantic read or
                // incorporation. Never acquire/replace its shared range or ACK
                // language merely because it is available to the voice owner.
                let mut content: Value = serde_json::from_str(&snapshot(&p, true)?)?;
                content
                    .as_object_mut()
                    .unwrap()
                    .remove("checkpoint_request");
                content["kind"] = json!("internal_live_context_pin");
                content["generation"] = json!(p.generation);
                let bytes = serde_json::to_vec(&content)?.len();
                if bytes > MAX_PIN {
                    bail!("Live pin needs semantic compaction before its bounded preamble can fit");
                }
                let mut result = view(&p);
                result["pin"] = json!({"revision":hash(&content)?,"through":p.high,
                    "checkpointed":p.checkpoint.through,"bytes":bytes,"content":content});
                tx.commit()?;
                return Ok(result);
            }
            LiveContextCommand::CheckpointNeeded {
                generation,
                reason,
                tokens,
                usage_kind,
                request_id,
                ..
            } => {
                if !request_checkpoint(&mut p, generation, reason, tokens, usage_kind, request_id)?
                {
                    return Ok(view(&p));
                }
                view(&p)
            }
            LiveContextCommand::RolloverStatus {
                generation,
                next_generation,
                revision,
                ..
            }
            | LiveContextCommand::RolloverAbort {
                generation,
                next_generation,
                revision,
                ..
            } => {
                uuid(&generation)?;
                uuid(&next_generation)?;
                let target = next_generation.clone();
                if generation == next_generation
                    || revision.len() != 64
                    || !revision
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                {
                    bail!("Select an exact distinct Live rollover attempt");
                }
                let committed = p.rollover.as_ref().is_some_and(|r| {
                    r.committed
                        && r.previous == generation
                        && r.next == next_generation
                        && r.revision == revision
                        && p.generation == next_generation
                });
                if !committed && p.generation != generation {
                    bail!("Live rollover generation differs");
                }
                if abort
                    && !committed
                    && !p.generations.contains(&next_generation)
                    && p.generations.len() < 65
                {
                    if p.generations.is_empty() {
                        p.generations.push(generation.clone());
                    }
                    p.generations.push(next_generation.clone());
                    p.rollover = Some(RolloverReceipt {
                        previous: generation,
                        next: next_generation,
                        revision,
                        through: p.high,
                        committed: false,
                    });
                    save(&tx, &p)?;
                    tx.commit()?;
                }
                let mut result = view(&p);
                result["rollover_committed"] = json!(committed);
                result["rollover_fenced"] = json!(
                    !committed && (p.generations.contains(&target) || p.generations.len() >= 65)
                );
                return Ok(result);
            }
            LiveContextCommand::RolloverRead { generation, .. } => {
                if generation != p.generation {
                    bail!("Live producer generation differs");
                }
                let mut result = view(&p);
                result["rollover_basis"] = rollover_basis(&tx, &p)?;
                // A read must not wake the event watcher or create work.
                return Ok(result);
            }
            LiveContextCommand::RolloverCommit {
                generation,
                next_generation,
                revision,
                ..
            } => {
                uuid(&next_generation)?;
                if let Some(old) = &p.rollover
                    && old.committed
                    && old.previous == generation
                    && old.next == next_generation
                    && old.revision == revision
                    && p.generation == next_generation
                {
                    return Ok(view(&p));
                }
                if generation != p.generation || generation == next_generation {
                    bail!("Live rollover generation differs");
                }
                if p.generations.is_empty() {
                    p.generations.push(generation.clone());
                }
                if p.generations.len() >= 65 || p.generations.contains(&next_generation) {
                    bail!("Live rollover generation retired or finite session bound reached");
                }
                let basis = rollover_basis(&tx, &p)?;
                if basis["revision"] != revision {
                    bail!("Live rollover basis changed");
                }
                p.rollover = Some(RolloverReceipt {
                    previous: generation,
                    next: next_generation.clone(),
                    revision,
                    through: p.high,
                    committed: true,
                });
                p.generation = next_generation;
                p.checkpoint_request = None;
                p.generations.push(p.generation.clone());
                view(&p)
            }
            LiveContextCommand::Append {
                generation,
                source,
                role,
                text,
                interrupted,
                ..
            } => {
                uuid(&source)?;
                bounded(&text, 16384)?;
                if p.generation != generation {
                    bail!("Live producer generation differs");
                }
                let capture_order = if role == "human" {
                    let original = super::conversation_inputs::read_on(&tx, &source, human)?;
                    if original.entry != entry
                        || original.native != p.native
                        || original.epoch != p.epoch
                        || original.retired
                        || original.foreground_dialogue.as_deref() != Some(&p.dialogue)
                        || original.text != text
                        || interrupted
                    {
                        bail!("Live human context does not match its canonical original");
                    }
                    // Existing receiver ordering spans channel arrival and slow
                    // finalization; never synthesize it from projection sequence.
                    Some(tx.query_row("SELECT id FROM original_ingress_order WHERE channel='conversation' AND event_id=?1",[&source],|r|r.get::<_,i64>(0))?)
                } else if role == "assistant" {
                    None
                } else {
                    bail!("Invalid Live context role");
                };
                retain_event(&mut p, source, role, text, interrupted, capture_order, None)?
            }
            LiveContextCommand::Sync {
                generation,
                assistant,
                prepare_continuation,
                ..
            } => {
                if p.generation != generation {
                    bail!("Live producer generation differs");
                }
                if assistant.len() > 8
                    || assistant.iter().map(|s| s.text.len()).sum::<usize>() > 65536
                {
                    bail!("Live assistant catch-up exceeds its batch bound");
                }
                // Read only this selected dialogue's canonical finalized text.
                // No media/status helper, ASR, work admission or native replay.
                // Source receipts deduplicate earlier rows even after checkpoint
                // retirement; a cursor alone could miss slow finalization.
                let rows = {
                    let mut q=tx.prepare("SELECT c.id,c.doc,o.id FROM conversation_inputs c JOIN original_ingress_order o ON o.channel='conversation' AND o.event_id=c.id WHERE c.human_id=?1 AND c.session_id=?2 AND c.native_thread=?3 AND c.retired=0 AND json_extract(c.doc,'$.foreground_dialogue')=?4 AND length(json_extract(c.doc,'$.text'))>0 ORDER BY o.id LIMIT 4097")?;
                    q.query_map(params![human, p.session, p.native, p.dialogue], |r| {
                        Ok((
                            r.get::<_, String>(0)?,
                            r.get::<_, String>(1)?,
                            r.get::<_, i64>(2)?,
                        ))
                    })?
                    .collect::<rusqlite::Result<Vec<_>>>()?
                };
                if rows.len() > MAX_SOURCES {
                    bail!("Live canonical catch-up exceeds its source bound");
                }
                let mut fresh = 0;
                for (id, raw, order) in rows {
                    let original: super::conversation_inputs::ConversationInput =
                        serde_json::from_str(&raw)?;
                    if original.epoch != p.epoch {
                        bail!("Canonical Live original epoch changed");
                    }
                    bounded(&original.text, 16384)?;
                    fresh += usize::from(
                        retain_event(
                            &mut p,
                            id,
                            "human".into(),
                            original.text,
                            false,
                            Some(order),
                            None,
                        )?["fresh"]
                            == true,
                    );
                }
                let mut receipts = Vec::new();
                for source in assistant {
                    uuid(&source.source)?;
                    if let Some(caption) = &source.derived_caption {
                        uuid(&caption.parent_source)?;
                        bounded(&source.text, 16384)?;
                        let parent = p
                            .caption_parents
                            .get(&caption.parent_source)
                            .context("Derived caption needs its retained assistant audio parent")?;
                        if source.audio_without_transcript.is_some()
                            || caption.generated_bytes > 120 * 48000
                            || !caption.draft
                            || caption.parent_source == source.source
                            || caption.pcm_sha256 != parent.audio.pcm_sha256
                            || caption.generated_bytes != parent.audio.generated_bytes
                            || source.interrupted != parent.interrupted
                            || caption.asr_result_sha256.len() != 64
                            || !caption
                                .asr_result_sha256
                                .bytes()
                                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                            || parent
                                .derived_source
                                .as_ref()
                                .is_some_and(|id| id != &source.source)
                        {
                            bail!(
                                "Derived caption differs from its retained audio or ASR draft provenance"
                            );
                        }
                    } else if let Some(audio) = &source.audio_without_transcript {
                        audio.validate()?;
                        if !source.text.is_empty() {
                            bail!("Missing-transcript observation cannot also claim language");
                        }
                    } else {
                        bounded(&source.text, 16384)?;
                    }
                    let id = source.source.clone();
                    let mut receipt = retain_event(
                        &mut p,
                        source.source,
                        "assistant".into(),
                        source.text,
                        source.interrupted,
                        None,
                        Some(SourceEvidence {
                            audio_without_transcript: source.audio_without_transcript,
                            derived_caption: source.derived_caption,
                        }),
                    )?;
                    receipt["source"] = json!(id);
                    receipts.push(receipt);
                }
                if prepare_continuation && continuation_status(&p)["eligible"] == true {
                    let generation = p.generation.clone();
                    request_checkpoint(
                        &mut p,
                        generation,
                        "continuation".into(),
                        None,
                        "unknown".into(),
                        Some(Uuid::now_v7().to_string()),
                    )?;
                }
                let mut value = view(&p);
                value["new_sources"] = json!(fresh);
                value["new_human_sources"] = json!(fresh);
                value["assistant_receipts"] = json!(receipts);
                value
            }
            LiveContextCommand::Close { generation, .. } => {
                if generation != p.generation {
                    bail!("Live producer generation differs");
                }
                p.closed = true;
                for g in &mut p.guidance {
                    if g.phase == "pending" {
                        g.phase = "retired_unsent".into();
                    } else if g.phase == "submitting" {
                        g.phase = "uncertain".into();
                    }
                }
                view(&p)
            }
            LiveContextCommand::Guide {
                generation,
                id,
                basis,
                mode,
                text,
                supersedes,
                ..
            } => {
                uuid(&id)?;
                bounded(&text, 8192)?;
                if generation != p.generation
                    || basis > p.incorporated
                    || !matches!(mode.as_str(), "context_only" | "spoken_offer")
                {
                    bail!("Live guidance needs the selected generation and an incorporated basis");
                }
                if let Some(old) = p.guidance.iter().find(|g| g.id == id) {
                    if old.generation != generation
                        || old.basis != basis
                        || old.mode != mode
                        || old.checkpointed_text_hash.as_ref().map_or_else(
                            || Ok(old.text != text),
                            |digest| hash(&text).map(|candidate| &candidate != digest),
                        )?
                        || old.supersedes != supersedes
                    {
                        bail!("Live guidance identity cannot be rewritten");
                    }
                    return Ok(json!({"dialogue":p.dialogue,"guidance":old}));
                }
                if p.closed || p.guidance.len() >= 64 {
                    bail!("Live guidance closed or retained bound reached");
                }
                if let Some(old) = supersedes.as_ref() {
                    let previous = p
                        .guidance
                        .iter_mut()
                        .find(|g| &g.id == old)
                        .context("Superseded guidance missing")?;
                    if previous.phase != "pending" {
                        bail!("Only known-unsent guidance can be superseded");
                    }
                    previous.phase = "superseded".into();
                }
                let guide = Guidance {
                    id,
                    generation,
                    basis,
                    mode,
                    text,
                    supersedes,
                    phase: "pending".into(),
                    sender_instance: None,
                    incorporated_revision: None,
                    checkpointed_text_hash: None,
                };
                let result = json!({"dialogue":p.dialogue,"guidance":guide});
                p.guidance.push(guide);
                result
            }
            LiveContextCommand::GuideStatus { id, .. } => {
                let guide = p
                    .guidance
                    .iter()
                    .find(|g| g.id == id)
                    .context("Live guidance missing")?;
                return Ok(
                    json!({"dialogue":p.dialogue,"guidance":guide,"meaning":"sent is a socket-write receipt; application and physical hearing are not established"}),
                );
            }
            LiveContextCommand::Guidance { generation, .. } => {
                if generation != p.generation {
                    bail!("Live producer generation differs");
                }
                let mut result = view(&p);
                result["guidance"] = if p.closed {
                    Value::Null
                } else {
                    json!(
                        p.guidance
                            .iter()
                            .find(|g| g.phase == "pending" && g.generation == p.generation)
                    )
                };
                // Polling a pending source is a read, not another DB-change
                // event that would recursively wake the source watcher.
                return Ok(result);
            }
            LiveContextCommand::GuidanceBegin { generation, id, .. } => {
                if p.closed || generation != p.generation {
                    bail!("Live guidance producer retired");
                }
                let g = p
                    .guidance
                    .iter_mut()
                    .find(|g| g.id == id)
                    .context("Live guidance missing")?;
                if g.phase != "pending" || g.generation != generation {
                    bail!("Live guidance is not known-unsent");
                }
                g.phase = "submitting".into();
                g.sender_instance = Some(self.instance_id.clone());
                let mut result = view(&p);
                result["guidance"] = json!(p.guidance.iter().find(|g| g.id == id));
                result
            }
            LiveContextCommand::GuidanceOutcome {
                generation,
                id,
                outcome,
                ..
            } => {
                if generation != p.generation {
                    bail!("Live producer generation differs");
                }
                let next = match outcome.as_str() {
                    "sent" => "sent",
                    "unsent" => "pending",
                    "uncertain" => "uncertain",
                    _ => bail!("No provider-applied receipt is available"),
                };
                let g = p
                    .guidance
                    .iter_mut()
                    .find(|g| g.id == id)
                    .context("Live guidance missing")?;
                if g.generation != generation {
                    bail!("Live guidance belongs to another provider generation");
                }
                if g.phase != next {
                    if !matches!(g.phase.as_str(), "submitting" | "uncertain") {
                        bail!("Live guidance outcome cannot overwrite a settled receipt");
                    }
                    if p.closed && next == "pending" {
                        g.phase = "retired_unsent".into();
                    } else {
                        g.phase = next.into();
                    }
                }
                let mut result = view(&p);
                result["guidance"] = json!(p.guidance.iter().find(|g| g.id == id));
                result
            }
            LiveContextCommand::Read { full, .. } => freeze(&mut p, full)?,
            LiveContextCommand::Part {
                revision, offset, ..
            } => page(&mut p, &revision, offset)?,
            LiveContextCommand::Incorporate { revision, .. } => {
                let r = p.range.as_ref().context("No frozen Live range")?;
                if r.revision != revision
                    || r.supplied != r.body.chars().count()
                    || r.from > p.incorporated + 1
                    || r.through < p.incorporated
                {
                    bail!("Live incorporation requires the complete contiguous frozen range");
                }
                p.incorporated = r.through;
                if r.full {
                    p.full_incorporated_revision = Some(r.revision.clone());
                    p.checkpoint_read = Some(CheckpointRead {
                        request_revision: r.checkpoint_request_revision.clone(),
                        through: r.through,
                    });
                    // Only an exact full-read ACK observes guidance. Language
                    // incorporation alone cannot retire control context that
                    // arrived later or changed send disposition during reading.
                    let content: Value = serde_json::from_str(&r.body)?;
                    if let Some(guides) = content["guidance"].as_array() {
                        for supplied in guides {
                            if let Some(g) = p.guidance.iter_mut().find(|g| supplied["id"] == g.id)
                            {
                                let current = guidance_context(g);
                                if *supplied == current {
                                    g.incorporated_revision = Some(hash(&current)?);
                                }
                            }
                        }
                    }
                }
                if let Some(request) = p.checkpoint_request.as_mut()
                    && r.checkpoint_generation.as_ref() == Some(&request.generation)
                    && r.checkpoint_request_revision == request.revision
                {
                    request.acknowledged = true;
                }
                for receipt in &mut p.native_returns {
                    if receipt.envelope["revision"] == revision {
                        receipt.reported_revision = Some(revision.clone());
                        // The exact text stays in events until checkpointing;
                        // completed transport metadata must not retain a second
                        // full copy of every historical batch indefinitely.
                        if let Some(envelope) = receipt.envelope.as_object_mut() {
                            envelope.remove("content");
                            envelope.insert("incorporated".into(), json!(true));
                        }
                    }
                }
                p.range = None;
                view(&p)
            }
            LiveContextCommand::Checkpoint {
                revision,
                through,
                text,
                request_revision,
                ..
            } => {
                bounded(&text, 65536)?;
                if let Some(q) = &p.checkpoint_request {
                    if request_revision != q.revision
                        || (q.revision.is_some()
                            && (!q.acknowledged
                                || !p.checkpoint_read.as_ref().is_some_and(|r| {
                                    r.request_revision == q.revision
                                        && r.through == through
                                        && through >= q.requested_through
                                })))
                    {
                        bail!(
                            "Live checkpoint requires the exact request and complete full-read ACK"
                        );
                    }
                } else if request_revision.is_some() {
                    bail!("Live checkpoint request no longer exists");
                }
                if revision != p.checkpoint.revision
                    || through < p.checkpoint.through
                    || through > p.incorporated
                {
                    bail!(
                        "Live checkpoint must represent an incorporated prefix of its current basis"
                    );
                }
                let next = hash(&json!([
                    &p.checkpoint,
                    through,
                    &text,
                    p.events
                        .iter()
                        .filter(|e| e.sequence <= through)
                        .collect::<Vec<_>>()
                ]))?;
                p.checkpoint = Checkpoint {
                    through,
                    text,
                    revision: next,
                };
                p.events.retain(|e| e.sequence > through);
                if p.range.as_ref().is_some_and(|r| {
                    r.full
                        && r.through <= through
                        && r.supplied == r.body.chars().count()
                        && p.full_incorporated_revision.as_ref() == Some(&r.revision)
                }) {
                    // Re-reading an IDENTICAL already-incorporated snapshot
                    // does not resurrect a reader after semantic retirement.
                    // A new/changed/unread range keeps its existing ACK gate.
                    p.range = None;
                }
                for g in &mut p.guidance {
                    if g.basis <= through
                        && g.checkpointed_text_hash.is_none()
                        && matches!(
                            g.phase.as_str(),
                            "sent" | "uncertain" | "retired_unsent" | "superseded"
                        )
                        && g.incorporated_revision.as_ref() == Some(&hash(&guidance_context(g))?)
                    {
                        // The compact receipt remains immutable/idempotent.
                        // Text already represented by this semantic checkpoint
                        // must not inflate every future seed or be sent again.
                        g.checkpointed_text_hash = Some(hash(&g.text)?);
                        g.text.clear();
                        g.incorporated_revision = None;
                    }
                }
                if p.closed && p.checkpoint.through == p.high && p.checkpoint_request.is_some() {
                    // Validate the COMPLETE reconnect envelope transactionally,
                    // before retiring its exact source events or guidance.
                    resume_content(&tx, &p, &p.generation)?;
                }
                if !p.closed && p.checkpoint_request.is_some() {
                    // A pressure checkpoint must fit its irreducible provider
                    // envelope BEFORE exact source text is retired. Guidance
                    // has separate incorporation/settlement gates; do not reject
                    // the checkpoint because unrelated guidance is still pending.
                    let mut seed = rollover_content(&p);
                    seed["guidance"] = json!([]);
                    let bytes = serde_json::to_vec(&seed)?.len();
                    if bytes > MAX_ROLLOVER_SEED {
                        bail!(
                            "Live pressure checkpoint needs {bytes} serialized continuity bytes (limit {MAX_ROLLOVER_SEED}); shorten its text before committing. Exact context remains retained"
                        );
                    }
                }
                let complete = p.checkpoint_request.as_ref().is_some_and(|q| {
                    q.acknowledged
                        && through >= q.requested_through
                        && p.checkpoint_read.as_ref().is_some_and(|r| {
                            r.request_revision == q.revision && r.through == through
                        })
                });
                if complete {
                    p.checkpoint_request.as_mut().unwrap().committed = true;
                    // Keep a nonshrinking checkpoint from retriggering on its
                    // own write. New canonical activity plus meaningful growth
                    // is required, even if the summary misses the target.
                    p.continuation.rearm_bytes = continuation_content(&p).to_string().len();
                }
                // Frozen readers keep their exact snapshot even when a newly
                // committed checkpoint retires the represented mutable projection.
                view(&p)
            }
        };
        save(&tx, &p)?;
        tx.commit()?;
        Ok(result)
    }
}

/// Reserve one coalesced context range through the existing native dispatcher.
/// No new source is discovered by transport recovery.
pub(in crate::store) fn reserve_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    dialogue: &str,
    instance: &str,
) -> Result<Option<Value>> {
    let mut p = load(conn, dialogue, human, entry)?;
    if (p.incorporated >= p.high && p.checkpoint_request.as_ref().is_none_or(|q| q.acknowledged))
        || p.range.as_ref().is_some_and(|r| r.full)
    {
        return Ok(None);
    }
    let evidence = freeze(&mut p, false)?;
    let revision = evidence["range"]["revision"]
        .as_str()
        .context("Missing frozen revision")?;
    let id = format!("foreground:{}:{}", p.dialogue, revision);
    if p.native_returns.iter().any(|r| r.id == id) {
        return Ok(None);
    }
    p.native_returns.push(super::workflows::WorkflowReturn {
        id,
        workflow: String::new(),
        attention_generation: None,
        reported_revision: None,
        envelope: evidence["range"].clone(),
        phase: "reserved".into(),
        local: None,
        collection_local: None,
        native_turn: None,
        instance: instance.into(),
        attempts: 1,
        retry_after: None,
    });
    save(conn, &p)?;
    Ok(Some(serde_json::to_value(&p)?))
}
pub(in crate::store) fn save_returns_on(
    conn: &Connection,
    dialogue: &str,
    returns: &[super::workflows::WorkflowReturn],
) -> Result<()> {
    let raw: String = conn.query_row(
        "SELECT doc FROM live_context WHERE dialogue=?1",
        [dialogue],
        |r| r.get(0),
    )?;
    let mut p: Projection = serde_json::from_str(&raw)?;
    // Change transport fields only; appends/checkpoints committed since the
    // native offer must not be overwritten by a copied parent document.
    p.native_returns = returns.to_vec();
    // Binding consolidation has already retained the context-only lifetime
    // fence. Release only accepted, incorporated transport records with NO
    // remaining collector binding. Never retire uncertainty or an active
    // observation merely because its language has been checkpointed.
    if p.native_returns.iter().any(|r| {
        r.reported_revision.is_some()
            && matches!(r.phase.as_str(), "accepted" | "accepted_reconciled")
    }) {
        let mut q = conn.prepare("SELECT DISTINCT j.value FROM bot_state b JOIN json_each(CASE WHEN json_valid(b.value) THEN b.value ELSE '[]' END) j WHERE b.key GLOB 'workflow_return_local:*' AND j.type='text' AND j.value GLOB ?1")?;
        let bound = q
            .query_map([format!("foreground:{}:*", p.dialogue)], |r| {
                r.get::<_, String>(0)
            })?
            .collect::<rusqlite::Result<BTreeSet<_>>>()?;
        p.native_returns.retain(|r| {
            r.reported_revision.is_none()
                || !matches!(r.phase.as_str(), "accepted" | "accepted_reconciled")
                || bound.contains(&r.id)
        });
    }
    save(conn, &p)
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fixture {
        file: tempfile::NamedTempFile,
        store: Store,
        entry: SessionKey,
        dialogue: String,
        generation: String,
        binding: String,
    }
    impl Fixture {
        fn new() -> Self {
            let file = tempfile::NamedTempFile::new().unwrap();
            let defaults = super::super::tests::defaults();
            let store = Store::open(file.path(), &[100], &defaults).unwrap();
            let entry = SessionKey::new(100, Some(1));
            store.ensure_session(entry, 100, &defaults).unwrap();
            store
                .set_session_codex_thread(entry, "entry-native")
                .unwrap();
            let binding = store
                .interaction_presentation_list(100, entry, 0, 0)
                .unwrap()["binding"]
                .as_str()
                .unwrap()
                .to_owned();
            let f = Self {
                file,
                store,
                entry,
                dialogue: Uuid::now_v7().to_string(),
                generation: Uuid::now_v7().to_string(),
                binding,
            };
            f.call(json!({"action":"open","dialogue":f.dialogue,"generation":f.generation,"binding":f.binding})).unwrap();
            f
        }
        fn call(&self, value: Value) -> Result<Value> {
            self.store
                .live_context(100, self.entry, serde_json::from_value(value)?)
        }
        fn append(&self, source: &str, text: &str) -> Result<Value> {
            self.call(
                json!({"action":"append","dialogue":self.dialogue,"generation":self.generation,
                "source":source,"role":"assistant","text":text,"interrupted":true}),
            )
        }
        fn read(&self, full: bool) -> Value {
            self.call(json!({"action":"read","dialogue":self.dialogue,"full":full}))
                .unwrap()
        }
        fn read_all(&self, full: bool) -> Value {
            let initial = self.read(full);
            if initial["range"]["complete"] == true {
                return initial;
            }
            let revision = initial["range"]["revision"].clone();
            let mut offset = 0;
            let mut text = String::new();
            loop {
                let page=self.call(json!({"action":"part","dialogue":self.dialogue,"revision":revision,"offset":offset})).unwrap();
                text.push_str(page["range"]["text"].as_str().unwrap());
                if page["range"]["more"] == false {
                    assert!(serde_json::from_str::<Value>(&text).is_ok());
                    return page;
                }
                offset = page["range"]["next"].as_u64().unwrap();
            }
        }
        fn ack(&self, page: &Value) -> Result<Value> {
            self.call(json!({"action":"incorporate","dialogue":self.dialogue,"revision":page["range"]["revision"]}))
        }
        fn checkpoint(&self, basis: &Value, through: u64) -> Value {
            self.call(json!({"action":"checkpoint","dialogue":self.dialogue,
                "revision":basis["checkpoint_revision"],"through":through,
                "request_revision":basis["checkpoint_request"]["revision"],
                "text":format!("Purpose and unresolved effects through {through}; originals remain authoritative.")})).unwrap()
        }
    }

    fn continuation_request(f: &Fixture) -> Value {
        f.call(json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"continuation","tokens":null,
            "usage_kind":"unknown","request_id":Uuid::now_v7().to_string()}))
            .unwrap()
    }

    #[test]
    fn repeated_active_checkpoints_keep_new_tail_and_fence_stale_writers() {
        let f = Fixture::new();
        let mut old_writer = None;
        for _ in 0..2 {
            for _ in 0..2 {
                f.append(&Uuid::now_v7().to_string(), &"meaning ".repeat(1200))
                    .unwrap();
            }
            let requested = continuation_request(&f);
            assert_eq!(requested["checkpoint_request"]["reason"], "continuation");
            assert_eq!(requested["checkpoint_request"]["committed"], false);
            if let Some(writer) = old_writer.take() {
                assert!(
                    f.call(writer).is_err(),
                    "Old checkpoint CAS/request must not commit again"
                );
            }
            let full = f.read_all(true);
            let through = full["range"]["through"].as_u64().unwrap();
            f.append(
                &Uuid::now_v7().to_string(),
                "New correction arrived while reading",
            )
            .unwrap();
            let ack = f.ack(&full).unwrap();
            assert_eq!(ack["checkpoint_request"]["acknowledged"], true);
            // An ACK is not completion and new canonical arrivals do not launch
            // another semantic operation while the writer is outstanding.
            let coalesced = continuation_request(&f);
            assert_eq!(coalesced["checkpoint_request"], ack["checkpoint_request"]);
            let mut writer = full["checkpoint_writer"]["arguments"].clone();
            writer["text"] = json!(
                "Same identity and purpose; violet correction, unresolved copper bell and exact source references."
            );
            let mut missing_nonce = writer.clone();
            missing_nonce
                .as_object_mut()
                .unwrap()
                .remove("request_revision");
            assert!(f.call(missing_nonce).is_err());
            let done = f.call(writer.clone()).unwrap();
            assert_eq!(done["checkpoint_request"]["committed"], true);
            assert_eq!(done["checkpointed"], through);
            assert_eq!(done["high"], through + 1);
            assert_eq!(done["generation"], f.generation);
            assert!(done["rollover"].is_null());
            old_writer = Some(writer);
        }
        let full = f.read_all(true);
        let ack = f.ack(&full).unwrap();
        f.checkpoint(&ack, ack["high"].as_u64().unwrap());
        let basis = f
            .call(json!({"action":"rollover_read","dialogue":f.dialogue,
            "generation":f.generation}))
            .unwrap();
        assert!(basis["rollover_basis"]["content"].is_object());
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let resumed = f
            .call(json!({"action":"resume_read","dialogue":f.dialogue,
            "generation":f.generation}))
            .unwrap();
        assert!(resumed["resume"]["bytes"].as_u64().unwrap() < MAX_ROLLOVER_SEED as u64);
    }

    #[test]
    fn incremental_ack_cannot_write_a_semantic_request_or_steal_its_operation() {
        let f = Fixture::new();
        for _ in 0..2 {
            f.append(&Uuid::now_v7().to_string(), &"x".repeat(10000))
                .unwrap();
        }
        let old = f.read_all(true);
        let requested = continuation_request(&f);
        let ack = f.ack(&old).unwrap();
        assert_eq!(ack["checkpoint_request"]["acknowledged"], false);
        let incremental = f.read_all(false);
        let ack = f.ack(&incremental).unwrap();
        // Incremental incorporation observes pressure but never proves that
        // the complete prior checkpoint/guidance was read by the writer.
        let attempt = json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":ack["checkpoint_revision"],"through":ack["high"],
            "request_revision":requested["checkpoint_request"]["revision"],"text":"Unverified summary"});
        assert!(f.call(attempt).is_err());
        let pressure = f
            .call(json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"tokens","tokens":48000,"usage_kind":"observed"}))
            .unwrap();
        assert_eq!(pressure["checkpoint_request"], ack["checkpoint_request"]);
        let full = f.read_all(true);
        f.ack(&full).unwrap();
        let mut writer = full["checkpoint_writer"]["arguments"].clone();
        writer["text"] = json!("Verified complete meaning.");
        f.call(writer).unwrap();
        let pressure = f
            .call(json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"tokens","tokens":48000,"usage_kind":"observed"}))
            .unwrap();
        assert_eq!(pressure["checkpoint_request"]["reason"], "tokens");
    }

    #[test]
    fn nonshrinking_summary_needs_fresh_meaning_and_growth_and_has_finite_requests() {
        let f = Fixture::new();
        for _ in 0..2 {
            f.append(&Uuid::now_v7().to_string(), &"x".repeat(10000))
                .unwrap();
        }
        continuation_request(&f);
        let full = f.read_all(true);
        f.ack(&full).unwrap();
        let mut writer = full["checkpoint_writer"]["arguments"].clone();
        writer["text"] = json!("y".repeat(20000));
        let done = f.call(writer).unwrap();
        assert_eq!(done["continuation"]["eligible"], false);
        let no_loop = continuation_request(&f);
        assert_eq!(no_loop["continuation"]["requests"], 1);
        f.append(&Uuid::now_v7().to_string(), "A small fresh word")
            .unwrap();
        assert_eq!(continuation_request(&f)["continuation"]["requests"], 1);
        f.append(&Uuid::now_v7().to_string(), &"z".repeat(5000))
            .unwrap();
        assert_eq!(continuation_request(&f)["continuation"]["requests"], 2);
        // Existing bounded projection is the durable authority, not a Python
        // process counter that a restart or provider replacement can reset.
        let conn = Connection::open(f.file.path()).unwrap();
        let mut p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
        p.continuation.requests = MAX_CONTINUATION_REQUESTS;
        p.checkpoint_request.as_mut().unwrap().committed = true;
        p.continuation.activity = None;
        save(&conn, &p).unwrap();
        let capped = continuation_request(&f);
        assert_eq!(
            capped["continuation"]["requests"],
            MAX_CONTINUATION_REQUESTS
        );
        assert_eq!(capped["continuation"]["eligible"], false);
    }

    #[test]
    fn active_continuation_measurement_matches_exact_closed_unicode_envelope() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), &"🌿\"\\".repeat(1500))
            .unwrap();
        let active = f
            .call(json!({"action":"sync","dialogue":f.dialogue,
            "generation":f.generation,"assistant":[]}))
            .unwrap();
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let resumed = f
            .call(json!({"action":"resume_read","dialogue":f.dialogue,
            "generation":f.generation}))
            .unwrap();
        assert_eq!(active["continuation"]["bytes"], resumed["resume"]["bytes"]);
        assert_eq!(
            active["continuation"]["revision"],
            resumed["resume"]["revision"]
        );
        assert_eq!(resumed["incorporated"], 0);
    }

    #[test]
    fn derived_caption_keeps_parent_after_checkpoint_close_and_deduplicates() {
        let f = Fixture::new();
        let parent = Uuid::now_v7().to_string();
        let source = Uuid::now_v7().to_string();
        f.call(
            json!({"action":"sync","dialogue":f.dialogue,"generation":f.generation,
            "assistant":[{"source":parent,"text":"","interrupted":true,
                "audio_without_transcript":{"pcm_sha256":"b".repeat(64),"generated_bytes":640}}]}),
        )
        .unwrap();
        let ack = f.ack(&f.read(true)).unwrap();
        f.checkpoint(&ack, 1);
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let request = json!({"action":"sync","dialogue":f.dialogue,"generation":f.generation,
            "assistant":[{"source":source,"text":"Approximate recovered words.","interrupted":true,
                "derived_caption":{"parent_source":parent,"pcm_sha256":"b".repeat(64),
                    "generated_bytes":640,"asr_result_sha256":"c".repeat(64),"draft":true}}]});
        let first = f.call(request.clone()).unwrap();
        assert_eq!(first["high"], 2);
        assert_eq!(
            first["closed"], true,
            "Late captions do not reopen audio or guidance"
        );
        assert_eq!(first["new_human_sources"], 0);
        assert_eq!(
            f.call(request.clone()).unwrap()["assistant_receipts"][0]["fresh"],
            false
        );
        let page = f.read(true);
        let content = &page["range"]["content"];
        assert_eq!(content["checkpoint"]["through"], 1);
        assert_eq!(
            content["events"][0]["derived_caption"]["parent_source"],
            parent
        );
        assert_eq!(content["events"][0]["role"], "assistant");
        for (field, value) in [
            ("parent_source", json!(Uuid::now_v7().to_string())),
            ("pcm_sha256", json!("d".repeat(64))),
            ("generated_bytes", json!(642)),
            ("asr_result_sha256", json!("invalid")),
            ("draft", json!(false)),
        ] {
            let mut bad = request.clone();
            bad["assistant"][0]["derived_caption"][field] = value;
            assert!(f.call(bad).is_err());
        }
        let mut second = request.clone();
        second["assistant"][0]["source"] = json!(Uuid::now_v7().to_string());
        assert!(
            f.call(second).is_err(),
            "Only one derived source per missing-caption parent"
        );
        let mut rewrite = request;
        rewrite["assistant"][0]["text"] = json!("Different draft");
        assert!(f.call(rewrite).is_err());
        assert!(
            f.append(&Uuid::now_v7().to_string(), "New independent speech")
                .is_err()
        );
        let ack = f.ack(&page).unwrap();
        assert_eq!(f.checkpoint(&ack, 2)["checkpointed"], 2);
    }

    #[test]
    fn missing_assistant_caption_is_an_idempotent_bounded_observation_not_language() {
        let f = Fixture::new();
        let source = Uuid::now_v7().to_string();
        let observation = json!({"pcm_sha256":"b".repeat(64),"generated_bytes":285600});
        let request = json!({"action":"sync","dialogue":f.dialogue,"generation":f.generation,
            "assistant":[{"source":source,"text":"","interrupted":false,
                "audio_without_transcript":observation}]});
        let first = f.call(request.clone()).unwrap();
        assert_eq!(first["high"], 1);
        let repeated = f.call(request.clone()).unwrap();
        assert_eq!(repeated["high"], 1);
        assert_eq!(repeated["assistant_receipts"][0]["fresh"], false);
        let pin = f
            .call(json!({"action":"pin_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let event = &pin["pin"]["content"]["events"][0];
        assert_eq!(event["role"], "assistant");
        assert_eq!(event["text"], "");
        assert_eq!(event["audio_without_transcript"], observation);
        let mut rewrite = request.clone();
        rewrite["assistant"][0]["audio_without_transcript"]["pcm_sha256"] = json!("c".repeat(64));
        assert!(f.call(rewrite).is_err());
        for invalid in [json!(0), json!(3), json!(14400002)] {
            let mut bad = request.clone();
            bad["assistant"][0]["source"] = json!(Uuid::now_v7().to_string());
            bad["assistant"][0]["audio_without_transcript"]["generated_bytes"] = invalid;
            assert!(f.call(bad).is_err());
        }
        let mut invented = request.clone();
        invented["assistant"][0]["text"] = json!("Unknown generated words");
        assert!(f.call(invented).is_err());
        let mut unmarked = request;
        unmarked["assistant"][0]
            .as_object_mut()
            .unwrap()
            .remove("audio_without_transcript");
        assert!(f.call(unmarked).is_err());
        let legacy_id = Uuid::now_v7().to_string();
        let legacy = f.append(&legacy_id, "Existing exact words").unwrap();
        assert_eq!(
            legacy["revision"],
            hash(&json!([
                legacy_id,
                "assistant",
                "Existing exact words",
                true,
                None::<i64>
            ]))
            .unwrap()
        );
    }

    #[test]
    fn reconnect_reads_closed_checkpoint_and_tail_without_consuming_reader() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Original purpose")
            .unwrap();
        let ack = f.ack(&f.read(true)).unwrap();
        f.checkpoint(&ack, 1);
        f.append(&Uuid::now_v7().to_string(), "Later exact correction")
            .unwrap();
        let frozen = f.read(false);
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let raw = || {
            f.store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT doc FROM live_context WHERE dialogue=?1",
                    [&f.dialogue],
                    |r| r.get::<_, String>(0),
                )
                .unwrap()
        };
        let before = raw();
        let request =
            json!({"action":"resume_read","dialogue":f.dialogue,"generation":f.generation});
        let result = f.call(request.clone()).unwrap();
        assert_eq!(result["closed"], true);
        assert_eq!(result["resume"]["content"]["checkpoint"]["through"], 1);
        assert_eq!(
            result["resume"]["content"]["events"][0]["text"],
            "Later exact correction"
        );
        assert_eq!(
            result["resume"]["content"]["events"][0]["interrupted"],
            true
        );
        assert_eq!(
            before,
            raw(),
            "Reconnect reads must not change retained state"
        );
        assert_eq!(
            f.call(request).unwrap(),
            result,
            "Exact reads are repeatable"
        );
        assert_eq!(f.ack(&frozen).unwrap()["incorporated"], 2);
    }

    #[test]
    fn reconnect_seed_survives_second_visit_and_rejects_changed_source_or_owner() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Remember the violet bridge")
            .unwrap();
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let basis = f
            .call(json!({"action":"resume_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let next = Uuid::now_v7().to_string();
        let generation = Uuid::now_v7().to_string();
        let request = json!({"action":"open","dialogue":next,"generation":generation,"binding":f.binding,
            "resume":{"dialogue":f.dialogue,"generation":f.generation,"revision":basis["resume"]["revision"]}});
        let mut changed = request.clone();
        changed["resume"]["revision"] = json!("a".repeat(64));
        assert!(f.call(changed).is_err());
        let foreign: LiveContextCommand = serde_json::from_value(request.clone()).unwrap();
        assert!(f.store.live_context(101, f.entry, foreign).is_err());
        let opened = f.call(request.clone()).unwrap();
        assert_eq!(f.call(request).unwrap(), opened);
        f.call(json!({"action":"append","dialogue":next,"generation":generation,
            "source":Uuid::now_v7().to_string(),"role":"assistant","text":"Keep the copper bell too","interrupted":true})).unwrap();
        f.call(json!({"action":"close","dialogue":next,"generation":generation}))
            .unwrap();
        let second = f
            .call(json!({"action":"resume_read","dialogue":next,"generation":generation}))
            .unwrap();
        let inherited = second["resume"]["content"]["checkpoint"]["text"]
            .as_str()
            .unwrap();
        assert!(inherited.contains("Remember the violet bridge"));
        assert_eq!(
            second["resume"]["content"]["events"][0]["text"],
            "Keep the copper bell too"
        );
        assert_eq!(
            second["incorporated"], 0,
            "Copying does not acknowledge either visit"
        );
    }

    #[test]
    fn repeated_empty_reconnects_do_not_reescape_inherited_language() {
        let f = Fixture::new();
        let exact = "Keep \"violet\" and \\ copper\nwith its exact newline";
        f.append(&Uuid::now_v7().to_string(), exact).unwrap();
        let mut dialogue = f.dialogue.clone();
        let mut generation = f.generation.clone();
        let mut inherited = None;
        for _ in 0..20 {
            f.call(json!({"action":"close","dialogue":dialogue,"generation":generation}))
                .unwrap();
            let basis = f
                .call(json!({"action":"resume_read","dialogue":dialogue,"generation":generation}))
                .unwrap();
            assert!(basis["resume"]["bytes"].as_u64().unwrap() < 4096);
            let next = Uuid::now_v7().to_string();
            let successor = Uuid::now_v7().to_string();
            f.call(json!({"action":"open","dialogue":next,"generation":successor,"binding":f.binding,
                "resume":{"dialogue":dialogue,"generation":generation,"revision":basis["resume"]["revision"]}})).unwrap();
            let conn = f.store.conn.lock().unwrap();
            let p = load(&conn, &next, 100, f.entry).unwrap();
            if let Some(previous) = &inherited {
                assert_eq!(&p.checkpoint.text, previous);
            } else {
                let first: Value = serde_json::from_str(&p.checkpoint.text).unwrap();
                assert_eq!(first["events"][0]["text"], exact);
                inherited = Some(p.checkpoint.text.clone());
            }
            assert_eq!(p.incorporated, 0);
            drop(conn);
            dialogue = next;
            generation = successor;
        }
    }

    #[test]
    fn reconnect_refuses_active_wrong_generation_and_oversize_without_clipping() {
        let f = Fixture::new();
        let request =
            json!({"action":"resume_read","dialogue":f.dialogue,"generation":f.generation});
        assert!(f.call(request.clone()).is_err());
        for _ in 0..2 {
            f.append(&Uuid::now_v7().to_string(), &"a".repeat(15000))
                .unwrap();
        }
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let mut wrong = request.clone();
        wrong["generation"] = json!(Uuid::now_v7().to_string());
        assert!(f.call(wrong).is_err());
        let needed = f.call(request).unwrap();
        assert!(needed["resume"].is_null());
        assert_eq!(needed["resume_requirement"]["max_bytes"], MAX_ROLLOVER_SEED);
        assert!(needed["resume_requirement"]["bytes"].as_u64().unwrap() > MAX_ROLLOVER_SEED as u64);
        let exact = f.read(true);
        assert_eq!(exact["incorporated"], 0);
        assert_eq!(exact["high"], 2);
    }

    #[test]
    fn closed_reconnect_requests_semantics_and_rejects_unseedable_summary_atomically() {
        let f = Fixture::new();
        for _ in 0..2 {
            f.append(&Uuid::now_v7().to_string(), &"x".repeat(15000))
                .unwrap();
        }
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let request = json!({"action":"checkpoint_needed","dialogue":f.dialogue,"generation":f.generation,
            "reason":"reconnect","tokens":null,"usage_kind":"unknown","request_id":Uuid::now_v7().to_string()});
        let needed = f.call(request.clone()).unwrap();
        assert_eq!(f.call(request).unwrap(), needed);
        assert!(needed["checkpoint_request"]["revision"].is_string());
        let full = f.read_all(true);
        let acknowledged = f.ack(&full).unwrap();
        assert_eq!(acknowledged["checkpoint_request"]["acknowledged"], true);
        let oversized = json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":acknowledged["checkpoint_revision"],"request_revision":acknowledged["checkpoint_request"]["revision"],"through":2,"text":"\"".repeat(13000)});
        assert!(f.call(oversized).is_err());
        let retained = f.read_all(true);
        assert_eq!(retained["checkpointed"], 0);
        f.ack(&retained).unwrap();
        f.call(json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":acknowledged["checkpoint_revision"],"request_revision":acknowledged["checkpoint_request"]["revision"],"through":2,"text":"Keep the corrected violet key and unresolved question."})).unwrap();
        let ready = f
            .call(json!({"action":"resume_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert!(ready["resume"]["bytes"].as_u64().unwrap() <= MAX_ROLLOVER_SEED as u64);
        assert_eq!(ready["resume"]["content"]["checkpoint"]["through"], 2);
        assert!(ready["resume_requirement"].is_null());
        assert!(
            ready["resume"]["content"]["events"]
                .as_array()
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn closed_pressure_cannot_retire_oversized_sources_and_upgrades_to_reconnect() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), &"x".repeat(15000))
            .unwrap();
        f.call(json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"tokens","tokens":48000,"usage_kind":"observed"}))
            .unwrap();
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let full = f.read_all(true);
        let ack = f.ack(&full).unwrap();
        let checkpoint = json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":ack["checkpoint_revision"],"through":1,"text":"\"".repeat(13000)});
        assert!(
            f.call(checkpoint).is_err(),
            "Closed active-pressure checkpoint retains capacity fence"
        );
        let retained = f.read_all(true);
        assert_eq!(retained["checkpointed"], 0);
        // Create an unacknowledged active request in a distinct producer too.
        f.ack(&retained).unwrap();
        let g = Fixture::new();
        g.append(&Uuid::now_v7().to_string(), "Exact pending source")
            .unwrap();
        g.call(json!({"action":"checkpoint_needed","dialogue":g.dialogue,
            "generation":g.generation,"reason":"lifetime","tokens":null,"usage_kind":"unknown"}))
            .unwrap();
        let old = g.read(true);
        g.call(json!({"action":"close","dialogue":g.dialogue,"generation":g.generation}))
            .unwrap();
        let requested = g
            .call(json!({"action":"checkpoint_needed","dialogue":g.dialogue,
            "generation":g.generation,"reason":"reconnect","tokens":null,"usage_kind":"unknown",
            "request_id":Uuid::now_v7().to_string()}))
            .unwrap();
        assert_eq!(requested["checkpoint_request"]["reason"], "reconnect");
        assert!(requested["checkpoint_request"]["revision"].is_string());
        assert_eq!(
            g.ack(&old).unwrap()["checkpoint_request"]["acknowledged"],
            false
        );
    }

    #[test]
    fn old_reconnect_reader_cannot_ack_a_later_explicit_attempt() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Pending source")
            .unwrap();
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let request = |id: String| {
            json!({"action":"checkpoint_needed","dialogue":f.dialogue,"generation":f.generation,
            "reason":"reconnect","tokens":null,"usage_kind":"unknown","request_id":id})
        };
        f.call(request(Uuid::now_v7().to_string())).unwrap();
        let first = f.read(true);
        f.ack(&first).unwrap();
        // An already-ACKed full reader still carries the first pressure identity.
        let old = f.read(true);
        f.call(request(Uuid::now_v7().to_string())).unwrap();
        let ack = f.ack(&old).unwrap();
        assert_eq!(ack["checkpoint_request"]["acknowledged"], false);
        let current = f.read(true);
        assert_ne!(
            old["range"]["checkpoint_request_revision"],
            current["range"]["checkpoint_request_revision"]
        );
        assert_eq!(
            f.ack(&current).unwrap()["checkpoint_request"]["acknowledged"],
            true
        );
    }

    #[test]
    fn owner_pin_keeps_exact_unincorporated_tail_without_changing_sol_reader() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "First exact source")
            .unwrap();
        let frozen = f.read(true);
        f.append(&Uuid::now_v7().to_string(), "Newer interrupted words")
            .unwrap();
        let request = json!({"action":"pin_read","dialogue":f.dialogue,"generation":f.generation});
        let before = {
            let conn = f.store.conn.lock().unwrap();
            conn.query_row(
                "SELECT doc FROM live_context WHERE dialogue=?1",
                [&f.dialogue],
                |r| r.get::<_, String>(0),
            )
            .unwrap()
        };
        let pin = f.call(request.clone()).unwrap();
        assert_eq!(pin["incorporated"], 0);
        assert_eq!(pin["pin"]["through"], 2);
        assert_eq!(pin["pin"]["content"]["events"].as_array().unwrap().len(), 2);
        assert_eq!(
            pin["pin"]["content"]["events"][1]["text"],
            "Newer interrupted words"
        );
        assert_eq!(pin["pin"]["content"]["events"][1]["interrupted"], true);
        let after = {
            let conn = f.store.conn.lock().unwrap();
            conn.query_row(
                "SELECT doc FROM live_context WHERE dialogue=?1",
                [&f.dialogue],
                |r| r.get::<_, String>(0),
            )
            .unwrap()
        };
        assert_eq!(
            before, after,
            "A pin read cannot mutate or wake the projection"
        );
        assert_eq!(f.ack(&frozen).unwrap()["incorporated"], 1);
        let still_exact = f.call(request.clone()).unwrap();
        assert_eq!(
            still_exact["pin"]["revision"], pin["pin"]["revision"],
            "An ACK alone cannot retire exact words"
        );
        f.checkpoint(&frozen, 1);
        let compact = f.call(request).unwrap();
        assert_eq!(compact["pin"]["checkpointed"], 1);
        assert_eq!(compact["pin"]["content"]["checkpoint"]["through"], 1);
        assert_eq!(
            compact["pin"]["content"]["events"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            compact["pin"]["content"]["events"][0]["text"],
            "Newer interrupted words"
        );
        assert_ne!(compact["pin"]["revision"], pin["pin"]["revision"]);
    }

    #[test]
    fn owner_pin_rejects_oversize_closed_and_wrong_generation_without_clipping() {
        let f = Fixture::new();
        let request = json!({"action":"pin_read","dialogue":f.dialogue,"generation":f.generation});
        let mut wrong = request.clone();
        wrong["generation"] = json!(Uuid::now_v7().to_string());
        assert!(f.call(wrong).is_err());
        for _ in 0..4 {
            f.append(&Uuid::now_v7().to_string(), &"a".repeat(15000))
                .unwrap();
        }
        assert!(f.call(request.clone()).is_err());
        let exact = f.read(true);
        assert_eq!(exact["high"], 4);
        assert_eq!(exact["incorporated"], 0);
        assert!(exact["range"]["characters"].as_u64().unwrap() > MAX_PIN as u64);
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert!(f.call(request).is_err());
    }

    #[test]
    fn pressure_checkpoint_rejects_unseedable_escaped_text_without_retiring_sources() {
        let f = Fixture::new();
        let mut generation = f.generation.clone();
        for through in 1..=2 {
            let source = Uuid::now_v7().to_string();
            f.call(json!({"action":"append","dialogue":f.dialogue,"generation":generation,
                "source":source,"role":"assistant","text":format!("Exact correction {through}: información, not a work request."),"interrupted":true})).unwrap();
            f.call(
                json!({"action":"checkpoint_needed","dialogue":f.dialogue,"generation":generation,
                "reason":"tokens","tokens":105000,"usage_kind":"observed"}),
            )
            .unwrap();
            let full = f.read(true);
            assert_eq!(
                full["checkpoint_writer_notes"]["pressure_seed_max_bytes"],
                MAX_ROLLOVER_SEED
            );
            let ack = f.ack(&full).unwrap();
            let before: String = f
                .store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT doc FROM live_context WHERE dialogue=?1",
                    [&f.dialogue],
                    |r| r.get(0),
                )
                .unwrap();
            // The text fits its language limit, but JSON escaping makes the
            // complete continuity seed exceed the selected provider envelope.
            let result = f.call(json!({"action":"checkpoint","dialogue":f.dialogue,
                "revision":ack["checkpoint_revision"],"through":through,"text":"\"".repeat(13000)}));
            if result.is_ok() {
                assert!(f.call(json!({"action":"rollover_read","dialogue":f.dialogue,"generation":generation})).is_err());
            }
            assert!(
                result.is_err(),
                "An unseedable pressure checkpoint must not retire exact context"
            );
            let after: String = f
                .store
                .conn
                .lock()
                .unwrap()
                .query_row(
                    "SELECT doc FROM live_context WHERE dialogue=?1",
                    [&f.dialogue],
                    |r| r.get(0),
                )
                .unwrap();
            assert_eq!(
                before, after,
                "Known rejection keeps the reader, source and prior checkpoint unchanged"
            );
            let compact = f.checkpoint(&ack, through);
            assert_eq!(compact["checkpointed"], through);
            let basis = f
                .call(
                    json!({"action":"rollover_read","dialogue":f.dialogue,"generation":generation}),
                )
                .unwrap();
            let next = Uuid::now_v7().to_string();
            let settled = f.call(json!({"action":"rollover_commit","dialogue":f.dialogue,
                "generation":generation,"next_generation":next,"revision":basis["rollover_basis"]["revision"]})).unwrap();
            assert_eq!(settled["generation"], next);
            assert_eq!(settled["high"], through);
            assert!(settled["checkpoint_request"].is_null());
            generation = next;
        }
        let conn = f.store.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM interaction_instructions", [], |r| r
                .get::<_, i64>(
                0
            ))
            .unwrap(),
            0
        );
        assert_eq!(
            conn.query_row("SELECT count(*) FROM conversation_inputs", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }

    #[test]
    fn stored_checkpoints_without_pressure_keep_their_existing_language_bound() {
        for closed in [false, true] {
            let f = Fixture::new();
            f.append(&Uuid::now_v7().to_string(), "Retained source, no new work")
                .unwrap();
            let full = f.read(true);
            let ack = f.ack(&full).unwrap();
            if closed {
                f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
                    .unwrap();
            }
            let saved = f
                .call(json!({"action":"checkpoint","dialogue":f.dialogue,
                "revision":ack["checkpoint_revision"],"through":1,"text":"a".repeat(60000)}))
                .unwrap();
            assert_eq!(saved["checkpointed"], 1);
            assert_eq!(saved["closed"], closed);
        }
    }

    #[test]
    fn checkpoint_pressure_is_once_per_generation_and_not_acknowledged_by_an_older_range() {
        let f = Fixture::new();
        f.append(
            &Uuid::now_v7().to_string(),
            "Exact language before pressure",
        )
        .unwrap();
        let old = f.read(false);
        let request = json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"tokens","tokens":105000,"usage_kind":"observed"});
        let pressure = f.call(request.clone()).unwrap();
        let changes = f.store.conn.lock().unwrap().total_changes();
        assert_eq!(f.call(request).unwrap(), pressure);
        assert_eq!(f.store.conn.lock().unwrap().total_changes(), changes);
        assert_eq!(
            f.ack(&old).unwrap()["checkpoint_request"]["acknowledged"],
            false
        );
        let r = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        let output: Value = serde_json::from_str(&r.output).unwrap();
        assert_eq!(output["checkpoint_request"]["generation"], f.generation);
        assert_eq!(output["checkpoint_basis"]["through"], 1);
        let l = local(&f, "");
        linked(&f, &r, l);
        assert!(!f.store.workflow_native_visible(l).unwrap());
        f.call(output["after_incorporation"]["arguments"].clone())
            .unwrap();
        assert!(
            f.store
                .native_foreground_reserve(100, f.entry, &f.dialogue)
                .unwrap()
                .is_none()
        );
        let full = f.read(true);
        assert_eq!(
            full["range"]["content"]["events"][0]["text"],
            "Exact language before pressure"
        );
        let ack = f.ack(&full).unwrap();
        f.checkpoint(&ack, 1);
        let basis = f
            .call(json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let next = Uuid::now_v7().to_string();
        let new = f
            .call(
                json!({"action":"rollover_commit","dialogue":f.dialogue,"generation":f.generation,
            "next_generation":next,"revision":basis["rollover_basis"]["revision"]}),
            )
            .unwrap();
        assert!(new["checkpoint_request"].is_null());
    }

    #[test]
    fn empty_dialogue_requires_an_explicit_semantic_checkpoint_before_handover() {
        let f = Fixture::new();
        let read =
            json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation});
        assert!(f.call(read.clone()).is_err());
        f.call(json!({"action":"checkpoint_needed","dialogue":f.dialogue,
            "generation":f.generation,"reason":"lifetime","usage_kind":"unknown"}))
            .unwrap();
        let batch = f.read(false);
        f.ack(&batch).unwrap();
        let full = f.read(true);
        let ack = f.ack(&full).unwrap();
        f.checkpoint(&ack, 0);
        assert_eq!(f.call(read).unwrap()["rollover_basis"]["through"], 0);
    }

    #[test]
    fn exact_checkpoint_template_and_repeated_full_reader_do_not_block_handover() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Exact continuity word: ceibo")
            .unwrap();
        let full = f.read(true);
        assert_eq!(
            full["checkpoint_writer"]["arguments"]["revision"],
            full["checkpoint_revision"]
        );
        f.call(full["after_incorporation"]["arguments"].clone())
            .unwrap();
        let repeated = f.read(true);
        assert_eq!(repeated["range"]["revision"], full["range"]["revision"]);
        let mut writer = repeated["checkpoint_writer"]["arguments"].clone();
        writer["text"] =
            json!("Keep the exact continuity word ceibo; no work or memory write was requested.");
        f.call(writer).unwrap();
        assert!(
            f.call(
                json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation})
            )
            .is_ok()
        );
        f.append(&Uuid::now_v7().to_string(), "Later unincorporated language")
            .unwrap();
        let unseen = f.read(true);
        let current = f
            .call(json!({"action":"read","dialogue":f.dialogue,"full":true}))
            .unwrap();
        f.checkpoint(&current, 1);
        assert_eq!(
            f.read(true)["range"]["revision"],
            unseen["range"]["revision"],
            "A changed full range cannot borrow the old incorporation receipt"
        );
    }

    #[test]
    fn rollover_requires_exact_complete_checkpoint_and_preserves_once_only_sources() {
        let mut f = Fixture::new();
        let mut generation = f.generation.clone();
        for cycle in 1..=2 {
            let source = Uuid::now_v7().to_string();
            let append = json!({"action":"append","dialogue":f.dialogue,"generation":generation,
                "source":source,"role":"assistant","text":format!("Exact dialogue cycle {cycle}"),"interrupted":false});
            f.call(append.clone()).unwrap();
            let read =
                json!({"action":"rollover_read","dialogue":f.dialogue,"generation":generation});
            assert!(f.call(read.clone()).is_err());
            let batch = f.read(false);
            let ack = f.ack(&batch).unwrap();
            assert!(
                f.call(read.clone()).is_err(),
                "Incorporated text alone is not a checkpoint"
            );
            f.checkpoint(&ack, cycle);
            let changes = f.store.conn.lock().unwrap().total_changes();
            let basis = f.call(read.clone()).unwrap();
            assert_eq!(f.store.conn.lock().unwrap().total_changes(), changes);
            let next = Uuid::now_v7().to_string();
            let commit = json!({"action":"rollover_commit","dialogue":f.dialogue,"generation":generation,
                "next_generation":next,"revision":basis["rollover_basis"]["revision"]});
            let mut wrong = commit.clone();
            wrong["revision"] = json!("stale");
            assert!(f.call(wrong).is_err());
            if cycle == 2 {
                let mut reused = commit.clone();
                reused["next_generation"] = json!(f.generation);
                assert!(
                    f.call(reused).is_err(),
                    "A retired socket generation must never regain writer authority"
                );
            }
            let settled = f.call(commit.clone()).unwrap();
            assert_eq!(settled["generation"], next);
            assert_eq!(settled["rollover"]["through"], cycle);
            assert_eq!(
                f.call(commit).unwrap()["generation"],
                next,
                "Lost commit ACK is inspected under the same generation identity"
            );
            assert!(
                f.call(append.clone()).is_err(),
                "The old producer cannot append"
            );
            let mut repeated = append;
            repeated["generation"] = json!(next);
            assert_eq!(
                f.call(repeated).unwrap()["fresh"],
                false,
                "Canonical source receipts survive rollover"
            );
            generation = next;
            if cycle == 1 {
                drop(f.store);
                f.store =
                    Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
            }
        }
        assert_eq!(f.read(true)["range"]["content"]["checkpoint"]["through"], 2);
    }

    #[test]
    fn rollover_is_invalidated_by_new_language_or_pending_guidance() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Initial context")
            .unwrap();
        let ack = f.ack(&f.read(false)).unwrap();
        f.checkpoint(&ack, 1);
        let basis = f
            .call(json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let guide = Uuid::now_v7().to_string();
        f.call(
            json!({"action":"guide","dialogue":f.dialogue,"generation":f.generation,
            "id":guide,"basis":1,"mode":"context_only","text":"A newer correction"}),
        )
        .unwrap();
        let commit = json!({"action":"rollover_commit","dialogue":f.dialogue,"generation":f.generation,
            "next_generation":Uuid::now_v7().to_string(),"revision":basis["rollover_basis"]["revision"]});
        assert!(f.call(commit.clone()).is_err());
        f.call(json!({"action":"guidance_begin","dialogue":f.dialogue,"generation":f.generation,"id":guide})).unwrap();
        assert!(f.call(commit.clone()).is_err());
        f.call(json!({"action":"guidance_outcome","dialogue":f.dialogue,"generation":f.generation,"id":guide,"outcome":"sent"})).unwrap();
        assert!(
            f.call(commit.clone()).is_err(),
            "Settled new guidance changes the seed digest too"
        );
        f.append(
            &Uuid::now_v7().to_string(),
            "New speech before the candidate opens",
        )
        .unwrap();
        assert!(f.call(commit).is_err());
    }

    #[test]
    fn rollover_abort_fences_a_late_commit_without_undoing_a_committed_transition() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Known continuity")
            .unwrap();
        let ack = f.ack(&f.read(false)).unwrap();
        f.checkpoint(&ack, 1);
        let basis = f
            .call(json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        let mut attempt = json!({"action":"rollover_status","dialogue":f.dialogue,"generation":f.generation,
            "next_generation":Uuid::now_v7().to_string(),"revision":basis["rollover_basis"]["revision"]});
        let changes = f.store.conn.lock().unwrap().total_changes();
        assert_eq!(
            f.call(attempt.clone()).unwrap()["rollover_committed"],
            false
        );
        assert_eq!(f.store.conn.lock().unwrap().total_changes(), changes);
        attempt["action"] = json!("rollover_abort");
        assert_eq!(
            f.call(attempt.clone()).unwrap()["rollover_committed"],
            false
        );
        let after = f.store.conn.lock().unwrap().total_changes();
        assert_eq!(
            f.call(attempt.clone()).unwrap()["rollover_committed"],
            false
        );
        assert_eq!(f.store.conn.lock().unwrap().total_changes(), after);
        attempt["action"] = json!("rollover_commit");
        assert!(
            f.call(attempt.clone()).is_err(),
            "An abort observation must fence even a queued later commit"
        );
        attempt["next_generation"] = json!(Uuid::now_v7().to_string());
        let committed = f.call(attempt.clone()).unwrap();
        attempt["action"] = json!("rollover_abort");
        let observed = f.call(attempt).unwrap();
        assert_eq!(observed["rollover_committed"], true);
        assert_eq!(
            observed["generation"], committed["generation"],
            "Abort never reverses an actual commit"
        );
    }

    #[test]
    fn rollover_rechecks_late_canonical_original_before_generation_commit() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Earlier language")
            .unwrap();
        let ack = f.ack(&f.read(false)).unwrap();
        f.checkpoint(&ack, 1);
        let read =
            json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation});
        let basis = f.call(read.clone()).unwrap();
        f.store
            .conversation_foreground_capture(
                100,
                f.entry,
                &f.binding,
                &Uuid::now_v7().to_string(),
                "A late finalized human correction.",
                &f.dialogue,
                None,
            )
            .unwrap();
        assert!(f.call(read).is_err());
        assert!(f.call(json!({"action":"rollover_commit","dialogue":f.dialogue,"generation":f.generation,
            "next_generation":Uuid::now_v7().to_string(),"revision":basis["rollover_basis"]["revision"]})).is_err());
        let sync = f
            .call(json!({"action":"sync","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert_eq!(sync["high"], 2);
        let batch = f.read(false);
        assert_eq!(
            batch["range"]["content"]["events"][0]["text"],
            "A late finalized human correction."
        );
    }

    #[test]
    fn rollover_does_not_clip_an_oversized_checkpoint_to_fit_provider_setup() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "A retained original")
            .unwrap();
        let ack = f.ack(&f.read(false)).unwrap();
        f.call(json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":ack["checkpoint_revision"],"through":1,"text":"α".repeat(16000)}))
            .unwrap();
        let changes = f.store.conn.lock().unwrap().total_changes();
        assert!(
            f.call(
                json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation})
            )
            .is_err()
        );
        assert_eq!(f.store.conn.lock().unwrap().total_changes(), changes);
        let full = f.read(true);
        let revision = full["range"]["revision"].as_str().unwrap();
        let mut text = String::new();
        let mut offset = 0;
        loop {
            let part=f.call(json!({"action":"part","dialogue":f.dialogue,"revision":revision,"offset":offset})).unwrap();
            text.push_str(part["range"]["text"].as_str().unwrap());
            if part["range"]["more"] == true {
                offset = part["range"]["next"].as_u64().unwrap() as usize;
            } else {
                break;
            }
        }
        let retained: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(retained["checkpoint"]["text"], "α".repeat(16000));
    }

    #[test]
    fn acknowledgement_keeps_exact_tail_until_two_semantic_checkpoints_and_restart() {
        let mut f = Fixture::new();
        let first = Uuid::now_v7().to_string();
        f.append(&first, "Primera respuesta α, quizá interrumpida.")
            .unwrap();
        let batch = f.read(false);
        let ack = f.ack(&batch).unwrap();
        assert_eq!(ack["incorporated"], 1);
        assert_eq!(ack["checkpointed"], 0);
        let full = f.read(true);
        assert_eq!(
            full["range"]["content"]["events"][0]["text"],
            "Primera respuesta α, quizá interrumpida."
        );
        assert_eq!(full["range"]["content"]["events"][0]["interrupted"], true);
        f.ack(&full).unwrap();
        let one = f.checkpoint(&ack, 1);
        assert_eq!(one["checkpointed"], 1);
        assert_eq!(
            f.append(&first, "Primera respuesta α, quizá interrumpida.")
                .unwrap()["fresh"],
            false
        );
        assert!(f.append(&first, "Changed finalized source").is_err());
        f.append(&Uuid::now_v7().to_string(), "Exact tail after checkpoint.")
            .unwrap();
        let batch = f.read(false);
        assert_eq!(batch["range"]["from"], 2);
        f.ack(&batch).unwrap();
        f.checkpoint(&one, 2);
        // Reopen the actual database. No migration/replay or new human input.
        drop(f.store);
        f.store = Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let full = f.read(true);
        assert_eq!(full["incorporated"], 2);
        assert_eq!(full["range"]["content"]["checkpoint"]["through"], 2);
        assert_eq!(full["range"]["content"]["events"], json!([]));
    }

    #[test]
    fn frozen_pages_reject_gaps_and_preserve_later_appends() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), &"á".repeat(8000))
            .unwrap();
        let batch = f.read(false);
        assert_eq!(batch["range"]["complete"], false);
        assert!(f.ack(&batch).is_err());
        let rev = &batch["range"]["revision"];
        assert!(
            f.call(json!({"action":"part","dialogue":f.dialogue,"revision":rev,"offset":1}))
                .is_err()
        );
        f.append(
            &Uuid::now_v7().to_string(),
            "Later canonical retention while Sol reads.",
        )
        .unwrap();
        assert_eq!(f.read(false)["range"]["revision"], *rev);
        let mut offset = 0;
        let mut joined = String::new();
        loop {
            let page = f
                .call(json!({"action":"part","dialogue":f.dialogue,"revision":rev,"offset":offset}))
                .unwrap();
            joined.push_str(page["range"]["text"].as_str().unwrap());
            offset = page["range"]["next"].as_u64().unwrap();
            if page["range"]["more"] == false {
                break;
            }
        }
        assert_eq!(
            serde_json::from_str::<Value>(&joined).unwrap()["events"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(f.ack(&batch).unwrap()["incorporated"], 1);
        let later = f.read(false);
        assert_eq!(later["range"]["from"], 2);
        assert_eq!(later["range"]["through"], 2);
    }

    #[test]
    fn canonical_human_context_never_admits_work_and_rejects_forgery() {
        let f = Fixture::new();
        let source = Uuid::now_v7().to_string();
        f.store
            .conversation_foreground_capture(
                100,
                f.entry,
                &f.binding,
                &source,
                "An idea to discuss, not a delegated task.",
                &f.dialogue,
                None,
            )
            .unwrap();
        let value = json!({"action":"append","dialogue":f.dialogue,"generation":f.generation,
            "source":source,"role":"human","text":"An idea to discuss, not a delegated task.","interrupted":false});
        let mut forged = value.clone();
        forged["text"] = json!("Invented task");
        assert!(f.call(forged).is_err());
        f.call(value).unwrap();
        let batch = f.read(false);
        let event = &batch["range"]["content"]["events"][0];
        assert!(event["capture_order"].as_i64().unwrap() > 0);
        let conn = f.store.conn.lock().unwrap();
        let (phase, local): (String, Option<i64>) = conn
            .query_row(
                "SELECT phase,local_turn FROM conversation_inputs WHERE id=?1",
                [source],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(phase, "foreground");
        assert_eq!(local, None);
        let count: i64 = conn
            .query_row("SELECT count(*) FROM turns", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 0);
    }

    #[test]
    fn owner_generation_and_unincorporated_checkpoint_are_fenced() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Exact source.")
            .unwrap();
        let batch = f.read(false);
        assert!(
            f.call(json!({"action":"checkpoint","dialogue":f.dialogue,
            "revision":batch["checkpoint_revision"],"through":1,"text":"Premature"}))
                .is_err()
        );
        assert!(
            f.store
                .live_context(
                    101,
                    f.entry,
                    serde_json::from_value(
                        json!({"action":"read","dialogue":f.dialogue,"full":true})
                    )
                    .unwrap()
                )
                .is_err()
        );
        f.store
            .set_session_codex_thread(f.entry, "replacement-native")
            .unwrap();
        assert!(
            f.call(json!({"action":"read","dialogue":f.dialogue,"full":false}))
                .is_err()
        );
        assert!(f.ack(&batch).is_err());
    }

    #[test]
    fn capacity_failure_rolls_back_without_dropping_existing_context() {
        let f = Fixture::new();
        let source = Uuid::now_v7().to_string();
        f.append(&source, "Must survive saturation.").unwrap();
        {
            let conn = f.store.conn.lock().unwrap();
            let mut p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
            // Fill the real bounded document, not a mock success response.
            for n in 0..MAX_SOURCES {
                p.sources
                    .insert(format!("fixture:{n}"), (1, "a".repeat(64)));
            }
            save(&conn, &p).unwrap();
        }
        assert!(
            f.append(&Uuid::now_v7().to_string(), "Cannot fit another source.")
                .is_err()
        );
        let full = f.read(true);
        assert_eq!(full["high"], 1);
        assert_eq!(full["range"]["content"]["events"][0]["source"], source);
    }

    fn local(f: &Fixture, prompt: &str) -> i64 {
        f.store
            .record_turn_started(
                f.store.get_session(f.entry).unwrap().unwrap().id,
                &crate::models::TurnRequest {
                    session_key: f.entry,
                    from_user_id: 100,
                    prompt: prompt.into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap()
    }
    fn linked(f: &Fixture, r: &super::super::ReturnDispatch, local: i64) {
        f.store.workflow_native_link(&r.id, local).unwrap();
        f.store.workflow_native_submitting(&r.id).unwrap();
        f.store
            .workflow_native_outcome(&r.id, "accepted", Some("physical-context-turn"))
            .unwrap();
    }
    #[test]
    fn foreground_attachment_requires_owned_unincorporated_ack_not_another_input() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Pending context language")
            .unwrap();
        let packet = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        let old = local(&f, "Earlier collector");
        f.store
            .native_collection_started(old, "old-context-turn")
            .unwrap();
        f.store.workflow_native_link(&packet.id, old).unwrap();
        f.store.workflow_native_submitting(&packet.id).unwrap();
        assert!(
            f.store
                .native_foreground_attachment(100, f.entry)
                .unwrap()
                .is_none()
        );
        f.store
            .workflow_native_outcome(&packet.id, "accepted_uncollected", Some("new-context-turn"))
            .unwrap();
        let native = f
            .store
            .get_session(f.entry)
            .unwrap()
            .unwrap()
            .codex_thread_id
            .unwrap();
        assert_eq!(
            f.store.native_foreground_attachment(100, f.entry).unwrap(),
            Some((native, "new-context-turn".into()))
        );
        assert!(
            f.store
                .native_foreground_attachment(101, f.entry)
                .unwrap()
                .is_none()
        );
        assert!(
            f.store
                .native_foreground_attachment(100, SessionKey::new(100, Some(999)))
                .unwrap()
                .is_none()
        );
        let page = f.read(false);
        f.ack(&page).unwrap();
        assert!(
            f.store
                .native_foreground_attachment(100, f.entry)
                .unwrap()
                .is_none(),
            "Incorporated context does not request another collector"
        );
    }

    #[test]
    fn native_context_coalesces_and_never_contributes_chat_publication() {
        let f = Fixture::new();
        f.append(
            &Uuid::now_v7().to_string(),
            "Assistant context, not a work result.",
        )
        .unwrap();
        let r = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        let output: Value = serde_json::from_str(&r.output).unwrap();
        assert_eq!(r.name, "foreground_context");
        assert_eq!(output["evidence"]["complete"], true);
        let l = local(&f, "");
        linked(&f, &r, l);
        assert!(!f.store.workflow_native_visible(l).unwrap());
        f.append(
            &Uuid::now_v7().to_string(),
            "A later semantic turn while Sol incorporates.",
        )
        .unwrap();
        assert!(
            f.store
                .native_foreground_reserve(100, f.entry, &f.dialogue)
                .unwrap()
                .is_none()
        );
        f.call(output["after_incorporation"]["arguments"].clone())
            .unwrap();
        assert!(!f.store.workflow_native_visible(l).unwrap());
        let next = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        let next: Value = serde_json::from_str(&next.output).unwrap();
        assert_eq!(next["evidence"]["from"], 2);
        assert_eq!(next["evidence"]["through"], 2);
        // The coalesced transport released its duplicate text, not the exact
        // post-checkpoint projection needed by an explicit full-context reader.
        let conn = f.store.conn.lock().unwrap();
        let p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
        assert_eq!(p.events.len(), 2);
        assert!(p.native_returns[0].envelope.get("content").is_none());
    }
    #[test]
    fn native_context_does_not_suppress_real_human_lifetime_or_exhaust_32_batches() {
        let f = Fixture::new();
        let internal = local(&f, "");
        for n in 0..40 {
            f.append(&Uuid::now_v7().to_string(), &format!("Context turn {n}."))
                .unwrap();
            let r = f
                .store
                .native_foreground_reserve(100, f.entry, &f.dialogue)
                .unwrap()
                .unwrap();
            let output: Value = serde_json::from_str(&r.output).unwrap();
            linked(&f, &r, internal);
            f.call(output["after_incorporation"]["arguments"].clone())
                .unwrap();
            assert!(!f.store.workflow_native_visible(internal).unwrap());
        }
        let human = local(&f, "An actual independent human question.");
        f.append(
            &Uuid::now_v7().to_string(),
            "Context arriving during the real question.",
        )
        .unwrap();
        let r = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        linked(&f, &r, human);
        assert!(f.store.workflow_native_visible(human).unwrap());
        let conn = f.store.conn.lock().unwrap();
        let raw: String = conn
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [format!("workflow_return_local:{internal}")],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(serde_json::from_str::<Vec<String>>(&raw).unwrap().len(), 1);
        let p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
        assert_eq!(
            p.native_returns.len(),
            2,
            "Only the currently bound return in each physical lifetime remains; incorporated unbound transport is retired"
        );
        // Even after transport-binding consolidation, a pure internal lifetime
        // remains internal. Retiring IDs never silently widens publication.
        conn.execute(
            "DELETE FROM bot_state WHERE key=?1",
            [format!("workflow_return_local:{internal}")],
        )
        .unwrap();
        assert!(!super::super::workflows::native_visible_on(&conn, internal).unwrap());
    }
    #[test]
    fn incorporated_language_does_not_retire_unknown_native_submission() {
        let f = Fixture::new();
        f.append(
            &Uuid::now_v7().to_string(),
            "Context whose native ACK is lost",
        )
        .unwrap();
        let first = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        let l = local(&f, "");
        f.store.workflow_native_link(&first.id, l).unwrap();
        f.store.workflow_native_submitting(&first.id).unwrap();
        // Sol incorporated it, but the submission ACK remains unobserved.
        let packet: Value = serde_json::from_str(&first.output).unwrap();
        f.call(packet["after_incorporation"]["arguments"].clone())
            .unwrap();
        f.store
            .workflow_native_outcome(&first.id, "uncertain", None)
            .unwrap();
        f.append(&Uuid::now_v7().to_string(), "Later context")
            .unwrap();
        let next = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        linked(&f, &next, l);
        let packet: Value = serde_json::from_str(&next.output).unwrap();
        f.call(packet["after_incorporation"]["arguments"].clone())
            .unwrap();
        let ack = f.ack(&f.read(true)).unwrap();
        f.checkpoint(&ack, 2);
        let conn = f.store.conn.lock().unwrap();
        let p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
        assert!(
            p.native_returns
                .iter()
                .any(|r| r.id == first.id && r.phase == "uncertain")
        );
        assert!(!super::super::workflows::native_visible_on(&conn, l).unwrap());
    }
    #[test]
    fn restart_distinguishes_unsent_from_uncertain_and_never_reauthors_a_range() {
        let mut f = Fixture::new();
        f.append(
            &Uuid::now_v7().to_string(),
            "Retained before native boundary.",
        )
        .unwrap();
        let r = f
            .store
            .native_foreground_reserve(100, f.entry, &f.dialogue)
            .unwrap()
            .unwrap();
        drop(f.store);
        f.store = Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
        {
            let conn = f.store.conn.lock().unwrap();
            let mut p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
            assert_eq!(p.native_returns[0].id, r.id);
            assert_eq!(p.native_returns[0].phase, "retained_unsent");
            p.native_returns[0].retry_after = Some(0);
            save(&conn, &p).unwrap();
        }
        let retry = f
            .store
            .native_returns_recover_unsent(100, f.entry, false, false)
            .unwrap();
        assert_eq!(retry.len(), 1);
        assert_eq!(retry[0].id, r.id);
        assert_eq!(retry[0].attempts, 2);
        let l = local(&f, "");
        f.store.workflow_native_link(&r.id, l).unwrap();
        f.store.workflow_native_submitting(&r.id).unwrap();
        drop(f.store);
        f.store = Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert!(
            f.store
                .native_returns_recover_unsent(100, f.entry, false, false)
                .unwrap()
                .is_empty()
        );
        assert!(
            f.store
                .native_foreground_reserve(100, f.entry, &f.dialogue)
                .unwrap()
                .is_none()
        );
        let conn = f.store.conn.lock().unwrap();
        let p = load(&conn, &f.dialogue, 100, f.entry).unwrap();
        assert_eq!(p.native_returns[0].phase, "uncertain");
        assert_eq!(p.native_returns.len(), 1);
    }

    fn guide(f: &Fixture, id: &str, basis: u64) -> Value {
        json!({"action":"guide","dialogue":f.dialogue,"generation":f.generation,
            "id":id,"basis":basis,"mode":"context_only","text":"Use the confirmed shared memory; do not invent a saved note."})
    }
    fn guide_operation(f: &Fixture, action: &str, id: &str) -> Value {
        json!({"action":action,"dialogue":f.dialogue,"generation":f.generation,"id":id})
    }
    #[test]
    fn checkpoint_retires_only_exact_full_read_guidance_and_keeps_receipts() {
        let mut f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Current conversation basis")
            .unwrap();
        let ack = f.ack(&f.read(false)).unwrap();
        let first = Uuid::now_v7().to_string();
        let original = guide(&f, &first, 1);
        f.call(original.clone()).unwrap();
        f.call(guide_operation(&f, "guidance_begin", &first))
            .unwrap();
        f.call(
            json!({"action":"guidance_outcome","dialogue":f.dialogue,"generation":f.generation,
            "id":first,"outcome":"sent"}),
        )
        .unwrap();
        let cp = f.checkpoint(&ack, 1);
        assert!(
            !f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":first}))
                .unwrap()["guidance"]["text"]
                .as_str()
                .unwrap()
                .is_empty(),
            "A language-only ACK did not incorporate the guide"
        );
        let second = Uuid::now_v7().to_string();
        f.call(guide(&f, &second, 1)).unwrap();
        let full = f.read(true);
        // A send disposition changing after freeze was not seen by that ACK.
        f.call(guide_operation(&f, "guidance_begin", &second))
            .unwrap();
        f.call(
            json!({"action":"guidance_outcome","dialogue":f.dialogue,"generation":f.generation,
            "id":second,"outcome":"uncertain"}),
        )
        .unwrap();
        f.ack(&full).unwrap();
        f.checkpoint(&cp, 1);
        let status = f
            .call(json!({"action":"guide_status","dialogue":f.dialogue,"id":first}))
            .unwrap();
        assert_eq!(status["guidance"]["text"], "");
        assert_eq!(status["guidance"]["phase"], "sent");
        assert!(status["guidance"]["checkpointed_text_hash"].is_string());
        let full = f.read(true);
        assert_eq!(
            full["range"]["content"]["guidance"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(full["range"]["content"]["guidance"][0]["id"], second);
        assert_eq!(
            full["range"]["content"]["guidance"][0]["phase"],
            "uncertain"
        );
        let ack = f.ack(&full).unwrap();
        f.checkpoint(&ack, 1);
        drop(f.store);
        f.store = Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            f.call(original.clone()).unwrap()["guidance"]["phase"],
            "sent"
        );
        let mut changed = original;
        changed["text"] = json!("Changed original control text");
        assert!(f.call(changed).is_err());
        let basis = f
            .call(json!({"action":"rollover_read","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert_eq!(basis["rollover_basis"]["content"]["guidance"], json!([]));
        assert_eq!(
            f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":second}))
                .unwrap()["guidance"]["phase"],
            "uncertain"
        );
    }

    #[test]
    fn guidance_basis_survives_later_speech_and_receipts_never_claim_application() {
        let f = Fixture::new();
        f.append(&Uuid::now_v7().to_string(), "Basis.").unwrap();
        let batch = f.read(false);
        f.ack(&batch).unwrap();
        let id = Uuid::now_v7().to_string();
        let request = guide(&f, &id, 1);
        let mut wrong_generation = request.clone();
        wrong_generation["generation"] = json!(Uuid::now_v7().to_string());
        assert!(f.call(wrong_generation).is_err());
        assert_eq!(
            f.call(request.clone()).unwrap()["guidance"]["phase"],
            "pending"
        );
        assert_eq!(
            f.call(request.clone()).unwrap()["guidance"]["phase"],
            "pending"
        );
        let mut changed = request.clone();
        changed["text"] = json!("Rewritten same identity");
        assert!(f.call(changed).is_err());
        assert!(f.call(guide(&f, &Uuid::now_v7().to_string(), 2)).is_err());
        f.append(
            &Uuid::now_v7().to_string(),
            "Later speech does not itself supersede useful guidance.",
        )
        .unwrap();
        let next = Uuid::now_v7().to_string();
        let mut replacement = guide(&f, &next, 1);
        replacement["supersedes"] = json!(id);
        f.call(replacement).unwrap();
        assert_eq!(
            f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":id}))
                .unwrap()["guidance"]["phase"],
            "superseded"
        );
        let before = f.store.conn.lock().unwrap().total_changes();
        let peek = f
            .call(json!({"action":"guidance","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert_eq!(peek["guidance"]["id"], next);
        assert_eq!(
            f.store.conn.lock().unwrap().total_changes(),
            before,
            "A guidance peek must not wake its own DB watcher"
        );
        f.call(guide_operation(&f, "guidance_begin", &next))
            .unwrap();
        let mut refused = guide(&f, &Uuid::now_v7().to_string(), 1);
        refused["supersedes"] = json!(next);
        assert!(f.call(refused).is_err());
        let mut outcome = guide_operation(&f, "guidance_outcome", &next);
        outcome["outcome"] = json!("unsent");
        assert_eq!(
            f.call(outcome.clone()).unwrap()["guidance"]["phase"],
            "pending"
        );
        f.call(guide_operation(&f, "guidance_begin", &next))
            .unwrap();
        outcome["outcome"] = json!("sent");
        assert_eq!(
            f.call(outcome.clone()).unwrap()["guidance"]["phase"],
            "sent"
        );
        assert_eq!(
            f.call(outcome.clone()).unwrap()["guidance"]["phase"],
            "sent"
        );
        outcome["outcome"] = json!("applied");
        assert!(f.call(outcome).is_err());
        let full = f.read(true);
        assert_eq!(full["range"]["content"]["guidance"][1]["phase"], "sent");
        assert_eq!(
            full["range"]["content"]["events"].as_array().unwrap().len(),
            2
        );
        let conn = f.store.conn.lock().unwrap();
        assert_eq!(
            conn.query_row("SELECT count(*) FROM turns", [], |r| r.get::<_, i64>(0))
                .unwrap(),
            0
        );
    }

    #[test]
    fn guidance_restart_close_and_generation_changes_preserve_uncertainty() {
        let mut f = Fixture::new();
        let id = Uuid::now_v7().to_string();
        f.call(guide(&f, &id, 0)).unwrap();
        f.call(guide_operation(&f, "guidance_begin", &id)).unwrap();
        drop(f.store);
        f.store = Store::open(f.file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":id}))
                .unwrap()["guidance"]["phase"],
            "uncertain"
        );
        assert!(f.call(guide_operation(&f, "guidance_begin", &id)).is_err());
        let pending = Uuid::now_v7().to_string();
        f.call(guide(&f, &pending, 0)).unwrap();
        f.call(json!({"action":"close","dialogue":f.dialogue,"generation":f.generation}))
            .unwrap();
        assert_eq!(
            f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":pending}))
                .unwrap()["guidance"]["phase"],
            "retired_unsent"
        );
        assert_eq!(
            f.call(json!({"action":"guide_status","dialogue":f.dialogue,"id":id}))
                .unwrap()["guidance"]["phase"],
            "uncertain"
        );
        assert!(f.call(guide(&f, &Uuid::now_v7().to_string(), 0)).is_err());
        assert_eq!(
            f.call(json!({"action":"guidance","dialogue":f.dialogue,"generation":f.generation}))
                .unwrap()["guidance"],
            Value::Null
        );
    }
}
