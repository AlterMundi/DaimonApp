//! Foreground /we requests share the canonical Matrix request journal.
use super::*;
use serde_json::Value;

// Each entry may run one undispatched foreground turn at a time. Bound the
// catalog without removing originals or uncertain effects.
const MAX_REQUESTS: i64 = 64;

#[derive(Serialize, Deserialize, PartialEq, Eq, Debug)]
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
    entry_session: i64,
    original: String,
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
    let native_session_id = result.as_object_mut().and_then(|outcome| {
        outcome.remove("text");
        outcome.remove("native_session_id")
    });
    if phase == WePhase::ProviderExposed && result.as_object().is_some_and(|obj| obj.is_empty()) {
        result = Value::Null;
    }
    let native_session_id = native_session_id
        .as_ref()
        .and_then(Value::as_str)
        .or_else(|| {
            // Legacy Claude attempts used the allocated UUID for both identities.
            (!matches!(phase, WePhase::Starting | WePhase::Rejected))
                .then_some(request.session_id.as_str())
        });
    json!({"request_id":request.id,"input_id":request.original.event_id,
        "session_id":request.session_id,"native_session_id":native_session_id,
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

    pub(crate) fn we_start(
        &self,
        owner: i64,
        entry: SessionKey,
        source: MatrixAuthor,
        body: Value,
        original: WeOriginal,
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
        use crate::store::{presentation, stopping};
        let (session, _) = presentation::entry_on(&tx, owner, entry)?;
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
        let request = Request {
            id: Uuid::now_v7().to_string(),
            instance: self.instance_id.clone(),
            entry_generation: presentation::entry_binding(&tx, owner, entry, session)?,
            epoch: stopping::admission_epoch_on(&tx, entry)?,
            session_id: Uuid::new_v4().to_string(),
            source,
            body,
            original,
        };
        anyhow::ensure!(
            request.current(&tx, owner, entry, session)?,
            "Foreground Matrix admission is fenced"
        );
        tx.execute(
            "INSERT INTO interaction_matrix_requests(id,human_id,entry_session,source_channel,source_event,doc,phase,created_at)
             VALUES(?1,?2,?3,'/we',?4,?5,'starting',?6)",
            params![request.id, owner, session, request.original.event_id, serde_json::to_string(&request)?, now_string()],
        )?;
        tx.commit()?;
        Ok(Some(WeAttempt {
            id: request.id,
            session_id: request.session_id,
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
            if bound != session || !request.current(&tx, owner, entry, session)? {
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
        if let Some(native_session) = retained.get("native_session_id") {
            outcome
                .as_object_mut()
                .context("Foreground outcome must retain its native session")?
                .insert("native_session_id".into(), native_session.clone());
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
