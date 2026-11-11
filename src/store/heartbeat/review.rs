//! One finite report-source successor inside the existing heartbeat parent.
use super::*;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatReviewContract {
    pub purpose: HeartbeatPurpose,
    pub reports: Vec<HeartbeatReportSource>,
    pub interval_seconds: u32,
    pub max_checks: Option<u32>,
    pub expires_at_unix_ms: Option<i64>,
    #[serde(default)]
    pub production: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(in crate::store) struct Review {
    pub contract: HeartbeatReviewContract,
    pub purpose_revision: String,
    pub checks: u32,
    pub next_check_ms: i64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tasks: Vec<HeartbeatReviewTask>,
}

pub(super) fn purpose_on(
    conn: &Connection,
    p: &producer::Parent,
) -> Result<Option<(crate::interaction::SourceInput, String)>> {
    let Some(review) = &p.review else {
        return Ok(None);
    };
    let (source, revision) =
        producer::purpose_source(conn, p.human, p.entry, &p.native, &review.contract.purpose)?;
    anyhow::ensure!(
        revision == review.purpose_revision,
        "Finite review purpose changed or retired"
    );
    Ok(Some((source, revision)))
}
pub(super) fn live(conn: &Connection, p: &producer::Parent) -> Result<bool> {
    let Some(review) = &p.review else {
        return Ok(false);
    };
    Ok((review.contract.production
        || review
            .contract
            .expires_at_unix_ms
            .is_some_and(|t| Utc::now().timestamp_millis() < t))
        && purpose_on(conn, p).is_ok())
}
pub(super) fn status_on(conn: &Connection, p: &producer::Parent) -> Result<Value> {
    let Some(r) = &p.review else {
        return Ok(json!({"state":"not_configured"}));
    };
    let state = if r
        .contract
        .expires_at_unix_ms
        .is_some_and(|t| Utc::now().timestamp_millis() >= t)
    {
        "expired"
    } else if purpose_on(conn, p).is_err() {
        "purpose_retired"
    } else if !resources::finite_available_on(conn, p.session, p.human)? {
        "exhausted"
    } else if r.contract.max_checks.is_some_and(|max| r.checks >= max) {
        "check_capacity"
    } else {
        "configured"
    };
    Ok(
        json!({"state":state,"contract":r.contract,"checks":r.checks,
        "next_check_ms":r.next_check_ms,"maximum_executions":if r.contract.production {Value::Null} else {json!(4)},
        "mode":if r.contract.production {"production"} else {"finite"},
        "periodic_tasks":r.tasks.iter().map(|t|json!({"id":t.id,"purpose":t.purpose,"state":if producer::purpose_source(conn,p.human,p.entry,&p.native,&t.purpose).is_ok_and(|(_,rev)|rev==t.purpose_revision){"selected"}else{"purpose_retired"}})).collect::<Vec<_>>(),
        "funding":if r.contract.production {"shared_production_hourly_allowance"} else {"original_shared_pilot_only_no_standing_refill"},
        "meaning":"Selected purpose/source observation; native useful review and delivery remain separate"}),
    )
}
pub(super) fn due(conn: &Connection, p: &producer::Parent) -> Result<bool> {
    Ok(live(conn, p)?
        && resources::finite_available_on(conn, p.session, p.human)?
        && p.review.as_ref().is_some_and(|r| {
            r.contract.max_checks.is_none_or(|max| r.checks < max)
                && Utc::now().timestamp_millis() >= r.next_check_ms
        }))
}
pub(super) fn reserve_on(conn: &rusqlite::Transaction<'_>, p: &producer::Parent) -> Result<Value> {
    anyhow::ensure!(
        live(conn, p)?,
        "Finite review expired, retired or exhausted; no standing refill"
    );
    let mut allowance = resources::reserve_finite_on(conn, p.session, p.human)?;
    if let Some(expiry) = p.review.as_ref().unwrap().contract.expires_at_unix_ms {
        allowance["deadline_unix_ms"] =
            json!(allowance["deadline_unix_ms"].as_i64().unwrap().min(expiry));
    }
    Ok(allowance)
}

impl Store {
    /// Owner-only source selection; never renews resources or resumes a lane.
    pub fn heartbeat_select_review(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        contract: HeartbeatReviewContract,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let mut p =
            producer::load(&tx, human, session)?.context("Select the existing heartbeat parent")?;
        let raw: String = tx.query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )?;
        let c: Control = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            c.paused && c.generation == generation,
            "Pause and inspect the exact heartbeat generation before selecting review sources"
        );
        anyhow::ensure!(
            c.lanes
                .get(&HeartbeatLane::Reports)
                .is_none_or(|lane| lane.paused)
                && !executions::unresolved_on(&tx, human, entry)?,
            "Review lane must be paused with no unresolved execution"
        );
        anyhow::ensure!(
            producer::bound(&tx, &p)?
                && p.native_returns
                    .iter()
                    .all(|r| r.reported_revision.is_some()
                        || matches!(
                            r.phase.as_str(),
                            "retired_unsent"
                                | "attention_failed"
                                | "attention_interrupted"
                                | "accepted_terminal_unreviewed"
                        )),
            "Preserve existing sources, pending originals and prior review selection"
        );
        let now = Utc::now().timestamp_millis();
        anyhow::ensure!(
            (900..=3600).contains(&contract.interval_seconds)
                && if contract.production {
                    contract.max_checks.is_none()
                        && contract.expires_at_unix_ms.is_none()
                        && resources::production_on(&tx, session, human)?
                } else {
                    contract.max_checks.is_some_and(|v| (1..=96).contains(&v))
                        && contract
                            .expires_at_unix_ms
                            .is_some_and(|t| t > now && t <= now + 86_400_000)
                }
                && !contract.reports.is_empty(),
            "Select15minute sources with either explicit production policy or finite24hour bounds"
        );
        reports::validate(&contract.reports)?;
        if !contract.production {
            anyhow::ensure!(
                resources::finite_available_on(&tx, session, human)?,
                "Original shared pilot allocation exhausted; finite review cannot borrow standing funding"
            );
        }
        let (_, revision) =
            producer::purpose_source(&tx, human, entry, &p.native, &contract.purpose)?;
        if let Some(review) = &mut p.review {
            anyhow::ensure!(
                review.contract.production
                    && contract.production
                    && review.purpose_revision == revision
                    && serde_json::to_value(&review.contract.purpose)?
                        == serde_json::to_value(&contract.purpose)?
                    && review.contract.interval_seconds == contract.interval_seconds
                    && review.contract.max_checks == contract.max_checks
                    && review.contract.expires_at_unix_ms == contract.expires_at_unix_ms,
                "Update production sources only; preserve the selected purpose, cadence and funding"
            );
            // Pending originals were checked above. Keep review clocks, accounting,
            // cursors and retained returns; changed fields get a new source revision.
            p.contract.reports = contract.reports.clone();
            review.contract.reports = contract.reports;
            producer::save(&tx, &p)?;
            tx.commit()?;
            return Ok(());
        }
        anyhow::ensure!(
            p.contract.reports.is_empty(),
            "Preserve existing producer report sources"
        );
        if contract.production {
            resources::select_production_review_on(&tx, session, human)?;
        } else {
            resources::select_finite_on(&tx, session, human)?;
        }
        p.contract.reports = contract.reports.clone();
        p.review = Some(Review {
            tasks: vec![],
            contract,
            purpose_revision: revision,
            checks: 0,
            next_check_ms: 0,
        });
        producer::save(&tx, &p)?;
        tx.commit()?;
        Ok(())
    }
}

