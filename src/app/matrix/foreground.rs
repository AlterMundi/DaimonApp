//! An explicitly selected sibling original through the existing Gateway owner socket.
use super::*;
use crate::interaction::{ClaudeForegroundConfig, InteractionConfig};
use crate::store::{MatrixAuthor, WeOriginal, WePhase, WeSelection};

const WORKER_SCHEMA: &str = "daimon-gateway.claude-turn/v1";

pub(super) async fn owner(app: &App, cfg: &InteractionConfig, args: &str) -> Result<Value> {
    let store = &app.shared.store;
    let (human, entry) = (cfg.human_id, cfg.entry());
    if let Some(id) = args.strip_prefix("status ") {
        return Ok(store.we_status(human, entry, id)?.unwrap_or(Value::Null));
    }
    let Some(raw) = args.strip_prefix("run ") else {
        bail!("Expected matrix claude run with a selected original, or status with its UUID");
    };
    anyhow::ensure!(raw.len() <= 4096, "Bounded Matrix selection required");
    let selected: WeSelection = serde_json::from_str(raw)?;
    selected.validate()?;
    if let Some(existing) = store.we_status(human, entry, &selected.event_id)? {
        return Ok(existing);
    }
    let config = cfg
        .claude_foreground
        .as_ref()
        .context("Claude foreground route is unavailable")?;
    let MatrixDestination::Body {
        being_ref,
        embodiment_id,
    } = &config.transport.source
    else {
        bail!("Claude foreground source body required");
    };
    let source = MatrixAuthor {
        being_ref: being_ref.clone(),
        embodiment_id: embodiment_id.clone(),
    };
    anyhow::ensure!(
        !app.shared.shutdown.is_cancelled(),
        "Gateway is shutting down"
    );
    let observed = host_command_mode(
        &config.transport,
        &json!({"source":source}),
        Some("--body-status"),
    )
    .await?;
    let body = worker_body(&source, &observed)?;
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
    let Some(attempt) = store.we_start(human, entry, source, observed, original)? else {
        return store
            .we_status(human, entry, &id)?
            .context("Retained original unavailable");
    };
    let mut exposed = false;
    let execution = tokio::select! {
        biased;
        _ = app.shared.shutdown.cancelled() => Err(anyhow!("Gateway is shutting down")),
        result = execute_worker(config, &id, &attempt.session_id, &text, body, || {
            exposed = store.we_transition(human, entry, &id, &attempt,
                WePhase::Starting, WePhase::ProviderExposed, Value::Null)?;
            Ok(exposed)
        }) => result,
    };
    match (exposed, execution) {
        (false, outcome) => {
            let known = outcome
                .ok()
                .filter(|value| value["phase"] == "not_submitted");
            store.we_transition(
                human,
                entry,
                &id,
                &attempt,
                WePhase::Starting,
                WePhase::Rejected,
                known.unwrap_or_else(|| json!({"reason":"worker_exited_before_exposure"})),
            )?;
        }
        (true, Ok(outcome)) if outcome["phase"] == "completed" => {
            let reply = outcome["text"]
                .as_str()
                .context("Bounded Claude result required")?;
            let send_id = uuid::Uuid::now_v7().to_string();
            host["text"] = json!(reply);
            host["send_id"] = json!(send_id);
            let can_return = reply.len() <= 16384
                && serde_json::to_vec(&host)?.len() <= 65536
                && !app.shared.shutdown.is_cancelled()
                && store.we_transition(
                    human,
                    entry,
                    &id,
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
                store.we_transition(
                    human,
                    entry,
                    &id,
                    &attempt,
                    WePhase::Returning,
                    phase,
                    delivery,
                )?;
            } else {
                store.we_transition(
                    human,
                    entry,
                    &id,
                    &attempt,
                    WePhase::ProviderExposed,
                    WePhase::ResultRetained,
                    json!({"text":reply,"reason":"return_not_dispatched"}),
                )?;
            }
        }
        (true, _) => {
            store.we_transition(
                human,
                entry,
                &id,
                &attempt,
                WePhase::ProviderExposed,
                WePhase::ProviderUncertain,
                json!({"reason":"native_result_unconfirmed"}),
            )?;
        }
    }
    store
        .we_status(human, entry, &id)?
        .context("Retained original unavailable")
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

#[cfg(unix)]
async fn execute_worker(
    config: &ClaudeForegroundConfig,
    id: &str,
    session: &str,
    text: &str,
    body: Value,
    commit: impl FnOnce() -> Result<bool>,
) -> Result<Value> {
    use std::{os::unix::process::CommandExt, process::Stdio, time::Duration};
    use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
    use tokio::process::Command;

    async fn send(input: &mut tokio::process::ChildStdin, value: Value) -> Result<()> {
        let mut raw = serde_json::to_vec(&value)?;
        raw.push(b'\n');
        input.write_all(&raw).await?;
        Ok(())
    }
    async fn receive(
        output: &mut (impl AsyncBufReadExt + Unpin),
        id: &str,
        session: &str,
    ) -> Result<Value> {
        let mut frame = Vec::new();
        let length = output.read_until(b'\n', &mut frame).await?;
        anyhow::ensure!(
            length > 0 && frame.last() == Some(&b'\n'),
            "Unconfirmed Claude worker frame"
        );
        let decoded: Value = serde_json::from_slice(&frame)?;
        anyhow::ensure!(
            decoded["schema"] == WORKER_SCHEMA
                && decoded["inputId"] == id
                && decoded["sessionId"] == session,
            "Claude worker frame differs from the selected attempt"
        );
        Ok(decoded)
    }
    let mut command = Command::new(&config.worker_command[0]);
    command
        .args(&config.worker_command[1..])
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    command.as_std_mut().process_group(0);
    let mut child = command.spawn().context("Claude worker unavailable")?;
    let group = OwnedMatrixCommand(child.id().context("Missing Claude worker process")?);
    let result = tokio::time::timeout(Duration::from_secs(130), async {
        let mut input = child.stdin.take().context("Missing Claude worker input")?;
        let mut output = BufReader::new(
            child
                .stdout
                .take()
                .context("Missing Claude worker output")?,
        )
        .take(528_385);
        send(
            &mut input,
            json!({"schema":WORKER_SCHEMA,"type":"start","inputId":id,
            "sessionId":session,"text":text,"body":body}),
        )
        .await?;
        let mut frame = receive(&mut output, id, session).await?;
        if frame["type"] == "prepare_submission" {
            let committed = commit()?;
            send(
                &mut input,
                json!({"schema":WORKER_SCHEMA,"type":"submission_decision",
                "inputId":id,"sessionId":session,"committed":committed}),
            )
            .await?;
            frame = receive(&mut output, id, session).await?;
        }
        let outcome = frame["outcome"].take();
        anyhow::ensure!(
            frame["type"] == "outcome"
                && match outcome["phase"].as_str() {
                    Some("completed") =>
                        outcome["sessionId"] == session
                            && outcome["text"]
                                .as_str()
                                .is_some_and(|text| !text.trim().is_empty() && text.len() <= 65536),
                    Some("uncertain") => outcome["sessionId"] == session,
                    Some("not_submitted") => true,
                    _ => false,
                },
            "Unconfirmed Claude worker outcome"
        );
        anyhow::ensure!(
            child.wait().await?.success(),
            "Claude worker exited without a verified outcome"
        );
        Ok(outcome)
    })
    .await;
    drop(group);
    let _ = child.wait().await;
    result.context("Claude worker deadline")?
}

#[cfg(not(unix))]
async fn execute_worker(
    _config: &ClaudeForegroundConfig,
    _id: &str,
    _session: &str,
    _text: &str,
    _body: Value,
    _commit: impl FnOnce() -> Result<bool>,
) -> Result<Value> {
    bail!("Claude worker requires Unix process groups")
}
