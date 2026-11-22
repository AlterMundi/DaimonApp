//! Finite owner-local adapter to the existing session preference fields.
//! Never bootstraps a listener, takes its instance lock, or starts native work.
use super::*;
use anyhow::{bail, ensure};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    chat_id: i64,
    thread_id: i64,
    native_thread: String,
    expected: Option<Value>,
    model: Option<String>,
    reasoning_effort: Option<String>,
}

pub(crate) fn owner_local(path: &Path, human: i64, action: &str, raw: &str) -> Result<Value> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    ensure!(raw.len() <= 4096, "Preference request exceeds bound");
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    ensure!(
        meta.is_file() && meta.uid() == unsafe { libc::geteuid() } && meta.mode() & 0o077 == 0,
        "Owner-only existing database required"
    );
    // No CREATE, schema initialization, recovery, or app-instance mutation.
    let mut conn = Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)?;
    conn.busy_timeout(std::time::Duration::from_secs(5))?;
    execute(&mut conn, human, action, raw)
}

fn execute(conn: &mut Connection, human: i64, action: &str, raw: &str) -> Result<Value> {
    let request: Selection = serde_json::from_str(raw)?;
    ensure!(
        matches!(action, "inspect" | "set"),
        "Unsupported preference action"
    );
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let current = read(&tx, human, &request)?;
    if action == "inspect" {
        ensure!(
            request.expected.is_none()
                && request.model.is_none()
                && request.reasoning_effort.is_none(),
            "Inspection accepts binding only"
        );
        tx.commit()?;
        return Ok(current);
    }
    ensure!(
        request.expected.as_ref() == Some(&current),
        "Session preference changed; inspect before selection"
    );
    let model = request.model.as_deref().context("Exact model required")?;
    ensure!(
        !model.is_empty()
            && model.len() <= 128
            && model
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-._".contains(&c)),
        "Invalid model"
    );
    let effort = request
        .reasoning_effort
        .as_deref()
        .context("Exact reasoning effort required")?;
    ensure!(
        matches!(
            effort,
            "low" | "medium" | "high" | "xhigh" | "max" | "ultra"
        ),
        "Invalid reasoning effort"
    );
    // Same fields as /model and /effort, atomically, without touching busy,
    // native history, goals, jobs, tier, account or any other session preference.
    let n = tx.execute("UPDATE sessions SET model=?3, reasoning_effort=?4, updated_at=?5 WHERE chat_id=?1 AND thread_id=?2",
        params![request.chat_id, request.thread_id, model, effort, now_string()])?;
    ensure!(n == 1, "Session changed");
    let selected = read(&tx, human, &request)?;
    tx.execute(
        "INSERT INTO audit_log(actor_user_id,action,details_json,created_at) VALUES(?1,?2,?3,?4)",
        params![
            human,
            "owner_session_preferences",
            json!({"before":current,"after":selected,"effective":"next_turn"}).to_string(),
            now_string()
        ],
    )?;
    tx.commit()?;
    Ok(selected)
}

fn read(conn: &Connection, human: i64, request: &Selection) -> Result<Value> {
    let row = conn.query_row("SELECT s.id,s.model,s.reasoning_effort,s.updated_at FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1 AND s.codex_thread_id=?4 AND s.force_fresh_thread=0",
        params![request.chat_id, request.thread_id, human, request.native_thread], |r| Ok((r.get::<_,i64>(0)?,r.get::<_,Option<String>>(1)?,r.get::<_,Option<String>>(2)?,r.get::<_,String>(3)?))).optional()?;
    let Some((id, model, effort, revision)) = row else {
        bail!("Selected owner/native binding is unavailable")
    };
    Ok(
        json!({"session":id,"chat_id":request.chat_id,"thread_id":request.thread_id,"native_thread":request.native_thread,"model":model,"reasoning_effort":effort,"revision":revision,"effective":"next_turn"}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE users(tg_user_id INTEGER,allowed INTEGER); CREATE TABLE sessions(id INTEGER,chat_id INTEGER,thread_id INTEGER,creator_user_id INTEGER,codex_thread_id TEXT,force_fresh_thread INTEGER,model TEXT,reasoning_effort TEXT,updated_at TEXT,busy INTEGER); CREATE TABLE audit_log(actor_user_id INTEGER,action TEXT,details_json TEXT,created_at TEXT); INSERT INTO users VALUES(1,1); INSERT INTO sessions VALUES(28,1,2,1,'native',0,'old','high','r1',1); INSERT INTO sessions VALUES(29,1,3,1,'other',0,'old','high','r1',0);").unwrap();
        c
    }
    #[test]
    fn selected_preferences_preserve_busy_other_sessions_and_refuse_stale_binding() {
        let mut c = fixture();
        let mut request = json!({"chat_id":1,"thread_id":2,"native_thread":"native"});
        let before = execute(&mut c, 1, "inspect", &request.to_string()).unwrap();
        assert!(execute(&mut c, 9, "inspect", &request.to_string()).is_err());
        request["expected"] = before.clone();
        request["model"] = json!("gpt-6.2-astra");
        request["reasoning_effort"] = json!("medium");
        let after = execute(&mut c, 1, "set", &request.to_string()).unwrap();
        assert_eq!(after["model"], "gpt-6.2-astra");
        assert_eq!(after["reasoning_effort"], "medium");
        assert!(execute(&mut c, 1, "set", &request.to_string()).is_err());
        let fields: (i64, String) = c
            .query_row(
                "SELECT busy,(SELECT model FROM sessions WHERE id=29) FROM sessions WHERE id=28",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(fields, (1, "old".into()));
        request["native_thread"] = json!("rebound");
        assert!(execute(&mut c, 1, "set", &request.to_string()).is_err());
        request["native_thread"] = json!("native");
        request["expected"] = after;
        request["reasoning_effort"] = json!("invalid");
        assert!(execute(&mut c, 1, "set", &request.to_string()).is_err());
    }
}
