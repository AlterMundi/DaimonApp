//! An explicitly selected sibling original through the existing Gateway owner socket.
use super::*;
use crate::app::foreground::{WorkerTurn, execute_worker};
use crate::interaction::{ForegroundEngine, InteractionConfig};
use crate::store::{MatrixAuthor, WeOriginal, WePhase, WeSelection};

struct ForegroundRun<'a> {
    shared: &'a AppShared,
    event: &'a str,
}

impl Drop for ForegroundRun<'_> {
    fn drop(&mut self) {
        self.shared
            .matrix_foreground_runs
            .lock()
            .expect("Matrix foreground mutex poisoned")
            .remove(self.event);
    }
}

pub(super) async fn owner(
    app: &App,
    cfg: &InteractionConfig,
    engine: ForegroundEngine,
    args: &str,
) -> Result<Value> {
    let store = &app.shared.store;
    let (human, entry) = (cfg.human_id, cfg.entry());
    if let Some(id) = args.strip_prefix("status ") {
        return Ok(store.we_status(human, entry, id)?.unwrap_or(Value::Null));
    }
    if let Some(id) = args.strip_prefix("interrupt ") {
        let active = app
            .shared
            .matrix_foreground_runs
            .lock()
            .expect("Matrix foreground mutex poisoned");
        let retained = store.we_status(human, entry, id)?;
        let requested = retained.is_some_and(|status| {
            matches!(
                status["phase"].as_str(),
                Some("starting" | "provider_exposed")
            ) && active.get(id).is_some_and(|(active_engine, cancel)| {
                if *active_engine != engine {
                    return false;
                }
                cancel.cancel();
                true
            })
        });
        return Ok(json!({"event_id":id,"interruption_requested":requested}));
    }
    let Some(raw) = args.strip_prefix("run ") else {
        bail!("Expected run with a selected original, or status or interrupt with its UUID");
    };
    anyhow::ensure!(raw.len() <= 4096, "Bounded Matrix selection required");
    let selected: WeSelection = serde_json::from_str(raw)?;
    run_selected(app, cfg, engine, selected, None).await
}

pub(super) async fn run_selected(
    app: &App,
    cfg: &InteractionConfig,
    engine: ForegroundEngine,
    selected: WeSelection,
    input: Option<&crate::store::ConversationInput>,
) -> Result<Value> {
    selected.validate()?;
    let store = &app.shared.store;
    let (human, entry) = (cfg.human_id, cfg.entry());
    if let Some(existing) = store.we_status(human, entry, &selected.event_id)? {
        return Ok(existing);
    }
    let config = cfg
        .matrix_foreground(engine)
        .context("Selected native foreground route is unavailable")?;
    let MatrixDestination::Body {
        being_ref,
        embodiment_id,
    } = &config.transport.source
    else {
        bail!("Native foreground source body required");
    };
    let source = MatrixAuthor {
        being_ref: being_ref.clone(),
        embodiment_id: embodiment_id.clone(),
    };
    anyhow::ensure!(
        !app.shared.shutdown.is_cancelled(),
        "Gateway is shutting down"
    );
    let (observed, body) = authenticate_foreground_body(&config.transport, &source).await?;
    let mut host = json!({"source":source,"body":observed,"original":selected});
    let original: WeOriginal = serde_json::from_value(
        host_command_mode(&config.transport, &host, Some("--we-read")).await?,
    )?;
    anyhow::ensure!(
        original.event_id == selected.event_id
            && original.author == selected.author
            && original.thread_id == selected.thread_id,
        "Matrix host returned another original"
    );
    let text = original.text.clone();
    let id = selected.event_id;
    let cancel = app.shared.shutdown.child_token();
    let attempt = {
        let mut active = app
            .shared
            .matrix_foreground_runs
            .lock()
            .expect("Matrix foreground mutex poisoned");
        let Some(attempt) =
            store.we_start(human, entry, engine, source, observed, original, input)?
        else {
            return store
                .we_status(human, entry, &id)?
                .context("Retained original unavailable");
        };
        active.insert(id.clone(), (engine, cancel.clone()));
        attempt
    };
    let foreground = ForegroundRun {
        shared: &app.shared,
        event: &id,
    };
    let mut exposed = false;
    let execution = execute_worker(
        &config.worker_command,
        engine,
        WorkerTurn {
            id: &id,
            session: &attempt.session_id,
            resume: attempt.resume.as_slice(),
            acp_topic: None,
            qwen_resume: None,
            human_original: attempt.human_original,
            native_goal_command: false,
            routed_human: false,
            routed_host_access: false,
            session_instructions: None,
            workspace: None,
            output_directory: None,
            history_seed: None,
            project_checkpoint: None,
            require_recovery_context: false,
            text: &text,
            attachments: &[],
            body,
            cancel: &cancel,
            shutdown: &app.shared.shutdown,
            controller: None,
            steering: None,
            acceptance: None,
        },
        |prepared| {
            // Order the exposure commit and the operator interruption together.
            let _active = app
                .shared
                .matrix_foreground_runs
                .lock()
                .expect("Matrix foreground mutex poisoned");
            if cancel.is_cancelled() {
                return Ok(false);
            }
            exposed = store.we_transition(
                human,
                entry,
                &attempt,
                WePhase::Starting,
                WePhase::ProviderExposed,
                prepared,
            )?;
            Ok(exposed)
        },
    )
    .await;
    // Close the operator interruption window before a possible signed return.
    drop(foreground);
    let interrupted = cancel.is_cancelled() && !app.shared.shutdown.is_cancelled();
    match (exposed, execution) {
        (false, outcome) => {
            let known = outcome
                .ok()
                .filter(|value| value["phase"] == "not_submitted")
                .and_then(|value| {
                    let reason = value["reason"].as_str()?;
                    (reason.len() <= 128
                        && !reason.is_empty()
                        && reason.bytes().all(|b| b.is_ascii_lowercase() || b == b'_'))
                    .then(|| json!({"reason":reason}))
                });
            store.we_transition(
                human,
                entry,
                &attempt,
                WePhase::Starting,
                WePhase::Rejected,
                if interrupted {
                    json!({"reason":"interrupted_before_submission"})
                } else {
                    known.unwrap_or_else(|| json!({"reason":"worker_exited_before_exposure"}))
                },
            )?;
        }
        (true, Ok(outcome)) if outcome["phase"] == "completed" => {
            let reply = outcome["text"]
                .as_str()
                .context("Bounded native result required")?;
            let send_id = uuid::Uuid::now_v7().to_string();
            host["text"] = json!(reply);
            host["send_id"] = json!(send_id);
            let can_return = reply.len() <= 16384
                && serde_json::to_vec(&host)?.len() <= 65536
                && !cancel.is_cancelled()
                && store.we_transition(
                    human,
                    entry,
                    &attempt,
                    WePhase::ProviderExposed,
                    WePhase::Returning,
                    json!({"send_id":send_id,"text":reply}),
                )?;
            if can_return {
                let delivery = tokio::select! {
                    biased;
                    _ = app.shared.shutdown.cancelled() => None,
                    result = host_command_mode(&config.transport, &host, Some("--we-return")) => result.ok(),
                };
                let (phase, delivery) = settle_return(delivery, &send_id, &selected.thread_id);
                store.we_transition(human, entry, &attempt, WePhase::Returning, phase, delivery)?;
            } else {
                store.we_transition(
                    human,
                    entry,
                    &attempt,
                    WePhase::ProviderExposed,
                    WePhase::ResultRetained,
                    json!({"text":reply,"reason":"return_not_dispatched"}),
                )?;
            }
        }
        (true, outcome) => {
            let budget_exhausted = outcome.is_ok_and(|value| {
                value["phase"] == "uncertain" && value["reason"] == "claude_budget_exhausted"
            });
            let reason = if interrupted {
                "foreground_interrupted"
            } else if budget_exhausted {
                "claude_budget_exhausted"
            } else {
                "native_result_unconfirmed"
            };
            store.we_transition(
                human,
                entry,
                &attempt,
                WePhase::ProviderExposed,
                WePhase::ProviderUncertain,
                json!({"reason":reason}),
            )?;
        }
    }
    store
        .we_status(human, entry, &id)?
        .context("Retained original unavailable")
}

