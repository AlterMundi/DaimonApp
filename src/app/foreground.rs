//! Native worker protocol shared by the Gateway's foreground entrypoints.
use crate::store::{ClaudeContinuation, valid_claude_scope};
use crate::{
    execution::{Harness, ToolInvocation},
    interaction::ForegroundEngine,
};
use anyhow::{Context, Result};
use serde_json::{Value, json};

pub(in crate::app) struct WorkerTurn<'a> {
    pub id: &'a str,
    pub session: &'a str,
    pub resume: &'a [ClaudeContinuation],
    pub human_original: bool,
    pub native_goal_command: bool,
    pub routed_human: bool,
    pub routed_host_access: bool,
    pub session_instructions: Option<&'a str>,
    pub text: &'a str,
    pub attachments: &'a [crate::models::LocalAttachment],
    pub body: Value,
    pub cancel: &'a tokio_util::sync::CancellationToken,
    pub controller: Option<WorkerController<'a>>,
}

pub(in crate::app) struct WorkerController<'a> {
    app: &'a super::App,
    key: crate::models::SessionKey,
    human: i64,
    local_turn: i64,
    routed: bool,
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
    use std::{
        os::unix::process::CommandExt,
        process::Stdio,
        sync::atomic::{AtomicBool, Ordering},
        time::Duration,
    };
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
        let length = output.take(528_385).read_until(b'\n', &mut frame).await?;
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
        native_goal_command,
        routed_human,
        routed_host_access,
        session_instructions,
        text,
        attachments,
        body,
        cancel,
        controller,
    } = turn;
    anyhow::ensure!(
        !cancel.is_cancelled(),
        "Native worker cancelled before preparation"
    );
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
    let controller_closed = cancel.child_token();
    let lease = controller_closed.clone().drop_guard();
    let allow_long_turn =
        engine == ForegroundEngine::Claude && (human_original || routed_host_access);
    let committed_long_turn = AtomicBool::new(false);
    let deadline = tokio::time::sleep(Duration::from_secs(130));
    let exchange = async {
        let mut input = child.stdin.take().context("Missing native worker input")?;
        let mut output = BufReader::new(
            child
                .stdout
                .take()
                .context("Missing native worker output")?,
        );
        let mut start = json!({"schema":schema,"type":"start","inputId":id,
            "sessionId":session,"text":text,"body":body});
        if engine == ForegroundEngine::Claude {
            if !attachments.is_empty() {
                anyhow::ensure!(
                    human_original && !native_goal_command,
                    "Attachments require a direct human turn"
                );
                start["attachments"] = json!(
                    attachments
                        .iter()
                        .map(|file| json!({
                            "path": file.path, "name": file.file_name, "mime": file.mime_type
                        }))
                        .collect::<Vec<_>>()
                );
            }
            if let Some(instructions) = session_instructions {
                start["sessionInstructions"] = json!(instructions);
            }
            start["freshNativeSessionId"] = json!(fresh_native);
            start["resume"] = json!(resume.first());
            if resume.len() > 1 {
                start["resumeAlternates"] = json!(&resume[1..]);
            }
            start["humanOriginal"] = json!(human_original);
            if native_goal_command {
                start["nativeGoalCommand"] = json!(true);
            }
            if routed_human {
                start["routedHuman"] = json!(true);
                if routed_host_access {
                    start["routedHostAccess"] = json!(true);
                }
            }
            if controller.is_some() {
                start["controller"] = json!(true);
            }
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
                        .iter()
                        .find(|prior| prior.scope == scope)
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
                committed_long_turn.store(allow_long_turn, Ordering::Relaxed);
            }
            send(
                &mut input,
                json!({"schema":schema,"type":"submission_decision",
                "inputId":id,"sessionId":session,"committed":committed}),
            )
            .await?;
            frame = receive(&mut output, schema, id, session).await?;
        }
        let mut next_call = 1;
        while frame["type"] == "controller_call" {
            let owner = controller
                .as_ref()
                .context("Worker has no controller access")?;
            let native = native_session
                .as_ref()
                .context("Worker has no recorded execution")?;
            anyhow::ensure!(
                frame.as_object().is_some_and(|object| object.len() == 8)
                    && frame["nativeSessionId"] == *native
                    && frame["callId"].as_u64() == Some(next_call)
                    && frame["operation"]
                        .as_str()
                        .is_some_and(|name| name.len() <= 64)
                    && frame["arguments"].is_object()
                    && frame["arguments"].to_string().len() <= 15600,
                "Invalid native controller call"
            );
            let request = ToolInvocation {
                local_turn: owner.local_turn,
                harness: Harness::Claude,
                native_session: native.clone(),
                native_turn: id.to_owned(),
                tool: "interaction_controller".into(),
                namespace: None,
                arguments: json!({"operation":frame["operation"],"arguments":frame["arguments"]}),
            };
            let result = if owner.routed {
                super::session_requests::tool_call(
                    owner.app.clone(),
                    owner.key,
                    owner.human,
                    request,
                    controller_closed.clone(),
                    Some(owner.local_turn),
                )
            } else {
                super::dialogue::tool_call(
                    owner.app.clone(),
                    owner.key,
                    owner.human,
                    request,
                    controller_closed.clone(),
                )
            };
            let reply = result
                .await
                .context("Native controller result unavailable; inspect retained effects")?;
            let mut response = json!({"schema":schema,"type":"controller_reply",
                "inputId":id,"sessionId":session,"callId":next_call,
                "success":reply.success,"text":reply.text});
            // Bound the encoded line, including escaped text, to the reader's
            // frame limit. Do not convert a retained result into a turn abort.
            if serde_json::to_vec(&response)?.len() > 128 * 1024 {
                response["success"] = json!(false);
                response["text"] = json!(
                    "Controller result exceeds the worker frame. Inspect a smaller selection."
                );
            }
            send(&mut input, response).await?;
            next_call += 1;
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
                    Some("subscription_limited") =>
                        engine == ForegroundEngine::Claude
                            && outcome["sessionId"].as_str() == native_session.as_deref()
                            && native_session.is_some()
                            && outcome["limit"].is_object()
                            && outcome["workObserved"].is_boolean()
                            && outcome["terminalObserved"].is_boolean(),
                    Some("not_submitted") => true,
                    _ => false,
                },
            "Unconfirmed native worker outcome"
        );
        anyhow::ensure!(
            child.wait().await?.success(),
            "native worker exited without a verified outcome"
        );
        let mut outcome = outcome;
        if let Some(object) = outcome.as_object_mut() {
            object.remove("resumeUnavailableBody");
        }
        if outcome["reason"] == "claude_resume_session_missing"
            && let Some(unavailable) = outcome.get("resumeUnavailable")
        {
            anyhow::ensure!(
                engine == ForegroundEngine::Claude
                    && outcome["phase"] == "not_submitted"
                    && native_session.is_none()
                    && resume.iter().any(|prior| {
                        unavailable["scope"].as_str() == Some(prior.scope.as_str())
                            && unavailable["sessionId"].as_str() == Some(prior.session_id.as_str())
                    }),
                "Missing Claude history does not match a selected candidate"
            );
            outcome["resumeUnavailableBody"] = body.clone();
        }
        Ok(outcome)
    };
    let result = tokio::select! {
        biased;
        _ = cancel.cancelled() => Err(anyhow::anyhow!("Native worker cancelled")),
        _ = async {
            deadline.await;
            if committed_long_turn.load(Ordering::Relaxed) {
                std::future::pending::<()>().await;
            }
        } => Err(anyhow::anyhow!("native worker deadline")),
        result = exchange => result,
    };
    drop(lease);
    drop(group);
    let _ = child.wait().await;
    result
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

