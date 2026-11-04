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
/// Must share the transaction that claims the fresh native execution. Charge
/// the complete possible execution before any provider packet; uncertainty is
/// retained as reserved, never reconstructed from prunable history or time.
pub(super) fn reserve_on(
    conn: &rusqlite::Transaction<'_>,
    session: i64,
    human: i64,
) -> Result<Value> {
    let mut account =
        load(conn, session, human)?.context("Heartbeat resources are not configured")?;
    let now = chrono::Utc::now().timestamp_millis();
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
