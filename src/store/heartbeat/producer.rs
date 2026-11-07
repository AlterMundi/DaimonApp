//! Finite metadata observation feeding the existing native-return journal.
//! One bounded source parent per entry; no additional scheduler or input queue.
use super::*;
use crate::store::workflows::{ReturnDispatch, WorkflowReturn};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatProducerContract {
    #[serde(default)]
    pub purpose: Option<HeartbeatPurpose>,
    pub interval_seconds: u32,
    pub max_checks: u32,
    pub expires_at_unix_ms: i64,
    pub matrix_replies: bool,
    #[serde(default)]
    pub matrix_inbox: Option<HeartbeatInboxSource>,
    pub workflows: bool,
    #[serde(default)]
    pub session_progress: bool,
    #[serde(default)]
    pub reports: Vec<super::HeartbeatReportSource>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatPurpose {
    pub input_ref: crate::interaction::InputReference,
    pub channel: String,
}
fn purpose_source(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    native: &str,
    purpose: &HeartbeatPurpose,
) -> Result<(crate::interaction::SourceInput, String)> {
    use crate::interaction::InputReference;
    anyhow::ensure!(
        match &purpose.input_ref {
            InputReference::Conversation(_) => purpose.channel == "conversation",
            InputReference::Telegram(_) => purpose
                .channel
                .strip_prefix("telegram:")
                .is_some_and(|v| v.parse::<u64>().is_ok_and(|n| n > 0)),
        },
        "Select the actual retained human original channel"
    );
    let (source, _) = crate::store::dialogue::original_owned_on(
        conn,
        entry,
        human,
        native,
        &purpose.input_ref,
        &purpose.channel,
        false,
    )?;
    anyhow::ensure!(
        !source.text.trim().is_empty() && source.text.len() <= 16384,
        "Bounded retained human operating purpose required"
    );
    let revision = format!("{:x}", Sha256::digest(serde_json::to_vec(&source)?));
    Ok((source, revision))
}
pub(super) fn purpose_on(
    conn: &Connection,
    p: &Parent,
) -> Result<Option<(crate::interaction::SourceInput, String)>> {
    let Some(purpose) = &p.contract.purpose else {
        return Ok(None);
    };
    let (source, revision) = purpose_source(conn, p.human, p.entry, &p.native, purpose)?;
    anyhow::ensure!(
        p.purpose_revision.as_deref() == Some(revision.as_str()),
        "Human operating-purpose original changed or retired"
    );
    Ok(Some((source, revision)))
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatInboxSource {
    pub source: crate::store::MatrixAuthor,
    pub channel_id: String,
}
/// Checks/cadence are persisted before SDK I/O. The finish guard verifies the
/// same generation/counter before retaining a page or admitting attention.
pub(crate) struct Check {
    human: i64,
    entry: SessionKey,
    session: i64,
    generation: u64,
    sequence: u32,
    binding: String,
    native: String,
    epoch: String,
    pub matrix_inbox: Option<HeartbeatInboxSource>,
    activation: lanes::Activation,
}
#[derive(Clone, Serialize, Deserialize)]
pub(in crate::store) struct Offer {
    pub key: String,
    pub revision: String,
    pub evidence: Value,
}

/// One replaceable observation, not a readiness lease or execution receipt.
#[derive(Clone, Serialize, Deserialize)]
struct CheckObservation {
    sequence: u32,
    generation: u64,
    activation: lanes::Activation,
    started_at_unix_ms: i64,
    completed_at_unix_ms: Option<i64>,
    outcome: String,
    error: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
pub(in crate::store) struct Parent {
    #[serde(default)]
    pub purpose_revision: Option<String>,
    pub human: i64,
    pub entry: SessionKey,
    pub session: i64,
    pub native: String,
    pub binding: String,
    pub epoch: String,
    pub contract: HeartbeatProducerContract,
    pub checks: u32,
    pub next_check_ms: i64,
    pub workflow_after: i64,
    #[serde(default)]
    pub progress_start: i64,
    #[serde(default)]
    pub progress_after: i64,
    pub next_lane: bool,
    #[serde(default)]
    pub next_activation: usize,
    pub stopped_reason: Option<String>,
    #[serde(default)]
    pub inbox_state: Option<String>,
    #[serde(default)]
    last_check: Option<CheckObservation>,
    #[serde(default)]
    last_success_at_unix_ms: Option<i64>,
    pub seen: BTreeMap<String, String>,
    pub native_returns: Vec<WorkflowReturn>,
}

fn select_batch(p: &mut Parent, lanes: &[Vec<Offer>; 5], progress_next: Option<i64>) -> Vec<Offer> {
    let mut selected = vec![];
    let mut lane = usize::from(p.next_lane);
    let mut positions = [0, 0, 0, 0, 0];
    for _ in 0..4 {
        for _ in 0..lanes.len() {
            if positions[lane] < lanes[lane].len() {
                break;
            }
            lane = (lane + 1) % lanes.len();
        }
        if let Some(offer) = lanes[lane].get(positions[lane]) {
            let new_keys = selected
                .iter()
                .filter(|offer: &&Offer| !p.seen.contains_key(&offer.key))
                .count();
            if p.seen.contains_key(&offer.key) || p.seen.len() + new_keys < 256 {
                selected.push(offer.clone());
            }
            positions[lane] += 1;
        }
        lane = (lane + 1) % lanes.len();
    }
    p.next_lane = !p.next_lane;
    // Scanning is not consumption. Keep this page until every unseen progress
    // offer has a slot (or was already reviewed); otherwise lane/page phase can
    // starve one page while repeatedly visiting its successor.
    if let Some(next) = progress_next
        && lanes[4].iter().all(|offer| {
            selected
                .iter()
                .any(|s| s.key == offer.key && s.revision == offer.revision)
        })
    {
        p.progress_after = next;
    }
    selected
}

fn key(human: i64, session: i64) -> String {
    format!("heartbeat_producer:{human}:{session}")
}
fn load(conn: &Connection, human: i64, session: i64) -> Result<Option<Parent>> {
    conn.query_row(
        "SELECT value FROM bot_state WHERE key=?1",
        [key(human, session)],
        |r| r.get::<_, String>(0),
    )
    .optional()?
    .map(|raw| serde_json::from_str(&raw).map_err(Into::into))
    .transpose()
}
pub(in crate::store) fn save_returns(
    conn: &Connection,
    p: &Parent,
    returns: &[WorkflowReturn],
) -> Result<()> {
    let mut p = p.clone();
    p.native_returns = returns.to_vec();
    save(conn, &p)
}
fn save(conn: &Connection, p: &Parent) -> Result<()> {
    let raw = serde_json::to_string(p)?;
    anyhow::ensure!(
        p.seen.len() <= 256 && p.native_returns.len() <= 16 && raw.len() <= 256 * 1024,
        "Heartbeat metadata capacity reached; retained evidence was preserved"
    );
    conn.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key(p.human,p.session),raw])?;
    Ok(())
}
pub(in crate::store) fn load_return(
    conn: &Connection,
    id: &str,
) -> Result<Option<(Parent, usize)>> {
    let Some(rest) = id.strip_prefix("heartbeat:") else {
        return Ok(None);
    };
    let fields: Vec<_> = rest.split(':').collect();
    anyhow::ensure!(fields.len() == 3, "Invalid heartbeat return identity");
    let human: i64 = fields[0].parse()?;
    let session: i64 = fields[1].parse()?;
    let p = load(conn, human, session)?.context("Heartbeat source is unavailable")?;
    let index = p
        .native_returns
        .iter()
        .position(|r| r.id == id)
        .context("Heartbeat return is unavailable")?;
    Ok(Some((p, index)))
}
pub(super) fn bound(conn: &Connection, p: &Parent) -> Result<bool> {
    let Ok((session, native)) = super::super::presentation::entry_on(conn, p.human, p.entry) else {
        return Ok(false);
    };
    Ok(session == p.session
        && native == p.native
        && super::super::presentation::entry_binding(conn, p.human, p.entry, session)? == p.binding
        && super::super::stopping::admission_epoch_on(conn, p.entry)? == p.epoch
        && !super::super::stopping::fenced_on(conn, p.entry)?
        && !super::super::maintenance_writer_held_on(conn, p.entry)?)
}
pub(in crate::store) fn current(
    conn: &Connection,
    p: &Parent,
    r: &WorkflowReturn,
    admission: bool,
) -> Result<bool> {
    if !bound(conn, p)?
        || admission
            && (Utc::now().timestamp_millis() >= p.contract.expires_at_unix_ms
                || r.reported_revision.is_some())
    {
        return Ok(false);
    }
    if admission {
        let Some(activation) = r.attention_activation.as_ref() else {
            return Ok(false);
        };
        if !lanes::current_on(conn, p.human, p.entry, activation)? {
            return Ok(false);
        }
    }
    // Accepted execution narration remains owned by this entry even when its
    // actions consume or change the offered sources. This grants no new work.
    if !admission {
        return Ok(true);
    }
    if purpose_on(conn, p).is_err() {
        return Ok(false);
    }
    let offers: Vec<Offer> = serde_json::from_value(r.envelope["offers"].clone())?;
    for offer in offers {
        if offer.key == "matrix-inbox-status" {
            if p.contract.matrix_inbox.is_none()
                || p.inbox_state
                    .as_ref()
                    .map(|s| format!("inbox-{s}"))
                    .as_deref()
                    != Some(offer.revision.as_str())
            {
                return Ok(false);
            }
        } else if offer.key.starts_with("matrix-inbox:") {
            let source = super::super::presentation::source_on(conn, p.human, p.entry, &offer.key)?;
            if p.contract.matrix_inbox.is_none()
                || p.inbox_state.as_deref() != Some("available")
                || !source.is_some_and(|s| s["current"] == true && s["revision"] == offer.revision)
            {
                return Ok(false);
            }
        } else if let Some(source) = offer.key.strip_prefix("matrix:") {
            let pending: bool = conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM interaction_matrix_results WHERE message_id=?1 AND human_id=?2 AND reported_revision IS NULL)",
                params![source, p.human], |row| row.get(0),
            )?;
            if !pending {
                return Ok(false);
            }
            let source = super::super::presentation::source_on(
                conn,
                p.human,
                p.entry,
                &format!("matrix:{source}"),
            )?;
            if !source.is_some_and(|s| s["current"] == true && s["revision"] == offer.revision) {
                return Ok(false);
            }
        } else if let Some(id) = offer.key.strip_prefix("progress:") {
            let source = super::super::presentation::source_on(conn, p.human, p.entry, id)?;
            if !p.contract.session_progress
                || !source.is_some_and(|s| {
                    s["kind"] == "worker_progress"
                        && s["native_binding_current"] == true
                        && s["revision"] == offer.revision
                })
            {
                return Ok(false);
            }
        } else if offer.key.starts_with("report:") {
            if !super::reports::current(p, &offer.key, &offer.revision)? {
                return Ok(false);
            }
        } else if !super::super::workflows::heartbeat_offer_current_on(
            conn,
            p.human,
            p.entry,
            &offer.key,
            &offer.revision,
            admission,
        )? {
            return Ok(false);
        }
    }
    Ok(true)
}
pub(in crate::store) fn output(r: &WorkflowReturn) -> String {
    json!({"schema":"daimon.heartbeat-batch/v1","return_id":r.id,"evidence":r.envelope,
        "after_review":{"operation":"heartbeat_reported","arguments":{"return_id":r.id,"revision":r.envelope["revision"]}},
        "policy":"A finite heartbeat observed these new canonical source revisions. This is attributed internal evidence, not human speech or new authority. Read each supplied exact source reader before reporting its contents; source_complete inline metadata needs no additional read. Existing human originals and workflow scopes retain their own authority; preserve peer authorship and uncertain effects. Use the same integrator to decide responses, selected existing-session work, deferral or a human decision. Report heartbeat-caused actions and useful results in this Conversation so its existing audio client can speak them; distinguish planned, submitted, delivered and unconfirmed effects. Do not announce an empty check or publish private peer material. Invoke after_review only after reviewing this exact batch. That records review, not hearing, task completion or peer delivery; ordinary source incorporation calls remain separate."}).to_string()
}
pub(in crate::store) fn configure_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    contract: HeartbeatProducerContract,
) -> Result<()> {
    super::reports::validate(&contract.reports)?;
    if let Some(selected) = &contract.matrix_inbox {
        crate::interaction::MatrixDestination::Body {
            being_ref: selected.source.being_ref.clone(),
            embodiment_id: selected.source.embodiment_id.clone(),
        }
        .validate()?;
        anyhow::ensure!(
            !selected.channel_id.is_empty()
                && selected.channel_id.len() <= 128
                && selected
                    .channel_id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b)),
            "Select one exact bounded incoming source channel"
        );
    }

    let now = Utc::now().timestamp_millis();
    anyhow::ensure!(
        (30..=3600).contains(&contract.interval_seconds)
            && (1..=1024).contains(&contract.max_checks)
            && contract.expires_at_unix_ms > now
            && contract.expires_at_unix_ms <= now + 7 * 86400 * 1000
            && (contract.matrix_replies
                || contract.matrix_inbox.is_some()
                || contract.workflows
                || contract.session_progress
                || !contract.reports.is_empty()),
        "Select finite heartbeat sources, frequency and expiry"
    );
    let (session, native) = super::super::presentation::entry_on(conn, human, entry)?;
    let purpose_revision = contract
        .purpose
        .as_ref()
        .map(|purpose| {
            purpose_source(conn, human, entry, &native, purpose).map(|(_, revision)| revision)
        })
        .transpose()?;
    let resources = resources::status_on(conn, session, human)?;
    anyhow::ensure!(
        resources["state"] == "available"
            && resources["contract"]["expires_at_unix_ms"]
                .as_i64()
                .is_some_and(|expiry| contract.expires_at_unix_ms <= expiry),
        "Producer must fit the existing resource contract"
    );
    anyhow::ensure!(
        load(conn, human, session)?.is_none(),
        "Heartbeat producer already configured; counters and cursors were not reset"
    );
    let progress_start: i64 = conn.query_row(
        "SELECT coalesce(max(rowid),0) FROM interaction_native_messages",
        [],
        |r| r.get(0),
    )?;
    save(
        conn,
        &Parent {
            purpose_revision,
            human,
            entry,
            session,
            native,
            binding: super::super::presentation::entry_binding(conn, human, entry, session)?,
            epoch: super::super::stopping::admission_epoch_on(conn, entry)?,
            contract,
            checks: 0,
            next_check_ms: 0,
            workflow_after: 0,
            progress_start,
            progress_after: progress_start,
            next_lane: false,
            next_activation: 0,
            stopped_reason: None,
            inbox_state: None,
            last_check: None,
            last_success_at_unix_ms: None,
            seen: BTreeMap::new(),
            native_returns: vec![],
        },
    )
}
pub(super) fn status_on(conn: &Connection, human: i64, session: i64) -> Result<Value> {
    let Some(p) = load(conn, human, session)? else {
        return Ok(json!({"state":"not_configured"}));
    };
    let state = if p.stopped_reason.is_some() {
        "stopped"
    } else if !bound(conn, &p)? {
        "binding_retired"
    } else if purpose_on(conn, &p).is_err() {
        "purpose_retired"
    } else if Utc::now().timestamp_millis() >= p.contract.expires_at_unix_ms {
        "expired"
    } else if p.checks >= p.contract.max_checks {
        "check_capacity"
    } else if p.seen.len() >= 256 {
        "cursor_capacity"
    } else if p.native_returns.len() >= 16 {
        "receipt_capacity"
    } else {
        "configured"
    };
    Ok(
        json!({"state":state,"contract":p.contract,"checks":p.checks,"next_check_ms":p.next_check_ms,"cursor_entries":p.seen.len(),"retained_returns":p.native_returns.len(),"max_cursor_entries":256,"max_returns":16,"max_document_bytes":262144,"stopped_reason":p.stopped_reason,"pending":pending(&p),"inbox_observation":p.inbox_state,"last_check":p.last_check,"last_success_at_unix_ms":p.last_success_at_unix_ms,"observation_meaning":"Source checks only; not native execution, delivery or current operational readiness","sources":"selected_canonical_matrix_inbox_replies_workflows_and_owned_reports"}),
    )
}
pub(in crate::store) fn retained(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
) -> Result<Option<Parent>> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    Ok(load(conn, human, session)?.filter(|p| {
        p.native_returns
            .iter()
            .any(|r| r.phase == "retained_unsent")
    }))
}
fn unsubmitted_on(conn: &Connection, r: &WorkflowReturn) -> Result<bool> {
    if !matches!(r.phase.as_str(), "reserved" | "retained_unsent")
        || r.native_turn.is_some()
        || r.collection_local.is_some()
    {
        return Ok(false);
    }
    let Some(local) = r.local else {
        return Ok(true);
    };
    Ok(conn.query_row("SELECT EXISTS(SELECT 1 FROM bot_state WHERE key='heartbeat_execution:'||?1 AND json_extract(value,'$.source')=?2 AND json_extract(value,'$.physical') IS NULL AND json_extract(value,'$.terminal_status')='not_submitted')",params![local,r.id],|row|row.get::<_,bool>(0))?)
}
fn pending(p: &Parent) -> bool {
    p.native_returns
        .iter()
        .any(|r| r.reported_revision.is_none() && r.phase != "retired_unsent")
}
pub(super) fn resume_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    generation: u64,
) -> Result<()> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let Some(mut p) = load(conn, human, session)? else {
        return Ok(());
    };
    if bound(conn, &p)? {
        for r in &mut p.native_returns {
            if unsubmitted_on(conn, r)? {
                r.attention_generation = Some(generation);
                if let Some(activation) = &mut r.attention_activation {
                    let raw: String = conn.query_row(
                        "SELECT value FROM bot_state WHERE key=?1",
                        [format!("heartbeat_control:{human}:{session}")],
                        |row| row.get(0),
                    )?;
                    let control: Control = serde_json::from_str(&raw)?;
                    if let Some(selected) = lanes::selected(&control, activation.lane) {
                        activation.generation = selected.generation;
                    }
                }
            }
        }
        save(conn, &p)?;
    }
    Ok(())
}

