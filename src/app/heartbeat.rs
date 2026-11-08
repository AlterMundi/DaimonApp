//! Human console and scoped integrator share one model-free attention control.
use super::*;
use crate::store::HeartbeatCommand;
use serde_json::Value;

mod readiness;

pub(super) async fn execute(
    app: &App,
    human: i64,
    entry: SessionKey,
    command: HeartbeatCommand,
) -> Result<Value> {
    let cfg = super::routing::profile(&app.shared)?;
    if cfg.human_id != human || cfg.entry() != entry {
        bail!("Heartbeat control belongs to the configured integrating entry");
    }
    if let HeartbeatCommand::ConfigureProducer { contract, .. } = &command {
        if let Some(purpose) = &contract.purpose {
            let purpose: &crate::store::HeartbeatPurpose = purpose;
            if matches!(
                purpose.input_ref,
                crate::interaction::InputReference::Telegram(_)
            ) {
                anyhow::ensure!(
                    purpose.channel == format!("telegram:{}", app.shared.bot_id),
                    "Human purpose must use this receiver's actual Telegram original identity"
                );
            }
        }
        if let Some(source) = &contract.matrix_inbox {
            super::matrix::inbox_matches(&cfg, source)?;
        }
    }
    let lane = match &command {
        HeartbeatCommand::PauseLane { lane }
        | HeartbeatCommand::SetLanePaused {
            lane, paused: true, ..
        } => Some(*lane),
        _ => None,
    };
    let pause = matches!(
        &command,
        HeartbeatCommand::Pause | HeartbeatCommand::SetPaused { paused: true, .. }
    ) || lane.is_some();
    // Persist the fence before attempting cancellation or any native read.
    let mut value = app.shared.store.heartbeat_control(human, entry, command)?;
    let records = app
        .shared
        .store
        .heartbeat_executions_scoped(human, entry, pause, lane)?;
    let mut observations = Vec::new();
    for r in records.iter().filter(|r| {
        r["phase"] == "stopping"
            && pause
            && lane
                .is_none_or(|lane| r["activation"]["lane"] == serde_json::to_value(lane).unwrap())
    }) {
        let Some(physical) = r["physical"].as_str() else {
            observations.push(serde_json::json!({"local":r["local"],"state":"unconfirmed","reason":"physical_identity_not_yet_observed"}));
            continue;
        };
        let native = r["native"]
            .as_str()
            .context("Heartbeat native identity missing")?;
        let acknowledged = app
            .shared
            .codex
            .interrupt_selected_turn(native, physical)
            .await
            .is_ok();
        let terminal = app
            .shared
            .codex
            .admitted_turn_status(native, Some(physical), "")
            .await
            .ok()
            .flatten()
            .filter(|(id, status)| {
                id == physical && matches!(status.as_str(), "completed" | "failed" | "interrupted")
            });
        if let Some((_, status)) = terminal {
            app.shared.store.heartbeat_native_terminal(
                r["local"]
                    .as_i64()
                    .context("Heartbeat local identity missing")?,
                physical,
                &status,
            )?;
            observations.push(serde_json::json!({"local":r["local"],"state":"terminal","status":status,"interrupt_acknowledged":acknowledged}));
        } else {
            observations.push(serde_json::json!({"local":r["local"],"state":"unconfirmed","interrupt_acknowledged":acknowledged}));
        }
    }
    value["owned_execution_control"] = serde_json::json!("exact_native_interrupt");
    value["executions"] =
        serde_json::to_value(app.shared.store.heartbeat_executions(human, entry, false)?)?;
    value["cancellation_observations"] = serde_json::to_value(observations)?;
    readiness::annotate(app, human, entry, &mut value).await;
    Ok(value)
}
pub(super) async fn owner(app: &App, human: i64, args: &str) -> Result<Value> {
    if let Some(rest) = args.strip_prefix("production-defaults ") {
        let (generation, raw) = rest
            .split_once(' ')
            .context("Expected heartbeat production-defaults GENERATION SOURCE_JSON_STRING")?;
        let source: String = serde_json::from_str(raw)?;
        let cfg = super::routing::profile(&app.shared)?;
        anyhow::ensure!(
            cfg.human_id == human,
            "Heartbeat belongs to the configured paired human"
        );
        app.shared.store.heartbeat_production_defaults(
            human,
            cfg.entry(),
            generation.parse()?,
            &source,
        )?;
        return execute(app, human, cfg.entry(), HeartbeatCommand::Status).await;
    }
    if let Some(rest) = args.strip_prefix("select-review ") {
        let (generation, raw) = rest
            .split_once(' ')
            .context("Expected heartbeat select-review GENERATION CONTRACT_JSON")?;
        let contract: crate::store::HeartbeatReviewContract = serde_json::from_str(raw)?;
        if matches!(
            contract.purpose.input_ref,
            crate::interaction::InputReference::Telegram(_)
        ) {
            anyhow::ensure!(
                contract.purpose.channel == format!("telegram:{}", app.shared.bot_id),
                "Select this receiving bot's actual original channel"
            );
        }
        let cfg = super::routing::profile(&app.shared)?;
        app.shared.store.heartbeat_select_review(
            human,
            cfg.entry(),
            generation.parse()?,
            contract,
        )?;
        return execute(app, human, cfg.entry(), HeartbeatCommand::Status).await;
    }
    if let Some(rest) = args.strip_prefix("continuous ") {
        let fields: Vec<_> = rest.split_whitespace().collect();
        anyhow::ensure!(
            fields.len() == 2,
            "Expected heartbeat continuous GENERATION ATTEMPTS_PER_HOUR"
        );
        let cfg = super::routing::profile(&app.shared)?;
        anyhow::ensure!(
            cfg.human_id == human,
            "Heartbeat belongs to the configured paired human"
        );
        app.shared.store.heartbeat_enable_continuous(
            human,
            cfg.entry(),
            fields[0].parse()?,
            fields[1].parse()?,
        )?;
        return execute(app, human, cfg.entry(), HeartbeatCommand::Status).await;
    }
    if let Some((action, rest)) = args
        .split_once(' ')
        .filter(|(action, _)| matches!(*action, "renew-window" | "renew-observation"))
    {
        let fields: Vec<_> = rest.split_whitespace().collect();
        let cfg = super::routing::profile(&app.shared)?;
        anyhow::ensure!(
            cfg.human_id == human,
            "Heartbeat belongs to the configured paired human"
        );
        match fields.as_slice() {
            [generation, previous_expiry, expiry] => {
                let renew = if action == "renew-window" {
                    crate::store::Store::heartbeat_renew_window
                } else {
                    crate::store::Store::heartbeat_renew_observation
                };
                renew(
                    &app.shared.store,
                    human,
                    cfg.entry(),
                    generation.parse()?,
                    previous_expiry.parse()?,
                    expiry.parse()?,
                )?;
            }
            [generation, previous_expiry, expiry, max_checks] if action == "renew-observation" => {
                app.shared.store.heartbeat_renew_observation_capacity(
                    human,
                    cfg.entry(),
                    generation.parse()?,
                    previous_expiry.parse()?,
                    expiry.parse()?,
                    max_checks.parse()?,
                )?;
            }
            _ => bail!(
                "Expected heartbeat {action} GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS (renew-observation also accepts an explicit cumulative MAX_CHECKS)"
            ),
        }
        return execute(app, human, cfg.entry(), HeartbeatCommand::Status).await;
    }
    if let Some(rest) = args.strip_prefix("configure-producer ") {
        let (generation, raw) = rest
            .split_once(' ')
            .context("Expected heartbeat configure-producer GENERATION CONTRACT_JSON")?;
        return execute(
            app,
            human,
            super::routing::profile(&app.shared)?.entry(),
            HeartbeatCommand::ConfigureProducer {
                generation: generation.parse()?,
                contract: serde_json::from_str::<crate::store::HeartbeatProducerContract>(raw)?,
            },
        )
        .await;
    }
    if let Some(rest) = args.strip_prefix("configure-resources ") {
        let (generation, raw) = rest
            .split_once(' ')
            .context("Expected heartbeat configure-resources GENERATION CONTRACT_JSON")?;
        return execute(
            app,
            human,
            super::routing::profile(&app.shared)?.entry(),
            HeartbeatCommand::ConfigureResources {
                generation: generation.parse()?,
                contract: serde_json::from_str::<crate::store::HeartbeatResources>(raw)?,
            },
        )
        .await;
    }
    let fields = args.split_whitespace().collect::<Vec<_>>();
    let command = match fields.as_slice() {
        ["status"] => HeartbeatCommand::Status,
        ["pause"] => HeartbeatCommand::Pause,
        ["pause", generation] => HeartbeatCommand::SetPaused {
            paused: true,
            generation: generation.parse()?,
        },
        ["pause-lane", lane] => HeartbeatCommand::PauseLane {
            lane: serde_json::from_value(serde_json::json!(lane))?,
        },
        ["resume-lane", lane, generation] => HeartbeatCommand::ResumeLane {
            lane: serde_json::from_value(serde_json::json!(lane))?,
            generation: generation.parse()?,
        },
        [
            action @ ("pause-lane" | "resume-lane"),
            lane,
            global,
            generation,
        ] => HeartbeatCommand::SetLanePaused {
            lane: serde_json::from_value(serde_json::json!(lane))?,
            paused: *action == "pause-lane",
            global_generation: global.parse()?,
            generation: generation.parse()?,
        },
        ["resume", generation] => HeartbeatCommand::Resume {
            generation: generation.parse()?,
        },
        _ => bail!(
            "Expected heartbeat status|pause [GENERATION]|resume GENERATION|select-review GENERATION CONTRACT_JSON|renew-window GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS|renew-observation GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS [MAX_CHECKS]|pause-lane LANE [GLOBAL_GENERATION LANE_GENERATION]|resume-lane LANE [GLOBAL_GENERATION] LANE_GENERATION|configure-resources GENERATION CONTRACT_JSON|configure-producer GENERATION CONTRACT_JSON"
        ),
    };
    execute(
        app,
        human,
        super::routing::profile(&app.shared)?.entry(),
        command,
    )
    .await
}

