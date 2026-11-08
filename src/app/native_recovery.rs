//! Bounded native observation and exact already-admitted writer collection.
//! No new input, kickoff, goal mutation, peer attention or service restart.
use super::*;

/// Finite continuation after this entry's writer releases its slot. Reuse the
/// existing exact-current-turn attachment; no kickoff, goal mutation or replay.
pub(super) fn attach_foreground(
    app: &App,
    human: i64,
    key: SessionKey,
) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + '_>> {
    Box::pin(async move {
        if !app.shared.config.codex.shared_app_server
            || !app
                .shared
                .config
                .interaction
                .as_ref()
                .is_some_and(|c| c.human_id == human && c.entry() == key)
            || app.shared.store.native_writer_held(key)?
        {
            return Ok(());
        }
        if app
            .workers
            .lock()
            .await
            .get(&key)
            .is_some_and(|w| w.cancel.lock().expect("cancel mutex poisoned").is_some())
        {
            return Ok(());
        }
        if let Some((native, physical)) =
            app.shared.store.native_foreground_attachment(human, key)?
        {
            let args = format!("{} {} {} {}", key.chat_id, key.thread_id, native, physical);
            super::goals::attach_active(app, human, &args).await?;
        }
        Ok(())
    })
}

pub(super) async fn tick(app: &App) -> Result<()> {
    let mut seen = std::collections::HashSet::new();
    let mut selected = Vec::new();
    for _ in 0..4 {
        let Some(row) = app.shared.store.native_collection_next()? else {
            break;
        };
        if !seen.insert(row.local) {
            break;
        }
        if !app.shared.store.native_writer_held(row.key)? {
            selected.push(row);
        }
    }
    let outcomes =
        futures_util::future::join_all(selected.into_iter().map(|selected| async move {
            let exact=app.shared.store.workflow_native_collection(selected.local)?;
            if exact.as_ref().is_some_and(|v|!v.live) {return Ok(());}
            if exact.is_none() {
                let handle=app.workers.lock().await.get(&selected.key).cloned();
                let active=handle.and_then(|w|w.steer.lock().expect("steer mutex poisoned").clone());
                if let Some(active)=active.filter(|a|a.turn_id==selected.local)
                    && let Some(raw)=app.shared.store.bot_state_value(&format!("collector_attachment:{}",selected.local))?
                {
                    let receipt:Value=serde_json::from_str(&raw)?;
                    if receipt["native_thread"]==selected.native
                        && let Some(physical)=receipt["native_turn"].as_str()
                        && let Some(observation)=app.shared.codex.terminal_observation(&selected.native,physical).await?
                    {
                        let (response,received)=oneshot::channel();
                        if active.sender.send(CodexSteerRequest{tool_output:None,observation:Some(observation),images:vec![],text:String::new(),client_message_id:None,goal:None,admission_check:None,response}).is_ok()
                            && matches!(tokio::time::timeout(std::time::Duration::from_secs(2),received).await,Ok(Ok(Ok(_)))) {
                            // Only lifecycle was reconciled. Full output and its
                            // collection checkpoint remain retained and unread.
                            return Ok(());
                        }
                    }
                }
            }
            let history=if let Some(exact)=&exact {
                if app.shared.config.telegram.enabled && app.shared.config.interaction.as_ref().is_some_and(|c|c.human_id==selected.human && c.entry()==selected.key && c.telegram_projection) {
                    app.shared.store.topic_projection_register(selected.local,selected.human,selected.key)?;
                }
                app.shared.codex.workflow_return_history(&selected.native,&exact.physical).await.map(|turn|(vec![turn],false))
            } else {app.shared.codex.recovery_history(
                    &selected.native,
                    &selected.anchor,
                    selected.client_id.as_deref(),
                )
                .await};
            match history {
                Ok((turns, goal_active)) => {
                    let observed = app.shared.store.native_collection_observed(
                        &selected,
                        &turns,
                        goal_active,
                    ).inspect_err(|_| {let _=app.shared.store.native_collection_failed(selected.local);})?;
                    super::topic_publications::wake(app.shared.clone(), selected.key);
                    if let Some(turn) = observed.as_ref().filter(|t| exact.is_none() && {
                        matches!(
                            t["status"].as_str(),
                            Some("completed" | "failed" | "interrupted")
                        )
                    }) {
                        if turn["status"] == "failed"
                            && let (Some(native_turn), Some(error)) = (turn["id"].as_str(), turn.get("error").filter(|v|v.is_object()))
                            && app.shared.store.goal_recovery_failure_observed(selected.key,selected.human,&selected.native,native_turn,error).is_err() {
                            tracing::warn!("Recovered terminal failure evidence could not be retained; no retry authorized");
                        }
                        let handle = app.workers.lock().await.get(&selected.key).cloned();
                        let active = handle
                            .and_then(|w| w.steer.lock().expect("steer mutex poisoned").clone());
                        if let Some(active) = active.filter(|a| a.turn_id == selected.local) {
                            let text = turn["items"]
                                .as_array()
                                .and_then(|items| {
                                    items.iter().rev().find(|i| {
                                        i["type"] == "agentMessage" && i["phase"] == "final_answer"
                                    })
                                })
                                .and_then(|i| i["text"].as_str())
                                .map(str::to_owned);
                            let (response, _) = oneshot::channel();
                            let _ = active.sender.send(CodexSteerRequest {
                tool_output: None,
                                observation: Some(crate::codex::NativeTerminalObservation {
                                    turn_id: turn["id"]
                                        .as_str()
                                        .context("Native observation identity missing")?
                                        .into(),
                                    status: turn["status"]
                                        .as_str()
                                        .context("Native observation status missing")?
                                        .into(),
                                    goal_active,
                                    assistant_text: text,
                                }),
                                images: vec![],
                                text: String::new(),
                                client_message_id: None,
                                goal: None,
                                admission_check: None,
                                response,
                            });
                        }
                    }
                    if exact.is_some() && observed.as_ref().is_some_and(|t|t["status"]=="inProgress") {
                        // Existing heartbeat fallback after process replacement.
                        // Only foreground context receipts can select attachment.
                        attach_foreground(app,selected.human,selected.key).await?;
                    }
                    if let Some(turn) = observed.as_ref().filter(|t| exact.is_none() && t["status"] == "inProgress") {
                        let physical = turn["id"]
                            .as_str()
                            .context("Native active identity missing")?;
                        let active = app
                            .workers
                            .lock()
                            .await
                            .get(&selected.key)
                            .is_some_and(|w| {
                                w.cancel.lock().expect("cancel mutex poisoned").is_some()
                            });
                        if !active {
                            let args = format!(
                                "{} {} {} {}",
                                selected.key.chat_id,
                                selected.key.thread_id,
                                selected.native,
                                physical
                            );
                            // Existing attach-active verifies the writer again and
                            // cannot kick off a turn or mutate/resume a native goal.
                            super::goals::attach_active(app, selected.human, &args).await?;
                        }
                    }
                }
                Err(error) => {
                    app.shared.store.native_collection_failed(selected.local)?;
                    return Err(error);
                }
            }
            Ok(())
        }))
        .await;
    for result in outcomes {
        result?;
    }
    Ok(())
}
