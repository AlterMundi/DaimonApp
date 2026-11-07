//! Fresh model-free observation; never an admission probe or another scheduler.
use super::*;
use serde_json::json;

fn eligible(value: &Value, now: i64, loop_started: i64) -> Result<(), &'static str> {
    if value["admission_paused"] != false {
        return Err("paused");
    }
    if value["lanes"]["messaging"]["paused"] != false {
        return Err("messaging_paused");
    }
    if value["resources"]["state"] != "available" {
        return Err("resources_unavailable");
    }
    if value["producer"]["state"] != "configured" {
        return Err("observation_unavailable");
    }
    for kind in ["producer", "resources"] {
        if value[kind]["contract"]["expires_at_unix_ms"]
            .as_i64()
            .is_none_or(|end| end <= now)
        {
            return Err("window_expired");
        }
    }
    let remaining = value["resources"]["remaining_provider_attempts"]
        .as_u64()
        .unwrap_or(0);
    let per_execution = value["resources"]["contract"]["provider_attempts_per_execution"]
        .as_u64()
        .unwrap_or(0);
    if per_execution == 0 || remaining < per_execution {
        return Err("resources_unavailable");
    }
    let producer = &value["producer"];
    if producer["checks"]
        .as_u64()
        .zip(producer["contract"]["max_checks"].as_u64())
        .is_none_or(|(count, max)| count >= max)
    {
        return Err("observation_capacity");
    }
    if producer["pending"] == true {
        return Err("attention_pending");
    }
    let check = &producer["last_check"];
    if check["outcome"] != "succeeded"
        || check["generation"] != value["generation"]
        || check["activation"]["lane"] != "messaging"
        || check["activation"]["generation"] != value["lanes"]["messaging"]["generation"]
    {
        return Err("source_check_unavailable");
    }
    let start = check["started_at_unix_ms"].as_i64().unwrap_or(0);
    let completed = check["completed_at_unix_ms"].as_i64().unwrap_or(0);
    // The existing serial maintenance loop may spend one bounded recovery pass
    // between checks. This is a freshness limit, not an additional check grant.
    let cadence = producer["contract"]["interval_seconds"]
        .as_i64()
        .filter(|s| (30..=3600).contains(s))
        .ok_or("source_check_unavailable")?;
    if loop_started <= 0
        || start < loop_started
        || completed < start
        || completed > now
        || now - completed > cadence * 2000 + 15_000
    {
        return Err("source_check_stale");
    }
    Ok(())
}

fn loop_alive(app: &App) -> bool {
    !app.shared.shutdown.is_cancelled()
        && app
            .shared
            .heartbeat_owner_held
            .load(std::sync::atomic::Ordering::Acquire)
        && app
            .shared
            .heartbeat_loop
            .lock()
            .is_ok_and(|task| task.as_ref().is_some_and(|t| !t.is_finished()))
}

