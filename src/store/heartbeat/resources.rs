//! Conserved parent allocation, independent of retained execution-detail pruning.
use super::*;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeartbeatResources {
    pub contract_id: String,
    pub max_provider_attempts: u32,
    pub provider_attempts_per_execution: u32,
    pub max_request_bytes: u32,
    pub execution_seconds: u32,
    pub expires_at_unix_ms: i64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Account {
    contract: HeartbeatResources,
    reserved_provider_attempts: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    finite_review_executions: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    continuous: Option<Continuous>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    production: Option<Production>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    production_review: Option<bool>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Production {
    source: String,
    selected_at_unix_ms: i64,
    max_executions_per_hour: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    provider_attempts_per_execution: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    execution_seconds: Option<u32>,
}
fn execution_limits(a: &Account, production: bool) -> (u32, u32) {
    if production && let Some(p) = &a.production {
        (
            p.provider_attempts_per_execution
                .unwrap_or(a.contract.provider_attempts_per_execution),
            p.execution_seconds.unwrap_or(a.contract.execution_seconds),
        )
    } else {
        (
            a.contract.provider_attempts_per_execution,
            a.contract.execution_seconds,
        )
    }
}
pub(super) fn production_on(conn: &Connection, session: i64, human: i64) -> Result<bool> {
    Ok(load(conn, session, human)?.is_some_and(|a| a.production.is_some()))
}
pub(super) fn production_defaults_on(
    conn: &Connection,
    session: i64,
    human: i64,
    source: &str,
) -> Result<()> {
    anyhow::ensure!(
        !source.trim().is_empty() && source.len() <= 2000,
        "Retain the actual owner production direction"
    );
    let mut a = load(conn, session, human)?.context("Heartbeat resources not configured")?;
    if let Some(p) = &a.production {
        anyhow::ensure!(
            p.source == source,
            "Production policy already selected; no reset applied"
        );
        if p.provider_attempts_per_execution.is_some() && p.execution_seconds.is_some() {
            return Ok(());
        }
    }
    let attempts = a.contract.provider_attempts_per_execution.max(64);
    let seconds = a.contract.execution_seconds.max(600);
    let rate = attempts
        .checked_mul(48)
        .filter(|v| *v <= 4096)
        .context("Production hourly execution bound exceeds supported capacity")?;
    let c = a
        .continuous
        .as_mut()
        .context("Select continuous messaging first")?;
    c.max_provider_attempts_per_hour = c.max_provider_attempts_per_hour.max(rate);
    a.production = Some(Production {
        source: source.into(),
        selected_at_unix_ms: a
            .production
            .as_ref()
            .map_or_else(|| Utc::now().timestamp_millis(), |p| p.selected_at_unix_ms),
        max_executions_per_hour: c.max_provider_attempts_per_hour / attempts,
        provider_attempts_per_execution: Some(attempts),
        execution_seconds: Some(seconds),
    });
    // Preserve the existing hour, all reservations, pilot and execution limits.
    save(conn, session, human, &a)
}
pub(super) fn select_production_review_on(
    conn: &Connection,
    session: i64,
    human: i64,
) -> Result<()> {
    let mut a = load(conn, session, human)?.context("Heartbeat resources unavailable")?;
    anyhow::ensure!(
        a.production.is_some() && a.finite_review_executions.is_none(),
        "Select production policy before new review sources; preserve prior review accounting"
    );
    a.finite_review_executions = Some(0);
    a.production_review = Some(true);
    save(conn, session, human, &a)
}
/// Recurring allowance is separate from the immutable pilot allocation. Neither
/// restart nor adoption can refund historical reservations or restart the hour.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Continuous {
    max_provider_attempts_per_hour: u32,
    pilot_reserved_at_adoption: u32,
    window_started_at_unix_ms: i64,
    reserved_in_window: u32,
    reserved_provider_attempts: u64,
}
impl Continuous {
    fn usage(&self, now: i64) -> u32 {
        if now >= self.window_started_at_unix_ms.saturating_add(3_600_000) {
            0
        } else {
            self.reserved_in_window
        }
    }
}
pub(super) fn continuous_on(conn: &Connection, session: i64, human: i64) -> Result<bool> {
    // An unreadable execution ledger grants no continuous lifetime. Keep the
    // independent finite observation policy usable; resource status/reservation
    // still reports/refuses the actual ledger failure before any inference.
    Ok(load(conn, session, human)
        .ok()
        .flatten()
        .is_some_and(|a| a.continuous.is_some()))
}
pub(super) fn enable_continuous_on(
    conn: &Connection,
    session: i64,
    human: i64,
    max_provider_attempts_per_hour: u32,
) -> Result<()> {
    let mut a = load(conn, session, human)?.context("Heartbeat resources not configured")?;
    anyhow::ensure!(
        (a.contract.provider_attempts_per_execution..=4096)
            .contains(&max_provider_attempts_per_hour),
        "Select a recurring hourly bound within4096 attempts, covering one execution"
    );
    if let Some(c) = &a.continuous {
        anyhow::ensure!(
            c.max_provider_attempts_per_hour == max_provider_attempts_per_hour,
            "Continuous allowance already selected; no rate change or refill applied"
        );
        return Ok(());
    }
    a.continuous = Some(Continuous {
        max_provider_attempts_per_hour,
        pilot_reserved_at_adoption: a.reserved_provider_attempts,
        window_started_at_unix_ms: chrono::Utc::now().timestamp_millis(),
        reserved_in_window: 0,
        reserved_provider_attempts: 0,
    });
    save(conn, session, human, &a)
}
fn key(session: i64, human: i64) -> String {
    format!("heartbeat_resources:{human}:{session}")
}
fn load(conn: &Connection, session: i64, human: i64) -> Result<Option<Account>> {
    conn.query_row(
        "SELECT value FROM bot_state WHERE key=?1",
        [key(session, human)],
        |r| r.get::<_, String>(0),
    )
    .optional()?
    .map(|raw| serde_json::from_str(&raw).map_err(Into::into))
    .transpose()
}
fn save(conn: &Connection, session: i64, human: i64, account: &Account) -> Result<()> {
    conn.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params![key(session,human),serde_json::to_string(account)?])?;
    Ok(())
}
/// Explicit owner renewal changes only the deadline of the existing account.
/// Call inside the same transaction as producer renewal; old native allowances
/// retain their original absolute deadlines and all reservations stay charged.
pub(super) fn renew_window_on(
    conn: &Connection,
    session: i64,
    human: i64,
    expected_expiry: i64,
    expiry: i64,
) -> Result<()> {
    let mut account = load(conn, session, human)?.context("Heartbeat resources not configured")?;
    anyhow::ensure!(
        account.contract.expires_at_unix_ms == expected_expiry,
        "Resource window changed; inspect status before renewal"
    );
    anyhow::ensure!(
        account
            .contract
            .max_provider_attempts
            .checked_sub(account.reserved_provider_attempts)
            .is_some_and(|remaining| remaining >= account.contract.provider_attempts_per_execution),
        "Heartbeat allocation exhausted; renewal cannot refill it"
    );
    account.contract.expires_at_unix_ms = expiry;
    validate(&account.contract, chrono::Utc::now().timestamp_millis())?;
    save(conn, session, human, &account)
}
fn validate(contract: &HeartbeatResources, now: i64) -> Result<()> {
    uuid::Uuid::parse_str(&contract.contract_id).context("Heartbeat contract requires a UUID")?;
    anyhow::ensure!(
        contract.max_provider_attempts > 0
            && contract.provider_attempts_per_execution > 0
            && contract.provider_attempts_per_execution <= contract.max_provider_attempts,
        "Heartbeat provider allocation must be positive and conserved"
    );
    anyhow::ensure!(
        contract.max_request_bytes > 0 && contract.max_request_bytes <= 64 * 1024 * 1024,
        "Heartbeat complete-request bound must be within64MiB"
    );
    anyhow::ensure!(
        contract.execution_seconds > 0 && contract.execution_seconds <= 600,
        "Heartbeat execution must have a finite deadline within600seconds"
    );
    anyhow::ensure!(
        contract.expires_at_unix_ms > now,
        "Heartbeat resource contract expired"
    );
    Ok(())
}
/// Initial configuration only. Resume, restart, a fresh source or a new UUID can
/// never replenish an existing account. A replacement requires its own explicit
/// owning contract, not an attention worker manufacturing another allocation.
pub(super) fn configure_on(
    conn: &Connection,
    session: i64,
    human: i64,
    contract: HeartbeatResources,
) -> Result<()> {
    validate(&contract, chrono::Utc::now().timestamp_millis())?;
    anyhow::ensure!(
        load(conn, session, human)?.is_none(),
        "Heartbeat resources already configured; no refill was applied"
    );
    save(
        conn,
        session,
        human,
        &Account {
            contract,
            reserved_provider_attempts: 0,
            finite_review_executions: None,
            continuous: None,
            production: None,
            production_review: None,
        },
    )
}
pub(super) fn status_on(conn: &Connection, session: i64, human: i64) -> Result<Value> {
    let Some(account) = load(conn, session, human)? else {
        return Ok(json!({"state":"not_configured"}));
    };
    let remaining = account
        .contract
        .max_provider_attempts
        .checked_sub(account.reserved_provider_attempts)
        .context("Heartbeat resource account is inconsistent")?;
    if let Some(c) = &account.continuous {
        let (attempts, seconds) = execution_limits(&account, true);
        let now = chrono::Utc::now().timestamp_millis();
        let remaining = c
            .max_provider_attempts_per_hour
            .saturating_sub(c.usage(now));
        return Ok(json!({"mode":"continuous",
            "state":if remaining >= attempts {"available"} else {"rate_limited"},
            "contract":account.contract,"reserved_provider_attempts":account.reserved_provider_attempts,
            "remaining_provider_attempts":remaining,"continuous":c,
            "pilot_remaining_provider_attempts":account.contract.max_provider_attempts-account.reserved_provider_attempts,
            "production":account.production,
            "remaining_execution_envelopes":remaining/attempts,
            "effective_execution":{"provider_attempts_per_execution":attempts,"execution_seconds":seconds,"max_request_bytes":account.contract.max_request_bytes},
            "lifetime_reserved_provider_attempts":u64::from(c.pilot_reserved_at_adoption)+c.reserved_provider_attempts,
            "measurement":"reserved_request_attempts_not_tokens_or_money"}));
    }
    let state = if account.contract.expires_at_unix_ms <= chrono::Utc::now().timestamp_millis() {
        "expired"
    } else if remaining < account.contract.provider_attempts_per_execution {
        "exhausted"
    } else {
        "available"
    };
    Ok(
        json!({"state":state,"contract":account.contract,"reserved_provider_attempts":account.reserved_provider_attempts,
        "remaining_provider_attempts":remaining,"measurement":"reserved_request_attempts_not_tokens_or_money"}),
    )
}
/// Presence is also a compatibility fence: strict older account readers refuse
/// this selected finite policy instead of spending standing credit for reports.
pub(super) fn select_finite_on(conn: &Connection, session: i64, human: i64) -> Result<()> {
    let mut account = load(conn, session, human)?.context("Heartbeat resources unavailable")?;
    anyhow::ensure!(
        account.finite_review_executions.is_none(),
        "Finite review was already selected; never reset it"
    );
    account.finite_review_executions = Some(0);
    save(conn, session, human, &account)
}
pub(super) fn finite_available_on(conn: &Connection, session: i64, human: i64) -> Result<bool> {
    let Some(a) = load(conn, session, human)? else {
        return Ok(false);
    };
    if a.production_review == Some(true) {
        return Ok(a.production.is_some()
            && a.continuous.as_ref().is_some_and(|c| {
                c.max_provider_attempts_per_hour
                    .saturating_sub(c.usage(Utc::now().timestamp_millis()))
                    >= execution_limits(&a, true).0
            }));
    }
    Ok(a.finite_review_executions.unwrap_or(0) < 4
        && a.contract
            .max_provider_attempts
            .saturating_sub(a.reserved_provider_attempts)
            >= a.contract.provider_attempts_per_execution)
}
pub(super) fn reserve_finite_on(
    conn: &rusqlite::Transaction<'_>,
    session: i64,
    human: i64,
) -> Result<Value> {
    anyhow::ensure!(
        finite_available_on(conn, session, human)?,
        "Finite review requires original pilot capacity; standing allowance cannot refill it"
    );
    anyhow::ensure!(
        load(conn, session, human)?
            .unwrap()
            .finite_review_executions
            .is_some(),
        "Select finite review before reservation"
    );
    let production = load(conn, session, human)?.is_some_and(|a| a.production_review == Some(true));
    let allowance = reserve_with_policy_on(conn, session, human, production)?;
    let mut account = load(conn, session, human)?.unwrap();
    let count = account
        .finite_review_executions
        .context("Select the finite review resource fence first")?;
    account.finite_review_executions = Some(count.saturating_add(1));
    save(conn, session, human, &account)?;
    Ok(allowance)
}
/// Must share the transaction that claims the fresh native execution. Charge
/// the complete possible execution before any provider packet; uncertainty is
/// retained as reserved, never reconstructed from prunable history or time.
pub(super) fn reserve_on(
    conn: &rusqlite::Transaction<'_>,
    session: i64,
    human: i64,
) -> Result<Value> {
    reserve_with_policy_on(conn, session, human, true)
}
fn reserve_with_policy_on(
    conn: &rusqlite::Transaction<'_>,
    session: i64,
    human: i64,
    production: bool,
) -> Result<Value> {
    let mut account =
        load(conn, session, human)?.context("Heartbeat resources are not configured")?;
    let (attempts, seconds) = execution_limits(&account, production);
    let now = chrono::Utc::now().timestamp_millis();
    if let Some(c) = &mut account.continuous {
        let usage = c.usage(now);
        let next = usage
            .checked_add(attempts)
            .context("Heartbeat hourly allocation overflow")?;
        anyhow::ensure!(
            next <= c.max_provider_attempts_per_hour,
            "Heartbeat hourly allocation exhausted"
        );
        if now >= c.window_started_at_unix_ms.saturating_add(3_600_000) {
            c.window_started_at_unix_ms = now;
        }
        c.reserved_in_window = next;
        c.reserved_provider_attempts = c
            .reserved_provider_attempts
            .checked_add(u64::from(attempts))
            .context("Heartbeat lifetime allocation overflow")?;
        // Consume the existing finite allocation first. Its remaining capacity
        // can still constrain a separately authorized finite review purpose;
        // continuous messaging never makes that pilot balance reappear.
        account.reserved_provider_attempts += account
            .contract
            .max_provider_attempts
            .saturating_sub(account.reserved_provider_attempts)
            .min(attempts);
        let reservation = json!({"contract_id":account.contract.contract_id,
            "max_provider_attempts":attempts,
            "max_request_bytes":account.contract.max_request_bytes,
            "deadline_unix_ms":now.checked_add(i64::from(seconds)*1000)
                .context("Heartbeat execution deadline overflow")?});
        save(conn, session, human, &account)?;
        return Ok(reservation);
    }
    validate(&account.contract, now)?;
    let reserved = account
        .reserved_provider_attempts
        .checked_add(account.contract.provider_attempts_per_execution)
        .context("Heartbeat provider allocation overflow")?;
    anyhow::ensure!(
        reserved <= account.contract.max_provider_attempts,
        "Heartbeat provider allocation exhausted"
    );
    account.reserved_provider_attempts = reserved;
    let deadline = now
        .checked_add(i64::from(account.contract.execution_seconds) * 1000)
        .context("Heartbeat deadline overflow")?
        .min(account.contract.expires_at_unix_ms);
    let reservation = json!({"contract_id":account.contract.contract_id,"max_provider_attempts":account.contract.provider_attempts_per_execution,
        "max_request_bytes":account.contract.max_request_bytes,"deadline_unix_ms":deadline});
    save(conn, session, human, &account)?;
    Ok(reservation)
}

