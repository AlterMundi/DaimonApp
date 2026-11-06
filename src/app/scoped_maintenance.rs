//! Owner-only finite maintenance. No turn credential, interrupt, global Stop or lifecycle control.
use super::*;
use crate::{codex::NativeGoalSnapshot, store::MaintenancePlan};
use serde_json::{Value, json};

pub(super) async fn command(app: &App, human: i64, args: &str) -> Result<Value> {
    if let Some(raw) = args.strip_prefix("prepare ") {
        let plan: MaintenancePlan = serde_json::from_str(raw)?;
        if plan.targets.is_empty() || plan.targets.len() > 4 || raw.len() > 131072 {
            bail!("Bounded maintenance plan required before native observation");
        }
        if !app.shared.config.codex.shared_app_server {
            bail!("Shared native conditional goal controls required");
        }
        if app
            .shared
            .store
            .maintenance_read(human, &plan.request_id)
            .is_ok()
        {
            return app.shared.store.maintenance_prepare(human, &plan);
        }
        // Read actual native snapshots before retaining any restoration authority.
        for target in &plan.targets {
            let native = target.binding["entry_binding"][3]
                .as_str()
                .context("Native target missing")?;
            app.shared
                .store
                .validate_owned_binding(target.target, human, native)?;
            let current = app.shared.codex.get_goal_snapshot(native).await?;
            if current != target.snapshot {
                bail!("Native snapshot/accounting changed after observation; inspect again");
            }
        }
        return app.shared.store.maintenance_prepare(human, &plan);
    }
    let (action, id) = args
        .split_once(' ')
        .context("Expected maintenance prepare JSON | status/pause/restore UUID")?;
    let doc = app.shared.store.maintenance_read(human, id)?;
    match action {
        "status" => Ok(doc),
        "pause" => {
            if !app.shared.store.maintenance_arm(human, id)? {
                return app.shared.store.maintenance_read(human, id);
            }
            // Install one finite backend continuation before the first pause. It
            // survives the command caller; restart recovery restores immediately.
            let owned = app.clone();
            let selected = id.to_owned();
            let deadline = doc["plan"]["deadline"]
                .as_i64()
                .context("Deadline missing")?;
            let count = doc["targets"].as_array().map_or(4, |v| v.len()) as i64;
            tokio::spawn(async move {
                let wait = (deadline - (40 * count + 10) - Utc::now().timestamp()).max(0) as u64;
                tokio::select! {_=sleep(Duration::from_secs(wait))=>{},_=owned.shared.shutdown.cancelled()=>return}
                if restore(&owned, human, &selected).await.is_err() {
                    tracing::warn!(
                        "Scoped restoration needs owner inspection; no uncertain write replayed"
                    );
                }
            });
            for i in 0..doc["targets"].as_array().context("Targets missing")?.len() {
                if pause_one(app, human, id, i).await.is_err() {
                    // A known failure cannot strand previously acknowledged pauses.
                    let _ = restore(app, human, id).await;
                    break;
                }
            }
            app.shared.store.maintenance_read(human, id)
        }
        "restore" => {
            restore(app, human, id).await?;
            app.shared.store.maintenance_read(human, id)
        }
        _ => bail!("Unsupported scoped maintenance action"),
    }
}
async fn pause_one(app: &App, human: i64, id: &str, index: usize) -> Result<()> {
    let doc = app.shared.store.maintenance_read(human, id)?;
    if doc["targets"][index]["phase"] != "prepared" {
        return Ok(());
    }
    app.shared.store.maintenance_transition(
        human,
        id,
        index,
        &doc,
        "pause_submitted",
        json!({"native_write_may_start":true,"automatic_retry":false}),
    )?;
    let expected: NativeGoalSnapshot =
        serde_json::from_value(doc["targets"][index]["snapshot"].clone())?;
    let result = mutate(
        app,
        human,
        id,
        index,
        "pause_submitted",
        &expected,
        "paused",
    )
    .await;
    let current = app.shared.store.maintenance_read(human, id)?;
    let receipt = json!({"phase":result.0,"receipt":result.1});
    let acknowledged = result.0 == "acknowledged";
    app.shared.store.maintenance_transition(
        human,
        id,
        index,
        &current,
        if acknowledged {
            "paused"
        } else if result.0 == "known_unsent" {
            "not_paused"
        } else {
            "pause_unconfirmed"
        },
        receipt,
    )?;
    if !acknowledged {
        bail!("Pause not confirmed; no inference or automatic replay");
    }
    Ok(())
}
async fn mutate(
    app: &App,
    human: i64,
    id: &str,
    index: usize,
    phase: &str,
    expected: &NativeGoalSnapshot,
    status: &str,
) -> (String, Value) {
    let shared = app.shared.clone();
    let selected = id.to_owned();
    let owned_phase = phase.to_owned();
    let admission: crate::codex::SteerAdmissionCheck = Arc::new(move || {
        shared
            .store
            .maintenance_admission(human, &selected, index, &owned_phase)
    });
    if status != "paused" {
        return (
            "known_unsent".into(),
            json!({"error":"Resume requires the existing context-aware collector","automatic_retry":false}),
        );
    }
    let plan = crate::store::GoalPlan {
        action: crate::store::GoalAction::Pause,
        expected: expected.clone(),
        objective: None,
        token_budget: None,
        followup: None,
    };
    let native = expected
        .goal
        .as_ref()
        .map(|g| g.thread_id.as_str())
        .unwrap_or("");
    let observed = app.shared.store.maintenance_read(human, id);
    let session = observed.and_then(|doc| {
        let target: SessionKey = serde_json::from_value(doc["targets"][index]["target"].clone())?;
        app.shared
            .store
            .get_session(target)?
            .context("Selected session unavailable")
    });
    let session = match session {
        Ok(s) => s,
        Err(e) => {
            return (
                "known_unsent".into(),
                json!({"error":e.to_string(),"automatic_retry":false}),
            );
        }
    };
    let receipt = Arc::new(StdMutex::new(None));
    let control = crate::codex::GoalControl::ConditionalMetadata(Box::new(
        crate::codex::GoalMetadataControl {
            origin: crate::codex::GoalMutationOrigin::Automatic,
            plan: plan.clone(),
            admission: admission.clone(),
            receipt: receipt.clone(),
            context: None,
            scope: None,
            settled: None,
        },
    ));
    match super::goals::control_live(app, &session, control).await {
        Ok(true) => receipt
            .lock()
            .expect("receipt mutex poisoned")
            .clone()
            .unwrap_or_else(|| {
                (
                    "uncertain".into(),
                    json!({"error":"Matched pause receipt unavailable","automatic_retry":false}),
                )
            }),
        Ok(false) => {
            if app
                .workers
                .lock()
                .await
                .get(&session.key)
                .is_some_and(|w| w.cancel.lock().expect("cancel mutex poisoned").is_some())
            {
                (
                    "known_unsent".into(),
                    json!({"error":"Selected writer preparing; no independent mutation submitted","automatic_retry":false}),
                )
            } else {
                app.shared
                    .codex
                    .conditional_goal_metadata(
                        native,
                        &plan,
                        &admission,
                        crate::codex::GoalMutationOrigin::Automatic,
                    )
                    .await
            }
        }
        Err(_) => (
            "uncertain".into(),
            json!({"error":"Owning writer acknowledgment unavailable","automatic_retry":false}),
        ),
    }
}
async fn restore_collector(
    app: &App,
    human: i64,
    id: &str,
    index: usize,
    expected: &NativeGoalSnapshot,
) -> Result<()> {
    let doc = app.shared.store.maintenance_read(human, id)?;
    let target: SessionKey = serde_json::from_value(doc["targets"][index]["target"].clone())?;
    let native = expected
        .goal
        .as_ref()
        .context("Owned pause identity missing")?
        .thread_id
        .clone();
    let shared = app.shared.clone();
    let selected = id.to_owned();
    let admission: crate::codex::SteerAdmissionCheck = Arc::new(move || {
        shared
            .store
            .maintenance_admission(human, &selected, index, "restore_submitted")
    });
    let shared = app.shared.clone();
    let selected = id.to_owned();
    let settled = Arc::new(move |phase: &str, receipt: &Value| {
        let current = shared.store.maintenance_read(human, &selected)?;
        if current["targets"][index]["phase"] != "restore_submitted" {
            bail!("Restoration receipt no longer owns this transaction phase");
        }
        shared.store.maintenance_transition(
            human,
            &selected,
            index,
            &current,
            if phase == "acknowledged" {
                "restored"
            } else {
                "restore_unconfirmed"
            },
            json!({"phase":phase,"receipt":receipt,"notification_delivered":false}),
        )?;
        Ok(())
    });
    let receipt = Arc::new(StdMutex::new(None));
    let mut control = crate::codex::GoalMetadataControl {
        origin: crate::codex::GoalMutationOrigin::Automatic,
        plan: crate::store::GoalPlan {
            action: crate::store::GoalAction::Resume,
            expected: expected.clone(),
            objective: None,
            token_budget: None,
            followup: None,
        },
        admission,
        receipt: receipt.clone(),
        context: None,
        scope: None,
        settled: Some(settled.clone()),
    };
    let attached = app
        .workers
        .lock()
        .await
        .get(&target)
        .and_then(|w| w.steer.lock().expect("steer mutex poisoned").clone());
    let activation = |control| crate::codex::GoalActivation {
        intent: id.into(),
        native_thread: Some(native.clone()),
        expected: expected.goal.clone(),
        objective: None,
        replace: false,
        attach_turn: None,
        conditional: Some(Box::new(control)),
    };
    if let Some(attached) = attached {
        if let Some(hint) = attached.controller_hint {
            control.context =
                Some(json!({"telecodex.controller":{"kind":"application","value":hint}}));
            let (response, ack) = oneshot::channel();
            if attached
                .sender
                .send(crate::codex::CodexSteerRequest {
                    tool_output: None,
                    observation: None,
                    images: vec![],
                    admission_check: None,
                    client_message_id: None,
                    text: String::new(),
                    goal: Some(crate::codex::GoalControl::Activate(Box::new(activation(
                        control,
                    )))),
                    response,
                })
                .is_err()
            {
                settled(
                    "known_unsent",
                    &json!({"error":"Collector closed before restoration admission","automatic_retry":false}),
                )?;
            } else {
                // Settlement belongs to the selected collector, not this wait.
                let _ = tokio::time::timeout(Duration::from_secs(18), ack).await;
            }
        } else {
            settled(
                "known_unsent",
                &json!({"error":"Fresh invocation lease unavailable","automatic_retry":false}),
            )?;
        }
    } else if app
        .workers
        .lock()
        .await
        .get(&target)
        .is_some_and(|w| w.cancel.lock().expect("cancel mutex poisoned").is_some())
    {
        settled(
            "known_unsent",
            &json!({"error":"Selected writer preparing; no independent resume submitted","automatic_retry":false}),
        )?;
    } else {
        // The existing collector constructs fresh invocation context and sends
        // conditionalActivate. This bookkeeping prompt is never a human input.
        app.enqueue_goal_turn(TurnRequest{session_key:target,from_user_id:human,prompt:"Restore the same explicitly authorized native goal after scoped maintenance; preserve its history and accounting.".into(),runtime_instructions:None,attachments:vec![],review_mode:None,override_search_mode:None},if target.chat_id<0{"supergroup"}else{"private"},Some(activation(control))).await?;
        let until = Instant::now() + Duration::from_secs(22);
        while Instant::now() < until && receipt.lock().expect("receipt mutex poisoned").is_none() {
            tokio::select! {_=sleep(Duration::from_millis(50))=>{},_=app.shared.shutdown.cancelled()=>break}
        }
    }
    Ok(())
}
pub(super) async fn restore(app: &App, human: i64, id: &str) -> Result<()> {
    let initial = app.shared.store.maintenance_read(human, id)?;
    for i in 0..initial["targets"]
        .as_array()
        .context("Targets missing")?
        .len()
    {
        let doc = app.shared.store.maintenance_read(human, id)?;
        let target = &doc["targets"][i];
        match target["phase"].as_str() {
            Some("prepared") => {
                app.shared.store.maintenance_transition(
                    human,
                    id,
                    i,
                    &doc,
                    "not_paused",
                    json!({"native_mutation":false}),
                )?;
            }
            Some("pause_submitted" | "restore_submitted") => {
                // Only startup uses this while no old command can still run.
                // Concurrent owner calls leave an in-flight write alone.
            }
            Some("paused") => {
                let paused: NativeGoalSnapshot = serde_json::from_value(
                    target["paused_receipt"]["receipt"]["native_receipt"].clone(),
                )?;
                let native = paused
                    .goal
                    .as_ref()
                    .context("Acknowledged pause identity missing")?
                    .thread_id
                    .clone();
                let observed = app.shared.codex.get_goal_snapshot(&native).await;
                let valid = observed.as_ref().is_ok_and(|s| {
                    s.revision == paused.revision
                        && crate::codex::goal_definitions_match(
                            s.goal.as_ref(),
                            paused.goal.as_ref(),
                        )
                });
                if !valid {
                    app.shared.store.maintenance_transition(human,id,i,&doc,if observed.is_ok(){"superseded"}else{"restore_unconfirmed"},json!({"native_mutation":false,"reason":"Native observation unavailable or goal changed; retained pause is not reusable authority"}))?;
                    continue;
                }
                let expected = observed?;
                app.shared.store.maintenance_transition(
                    human,
                    id,
                    i,
                    &doc,
                    "restore_submitted",
                    json!({"native_write_may_start":true,"automatic_retry":false,"admit_until":Utc::now().timestamp()+20}),
                )?;
                restore_collector(app, human, id, i, &expected).await?;
            }
            _ => {}
        }
    }
    Ok(())
}
/// Reconcile interrupted submission markers before accepting owner commands.
/// This synchronous pass cannot mistake a new post-startup attempt for a crash.
pub(super) fn reconcile_startup(app: &App) -> Result<Vec<(i64, String)>> {
    let pending = app.shared.store.maintenance_pending()?;
    for (human, id) in &pending {
        let initial = app.shared.store.maintenance_read(*human, id)?;
        for i in 0..initial["targets"]
            .as_array()
            .context("Targets missing")?
            .len()
        {
            let doc = app.shared.store.maintenance_read(*human, id)?;
            if matches!(
                doc["targets"][i]["phase"].as_str(),
                Some("pause_submitted" | "restore_submitted")
            ) {
                app.shared.store.maintenance_transition(*human,id,i,&doc,"restart_unconfirmed",json!({"automatic_retry":false,"reason":"Backend ended after durable submission marker; native effect may have happened"}))?;
            }
        }
    }
    Ok(pending)
}
/// One bounded recovery pass after the owner socket is available, so restored
/// native work receives a usable fresh controller instead of an expired lease.
pub(super) async fn recover(app: App, pending: Vec<(i64, String)>) -> Result<()> {
    let mut failed = false;
    for (human, id) in pending {
        if restore(&app, human, &id).await.is_err() {
            failed = true;
        }
    }
    if failed {
        bail!("Scoped restoration needs owner inspection; no uncertain write replayed");
    }
    Ok(())
}
