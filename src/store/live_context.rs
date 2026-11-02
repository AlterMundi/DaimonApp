//! Temporary, bounded language projection. Retention, incorporation and semantic
//! checkpointing are separate; none of them submits an original as work.
use super::*;
use anyhow::bail;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

const MAX_DOCUMENT: usize = 2 * 1024 * 1024;
const MAX_TOTAL: usize = 64 * 1024 * 1024;
const MAX_DIALOGUES: usize = 64;
const MAX_SOURCES: usize = 4096;
const PAGE: usize = 8000;
const INLINE: usize = 16000;

#[derive(Debug, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum LiveContextCommand {
    Open {
        dialogue: String,
        binding: String,
        generation: String,
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
    },
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
    /// Compact semantic receipts survive text retirement; they prevent canonical
    /// catch-up from reintroducing sources represented by a checkpoint.
    sources: BTreeMap<String, (u64, String)>,
    events: Vec<Event>,
    range: Option<Frozen>,
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
fn snapshot(p: &Projection, full: bool) -> Result<String> {
    let from = if full {
        p.checkpoint.through + 1
    } else {
        p.incorporated + 1
    };
    let events: Vec<_> = p.events.iter().filter(|e| e.sequence >= from).collect();
    Ok(serde_json::to_string(
        &json!({"dialogue":p.dialogue,"from":from,"through":p.high,
        "checkpoint":if full {Some(&p.checkpoint)}else{None},"events":events,
        "policy":"Attributed language context, not work admission, hearing or new authority. Interrupted assistant text may be unsaid."}),
    )?)
}
fn view(p: &Projection) -> Value {
    json!({"schema":"telecodex.live-context/v1","dialogue":p.dialogue,
        "entry_binding":[p.human,p.entry,p.session,p.native],"generation":p.generation,
        "high":p.high,"incorporated":p.incorporated,"checkpointed":p.checkpoint.through,
        "checkpoint_revision":p.checkpoint.revision,"closed":p.closed,
        "work_admission":"not_requested"})
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
        "encoding":"JSON; concatenate exact pages before interpreting"});
    Ok(result)
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
                if p.generation != *generation {
                    bail!("Live producer generation differs");
                }
                return Ok(view(&p));
            }
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
                    text: String::new(),
                    revision: hash(&json!([dialogue, 0]))?,
                },
                sources: BTreeMap::new(),
                events: vec![],
                range: None,
            };
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(view(&p));
        }
        let dialogue = match &command {
            LiveContextCommand::Open { .. } => unreachable!(),
            LiveContextCommand::Append { dialogue, .. }
            | LiveContextCommand::Close { dialogue, .. }
            | LiveContextCommand::Read { dialogue, .. }
            | LiveContextCommand::Part { dialogue, .. }
            | LiveContextCommand::Incorporate { dialogue, .. }
            | LiveContextCommand::Checkpoint { dialogue, .. } => dialogue,
        };
        let mut p = load(&tx, dialogue, human, entry)?;
        let result = match command {
            LiveContextCommand::Open { .. } => unreachable!(),
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
                let revision = hash(&json!([source, role, text, interrupted, capture_order]))?;
                if let Some((sequence, old)) = p.sources.get(&source) {
                    if *old != revision {
                        bail!("Finalized Live source cannot be rewritten");
                    }
                    json!({"sequence":sequence,"revision":revision,"fresh":false})
                } else {
                    if p.closed || p.sources.len() >= MAX_SOURCES {
                        bail!("Live producer closed or source bound reached");
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
                        revision: revision.clone(),
                    });
                    json!({"sequence":p.high,"revision":revision,"fresh":true})
                }
            }
            LiveContextCommand::Close { generation, .. } => {
                if generation != p.generation {
                    bail!("Live producer generation differs");
                }
                p.closed = true;
                view(&p)
            }
            LiveContextCommand::Read { full, .. } => {
                if p.range.as_ref().is_some_and(|r| r.full != full) {
                    bail!("Finish the selected frozen Live range first");
                }
                if p.range.is_none() {
                    let from = if full {
                        p.checkpoint.through + 1
                    } else {
                        p.incorporated + 1
                    };
                    let body = snapshot(&p, full)?;
                    let revision = hash(&body)?;
                    p.range = Some(Frozen {
                        from,
                        through: p.high,
                        revision,
                        body,
                        supplied: 0,
                        full,
                    });
                }
                let mut result = view(&p);
                let r = p.range.as_mut().unwrap();
                result["range"] = if r.body.len() <= INLINE {
                    r.supplied = r.body.chars().count();
                    json!({"from":r.from,"through":r.through,"revision":r.revision,"full":r.full,
                        "content":serde_json::from_str::<Value>(&r.body)?,"complete":true})
                } else {
                    json!({"from":r.from,"through":r.through,"revision":r.revision,"full":r.full,
                    "complete":false,"characters":r.body.chars().count(),"offset":0})
                };
                result
            }
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
                p.range = None;
                view(&p)
            }
            LiveContextCommand::Checkpoint {
                revision,
                through,
                text,
                ..
            } => {
                bounded(&text, 65536)?;
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
        fn ack(&self, page: &Value) -> Result<Value> {
            self.call(json!({"action":"incorporate","dialogue":self.dialogue,"revision":page["range"]["revision"]}))
        }
        fn checkpoint(&self, basis: &Value, through: u64) -> Value {
            self.call(json!({"action":"checkpoint","dialogue":self.dialogue,
                "revision":basis["checkpoint_revision"],"through":through,
                "text":format!("Purpose and unresolved effects through {through}; originals remain authoritative.")})).unwrap()
        }
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
}