#[cfg(test)]
pub(in crate::store) fn test_contract() -> HeartbeatResources {
    HeartbeatResources {
        contract_id: uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, b"heartbeat-resource-test")
            .to_string(),
        max_provider_attempts: 4096,
        provider_attempts_per_execution: 3,
        max_request_bytes: 1024 * 1024,
        execution_seconds: 90,
        expires_at_unix_ms: chrono::Utc::now().timestamp_millis() + 3_600_000,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn production_defaults_preserve_history_and_fund_selected_review_after_pilot() {
        let (_file, store, entry) = setup();
        let mut c = test_contract();
        c.max_provider_attempts = 48;
        c.provider_attempts_per_execution = 12;
        let mut conn = store.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        configure_on(&tx, entry.id, 100, c).unwrap();
        enable_continuous_on(&tx, entry.id, 100, 48).unwrap();
        for _ in 0..4 {
            reserve_on(&tx, entry.id, 100).unwrap();
        }
        let before = load(&tx, entry.id, 100).unwrap().unwrap();
        assert_eq!(
            status_on(&tx, entry.id, 100).unwrap()["state"],
            "rate_limited"
        );
        production_defaults_on(&tx, entry.id, 100, "actual owner production direction").unwrap();
        let after = load(&tx, entry.id, 100).unwrap().unwrap();
        assert_eq!(
            after.reserved_provider_attempts,
            before.reserved_provider_attempts
        );
        assert_eq!(after.contract.provider_attempts_per_execution, 12);
        assert_eq!(
            after.contract.execution_seconds,
            before.contract.execution_seconds
        );
        assert_eq!(execution_limits(&after, true), (64, 600));
        let old = before.continuous.unwrap();
        let new = after.continuous.unwrap();
        assert_eq!(new.window_started_at_unix_ms, old.window_started_at_unix_ms);
        assert_eq!(new.reserved_in_window, old.reserved_in_window);
        assert_eq!(
            new.reserved_provider_attempts,
            old.reserved_provider_attempts
        );
        assert_eq!(new.max_provider_attempts_per_hour, 3072);
        assert_eq!(
            status_on(&tx, entry.id, 100).unwrap()["remaining_execution_envelopes"],
            47
        );
        let selected = serde_json::to_value(load(&tx, entry.id, 100).unwrap().unwrap()).unwrap();
        production_defaults_on(&tx, entry.id, 100, "actual owner production direction").unwrap();
        assert_eq!(
            serde_json::to_value(load(&tx, entry.id, 100).unwrap().unwrap()).unwrap(),
            selected
        );
        assert!(production_defaults_on(&tx, entry.id, 100, "changed source").is_err());
        select_production_review_on(&tx, entry.id, 100).unwrap();
        for _ in 0..5 {
            reserve_finite_on(&tx, entry.id, 100).unwrap();
        }
        assert_eq!(
            load(&tx, entry.id, 100)
                .unwrap()
                .unwrap()
                .reserved_provider_attempts,
            48
        );
        assert_eq!(
            load(&tx, entry.id, 100)
                .unwrap()
                .unwrap()
                .finite_review_executions,
            Some(5)
        );
        for _ in 0..42 {
            reserve_on(&tx, entry.id, 100).unwrap();
        }
        assert!(reserve_on(&tx, entry.id, 100).is_err());
        assert!(reserve_finite_on(&tx, entry.id, 100).is_err());
        assert_eq!(
            status_on(&tx, entry.id, 100).unwrap()["remaining_execution_envelopes"],
            0
        );
        tx.commit().unwrap();
    }
    #[test]
    fn finite_review_shares_pilot_and_cannot_borrow_a_new_continuous_hour() {
        let (_file, store, entry) = setup();
        let mut contract = test_contract();
        contract.max_provider_attempts = 48;
        contract.provider_attempts_per_execution = 12;
        let mut conn = store.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        configure_on(&tx, entry.id, 100, contract).unwrap();
        enable_continuous_on(&tx, entry.id, 100, 48).unwrap();
        select_finite_on(&tx, entry.id, 100).unwrap();
        reserve_on(&tx, entry.id, 100).unwrap(); // Messaging consumes the same original balance.
        for _ in 0..3 {
            reserve_finite_on(&tx, entry.id, 100).unwrap();
        }
        assert!(!finite_available_on(&tx, entry.id, 100).unwrap());
        let before = serde_json::to_value(load(&tx, entry.id, 100).unwrap().unwrap()).unwrap();
        assert!(reserve_finite_on(&tx, entry.id, 100).is_err());
        assert_eq!(
            serde_json::to_value(load(&tx, entry.id, 100).unwrap().unwrap()).unwrap(),
            before
        );
        let mut a = load(&tx, entry.id, 100).unwrap().unwrap();
        a.continuous.as_mut().unwrap().window_started_at_unix_ms -= 3_600_001;
        save(&tx, entry.id, 100, &a).unwrap();
        assert!(reserve_finite_on(&tx, entry.id, 100).is_err());
        reserve_on(&tx, entry.id, 100).unwrap(); // Standing messaging may use its new hour.
        let a = load(&tx, entry.id, 100).unwrap().unwrap();
        assert_eq!(a.reserved_provider_attempts, 48);
        assert_eq!(a.finite_review_executions, Some(3));
        tx.commit().unwrap();
    }
    #[test]
    fn finite_review_has_four_execution_ceiling_even_with_larger_pilot() {
        let (_file, store, entry) = setup();
        let mut conn = store.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        configure_on(&tx, entry.id, 100, test_contract()).unwrap();
        select_finite_on(&tx, entry.id, 100).unwrap();
        for _ in 0..4 {
            reserve_finite_on(&tx, entry.id, 100).unwrap();
        }
        assert!(reserve_finite_on(&tx, entry.id, 100).is_err());
        reserve_on(&tx, entry.id, 100).unwrap();
        assert_eq!(
            load(&tx, entry.id, 100)
                .unwrap()
                .unwrap()
                .finite_review_executions,
            Some(4)
        );
        tx.commit().unwrap();
    }
    #[test]
    fn continuous_rate_survives_expiry_restart_and_adoption_without_resetting_history() {
        let (file, store, entry) = setup();
        let mut contract = test_contract();
        contract.max_provider_attempts = 6;
        store
            .heartbeat_control(
                100,
                entry.key,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract,
                },
            )
            .unwrap();
        {
            let mut conn = store.conn.lock().unwrap();
            let tx = conn.transaction().unwrap();
            reserve_on(&tx, entry.id, 100).unwrap();
            let mut a = load(&tx, entry.id, 100).unwrap().unwrap();
            a.contract.expires_at_unix_ms = chrono::Utc::now().timestamp_millis() - 1;
            save(&tx, entry.id, 100, &a).unwrap();
            enable_continuous_on(&tx, entry.id, 100, 6).unwrap();
            for _ in 0..2 {
                let allowance = reserve_on(&tx, entry.id, 100).unwrap();
                assert!(
                    allowance["deadline_unix_ms"].as_i64().unwrap() > a.contract.expires_at_unix_ms
                );
                assert_eq!(allowance["max_provider_attempts"], 3);
            }
            assert!(reserve_on(&tx, entry.id, 100).is_err());
            let before = status_on(&tx, entry.id, 100).unwrap();
            enable_continuous_on(&tx, entry.id, 100, 6).unwrap();
            assert_eq!(status_on(&tx, entry.id, 100).unwrap(), before);
            assert!(enable_continuous_on(&tx, entry.id, 100, 12).is_err());
            assert_eq!(before["state"], "rate_limited");
            assert_eq!(before["reserved_provider_attempts"], 6);
            assert_eq!(before["pilot_remaining_provider_attempts"], 0);
            assert_eq!(before["lifetime_reserved_provider_attempts"], 9);
            tx.commit().unwrap();
        }
        drop(store);
        let reopened = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let mut conn = reopened.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        assert_eq!(
            status_on(&tx, entry.id, 100).unwrap()["state"],
            "rate_limited"
        );
        let mut a = load(&tx, entry.id, 100).unwrap().unwrap();
        let c = a.continuous.as_mut().unwrap();
        assert_eq!(c.usage(c.window_started_at_unix_ms - 1000), 6);
        c.window_started_at_unix_ms -= 3_600_000;
        save(&tx, entry.id, 100, &a).unwrap();
        reserve_on(&tx, entry.id, 100).unwrap();
        let after = status_on(&tx, entry.id, 100).unwrap();
        assert_eq!(after["remaining_provider_attempts"], 3);
        assert_eq!(after["reserved_provider_attempts"], 6);
        assert_eq!(after["continuous"]["reserved_provider_attempts"], 9);
        assert_eq!(after["lifetime_reserved_provider_attempts"], 12);
        assert!(
            after["contract"]["expires_at_unix_ms"].as_i64().unwrap()
                < chrono::Utc::now().timestamp_millis()
        );
        tx.commit().unwrap();
    }
    fn setup() -> (tempfile::NamedTempFile, Store, SessionRecord) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &crate::store::tests::defaults())
            .unwrap();
        store
            .heartbeat_control(100, entry, HeartbeatCommand::Pause)
            .unwrap();
        let session = store.get_session(entry).unwrap().unwrap();
        (file, store, session)
    }
    #[test]
    fn account_survives_pause_resume_restart_and_detail_retirement_without_refill() {
        let (file, store, entry) = setup();
        let mut contract = test_contract();
        contract.max_provider_attempts = 6;
        store
            .heartbeat_control(
                100,
                entry.key,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract,
                },
            )
            .unwrap();
        for _ in 0..2 {
            let mut conn = store.conn.lock().unwrap();
            let tx = conn.transaction().unwrap();
            let allowance = reserve_on(&tx, entry.id, 100).unwrap();
            assert_eq!(allowance["max_provider_attempts"], 3);
            tx.commit().unwrap();
        }
        store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 1 })
            .unwrap();
        store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        let before = store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(before["resources"]["state"], "exhausted");
        assert_eq!(before["resources"]["reserved_provider_attempts"], 6);
        // Detail history is not the resource ledger. Real pruning targets this
        // separate key family; losing it cannot recreate any allocation.
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "DELETE FROM bot_state WHERE key LIKE 'heartbeat_execution:%'",
                [],
            )
            .unwrap();
        drop(store);
        let store = Store::open(file.path(), &[100], &crate::store::tests::defaults()).unwrap();
        let after = store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(before["resources"], after["resources"]);
        let mut replacement = test_contract();
        replacement.contract_id =
            uuid::Uuid::new_v5(&uuid::Uuid::NAMESPACE_URL, b"replacement-does-not-refill")
                .to_string();
        assert!(
            store
                .heartbeat_control(
                    100,
                    entry.key,
                    HeartbeatCommand::ConfigureResources {
                        generation: 3,
                        contract: replacement
                    }
                )
                .is_err()
        );
        let mut conn = store.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        assert!(reserve_on(&tx, entry.id, 100).is_err());
    }
    #[test]
    fn failed_execution_transaction_does_not_spend_and_expiry_caps_deadline() {
        let (_file, store, entry) = setup();
        let mut contract = test_contract();
        contract.expires_at_unix_ms = chrono::Utc::now().timestamp_millis() + 30_000;
        let expiry = contract.expires_at_unix_ms;
        store
            .heartbeat_control(
                100,
                entry.key,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract,
                },
            )
            .unwrap();
        {
            let mut conn = store.conn.lock().unwrap();
            let tx = conn.transaction().unwrap();
            assert_eq!(
                reserve_on(&tx, entry.id, 100).unwrap()["deadline_unix_ms"],
                expiry
            );
            // Simulate a later ownership/link failure in the SAME transaction.
        }
        let status = store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Status)
            .unwrap();
        assert_eq!(status["resources"]["reserved_provider_attempts"], 0);
        let mut conn = store.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        let mut account = load(&tx, entry.id, 100).unwrap().unwrap();
        account.contract.expires_at_unix_ms = chrono::Utc::now().timestamp_millis() - 1;
        save(&tx, entry.id, 100, &account).unwrap();
        tx.commit().unwrap();
        let tx = conn.transaction().unwrap();
        assert!(reserve_on(&tx, entry.id, 100).is_err());
    }
    #[test]
    fn resource_configuration_is_scoped_and_never_unpauses_attention() {
        let (_file, store, entry) = setup();
        assert!(
            store
                .heartbeat_control(
                    101,
                    entry.key,
                    HeartbeatCommand::ConfigureResources {
                        generation: 1,
                        contract: test_contract()
                    }
                )
                .is_err()
        );
        assert!(
            store
                .heartbeat_control(
                    100,
                    entry.key,
                    HeartbeatCommand::ConfigureResources {
                        generation: 0,
                        contract: test_contract()
                    }
                )
                .is_err()
        );
        let result = store
            .heartbeat_control(
                100,
                entry.key,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract: test_contract(),
                },
            )
            .unwrap();
        assert_eq!(result["admission_paused"], true);
        assert_eq!(result["generation"], 1);
        assert_eq!(result["resources"]["state"], "available");
        let mut bad = test_contract();
        bad.max_provider_attempts = 0;
        assert!(validate(&bad, chrono::Utc::now().timestamp_millis()).is_err());
    }
    #[test]
    fn damaged_resource_metadata_cannot_prevent_a_durable_pause() {
        let (_file, store, entry) = setup();
        store
            .heartbeat_control(
                100,
                entry.key,
                HeartbeatCommand::ConfigureResources {
                    generation: 1,
                    contract: test_contract(),
                },
            )
            .unwrap();
        store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Resume { generation: 1 })
            .unwrap();
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE bot_state SET value='damaged' WHERE key=?1",
                [key(entry.id, 100)],
            )
            .unwrap();
        let paused = store
            .heartbeat_control(100, entry.key, HeartbeatCommand::Pause)
            .unwrap();
        assert_eq!(paused["admission_paused"], true);
        assert_eq!(paused["generation"], 3);
        assert_eq!(paused["resources"]["state"], "unavailable");
        let conn = store.conn.lock().unwrap();
        assert!(!generation_current_on(&conn, 100, entry.key, 2).unwrap());
    }
}