pub(in crate::app) async fn authenticate_foreground_body(
    transport: &MatrixTransportConfig,
    source: &MatrixAuthor,
) -> Result<(Value, Value)> {
    let observed =
        host_command_mode(transport, &json!({"source":source}), Some("--body-status")).await?;
    let body = worker_body(source, &observed)?;
    Ok((observed, body))
}

fn worker_body(source: &MatrixAuthor, status: &Value) -> Result<Value> {
    let observed = &status["local_origin"];
    anyhow::ensure!(
        status["schema"] == "dm.runtime.status/v1"
            && status["integrity"] == "ok"
            && status["being_ref"] == source.being_ref
            && observed["embodiment_id"] == source.embodiment_id
            && observed["incarnation_id"]
                .as_str()
                .is_some_and(|value| !value.is_empty() && value.len() <= 240)
            && status["manifest_hash"]
                .as_str()
                .is_some_and(|value| value.len() == 64
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))),
        "Authenticated Matrix body differs from the foreground selection"
    );
    Ok(
        json!({"beingRef":source.being_ref,"embodimentId":source.embodiment_id,
        "incarnationId":observed["incarnation_id"],"manifestHash":status["manifest_hash"]}),
    )
}

fn settle_return(outcome: Option<Value>, send_id: &str, thread: &str) -> (WePhase, Value) {
    fn uuid_field(value: &Value) -> bool {
        value
            .as_str()
            .is_some_and(|text| uuid::Uuid::parse_str(text).is_ok_and(|id| id.to_string() == text))
    }
    let mut result = json!({"reason":"author_receipt_unconfirmed"});
    if let Some(value) = outcome.filter(|value| {
        value["schema"] == "daimon-gateway.matrix-we-return/v1"
            && value["request_id"] == send_id
            && value["thread_id"] == thread
            && uuid_field(&value["message_id"])
            && value["message_hash"].as_str().is_some_and(|hash| {
                hash.len() == 64
                    && hash
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
    }) {
        result["message_id"] = value["message_id"].clone();
        result["message_hash"] = value["message_hash"].clone();
        if value["state"] == "delivered" && uuid_field(&value["receipt_event_id"]) {
            return (
                WePhase::Delivered,
                json!({"message_id":value["message_id"],
                "message_hash":value["message_hash"],"receipt_event_id":value["receipt_event_id"]}),
            );
        }
    }
    (WePhase::ReturnUncertain, result)
}