pub(super) fn renew_window_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    expected_expiry: i64,
    expiry: i64,
) -> Result<Option<Value>> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let mut p = load(conn, human, session)?.context("Heartbeat producer not configured")?;
    anyhow::ensure!(
        p.contract.expires_at_unix_ms == expected_expiry,
        "Producer window changed; inspect status before renewal"
    );
    anyhow::ensure!(
        bound(conn, &p)? && purpose_on(conn, &p).is_ok(),
        "Heartbeat source binding changed"
    );
    anyhow::ensure!(
        p.stopped_reason.is_none()
            && p.checks < p.contract.max_checks
            && p.seen.len() < 256
            && p.native_returns.len() < 16,
        "Producer capacity exhausted; renewal cannot reset counters or evidence"
    );
    let mut retry = None;
    for r in p
        .native_returns
        .iter()
        .filter(|r| r.reported_revision.is_none() && r.phase != "retired_unsent")
    {
        anyhow::ensure!(
            unsubmitted_on(conn, r)?,
            "Pending native return is not proven unsent; renewal refused"
        );
        if r.automatic_retry_exhausted() {
            anyhow::ensure!(
                retry.is_none(),
                "Multiple exhausted pending returns require selected recovery"
            );
            let attempt = r
                .attempts
                .checked_add(1)
                .context("Native attempt counter exhausted")?;
            retry = Some(json!({"source":r.id,"attempt":attempt}));
        }
    }
    // Preserve every cursor, pending identity, retry count and next-check time.
    // Explicit resume separately reconciles only proven-unsent generations.
    p.contract.expires_at_unix_ms = expiry;
    save(conn, &p)?;
    Ok(retry)
}