pub(super) async fn annotate(app: &App, human: i64, entry: SessionKey, value: &mut Value) {
    let start = app
        .shared
        .heartbeat_loop_started_at
        .load(std::sync::atomic::Ordering::Acquire);
    let result = async {
        anyhow::ensure!(loop_alive(app), "loop_unavailable");
        eligible(value, Utc::now().timestamp_millis(), start).map_err(anyhow::Error::msg)?;
        let session = app
            .shared
            .store
            .get_session(entry)?
            .context("native_binding_unavailable")?;
        anyhow::ensure!(!session.busy, "native_busy");
        let reason = app
            .shared
            .codex
            .bounded_idle_readiness(&session)
            .await
            .map_err(|_| anyhow::anyhow!("native_observation_unavailable"))?;
        anyhow::ensure!(reason == "ready", reason);
        let fresh = app
            .shared
            .store
            .heartbeat_control(human, entry, HeartbeatCommand::Status)?;
        anyhow::ensure!(
            fresh["generation"] == value["generation"]
                && fresh["lanes"]["messaging"]["generation"]
                    == value["lanes"]["messaging"]["generation"],
            "controls_changed"
        );
        eligible(&fresh, Utc::now().timestamp_millis(), start).map_err(anyhow::Error::msg)?;
        let current = app
            .shared
            .store
            .get_session(entry)?
            .context("native_binding_unavailable")?;
        anyhow::ensure!(!current.busy, "native_busy");
        anyhow::ensure!(
            current.id == session.id
                && current.codex_thread_id == session.codex_thread_id
                && current.model == session.model
                && current.reasoning_effort == session.reasoning_effort
                && !current.force_fresh_thread
                && loop_alive(app),
            "native_binding_changed"
        );
        Ok::<_, anyhow::Error>(())
    }
    .await;
    // Only fixed classifications enter status; arbitrary native/DB errors may
    // contain private details and never become an operational reason.
    let reason = match result {
        Ok(()) => "ready".to_string(),
        Err(error) => {
            let text = error.to_string();
            match text.as_str() {
                "paused"
                | "messaging_paused"
                | "resources_unavailable"
                | "observation_unavailable"
                | "window_expired"
                | "observation_capacity"
                | "source_check_unavailable"
                | "source_check_stale"
                | "loop_unavailable"
                | "native_binding_unavailable"
                | "native_support_unavailable"
                | "native_admission_unavailable"
                | "native_busy"
                | "attention_pending"
                | "native_observation_unavailable"
                | "controls_changed"
                | "native_binding_changed" => text,
                _ => "readiness_unavailable".to_string(),
            }
        }
    };
    let operational = reason == "ready";
    value["operational"] = json!(operational);
    value["operational_evidence"] = json!({"schema":"telecodex.heartbeat-operational/v1",
        "generation":value["generation"],"observed_at_unix_ms":Utc::now().timestamp_millis(),
        "valid_for_seconds":15,"operational":operational,"reason":reason,
        "lanes":{"messaging":{"generation":value["lanes"]["messaging"]["generation"],"operational":operational}},
        "meaning":"Live loop, fresh successful source check, finite remaining resources and current native support/profile/idle admission observation; not a promise of provider success or delivered work"});
}

#[cfg(test)]
mod tests {
    use super::*;
    fn ready() -> Value {
        json!({"generation":4,"admission_paused":false,
            "lanes":{"messaging":{"generation":2,"paused":false}},
            "resources":{"state":"available","remaining_provider_attempts":12,"contract":{"provider_attempts_per_execution":12,"expires_at_unix_ms":200000}},
            "producer":{"state":"configured","checks":1,"pending":false,"contract":{"interval_seconds":30,"max_checks":120,"expires_at_unix_ms":200000},
                "last_check":{"generation":4,"activation":{"lane":"messaging","generation":2},"outcome":"succeeded","started_at_unix_ms":90000,"completed_at_unix_ms":91000}}})
    }
    #[test]
    fn operational_source_must_be_current_finite_and_from_this_live_loop() {
        assert!(eligible(&ready(), 100000, 80000).is_ok());
        assert_eq!(eligible(&ready(), 166001, 80000), Err("source_check_stale"));
        assert_eq!(eligible(&ready(), 100000, 92000), Err("source_check_stale"));
        for (pointer, replacement, reason) in [
            ("/admission_paused", json!(true), "paused"),
            ("/lanes/messaging/paused", json!(true), "messaging_paused"),
            (
                "/resources/remaining_provider_attempts",
                json!(0),
                "resources_unavailable",
            ),
            (
                "/producer/contract/expires_at_unix_ms",
                json!(99999),
                "window_expired",
            ),
            ("/producer/checks", json!(120), "observation_capacity"),
            ("/producer/pending", json!(true), "attention_pending"),
            (
                "/producer/last_check/outcome",
                json!("failed"),
                "source_check_unavailable",
            ),
            ("/generation", json!(5), "source_check_unavailable"),
            (
                "/lanes/messaging/generation",
                json!(3),
                "source_check_unavailable",
            ),
        ] {
            let mut value = ready();
            *value.pointer_mut(pointer).unwrap() = replacement;
            assert_eq!(eligible(&value, 100000, 80000), Err(reason), "{pointer}");
        }
    }
}
