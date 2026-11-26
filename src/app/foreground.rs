//! Native worker protocol shared by the Gateway's foreground entrypoints.
use crate::interaction::ForegroundEngine;
use crate::store::{ClaudeContinuation, valid_claude_scope};
use anyhow::{Context, Result};
use serde_json::{Value, json};

pub(in crate::app) struct WorkerTurn<'a> {
    pub id: &'a str,
    pub session: &'a str,
    pub resume: Option<&'a ClaudeContinuation>,
    pub human_original: bool,
    pub text: &'a str,
    pub body: Value,
}

#[cfg(unix)]
pub(super) struct OwnedProcessGroup(pub(super) u32);
#[cfg(unix)]
impl Drop for OwnedProcessGroup {
    fn drop(&mut self) {
        // Only the process group created for this configured child.
        unsafe {
            libc::kill(-(self.0 as i32), libc::SIGKILL);
        }
    }
}

#[cfg(unix)]
pub(in crate::app) async fn execute_worker(
    command: &[String],
    engine: ForegroundEngine,
    turn: WorkerTurn<'_>,
    commit: impl FnOnce(Value) -> Result<bool>,
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
        schema: &str,
        id: &str,
        session: &str,
    ) -> Result<Value> {
        let mut frame = Vec::new();
        let length = output.read_until(b'\n', &mut frame).await?;
        anyhow::ensure!(
            length > 0 && frame.last() == Some(&b'\n'),
            "Unconfirmed native worker frame"
        );
        let decoded: Value = serde_json::from_slice(&frame)?;
        anyhow::ensure!(
            decoded["schema"] == schema
                && decoded["inputId"] == id
                && decoded["sessionId"] == session,
            "native worker frame differs from the selected attempt"
        );
        Ok(decoded)
    }
    let schema = match engine {
        ForegroundEngine::Claude => "daimon-gateway.claude-turn/v2",
        ForegroundEngine::Goose => "daimon-gateway.goose-turn/v1",
        ForegroundEngine::Antigravity => "daimon-gateway.antigravity-turn/v1",
    };
    let WorkerTurn {
        id,
        session,
        resume,
        human_original,
        text,
        body,
    } = turn;
    let fresh_native = uuid::Uuid::new_v4().to_string();
    let mut child_command = Command::new(&command[0]);
    child_command
        .args(&command[1..])
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    child_command.as_std_mut().process_group(0);
    let mut child = child_command.spawn().context("native worker unavailable")?;
    let group = OwnedProcessGroup(child.id().context("Missing native worker process")?);
    let result = tokio::time::timeout(Duration::from_secs(130), async {
        let mut input = child.stdin.take().context("Missing native worker input")?;
        let mut output = BufReader::new(
            child
                .stdout
                .take()
                .context("Missing native worker output")?,
        )
        .take(528_385);
        let mut start = json!({"schema":schema,"type":"start","inputId":id,
            "sessionId":session,"text":text,"body":body});
        if engine == ForegroundEngine::Claude {
            start["freshNativeSessionId"] = json!(fresh_native);
            start["resume"] = json!(resume);
            start["humanOriginal"] = json!(human_original);
        }
        send(&mut input, start).await?;
        let mut frame = receive(&mut output, schema, id, session).await?;
        let mut native_session = None;
        if frame["type"] == "prepare_submission" {
            let observed = frame.get("nativeSessionId");
            let selected = match engine {
                ForegroundEngine::Claude => {
                    let scope = frame["sessionScope"]
                        .as_str()
                        .filter(|value| valid_claude_scope(value))
                        .context("Claude preparation omitted its authorization scope")?;
                    let expected = resume
                        .filter(|prior| prior.scope == scope)
                        .map_or(fresh_native.as_str(), |prior| prior.session_id.as_str());
                    anyhow::ensure!(
                        observed.and_then(Value::as_str) == Some(expected),
                        "Claude preparation returned another native session"
                    );
                    expected
                }
                ForegroundEngine::Goose => observed
                    .and_then(Value::as_str)
                    .context("Goose preparation omitted its native session")?,
                ForegroundEngine::Antigravity
                    if observed.and_then(Value::as_str) == Some(session) =>
                {
                    session
                }
                ForegroundEngine::Antigravity => {
                    anyhow::bail!(
                        "Antigravity preparation did not attest the selected native session"
                    )
                }
            };
            let mut prepared = json!({"native_session_id":selected});
            if engine == ForegroundEngine::Claude {
                prepared["native_session_scope"] = frame["sessionScope"].clone();
            }
            let committed = commit(prepared)?;
            if committed {
                native_session = Some(selected.to_owned());
            }
            send(
                &mut input,
                json!({"schema":schema,"type":"submission_decision",
                "inputId":id,"sessionId":session,"committed":committed}),
            )
            .await?;
            frame = receive(&mut output, schema, id, session).await?;
        }
        let outcome = frame["outcome"].take();
        anyhow::ensure!(
            frame["type"] == "outcome"
                && match outcome["phase"].as_str() {
                    Some("completed") =>
                        outcome["sessionId"].as_str() == native_session.as_deref()
                            && native_session.is_some()
                            && outcome["text"]
                                .as_str()
                                .is_some_and(|text| !text.trim().is_empty() && text.len() <= 65536),
                    Some("uncertain") =>
                        outcome["sessionId"].as_str() == native_session.as_deref()
                            && native_session.is_some(),
                    Some("not_submitted") => true,
                    _ => false,
                },
            "Unconfirmed native worker outcome"
        );
        anyhow::ensure!(
            child.wait().await?.success(),
            "native worker exited without a verified outcome"
        );
        Ok(outcome)
    })
    .await;
    drop(group);
    let _ = child.wait().await;
    result.context("native worker deadline")?
}

