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
pub(super) struct Review {
    pub contract: HeartbeatReviewContract,
    pub purpose_revision: String,
    pub checks: u32,
    pub next_check_ms: i64,
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
                && p.review.is_none()
                && p.contract.reports.is_empty()
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
        if contract.production {
            resources::select_production_review_on(&tx, session, human)?;
        } else {
            resources::select_finite_on(&tx, session, human)?;
        }
        p.contract.reports = contract.reports.clone();
        p.review = Some(Review {
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