/// Existing maintenance calls this; unconfigured/paused/no-news never starts a model.
pub(super) async fn tick(app: &App) -> Result<()> {
    if app.shared.shutdown.is_cancelled() {
        return Ok(());
    }
    let Some(cfg) = app.shared.config.interaction.as_ref() else {
        return Ok(());
    };
    let Some(session) = app.shared.store.get_session(cfg.entry())? else {
        return Ok(());
    };
    if session.codex_thread_id.is_none() {
        return Ok(());
    }
    let Some(check): Option<crate::store::HeartbeatCheck> = app
        .shared
        .store
        .heartbeat_begin_check(cfg.human_id, cfg.entry())?
    else {
        return Ok(());
    };
    let read = if let Some(source) = &check.matrix_inbox {
        if !app.shared.store.heartbeat_check_current(&check)? {
            return Ok(());
        }
        Some(tokio::select! {
            biased;
            _=app.shared.shutdown.cancelled()=>return Ok(()),
            result=super::matrix::read_inbox(app,cfg.human_id,cfg.entry(),source)=>result,
        })
    } else {
        None
    };
    let current = app.shared.store.get_session(cfg.entry())?;
    let allow_attention = if let Some(session) = current.filter(|s| !s.busy) {
        native_preflight_allows_dispatch(app.shared.codex.bounded_idle_readiness(&session).await)
    } else {
        false
    };
    if let Some(selected) =
        app.shared
            .store
            .heartbeat_finish_observation(&check, read, allow_attention)?
    {
        let id = selected.id.clone();
        let attempt = selected.attempts;
        if app.shared.shutdown.is_cancelled()
            || super::workflows::deliver(app, selected).await.is_err()
        {
            app.shared.store.workflow_native_outcome_attempt(
                &id,
                attempt,
                "retained_unsent",
                None,
            )?;
        }
    }
    Ok(())
}