/// One extra admission of a proven-unsent original, explicitly selected by the
/// owner renewal. The lifetime attempt counter advances; no automatic reset.
pub(in crate::store) fn owner_window_retry_on(
    conn: &Connection,
    r: &WorkflowReturn,
) -> Result<bool> {
    let Some((p, _)) = load_return(conn, &r.id)? else {
        return Ok(false);
    };
    if !unsubmitted_on(conn, r)? {
        return Ok(false);
    }
    let raw: Option<String> = conn
        .query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!(
                "heartbeat_window_renewal:{}:{}",
                p.human, p.session
            )],
            |row| row.get(0),
        )
        .optional()?;
    let Some(raw) = raw else { return Ok(false) };
    let receipt: Value = serde_json::from_str(&raw)?;
    Ok(receipt["retry"]["source"] == r.id
        && r.attempts
            .checked_add(1)
            .is_some_and(|attempt| receipt["retry"]["attempt"] == attempt))
}

fn check_on(conn: &Connection, c: &Check) -> Result<Option<Parent>> {
    let Some(p) = load(conn, c.human, c.session)? else {
        return Ok(None);
    };
    if p.stopped_reason.is_some()
        || executions::unresolved_on(conn, c.human, c.entry)?
        || p.seen.len() >= 256
        || p.native_returns.len() >= 16
        || p.checks != c.sequence
        || p.binding != c.binding
        || p.native != c.native
        || p.epoch != c.epoch
        || !bound(conn, &p)?
        || purpose_on(conn, &p).is_err()
        || !generation_current_on(conn, c.human, c.entry, c.generation)?
        || !lanes::current_on(conn, c.human, c.entry, &c.activation)?
        || Utc::now().timestamp_millis() >= p.contract.expires_at_unix_ms
        || resources::status_on(conn, c.session, c.human)?["state"] != "available"
    {
        return Ok(None);
    }
    Ok(Some(p))
}
impl Store {
    /// Called by existing owned maintenance, never a new background loop.
    #[cfg(test)]
    pub(crate) fn heartbeat_produce(
        &self,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<ReturnDispatch>> {
        let Some(check) = self.heartbeat_begin_check(human, entry)? else {
            return Ok(None);
        };
        self.heartbeat_finish_check(&check, None)
    }
    pub(crate) fn heartbeat_begin_check(
        &self,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<Check>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let Some(mut p) = load(&tx, human, session)? else {
            return Ok(None);
        };
        let control: Control = tx
            .query_row(
                "SELECT value FROM bot_state WHERE key=?1",
                [format!("heartbeat_control:{human}:{session}")],
                |r| r.get::<_, String>(0),
            )
            .map(|raw| serde_json::from_str(&raw))??;
        if control.paused || !bound(&tx, &p)? || purpose_on(&tx, &p).is_err() {
            return Ok(None);
        }
        let available = [
            (
                HeartbeatLane::Messaging,
                p.contract.matrix_replies || p.contract.matrix_inbox.is_some(),
            ),
            (HeartbeatLane::WorkflowReturns, p.contract.workflows),
            (HeartbeatLane::Reports, !p.contract.reports.is_empty()),
            (HeartbeatLane::SessionProgress, p.contract.session_progress),
        ];
        let activation = (0..available.len()).find_map(|offset| {
            let index = (p.next_activation % available.len() + offset) % available.len();
            let (lane, configured) = available[index];
            configured
                .then(|| lanes::selected(&control, lane))
                .flatten()
                .map(|a| (index, a))
        });
        let Some((index, activation)) = activation else {
            return Ok(None);
        };
        // Restart keeps original uncertainty and the same bounded retry journal.
        for r in &mut p.native_returns {
            if r.instance != self.instance_id {
                if r.phase == "reserved" {
                    r.phase = "retained_unsent".into();
                    r.retry_after = Some(Utc::now().timestamp() + 2)
                } else if r.phase == "submitting" {
                    r.phase = "uncertain".into()
                }
            }
        }
        let now = Utc::now().timestamp_millis();
        if p.stopped_reason.is_some()
            || executions::unresolved_on(&tx, human, entry)?
            || now < p.next_check_ms
            || now >= p.contract.expires_at_unix_ms
            || p.checks >= p.contract.max_checks
            || p.seen.len() >= 256
            || p.native_returns.len() >= 16
            || resources::status_on(&tx, session, human)?["state"] != "available"
        {
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        p.next_activation = (index + 1) % available.len();
        p.checks += 1;
        p.next_check_ms = now + i64::from(p.contract.interval_seconds) * 1000;
        p.last_check = Some(CheckObservation {
            sequence: p.checks,
            generation: control.generation,
            activation: activation.clone(),
            started_at_unix_ms: now,
            completed_at_unix_ms: None,
            outcome: "in_progress".into(),
            error: None,
        });
        // A failed source read still consumes this finite observation. It must
        // not roll back the cadence/counter and spin on the same failure.
        save(&tx, &p)?;
        tx.commit()?;
        Ok(Some(Check {
            human,
            entry,
            session,
            generation: control.generation,
            sequence: p.checks,
            binding: p.binding,
            native: p.native,
            epoch: p.epoch,
            matrix_inbox: if activation.lane == HeartbeatLane::Messaging {
                p.contract.matrix_inbox
            } else {
                None
            },
            activation,
        }))
    }
    pub(crate) fn heartbeat_check_current(&self, c: &Check) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        Ok(check_on(&conn, c)?.is_some())
    }
    pub(crate) fn heartbeat_finish_check(
        &self,
        c: &Check,
        read: Option<
            Result<(
                crate::store::MatrixInboxSelection,
                crate::store::MatrixInboxPage,
            )>,
        >,
    ) -> Result<Option<ReturnDispatch>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let mut tx = conn.transaction()?;
        let Some(mut p) = check_on(&tx, c)? else {
            return Ok(None);
        };
        let (human, entry, session) = (c.human, c.entry, c.session);
        if let Some(source) = &c.matrix_inbox {
            // Roll back all partial event/cursor writes before retaining a
            // failed observation. The check/cadence remains consumed.
            let retained = match read {
                Some(Ok((selected, page))) if selected.belongs(human, entry, source) => {
                    let savepoint = tx.savepoint()?;
                    match super::super::matrix::inbox::retain_on(&savepoint, &selected, page) {
                        Ok(_) => {
                            savepoint.commit()?;
                            true
                        }
                        Err(_) => false,
                    }
                }
                _ => false,
            };
            p.inbox_state = Some(if retained { "available" } else { "unavailable" }.into());
        }
        let now = Utc::now().timestamp_millis();
        let error = (c.matrix_inbox.is_some() && p.inbox_state.as_deref() != Some("available"))
            .then(|| "matrix_inbox_unavailable".to_owned());
        if let Some(observation) = &mut p.last_check {
            observation.completed_at_unix_ms = Some(now);
            observation.outcome = if error.is_some() {
                "failed"
            } else {
                "succeeded"
            }
            .into();
            observation.error = error.clone();
        }
        if error.is_none() {
            p.last_success_at_unix_ms = Some(now);
        }
        let mut retire = vec![];
        for (index, r) in p.native_returns.iter().enumerate() {
            if r.reported_revision.is_none()
                && unsubmitted_on(&tx, r)?
                && !current(&tx, &p, r, true)?
            {
                retire.push(index)
            }
        }
        for index in retire {
            p.native_returns[index].phase = "retired_unsent".into();
        }
        if pending(&p) {
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        let mut lanes = [vec![], vec![], vec![], vec![], vec![]];
        if c.activation.lane == HeartbeatLane::Messaging && p.contract.matrix_replies {
            let value = super::super::matrix::heartbeat_attention_on(&tx, human, entry, &p.seen)?;
            for item in value["envelopes"].as_array().into_iter().flatten() {
                if let (Some(key), Some(revision)) =
                    (item["source"].as_str(), item["revision"].as_str())
                {
                    if p.seen.get(key).is_none_or(|prior| prior != revision) {
                        lanes[0].push(Offer {
                            key: key.into(),
                            revision: revision.into(),
                            evidence: item.clone(),
                        });
                    }
                }
            }
        }
        if c.activation.lane == HeartbeatLane::WorkflowReturns && p.contract.workflows {
            let (after, offers) =
                super::super::workflows::heartbeat_offers_on(&tx, human, entry, p.workflow_after)?;
            p.workflow_after = after;
            lanes[1] = offers
                .into_iter()
                .filter(|offer| p.seen.get(&offer.key) != Some(&offer.revision))
                .collect();
        }
        lanes[2] = super::reports::offers(if c.activation.lane == HeartbeatLane::Reports {
            &p.contract.reports
        } else {
            &[]
        })?
        .into_iter()
        .filter(|offer| p.seen.get(&offer.key) != Some(&offer.revision))
        .collect();
        let mut progress_next = None;
        if c.activation.lane == HeartbeatLane::SessionProgress && p.contract.session_progress {
            let (after, offers) = super::super::presentation::heartbeat_progress_on(
                &tx,
                human,
                entry,
                p.progress_start,
                p.progress_after,
            )?;
            progress_next = Some(after);
            lanes[4] = offers
                .into_iter()
                .filter(|o| p.seen.get(&o.key) != Some(&o.revision))
                .collect();
        }
        if let Some(source) = &c.matrix_inbox {
            if p.inbox_state.as_deref() == Some("available") {
                lanes[3] =
                    super::super::matrix::inbox::offers_on(&tx, human, entry, source, &p.seen)?;
            }
            if let Some(state) = &p.inbox_state {
                let revision = format!("inbox-{state}");
                let health = "matrix-inbox-status";
                if (state == "unavailable" || p.seen.contains_key(health))
                    && p.seen.get(health) != Some(&revision)
                {
                    lanes[3].insert(0,Offer {key:health.into(),revision:revision.clone(),evidence:json!({"source":health,"revision":revision,"reason":"matrix_inbox_observation","state":state,"source_complete":true,"meaning":"Retained source-read health, not a peer message or execution authority"})});
                }
            }
        }
        let selected = select_batch(&mut p, &lanes, progress_next);
        if selected.is_empty() {
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        let id = format!("heartbeat:{human}:{session}:{}", Uuid::now_v7());
        let mut envelope = json!({"schema":"daimon.heartbeat-offer/v1","lane":c.activation.lane,"offers":selected,"internal_evidence":true,"publication_grant":false});
        if let Some((source, revision)) = purpose_on(&tx, &p)? {
            envelope["operating_purpose"] = json!({"input_ref":p.contract.purpose.as_ref().unwrap().input_ref,"human_id":human,"channel":source.channel,"event_id":source.event_id,"revision":revision,"reader":{"operation":"heartbeat_source","arguments":{"return_id":id,"source":"purpose:human","revision":revision,"offset":0}},"meaning":"Actual retained human operating-purpose original, not new speech or peer authority. Read before selecting an ordinary workflow under this same original and preserve peer source attribution."});
        }
        envelope["revision"] = json!(format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&envelope)?)
        ));
        if serde_json::to_vec(&envelope)?.len() > 16384 {
            p.stopped_reason = Some("batch_metadata_capacity".into());
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        let r = WorkflowReturn {
            id: id.clone(),
            workflow: String::new(),
            attention_generation: Some(c.generation),
            attention_activation: Some(c.activation.clone()),
            reported_revision: None,
            envelope,
            phase: "reserved".into(),
            local: None,
            collection_local: None,
            native_turn: None,
            instance: self.instance_id.clone(),
            attempts: 1,
            retry_after: None,
        };
        let result = ReturnDispatch {
            name: "heartbeat_attention",
            id,
            attempts: 1,
            human,
            entry,
            native: p.native.clone(),
            epoch: p.epoch.clone(),
            output: output(&r),
            attention_generation: r.attention_generation,
        };
        p.native_returns.push(r);
        // Reserve room for this receipt's ACK and at most four new cursor keys.
        if serde_json::to_vec(&p)?.len() > 256 * 1024 - 1024 {
            p.native_returns.pop();
            p.stopped_reason = Some("document_capacity".into());
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        save(&tx, &p)?;
        tx.commit()?;
        Ok(Some(result))
    }
    pub(crate) fn heartbeat_reported(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        id: &str,
        revision: &str,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (mut p, index) = load_return(&tx, id)?.context("Unknown heartbeat source")?;
        anyhow::ensure!(
            p.human == human && p.entry == entry && p.native == native && bound(&tx, &p)?,
            "Heartbeat owner retired"
        );
        let r = &p.native_returns[index];
        anyhow::ensure!(
            r.envelope["revision"] == revision && r.phase.starts_with("accepted"),
            "Heartbeat batch was not accepted at this exact revision"
        );
        if r.reported_revision.as_deref() == Some(revision) {
            return Ok(());
        }
        let offers: Vec<Offer> = serde_json::from_value(r.envelope["offers"].clone())?;
        for offer in offers {
            p.seen.insert(offer.key, offer.revision);
        }
        p.native_returns[index].reported_revision = Some(revision.into());
        save(&tx, &p)?;
        tx.commit()?;
        Ok(())
    }
}

#[cfg(test)]
mod inbox_tests {
    use super::*;
    use crate::store::HeartbeatCommand as H;
    fn setup() -> (
        tempfile::NamedTempFile,
        Store,
        SessionKey,
        HeartbeatInboxSource,
    ) {
        let f = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(f.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let e = SessionKey::new(100, Some(1));
        s.ensure_session(e, 100, &crate::store::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(e, "entry-native").unwrap();
        let source = HeartbeatInboxSource {
            source: crate::store::MatrixAuthor {
                being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
                embodiment_id: "embodiment:source".into(),
            },
            channel_id: "tribe".into(),
        };
        s.heartbeat_control(100, e, H::Pause).unwrap();
        let resources = test_contract();
        let expiry = resources.expires_at_unix_ms;
        s.heartbeat_control(
            100,
            e,
            H::ConfigureResources {
                generation: 1,
                contract: resources,
            },
        )
        .unwrap();
        s.heartbeat_control(
            100,
            e,
            H::ConfigureProducer {
                generation: 1,
                contract: HeartbeatProducerContract {
                    purpose: None,
                    interval_seconds: 30,
                    max_checks: 6,
                    expires_at_unix_ms: expiry,
                    matrix_replies: false,
                    matrix_inbox: Some(source.clone()),
                    workflows: false,
                    session_progress: false,
                    reports: vec![],
                },
            },
        )
        .unwrap();
        super::super::enable_test_lanes(&s, 100, e);
        s.heartbeat_control(100, e, H::Resume { generation: 1 })
            .unwrap();
        (f, s, e, source)
    }
    #[test]
    fn owner_window_renewal_preserves_pending_source_and_all_counters() {
        let (_f, s, e, source) = setup();
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let selected = selection(&s, e, &source);
        let original = s
            .heartbeat_finish_check(
                &c,
                Some(Ok((selected.clone(), page(&selected, vec![item(1)])))),
            )
            .unwrap()
            .unwrap();
        let status = s.heartbeat_control(100, e, H::Pause).unwrap();
        let generation = status["generation"].as_u64().unwrap();
        let expired = Utc::now().timestamp_millis() - 1000;
        let renewed = Utc::now().timestamp_millis() + 3_600_000;
        let before = {
            let mut conn = s.conn.lock().unwrap();
            let (session, _) = super::super::super::presentation::entry_on(&conn, 100, e).unwrap();
            let tx = conn.transaction().unwrap();
            resources::reserve_on(&tx, session, 100).unwrap();
            let mut p = load(&tx, 100, session).unwrap().unwrap();
            p.contract.expires_at_unix_ms = expired;
            p.native_returns[0].phase = "retained_unsent".into();
            p.native_returns[0].attempts = 3;
            p.native_returns[0].retry_after = None;
            save(&tx, &p).unwrap();
            tx.execute("UPDATE bot_state SET value=json_set(value,'$.contract.expires_at_unix_ms',?2) WHERE key=?1",
                params![format!("heartbeat_resources:100:{session}"),expired]).unwrap();
            tx.commit().unwrap();
            serde_json::to_value(p).unwrap()
        };
        assert!(
            s.heartbeat_renew_window(100, e, generation + 1, expired, renewed)
                .is_err()
        );
        s.heartbeat_renew_window(100, e, generation, expired, renewed)
            .unwrap();
        // An exact lost-ACK observation cannot renew a second time or refill.
        s.heartbeat_renew_window(100, e, generation, expired, renewed)
            .unwrap();
        let after = s.heartbeat_control(100, e, H::Status).unwrap();
        assert_eq!(after["admission_paused"], true);
        assert_eq!(after["generation"], generation);
        assert_eq!(after["resources"]["reserved_provider_attempts"], 3);
        assert_eq!(after["producer"]["checks"], 1);
        let conn = s.conn.lock().unwrap();
        let (session, _) = super::super::super::presentation::entry_on(&conn, 100, e).unwrap();
        let mut expected = before;
        expected["contract"]["expires_at_unix_ms"] = json!(renewed);
        let actual = serde_json::to_value(load(&conn, 100, session).unwrap().unwrap()).unwrap();
        assert_eq!(actual, expected);
        assert_eq!(actual["native_returns"][0]["id"], original.id);
        drop(conn);
        s.heartbeat_control(100, e, H::Resume { generation })
            .unwrap();
        let retry = s.heartbeat_returns_recover_unsent(100, e).unwrap();
        assert_eq!(retry.len(), 1);
        assert_eq!(retry[0].id, original.id);
        assert_eq!(retry[0].attempts, 4);
        assert!(
            s.heartbeat_returns_recover_unsent(100, e)
                .unwrap()
                .is_empty()
        );
        s.workflow_native_outcome_attempt(&original.id, 4, "retained_unsent", None)
            .unwrap();
        // A failed fourth admission cannot consume the same owner permit again.
        assert!(
            s.heartbeat_returns_recover_unsent(100, e)
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn owner_window_renewal_rolls_back_when_producer_is_exhausted_or_uncertain() {
        let (_f, s, e, source) = setup();
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let selected = selection(&s, e, &source);
        s.heartbeat_finish_check(
            &c,
            Some(Ok((selected.clone(), page(&selected, vec![item(1)])))),
        )
        .unwrap()
        .unwrap();
        let status = s.heartbeat_control(100, e, H::Pause).unwrap();
        let generation = status["generation"].as_u64().unwrap();
        let expired = Utc::now().timestamp_millis() - 1000;
        let renewed = Utc::now().timestamp_millis() + 3_600_000;
        let session = {
            let conn = s.conn.lock().unwrap();
            let (session, _) = super::super::super::presentation::entry_on(&conn, 100, e).unwrap();
            let mut p = load(&conn, 100, session).unwrap().unwrap();
            p.contract.expires_at_unix_ms = expired;
            p.native_returns[0].phase = "uncertain".into();
            save(&conn, &p).unwrap();
            conn.execute("UPDATE bot_state SET value=json_set(value,'$.contract.expires_at_unix_ms',?2) WHERE key=?1",
                params![format!("heartbeat_resources:100:{session}"),expired]).unwrap();
            session
        };
        let before = s.heartbeat_control(100, e, H::Status).unwrap();
        assert!(
            s.heartbeat_renew_window(100, e, generation, expired, renewed)
                .is_err()
        );
        assert_eq!(s.heartbeat_control(100, e, H::Status).unwrap(), before);
        {
            let conn = s.conn.lock().unwrap();
            let mut p = load(&conn, 100, session).unwrap().unwrap();
            p.native_returns[0].phase = "retained_unsent".into();
            p.checks = p.contract.max_checks;
            save(&conn, &p).unwrap();
        }
        assert!(
            s.heartbeat_renew_window(100, e, generation, expired, renewed)
                .is_err()
        );
        assert_eq!(
            s.heartbeat_control(100, e, H::Status).unwrap()["resources"],
            before["resources"]
        );
        // Renewal is deliberately absent from the model-accessible command enum.
        assert!(
            serde_json::from_value::<H>(json!({"action":"renew_window","generation":generation}))
                .is_err()
        );
    }

    #[test]
    fn heartbeat_lane_pause_fences_a_late_sdk_page_without_affecting_other_lane_changes() {
        let (_f, s, e, source) = setup();
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let selected = selection(&s, e, &source);
        let before = selected.after;
        s.heartbeat_control(
            100,
            e,
            H::PauseLane {
                lane: HeartbeatLane::Reports,
            },
        )
        .unwrap();
        assert!(s.heartbeat_check_current(&c).unwrap());
        s.heartbeat_control(
            100,
            e,
            H::PauseLane {
                lane: HeartbeatLane::Messaging,
            },
        )
        .unwrap();
        assert!(!s.heartbeat_check_current(&c).unwrap());
        assert!(
            s.heartbeat_finish_check(
                &c,
                Some(Ok((selected.clone(), page(&selected, vec![item(1)]))))
            )
            .unwrap()
            .is_none()
        );
        assert_eq!(selection(&s, e, &source).after, before);
        assert!(s.heartbeat_begin_check(100, e).unwrap().is_none());
        let state = s.heartbeat_control(100, e, H::Status).unwrap();
        assert_eq!(state["producer"]["checks"], 1);
        s.heartbeat_control(
            100,
            e,
            H::ResumeLane {
                lane: HeartbeatLane::Messaging,
                generation: 2,
            },
        )
        .unwrap();
        due(&s, e);
        let next = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        assert_eq!(next.activation.generation, 3);
        assert_eq!(next.activation.lane, HeartbeatLane::Messaging);
    }

    #[test]
    fn progress_pages_do_not_advance_past_unselected_rows_under_five_lane_contention() {
        let (_f, s, e, _) = setup();
        let conn = s.conn.lock().unwrap();
        let (session, _) = super::super::super::presentation::entry_on(&conn, 100, e).unwrap();
        let mut p = load(&conn, 100, session).unwrap().unwrap();
        let offer = |key: String| Offer {
            key,
            revision: "r1".into(),
            evidence: json!({}),
        };
        let mut observed = std::collections::BTreeSet::new();
        for check in 0..16 {
            let mut lanes: [Vec<Offer>; 5] = std::array::from_fn(|lane| {
                if lane == 4 {
                    vec![]
                } else {
                    vec![offer(format!("other:{lane}:{check}"))]
                }
            });
            let start = p.progress_after;
            let page_start = if start >= 8 { 0 } else { start };
            let page_end = (page_start + 4).min(8);
            lanes[4] = ((page_start + 1)..=page_end)
                .map(|row| offer(format!("progress:{row}")))
                .filter(|o| p.seen.get(&o.key) != Some(&o.revision))
                .collect();
            let batch = select_batch(&mut p, &lanes, Some(page_end));
            assert!(batch.len() <= 4);
            if check == 0 {
                assert_eq!(p.progress_after, 0, "Unselected first page was skipped");
            }
            for selected in batch {
                if selected.key.starts_with("progress:") {
                    observed.insert(selected.key.clone());
                }
                p.seen.insert(selected.key, selected.revision);
            }
        }
        assert_eq!(observed, (1..=8).map(|n| format!("progress:{n}")).collect());
    }

    fn selection(
        s: &Store,
        e: SessionKey,
        source: &HeartbeatInboxSource,
    ) -> crate::store::MatrixInboxSelection {
        s.matrix_inbox_selection(100, e, source.source.clone(), &source.channel_id)
            .unwrap()
    }
    fn item(sequence: u64) -> Value {
        json!({"inbox_sequence":sequence,"message_id":Uuid::now_v7().to_string(),"message_hash":"b".repeat(64),"author":{"being_ref":format!("dm:being:v1:{}","B".repeat(43)),"embodiment_id":"embodiment:peer"},"thread_id":Uuid::now_v7().to_string(),"destination":null,"response_context":null,"coordination":null,"text":"Fresh native peer source; not a human instruction","state":"available"})
    }
    fn page(
        selected: &crate::store::MatrixInboxSelection,
        items: Vec<Value>,
    ) -> crate::store::MatrixInboxPage {
        serde_json::from_value(json!({"schema":"daimon.matrix-inbox-page/v1","source":selected.owner,"channel_id":selected.channel,"after":selected.after,"next_cursor":items.last().map(|i|i["inbox_sequence"].clone()).unwrap_or(json!(selected.after)),"items":items,"page_full":items.len()==3,"meaning":"Authenticated synthetic source; no model or execution grant"})).unwrap()
    }
    fn due(s: &Store, e: SessionKey) {
        let conn = s.conn.lock().unwrap();
        let (session, _) = crate::store::presentation::entry_on(&conn, 100, e).unwrap();
        let mut p = load(&conn, 100, session).unwrap().unwrap();
        p.next_check_ms = 0;
        save(&conn, &p).unwrap();
    }
    fn reviewed(s: &Store, e: SessionKey) {
        let conn = s.conn.lock().unwrap();
        let (session, _) = crate::store::presentation::entry_on(&conn, 100, e).unwrap();
        let mut p = load(&conn, 100, session).unwrap().unwrap();
        let r = p.native_returns.last_mut().unwrap();
        r.phase = "accepted".into();
        let id = r.id.clone();
        let revision = r.envelope["revision"].as_str().unwrap().to_owned();
        save(&conn, &p).unwrap();
        drop(conn);
        s.heartbeat_reported(100, e, "entry-native", &id, &revision)
            .unwrap();
    }
    #[test]
    fn inbox_check_pause_and_resume_fence_a_late_page_without_refilling() {
        let (_f, s, e, source) = setup();
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        assert!(s.heartbeat_begin_check(100, e).unwrap().is_none());
        let selected = selection(&s, e, &source);
        let paused = s.heartbeat_control(100, e, H::Pause).unwrap();
        assert_eq!(paused["producer"]["last_check"]["outcome"], "in_progress");
        assert!(!s.heartbeat_check_current(&c).unwrap());
        assert!(
            s.heartbeat_finish_check(
                &c,
                Some(Ok((selected.clone(), page(&selected, vec![item(1)]))))
            )
            .unwrap()
            .is_none()
        );
        s.heartbeat_control(
            100,
            e,
            H::Resume {
                generation: paused["generation"].as_u64().unwrap(),
            },
        )
        .unwrap();
        assert!(
            s.heartbeat_finish_check(
                &c,
                Some(Ok((selected.clone(), page(&selected, vec![item(1)]))))
            )
            .unwrap()
            .is_none()
        );
        assert_eq!(selection(&s, e, &source).after, 0);
        let fenced = s.heartbeat_control(100, e, H::Status).unwrap();
        assert!(fenced["producer"]["last_check"]["completed_at_unix_ms"].is_null());
        assert!(fenced["producer"]["last_success_at_unix_ms"].is_null());
        due(&s, e);
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let r = s
            .heartbeat_finish_check(
                &c,
                Some(Ok((selected.clone(), page(&selected, vec![item(1)])))),
            )
            .unwrap()
            .unwrap();
        let packet: Value = serde_json::from_str(&r.output).unwrap();
        let offered = &packet["evidence"]["offers"][0];
        assert_eq!(offered["evidence"]["reason"], "matrix_original_available");
        let args = &offered["evidence"]["reader"]["arguments"];
        let part = s
            .interaction_presentation_part(
                100,
                e,
                args["source"].as_str().unwrap(),
                args["revision"].as_str().unwrap(),
                0,
            )
            .unwrap();
        assert_eq!(
            part["text"],
            "Fresh native peer source; not a human instruction"
        );
        let status = s.heartbeat_control(100, e, H::Status).unwrap();
        assert_eq!(status["producer"]["checks"], 2);
        assert_eq!(status["producer"]["last_check"]["sequence"], 2);
        assert_eq!(
            status["producer"]["last_check"]["generation"],
            status["generation"]
        );
        assert_eq!(
            status["producer"]["last_check"]["activation"]["lane"],
            "messaging"
        );
        assert_eq!(status["producer"]["last_check"]["outcome"], "succeeded");
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
        assert_eq!(selection(&s, e, &source).after, 1);
    }
    #[test]
    fn inbox_no_news_is_quiet_and_failed_reads_consume_checks_without_repeated_attention() {
        let (_f, s, e, source) = setup();
        let initial = s.heartbeat_control(100, e, H::Status).unwrap();
        assert!(initial["producer"]["last_check"].is_null());
        assert!(initial["producer"]["last_success_at_unix_ms"].is_null());
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let selected = selection(&s, e, &source);
        assert!(
            s.heartbeat_finish_check(&c, Some(Ok((selected.clone(), page(&selected, vec![])))))
                .unwrap()
                .is_none()
        );
        let success = s.heartbeat_control(100, e, H::Status).unwrap();
        let last_success = &success["producer"]["last_success_at_unix_ms"];
        assert!(last_success.as_i64().is_some());
        assert_eq!(
            last_success,
            &success["producer"]["last_check"]["completed_at_unix_ms"]
        );
        due(&s, e);
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let r = s
            .heartbeat_finish_check(
                &c,
                Some(Err(anyhow::anyhow!("synthetic source unavailable"))),
            )
            .unwrap()
            .unwrap();
        assert!(r.output.contains("matrix-inbox-status"));
        let failed = s.heartbeat_control(100, e, H::Status).unwrap();
        assert_eq!(failed["producer"]["last_check"]["outcome"], "failed");
        assert_eq!(
            failed["producer"]["last_check"]["error"],
            "matrix_inbox_unavailable"
        );
        assert_eq!(&failed["producer"]["last_success_at_unix_ms"], last_success);
        assert!(!failed.to_string().contains("synthetic source unavailable"));
        reviewed(&s, e);
        due(&s, e);
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        assert!(
            s.heartbeat_finish_check(&c, Some(Err(anyhow::anyhow!("same unavailable source"))))
                .unwrap()
                .is_none()
        );
        due(&s, e);
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let recovered = s
            .heartbeat_finish_check(&c, Some(Ok((selected.clone(), page(&selected, vec![])))))
            .unwrap()
            .unwrap();
        assert!(recovered.output.contains("inbox-available"));
        reviewed(&s, e);
        due(&s, e);
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        assert!(
            s.heartbeat_finish_check(&c, Some(Ok((selected.clone(), page(&selected, vec![])))))
                .unwrap()
                .is_none()
        );
        let status = s.heartbeat_control(100, e, H::Status).unwrap();
        assert_eq!(status["producer"]["checks"], 5);
        assert_eq!(status["producer"]["last_check"]["outcome"], "succeeded");
        assert!(status["producer"]["last_check"]["error"].is_null());
        assert!(
            status["producer"]["last_success_at_unix_ms"]
                .as_i64()
                .unwrap()
                >= last_success.as_i64().unwrap()
        );
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
    }
    #[test]
    fn inbox_failed_page_rolls_back_its_savepoint_but_retains_finite_observation() {
        let (_f, s, e, source) = setup();
        for n in 0..85 {
            let selected = selection(&s, e, &source);
            s.matrix_inbox_retain(
                &selected,
                page(&selected, (1..=3).map(|i| item(n * 3 + i)).collect()),
            )
            .unwrap();
        }
        let c = s.heartbeat_begin_check(100, e).unwrap().unwrap();
        let selected = selection(&s, e, &source);
        assert_eq!(selected.after, 255);
        let r = s
            .heartbeat_finish_check(
                &c,
                Some(Ok((
                    selected.clone(),
                    page(&selected, vec![item(256), item(257)]),
                ))),
            )
            .unwrap()
            .unwrap();
        assert!(r.output.contains("inbox-unavailable"));
        assert!(!r.output.contains("matrix_original_available"));
        assert_eq!(selection(&s, e, &source).after, 255);
        assert_eq!(
            s.conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            255
        );
        assert_eq!(
            s.heartbeat_control(100, e, H::Status).unwrap()["producer"]["checks"],
            1
        );
    }
}