/// Recurring bounded work shares the existing Reports cadence and funding.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatReviewTask {
    pub id: String,
    pub purpose: HeartbeatPurpose,
    pub purpose_revision: String,
    pub instructions: String,
}

pub(in crate::store) fn task_current(
    conn: &Connection,
    p: &producer::Parent,
    offer: &producer::Offer,
) -> Result<bool> {
    let Some(task) = p.review.as_ref().and_then(|r| {
        r.tasks
            .iter()
            .find(|t| offer.key == format!("review-task:{}", t.id))
    }) else {
        return Ok(false);
    };
    let (_, revision) = producer::purpose_source(conn, p.human, p.entry, &p.native, &task.purpose)?;
    Ok(revision == task.purpose_revision && offer.evidence["task"] == serde_json::to_value(task)?)
}

pub(in crate::store) fn task_offers(
    conn: &Connection,
    p: &producer::Parent,
) -> Result<Vec<producer::Offer>> {
    use sha2::{Digest, Sha256};
    let Some(review) = &p.review else {
        return Ok(vec![]);
    };
    let mut offers = Vec::new();
    for task in &review.tasks {
        let Ok((_, revision)) =
            producer::purpose_source(conn, p.human, p.entry, &p.native, &task.purpose)
        else {
            continue;
        };
        if revision != task.purpose_revision {
            continue;
        }
        let revision = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&(task, review.checks))?)
        );
        offers.push(producer::Offer {key:format!("review-task:{}",task.id),revision:revision.clone(),evidence:json!({
            "kind":"periodic_review_task","task":task,"revision":revision,
            "reader":{"operation":"heartbeat_source","arguments":{"source":format!("periodic:{}",task.id),"revision":revision}},
            "meaning":"Read this task's own retained human purpose before acting; the batch's other purpose does not replace it. Shared Reports cadence/funding; no publication permission."})});
    }
    Ok(offers)
}