pub(super) async fn recover_unsent(app: &App) -> Result<()> {
    let Some(cfg) = app.shared.config.interaction.as_ref() else {
        return Ok(());
    };
    if app.shared.shutdown.is_cancelled() {
        return Ok(());
    }
    let Some(session) = app.shared.store.get_session(cfg.entry())? else {
        return Ok(());
    };
    if session.busy || session.codex_thread_id.is_none() {
        return Ok(());
    }
    // A local slot can be free while the native goal has a physical writer.
    // Observe that contention before spending a retry or execution envelope;
    // the atomic native admission remains mandatory for races after this read.
    if !native_preflight_allows_dispatch(app.shared.codex.bounded_idle_readiness(&session).await) {
        return Ok(());
    }
    for selected in app
        .shared
        .store
        .heartbeat_returns_recover_unsent(cfg.human_id, cfg.entry())?
    {
        let id = selected.id.clone();
        let attempt = selected.attempts;
        if app.shared.shutdown.is_cancelled()
            || super::workflows::deliver(app, selected).await.is_err()
        {
            app.shared.store.workflow_native_outcome_attempt(
                &id,
                attempt,
                "retained_unsent",
                None,
            )?;
        }
    }
    Ok(())
}

// Yield only the finished ordinary collector. The existing parent then performs
// its usual exact idle admission; this neither starts work nor touches a goal.
// Only observed contention postpones dispatch. An unloaded cache may need
// the existing model-free resume before mandatory atomic native admission;
// missing metadata is not another permanent activation gate.
fn native_preflight_allows_dispatch(observation: Result<&'static str>) -> bool {
    !matches!(observation, Ok("native_busy"))
}
fn pending_attention_can_take_idle(value: &Value) -> bool {
    value["admission_paused"] == false
        && value["producer"]["pending"] == true
        && value["producer"]["state"] == "configured"
        && value["resources"]["state"] == "available"
        && value["lanes"].as_object().is_some_and(|lanes| {
            lanes
                .values()
                .any(|lane| lane["paused"] == false && lane["supported"] == true)
        })
}
pub(super) fn yield_collector_for_attention(app: &App, human: i64, entry: SessionKey) -> bool {
    app.shared
        .config
        .interaction
        .as_ref()
        .is_some_and(|cfg| cfg.human_id == human && cfg.entry() == entry)
        && app
            .shared
            .store
            .heartbeat_control(human, entry, HeartbeatCommand::Status)
            .is_ok_and(|value| pending_attention_can_take_idle(&value))
}
#[cfg(test)]
mod idle_handoff_tests {
    use super::*;
    #[test]
    fn contention_is_not_an_unloaded_cache_gate() {
        assert!(!native_preflight_allows_dispatch(Ok("native_busy")));
        assert!(native_preflight_allows_dispatch(Ok("ready")));
        assert!(native_preflight_allows_dispatch(Ok(
            "native_binding_unavailable"
        )));
        assert!(native_preflight_allows_dispatch(Err(anyhow::anyhow!(
            "metadata unavailable"
        ))));
    }
    #[test]
    fn pending_attention_yields_only_with_current_controls_and_capacity() {
        let value = serde_json::json!({"admission_paused":false,"producer":{"pending":true,"state":"configured"},"resources":{"state":"available"},"lanes":{"messaging":{"paused":false,"supported":true}}});
        assert!(pending_attention_can_take_idle(&value));
        for (pointer, v) in [
            ("/admission_paused", serde_json::json!(true)),
            ("/producer/pending", serde_json::json!(false)),
            ("/resources/state", serde_json::json!("rate_limited")),
            ("/lanes/messaging/paused", serde_json::json!(true)),
        ] {
            let mut blocked = value.clone();
            *blocked.pointer_mut(pointer).unwrap() = v;
            assert!(!pending_attention_can_take_idle(&blocked));
        }
    }
}
