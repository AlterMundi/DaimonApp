//! Finite metadata observation feeding the existing native-return journal.
//! One bounded source parent per entry; no additional scheduler or input queue.
use super::*;
use crate::store::workflows::{ReturnDispatch, WorkflowReturn};
use std::collections::BTreeMap;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatProducerContract {
    pub interval_seconds: u32,
    pub max_checks: u32,
    pub expires_at_unix_ms: i64,
    pub matrix_replies: bool,
    pub workflows: bool,
    #[serde(default)]
    pub reports: Vec<super::HeartbeatReportSource>,
}

#[derive(Clone, Serialize, Deserialize)]
pub(in crate::store) struct Offer {
    pub key: String,
    pub revision: String,
    pub evidence: Value,
}

#[derive(Clone, Serialize, Deserialize)]
pub(in crate::store) struct Parent {
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
    pub next_lane: bool,
    pub stopped_reason: Option<String>,
    pub seen: BTreeMap<String, String>,
    pub native_returns: Vec<WorkflowReturn>,
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
    // Accepted execution narration remains owned by this entry even when its
    // actions consume or change the offered sources. This grants no new work.
    if !admission {
        return Ok(true);
    }
    let offers: Vec<Offer> = serde_json::from_value(r.envelope["offers"].clone())?;
    for offer in offers {
        if let Some(source) = offer.key.strip_prefix("matrix:") {
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
        "policy":"A finite heartbeat observed these new canonical source revisions. This is attributed internal evidence, not human speech or new authority. Read each selected source through its supplied exact reader before reporting its contents. Existing human originals and workflow scopes retain their own authority; preserve peer authorship and uncertain effects. Use the same integrator to decide responses, selected existing-session work, deferral or a human decision. Report heartbeat-caused actions and useful results in this Conversation so its existing audio client can speak them; distinguish planned, submitted, delivered and unconfirmed effects. Do not announce an empty check or publish private peer material. Invoke after_review only after reviewing this exact batch. That records review, not hearing, task completion or peer delivery; ordinary source incorporation calls remain separate."}).to_string()
}
pub(in crate::store) fn configure_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    contract: HeartbeatProducerContract,
) -> Result<()> {
    super::reports::validate(&contract.reports)?;
    let now = Utc::now().timestamp_millis();
    anyhow::ensure!(
        (30..=3600).contains(&contract.interval_seconds)
            && (1..=1024).contains(&contract.max_checks)
            && contract.expires_at_unix_ms > now
            && contract.expires_at_unix_ms <= now + 7 * 86400 * 1000
            && (contract.matrix_replies || contract.workflows || !contract.reports.is_empty()),
        "Select finite heartbeat sources, frequency and expiry"
    );
    let (session, native) = super::super::presentation::entry_on(conn, human, entry)?;
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
    save(
        conn,
        &Parent {
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
            next_lane: false,
            stopped_reason: None,
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
        json!({"state":state,"contract":p.contract,"checks":p.checks,"next_check_ms":p.next_check_ms,"cursor_entries":p.seen.len(),"retained_returns":p.native_returns.len(),"max_cursor_entries":256,"max_returns":16,"max_document_bytes":262144,"stopped_reason":p.stopped_reason,"pending":pending(&p),"sources":"existing_canonical_matrix_replies_workflow_offers_and_selected_owned_reports"}),
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
                r.attention_generation = Some(generation)
            }
        }
        save(conn, &p)?;
    }
    Ok(())
}

impl Store {
    /// Called by existing owned maintenance, never a new background loop.
    pub(crate) fn heartbeat_produce(
        &self,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<ReturnDispatch>> {
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
        if control.paused || !bound(&tx, &p)? {
            return Ok(None);
        }
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
        p.checks += 1;
        p.next_check_ms = now + i64::from(p.contract.interval_seconds) * 1000;
        // A failed source read still consumes this finite observation. It must
        // not roll back the cadence/counter and spin on the same failure.
        save(&tx, &p)?;
        tx.commit()?;
        let tx = conn.transaction()?;
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
        let mut lanes = [vec![], vec![], vec![]];
        if p.contract.matrix_replies {
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
        if p.contract.workflows {
            let (after, offers) =
                super::super::workflows::heartbeat_offers_on(&tx, human, entry, p.workflow_after)?;
            p.workflow_after = after;
            lanes[1] = offers
                .into_iter()
                .filter(|offer| p.seen.get(&offer.key) != Some(&offer.revision))
                .collect();
        }
        lanes[2] = super::reports::offers(&p.contract.reports)?
            .into_iter()
            .filter(|offer| p.seen.get(&offer.key) != Some(&offer.revision))
            .collect();
        let mut selected = vec![];
        let mut lane = usize::from(p.next_lane);
        let mut positions = [0, 0, 0];
        for _ in 0..4 {
            for _ in 0..3 {
                if positions[lane] < lanes[lane].len() {
                    break;
                }
                lane = (lane + 1) % 3;
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
            lane = (lane + 1) % 3;
        }
        p.next_lane = !p.next_lane;
        if selected.is_empty() {
            save(&tx, &p)?;
            tx.commit()?;
            return Ok(None);
        }
        let mut envelope = json!({"schema":"daimon.heartbeat-offer/v1","offers":selected,"internal_evidence":true,"publication_grant":false});
        use sha2::{Digest, Sha256};
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
        let id = format!("heartbeat:{human}:{session}:{}", Uuid::now_v7());
        let r = WorkflowReturn {
            id: id.clone(),
            workflow: String::new(),
            attention_generation: Some(control.generation),
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