pub(super) async fn run_portable_turn(
    app: &super::App,
    request: &crate::models::TurnRequest,
    input: &crate::store::ConversationInput,
    slot: std::sync::Arc<std::sync::Mutex<Option<tokio_util::sync::CancellationToken>>>,
) -> Result<()> {
    use crate::{execution::Harness, interaction::MatrixDestination, store::MatrixAuthor};
    let target = input
        .portable
        .as_ref()
        .context("Portable destination missing")?;
    let cfg = super::routing::profile(&app.shared)?;
    let engine = match target.harness {
        Harness::Claude => ForegroundEngine::Claude,
        _ => anyhow::bail!("Selected native writer is unavailable"),
    };
    let config = cfg
        .claude_foreground
        .as_ref()
        .filter(|candidate| {
            candidate.interaction_direct && candidate.transport.source == target.body
        })
        .context("Retained Claude execution binding changed")?;
    let MatrixDestination::Body {
        being_ref,
        embodiment_id,
    } = &target.body
    else {
        anyhow::bail!("Portable execution requires an authenticated body");
    };
    let source = MatrixAuthor {
        being_ref: being_ref.clone(),
        embodiment_id: embodiment_id.clone(),
    };
    let store = &app.shared.store;
    let cancel = app.shared.shutdown.child_token();
    *slot.lock().expect("cancel mutex poisoned") = Some(cancel.clone());
    let local = store.begin_portable_turn(input, request)?;
    let observed = tokio::select! {
        biased;
        _ = cancel.cancelled() => Err(anyhow::anyhow!("Portable worker cancelled")),
        observed = super::matrix::authenticate_foreground_body(&config.transport,&source) => observed,
    };
    let outcome = async {
        let (_, body) = observed?;
        let resume = store.prior_portable_session(input, local, &body)?;
        execute_worker(
            &config.worker_command,
            engine,
            WorkerTurn {
                id: &input.id,
                session: &input.id,
                resume: resume.as_slice(),
                human_original: true,
                native_goal_command: input.paired_actor
                    && super::routing::native_claude_goal(&input.text),
                routed_human: false,
                routed_host_access: false,
                session_instructions: None,
                text: &input.text,
                attachments: &[],
                body: body.clone(),
                cancel: &cancel,
                controller: (cfg.entry() == request.session_key && cfg.human_id == input.human)
                    .then_some(WorkerController {
                        app,
                        key: request.session_key,
                        human: input.human,
                        local_turn: local,
                        routed: false,
                    }),
            },
            |prepared| {
                if cancel.is_cancelled() {
                    return Ok(false);
                }
                store.expose_portable_turn(input, local, &body, &prepared)
            },
        )
        .await
    }
    .await
    .ok();
    let deliveries = store.finish_portable_turn(input, local, &outcome.unwrap_or(Value::Null))?;
    super::routing::publish_results(app, input.human, deliveries);
    Ok(())
}

