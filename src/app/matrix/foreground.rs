//! An explicitly selected sibling original through the existing Gateway owner socket.
use super::*;
use crate::app::foreground::{WorkerTurn, execute_worker};
use crate::interaction::{ForegroundEngine, InteractionConfig};
use crate::store::{MatrixAuthor, WeOriginal, WePhase, WeSelection};

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
    let Some(raw) = args.strip_prefix("run ") else {
        bail!("Expected a foreground run with a selected original, or status with its UUID");
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
    let config = match engine {
        ForegroundEngine::Claude => cfg.claude_foreground.as_ref(),
        ForegroundEngine::Goose => cfg.goose_foreground.as_ref(),
        ForegroundEngine::Antigravity => cfg.antigravity_foreground.as_ref(),
    }
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
    let Some(attempt) = store.we_start(human, entry, engine, source, observed, original, input)?
    else {
        return store
            .we_status(human, entry, &id)?
            .context("Retained original unavailable");
    };
    let mut exposed = false;
    let execution = tokio::select! {
        biased;
        _ = app.shared.shutdown.cancelled() => Err(anyhow!("Gateway is shutting down")),
        result = execute_worker(&config.worker_command, engine, WorkerTurn {
            id: &id, session: &attempt.session_id, resume: attempt.resume.as_ref(),
            human_original: attempt.human_original, text: &text, body,
        }, |prepared| {
            exposed = store.we_transition(human, entry, &attempt,
                WePhase::Starting, WePhase::ProviderExposed, prepared)?;
            Ok(exposed)
        }) => result,
    };
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
                known.unwrap_or_else(|| json!({"reason":"worker_exited_before_exposure"})),
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
                && !app.shared.shutdown.is_cancelled()
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
            let reason = if budget_exhausted {
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