impl Store {
    /// Select one additional purpose without replacing existing sources or clocks.
    pub fn heartbeat_select_review_task(
        &self,
        human: i64,
        entry: SessionKey,
        generation: u64,
        mut task: HeartbeatReviewTask,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let mut p =
            producer::load(&tx, human, session)?.context("Existing Reports parent required")?;
        let raw: String = tx.query_row(
            "SELECT value FROM bot_state WHERE key=?1",
            [format!("heartbeat_control:{human}:{session}")],
            |r| r.get(0),
        )?;
        let control: Control = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            control.paused
                && control.generation == generation
                && control
                    .lanes
                    .get(&HeartbeatLane::Reports)
                    .is_none_or(|l| l.paused),
            "Pause exact Reports/global controls before task selection"
        );
        anyhow::ensure!(
            producer::bound(&tx, &p)?
                && !executions::unresolved_on(&tx, human, entry)?
                && p.native_returns
                    .iter()
                    .all(|r| r.reported_revision.is_some()
                        || matches!(
                            r.phase.as_str(),
                            "retired_unsent"
                                | "attention_failed"
                                | "attention_interrupted"
                                | "accepted_terminal_unreviewed"
                        )),
            "Preserve pending originals and execution"
        );
        anyhow::ensure!(
            !task.id.is_empty()
                && task.id.len() <= 64
                && task
                    .id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
                && !task.instructions.trim().is_empty()
                && task.instructions.len() <= 8000,
            "Bounded task identity/instructions required"
        );
        let (_, revision) = producer::purpose_source(&tx, human, entry, &p.native, &task.purpose)?;
        task.purpose_revision = revision;
        let review = p
            .review
            .as_mut()
            .context("Existing production review required")?;
        anyhow::ensure!(
            review.contract.production,
            "Finite review cannot borrow production task funding"
        );
        if let Some(existing) = review.tasks.iter().find(|t| t.id == task.id) {
            anyhow::ensure!(
                serde_json::to_value(existing)? == serde_json::to_value(&task)?,
                "Existing task differs; preserve its purpose and pending work"
            );
            return Ok(());
        }
        anyhow::ensure!(
            review.tasks.len() < 4,
            "At most four periodic purposes per parent"
        );
        review.tasks.push(task);
        producer::save(&tx, &p)?;
        tx.commit()?;
        Ok(())
    }
}