#[cfg(not(unix))]
pub(in crate::app) async fn execute_worker(
    _command: &[String],
    _engine: ForegroundEngine,
    _turn: WorkerTurn<'_>,
    _commit: impl FnOnce(Value) -> Result<bool>,
) -> Result<Value> {
    anyhow::bail!("native worker requires Unix process groups")
}

pub(super) async fn run_direct_claude(
    app: &super::App,
    config: &crate::interaction::ForegroundConfig,
    input: &crate::store::ConversationInput,
) -> Result<()> {
    use crate::{interaction::MatrixDestination, store::MatrixAuthor};
    let store = &app.shared.store;
    let result = tokio::select! {
        biased;
        _ = app.shared.shutdown.cancelled() => Err(anyhow::anyhow!("Gateway is shutting down")),
        value = async {
            let selected = &config.transport.source;
            let MatrixDestination::Body { being_ref, embodiment_id } = selected else {
                anyhow::bail!("Claude requires a configured receiving body")
            };
            let source = MatrixAuthor { being_ref: being_ref.clone(), embodiment_id: embodiment_id.clone() };
            let (observed, body) = super::matrix::authenticate_foreground_body(&config.transport, &source).await?;
            let resume = store.conversation_claude_prior(input, selected, &observed)?;
            execute_worker(&config.worker_command, ForegroundEngine::Claude, WorkerTurn {
                id: &input.id, session: &input.id, resume: resume.as_ref(),
                human_original: true, text: &input.text, body,
            }, |prepared| store.conversation_claude_expose(input, selected, &observed, &prepared)).await
        } => value,
    };
    let reply = result
        .as_ref()
        .ok()
        .filter(|outcome| outcome["phase"] == "completed")
        .and_then(|outcome| outcome["text"].as_str());
    let resume_unavailable = result.as_ref().is_ok_and(|outcome| {
        outcome["phase"] == "not_submitted" && outcome["reason"] == "claude_resume_session_missing"
    });
    store.conversation_claude_finish(input, reply, resume_unavailable)
}