pub(super) async fn run_routed_portable(
    app: &super::App,
    request: &crate::models::TurnRequest,
    input: &crate::interaction::Instruction,
    slot: std::sync::Arc<std::sync::Mutex<Option<tokio_util::sync::CancellationToken>>>,
) -> Result<()> {
    use crate::{interaction::MatrixDestination, store::MatrixAuthor};
    let cfg = super::routing::profile(&app.shared)?;
    let selected = input
        .target_execution
        .as_ref()
        .context("Routed portable selection is missing")?;
    let body = selected
        .body
        .as_ref()
        .context("Routed portable body is missing")?;
    let (engine, config) = cfg
        .portable_route(input.target)
        .filter(|(engine, config)| {
            engine.harness() == selected.harness && &config.transport.source == body
        })
        .context("Routed portable body or harness changed")?;
    let MatrixDestination::Body {
        being_ref,
        embodiment_id,
    } = body
    else {
        anyhow::bail!("Routed worker requires an authenticated body");
    };
    let source = MatrixAuthor {
        being_ref: being_ref.clone(),
        embodiment_id: embodiment_id.clone(),
    };
    let store = &app.shared.store;
    let cancel = app.shared.shutdown.child_token();
    *slot.lock().expect("cancel mutex poisoned") = Some(cancel.clone());
    let session = store
        .get_session(request.session_key)?
        .filter(|session| session.id == input.target_session)
        .context("Selected topic session changed")?;
    let (local, routed_host_access) = store.begin_routed_portable(input, request)?;
    let human_authored = store
        .interaction_author(&input.id, input.human_id)?
        .is_none();
    let direct_original =
        human_authored && input.origin.message_id.is_some() && !super::routing::relayed(input);
    anyhow::ensure!(
        request.attachments.is_empty() || (engine == ForegroundEngine::Claude && direct_original),
        "Routed worker attachments require a direct Claude turn"
    );
    let controller = (engine == ForegroundEngine::Claude && routed_host_access && human_authored)
        .then_some(WorkerController {
            app,
            key: input.target,
            human: input.human_id,
            local_turn: local,
            routed: true,
        });

    // A new known-unsent attempt may reuse the instruction, but CREATE_ONLY
    // adapters must receive a new session coordinate for that attempt.
    let attempt = uuid::Uuid::new_v4().to_string();
    let outcome = async {
        let (_,body) = tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(anyhow::anyhow!("Routed worker cancelled")),
            result = super::matrix::authenticate_foreground_body(&config.transport,&source) => result,
        }?;
        let resume = if engine==ForegroundEngine::Claude {
            store.routed_claude_continuations(local,&body)?
        } else {Vec::new()};
        execute_worker(&config.worker_command,engine,WorkerTurn{
            id:&input.id,session:&attempt,resume:&resume,human_original:direct_original,
            native_goal_command:engine==ForegroundEngine::Claude && direct_original
                && routed_host_access && request.attachments.is_empty()
                && super::routing::native_claude_goal(&request.prompt),
            routed_human:!direct_original,routed_host_access:routed_host_access && !direct_original,
            session_instructions:session.session_prompt.as_deref(),
            text:&request.prompt,attachments:&request.attachments,body:body.clone(),cancel:&cancel,controller,
        },|prepared| {
            if cancel.is_cancelled() {return Ok(false);}
            if engine == ForegroundEngine::Claude && !store.get_session(request.session_key)?
                .is_some_and(|current| current.id == session.id && current.session_prompt == session.session_prompt)
            {
                return Ok(false);
            }
            store.expose_routed_portable(input,local,&body,&prepared,routed_host_access)
        }).await
    }.await.unwrap_or(Value::Null);
    let deliveries = store.finish_routed_portable(input, local, &outcome)?;
    if input.origin.message_id.is_some()
        && let Some(limit) = store
            .interaction_instruction(&input.id, input.human_id)?
            .and_then(|instruction| instruction.subscription_limit)
    {
        super::routing::notice(app.shared.clone(), input.origin.clone(), limit.message());
    }
    super::routing::publish_results(app, input.human_id, deliveries);
    Ok(())
}
