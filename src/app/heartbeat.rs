//! Human console and scoped integrator share one model-free attention control.
use super::*;
use crate::store::HeartbeatCommand;
use serde_json::Value;

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
    let pause = matches!(&command, HeartbeatCommand::Pause);
    // Persist the fence before attempting cancellation or any native read.
    let mut value = app.shared.store.heartbeat_control(human, entry, command)?;
    let records = app.shared.store.heartbeat_executions(human, entry, pause)?;
    let mut observations = Vec::new();
    for r in records.iter().filter(|r| r["phase"] == "stopping" && pause) {
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
    Ok(value)
}
pub(super) async fn owner(app: &App, human: i64, args: &str) -> Result<Value> {
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
        ["resume", generation] => HeartbeatCommand::Resume {
            generation: generation.parse()?,
        },
        _ => bail!(
            "Expected heartbeat status|pause|resume GENERATION|configure-resources GENERATION CONTRACT_JSON|configure-producer GENERATION CONTRACT_JSON"
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
    if session.busy || session.codex_thread_id.is_none() {
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
    if let Some(selected) = app.shared.store.heartbeat_finish_check(&check, read)? {
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
