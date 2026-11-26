//! Foreground /we requests share the canonical Matrix request journal.
use super::*;
use crate::interaction::ForegroundEngine;
use serde_json::Value;

// Each entry may run one undispatched foreground turn at a time. Bound the
// catalog without removing originals or uncertain effects.
const MAX_REQUESTS: i64 = 64;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, Debug)]
#[serde(deny_unknown_fields)]
pub(crate) struct WeOriginal {
    pub schema: String,
    pub event_id: String,
    pub author: String,
    pub thread_id: String,
    pub receipt_event_id: String,
    pub text: String,
}

#[derive(Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct WeSelection {
    pub event_id: String,
    pub author: String,
    pub thread_id: String,
    pub cursor: Option<String>,
}

impl WeSelection {
    pub(crate) fn validate(&self) -> Result<()> {
        anyhow::ensure!(
            canonical_uuid(&self.event_id)
                && canonical_uuid(&self.thread_id)
                && !self.author.trim().is_empty()
                && self.author.len() <= 128
                && self
                    .cursor
                    .as_ref()
                    .is_none_or(|cursor| !cursor.is_empty() && cursor.len() <= 2048),
            "Invalid selected Matrix original"
        );
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum WePhase {
    Starting,
    ProviderExposed,
    Rejected,
    ProviderUncertain,
    Returning,
    ReturnUncertain,
    Delivered,
    ResultRetained,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    id: String,
    instance: String,
    entry_generation: String,
    epoch: String,
    session_id: String,
    source: MatrixAuthor,
    body: Value,
    original: WeOriginal,
}

impl Request {
    fn current(
        &self,
        tx: &Connection,
        owner: i64,
        entry: SessionKey,
        session: i64,
    ) -> Result<bool> {
        use crate::store::{presentation, stopping};
        Ok(
            self.entry_generation == presentation::entry_binding(tx, owner, entry, session)?
                && self.epoch == stopping::admission_epoch_on(tx, entry)?
                && !stopping::fenced_on(tx, entry)?
                && !crate::store::maintenance_writer_held_on(tx, entry)?,
        )
    }
}

pub(crate) struct WeAttempt {
    pub id: String,
    pub session_id: String,
    pub resume: bool,
    entry_session: i64,
    original: String,
}

fn owns_writer(tx: &Connection, instance: &str) -> Result<bool> {
    Ok(tx.query_row(
        "SELECT EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?1)",
        [instance],
        |row| row.get(0),
    )?)
}

fn load(
    tx: &Connection,
    owner: i64,
    session: i64,
    original: &str,
) -> Result<Option<(Request, WePhase, Value)>> {
    let row: Option<(String, String, Option<String>)> = tx
        .query_row(
            "SELECT doc,phase,submission FROM interaction_matrix_requests
         WHERE human_id=?1 AND entry_session=?2 AND source_event=?3 AND source_channel='/we'",
            params![owner, session, original],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    row.map(|(doc, phase, outcome)| {
        Ok((
            serde_json::from_str(&doc)?,
            serde_json::from_value(json!(phase))?,
            outcome
                .map(|raw| serde_json::from_str(&raw))
                .transpose()?
                .unwrap_or(Value::Null),
        ))
    })
    .transpose()
}

fn view(request: &Request, mut phase: WePhase, mut result: Value, instance: &str) -> Value {
    if instance != request.instance {
        phase = match phase {
            WePhase::Starting => WePhase::Rejected,
            WePhase::ProviderExposed => WePhase::ProviderUncertain,
            WePhase::Returning => WePhase::ReturnUncertain,
            phase => phase,
        };
    }
    let stored_engine = result
        .as_object_mut()
        .and_then(|outcome| outcome.remove("engine"));
    let engine = stored_engine
        .as_ref()
        .and_then(Value::as_str)
        .unwrap_or(ForegroundEngine::Claude.name());
    let native_session_id = result.as_object_mut().and_then(|outcome| {
        outcome.remove("text");
        outcome.remove("native_session_id")
    });
    if matches!(
        phase,
        WePhase::Starting | WePhase::Rejected | WePhase::ProviderExposed
    ) && result.as_object().is_some_and(|obj| obj.is_empty())
    {
        result = Value::Null;
    }
    let native_session_id = native_session_id
        .as_ref()
        .and_then(Value::as_str)
        .or_else(|| {
            // Legacy Claude attempts used the allocated UUID for both identities.
            (engine == ForegroundEngine::Claude.name()
                && !matches!(phase, WePhase::Starting | WePhase::Rejected))
            .then_some(request.session_id.as_str())
        });
    json!({"request_id":request.id,"input_id":request.original.event_id,
        "engine":engine,"session_id":request.session_id,"native_session_id":native_session_id,
        "thread_id":request.original.thread_id,
        "phase":phase,"result":result})
}

impl Store {
    pub(crate) fn we_status(
        &self,
        owner: i64,
        entry: SessionKey,
        original: &str,
    ) -> Result<Option<Value>> {
        anyhow::ensure!(
            canonical_uuid(original),
            "Canonical Matrix original required"
        );
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, _) = crate::store::presentation::entry_on(&conn, owner, entry)?;
        Ok(load(&conn, owner, session, original)?
            .map(|(request, phase, result)| view(&request, phase, result, &self.instance_id)))
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn we_start(
        &self,
        owner: i64,
        entry: SessionKey,
        engine: ForegroundEngine,
        source: MatrixAuthor,
        body: Value,
        original: WeOriginal,
        input: Option<&crate::store::ConversationInput>,
    ) -> Result<Option<WeAttempt>> {
        anyhow::ensure!(
            original.schema == "daimon-gateway.matrix-we-original/v1"
                && canonical_uuid(&original.event_id)
                && canonical_uuid(&original.thread_id)
                && canonical_uuid(&original.receipt_event_id)
                && !original.author.trim().is_empty()
                && original.author != source.embodiment_id
                && original.author.len() <= 128
                && !original.text.trim().is_empty()
                && original.text.len() <= 16384,
            "Invalid authenticated same-being original"
        );
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        anyhow::ensure!(
            owns_writer(&tx, &self.instance_id)?,
            "Foreground Matrix writer is no longer owned"
        );
        use crate::store::{presentation, stopping};
        let (session, _) = presentation::entry_on(&tx, owner, entry)?;
        let mut claude_input = None;
        if let Some(input) = input {
            use crate::interaction::MatrixDestination::Body;
            let retained = crate::store::conversation_inputs::read_on(&tx, &input.id, owner)?;
            crate::store::conversation_inputs::eligible_binding_on(&tx, &retained)?;
            let selection = retained
                .private_matrix
                .as_ref()
                .context("Private Matrix selection missing")?;
            let receipt = retained
                .private_matrix_origin
                .as_ref()
                .context("Private Matrix receipt missing")?;
            anyhow::ensure!(
                retained.entry == entry
                    && retained.phase == "matrix_received"
                    && selection.recipient
                        == (Body {
                            being_ref: source.being_ref.clone(),
                            embodiment_id: source.embodiment_id.clone()
                        })
                    && matches!(&selection.sender, Body { embodiment_id, .. } if embodiment_id == &original.author)
                    && selection.thread_id == original.thread_id
                    && receipt.message_id == original.event_id
                    && receipt.receipt_event_id == original.receipt_event_id
                    && retained.text == original.text,
                "Private Matrix work differs from the retained human original"
            );
            if engine == ForegroundEngine::Claude {
                claude_input = Some(retained.id);
            }
        }
        if selected_on(&tx, owner, "/we", &original.event_id, None)?.is_some() {
            return Ok(None);
        }
        let (count, busy): (i64, i64) = tx.query_row(
            "SELECT count(*), COALESCE(sum(CASE WHEN phase IN ('starting','provider_exposed','returning')
                AND json_extract(doc,'$.instance')=?3 THEN 1 ELSE 0 END),0)
                FROM interaction_matrix_requests WHERE human_id=?1 AND entry_session=?2 AND source_channel='/we'",
            params![owner, session, self.instance_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        anyhow::ensure!(
            count < MAX_REQUESTS && busy == 0,
            "Foreground Matrix destination is at capacity"
        );
        let entry_generation = presentation::entry_binding(&tx, owner, entry, session)?;
        let prior_session = if claude_input.is_some() {
            let previous: Option<(String, String, String, bool)> = tx
                .query_row(
                    "SELECT request.doc, request.phase, request.submission, COALESCE(
                        input.phase='matrix_replied'
                        AND json_extract(input.doc,'$.private_matrix_reply.event_id')
                          =json_extract(request.submission,'$.delivery.message_id'), 0)
                    FROM interaction_matrix_requests AS request
                    LEFT JOIN conversation_inputs AS input ON input.id=request.claude_input
                        AND input.human_id=request.human_id AND input.session_id=request.entry_session
                    WHERE request.human_id=?1 AND request.entry_session=?2 AND request.source_channel='/we'
                      AND json_extract(request.submission,'$.engine') IS NULL
                      AND json_extract(request.doc,'$.entry_generation')=?3
                      AND json_extract(request.doc,'$.original.author')=?4
                      AND json_extract(request.doc,'$.original.thread_id')=?5
                      AND (request.phase NOT IN ('starting','rejected')
                        OR (request.phase='rejected'
                          AND json_extract(request.submission,'$.reason')='claude_resume_session_missing'))
                    ORDER BY request.rowid DESC LIMIT 1",
                    params![
                        owner,
                        session,
                        entry_generation,
                        original.author,
                        original.thread_id
                    ],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
                )
                .optional()?;
            if let Some((doc, phase, result, read_back)) = previous {
                let prior: Request = serde_json::from_str(&doc)?;
                let result: Value = serde_json::from_str(&result)?;
                // An exposed turn without confirmed readback, including a
                // row from an older writer, breaks continuity for this lane.
                (phase == "delivered"
                    && read_back
                    && prior.source == source
                    && prior.body == body
                    && result["native_session_id"].as_str() == Some(&prior.session_id)
                    && canonical_uuid(&prior.session_id))
                .then_some(prior.session_id)
            } else {
                None
            }
        } else {
            None
        };
        let resume = prior_session.is_some();
        let request = Request {
            id: Uuid::now_v7().to_string(),
            instance: self.instance_id.clone(),
            entry_generation,
            epoch: stopping::admission_epoch_on(&tx, entry)?,
            session_id: prior_session.unwrap_or_else(|| Uuid::new_v4().to_string()),
            source,
            body,
            original,
        };
        anyhow::ensure!(
            request.current(&tx, owner, entry, session)?,
            "Foreground Matrix admission is fenced"
        );
        tx.execute(
            "INSERT INTO interaction_matrix_requests(id,human_id,entry_session,source_channel,source_event,doc,phase,created_at,submission,claude_input)
             VALUES(?1,?2,?3,'/we',?4,?5,'starting',?6,?7,?8)",
            params![request.id, owner, session, request.original.event_id, serde_json::to_string(&request)?, now_string(),
                (engine != ForegroundEngine::Claude).then(|| json!({"engine":engine.name()}).to_string()),
                claude_input],
        )?;
        tx.commit()?;
        Ok(Some(WeAttempt {
            id: request.id,
            session_id: request.session_id,
            resume,
            entry_session: session,
            original: request.original.event_id,
        }))
    }

    /// Advance only one owner-held attempt from its exact previous phase.
    /// Checks the current epoch only when authorizing a new external effect.
    pub(crate) fn we_transition(
        &self,
        owner: i64,
        entry: SessionKey,
        attempt: &WeAttempt,
        previous: WePhase,
        next: WePhase,
        outcome: Value,
    ) -> Result<bool> {
        use WePhase::*;
        let authorizes = matches!(
            (previous, next),
            (Starting, ProviderExposed) | (ProviderExposed, Returning)
        );
        anyhow::ensure!(
            authorizes
                || matches!(
                    (previous, next),
                    (Starting, Rejected)
                        | (ProviderExposed, ProviderUncertain | ResultRetained)
                        | (Returning, Delivered | ReturnUncertain)
                ),
            "Invalid foreground Matrix transition"
        );
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let session = attempt.entry_session;
        let Some((request, phase, retained)) = load(&tx, owner, session, &attempt.original)? else {
            return Ok(false);
        };
        if request.id != attempt.id
            || request.session_id != attempt.session_id
            || request.instance != self.instance_id
            || phase != previous
        {
            return Ok(false);
        }
        if authorizes {
            let Ok((bound, _)) = crate::store::presentation::entry_on(&tx, owner, entry) else {
                return Ok(false);
            };
            if bound != session
                || !owns_writer(&tx, &self.instance_id)?
                || !request.current(&tx, owner, entry, session)?
            {
                return Ok(false);
            }
        }
        let outcome = if next == ProviderExposed {
            let native_session = outcome["native_session_id"]
                .as_str()
                .filter(|id| {
                    !id.is_empty()
                        && id.len() <= 256
                        && !id.chars().any(|c| c.is_whitespace() || c.is_control())
                })
                .context("Bounded native session identity required before provider exposure")?;
            json!({"native_session_id":native_session})
        } else if previous == Returning {
            // Retain the selected send UUID and model result alongside readback.
            json!({"send_id":retained["send_id"],"text":retained["text"],"delivery":outcome})
        } else {
            outcome
        };
        let mut outcome = outcome;
        for field in ["native_session_id", "engine"] {
            if let Some(bound) = retained.get(field) {
                outcome
                    .as_object_mut()
                    .context("Foreground outcome must retain its attempt binding")?
                    .insert(field.into(), bound.clone());
            }
        }
        let raw = serde_json::to_string(&outcome)?;
        anyhow::ensure!(
            raw.len() <= 512 * 1024,
            "Foreground outcome exceeds the journal bound"
        );
        tx.execute(
            "UPDATE interaction_matrix_requests SET phase=?2,submission=?3 WHERE id=?1",
            params![request.id, serde_json::to_value(next)?.as_str(), raw],
        )?;
        tx.commit()?;
        Ok(true)
    }
}
