//! Authenticated conversation ingress into the existing native worker and steer.
use super::*;
use crate::store::{ConversationInput, ConversationInputEvent as E};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Submit {
    binding: String,
    id: String,
    text: String,
    #[serde(default)]
    visual: Option<crate::visual::VisualSelection>,
    #[serde(default)]
    files: Vec<crate::files::FileReference>,
    #[serde(default)]
    reply: Option<crate::store::ConversationReply>,
    #[serde(default)]
    playback: Option<crate::store::ConversationPlayback>,
}

fn outcome(input: &ConversationInput, fresh: bool) -> Value {
    let mut value = json!({"schema":"telecodex.conversation-input/v1","id":input.id,"phase":input.phase,"local_turn":input.local_turn,
        "new_input":fresh,"retired":input.retired,"text":input.text,"files":input.files,"visual":input.visual,"voice":input.voice,"routing":input.routing,"playback":input.playback,"capture_questions":input.capture_questions,
        "entry_binding":[input.human,input.entry,input.session,input.native],"native_acceptance":if input.foreground_dialogue.is_some() && input.foreground_delegation.is_none() {"not_requested"}else if input.phase=="accepted" {"observed"}else{"unconfirmed"},
        "incorporation":"Not established by input retention or native acceptance"});
    if let Some(dialogue) = &input.foreground_dialogue {
        value["foreground_dialogue"] = json!(dialogue);
        value["foreground_delegation"] = json!(input.foreground_delegation);
    }
    value
}

fn response(app: &App, input: &ConversationInput, fresh: bool) -> Result<Value> {
    let mut value = outcome(input, fresh);
    value["clarifiable"] = json!(
        input.phase == "awaiting_target"
            && app
                .shared
                .store
                .conversation_input_can_clarify(input.human, &input.id)?
    );
    if value["clarifiable"] == true {
        value["routing_choices"] = choices(app)?;
        value["binding"] = app
            .shared
            .store
            .conversation_request_binding(input.human, input.entry)?["binding"]
            .clone();
    }
    if input.phase == "answered" {
        if let Some(doc) =
            app.shared
                .store
                .conversation_answer_receipt(input.human, input.entry, &input.id)?
        {
            value["decision"] = json!({"id":doc["id"],"revision":doc["revision"],"recorded":true,"source_input":input.id,"recorded_at":doc["recorded_at"],"native_incorporation":"Not established by recording an answer"});
        }
    }
    decorate_recovery(app, input.human, input.entry, &input.id, &mut value)?;
    value["continuation"] = json!(app.shared.store.conversation_continuation(
        input.human,
        input.entry,
        &input.id
    )?);
    if input
        .routing
        .as_ref()
        .is_some_and(|r| r.phase == "accepted")
    {
        value["native_acceptance"] = json!("observed");
    }
    Ok(value)
}
fn decorate_recovery(
    app: &App,
    human: i64,
    entry: SessionKey,
    id: &str,
    value: &mut Value,
) -> Result<()> {
    let recoveries=app.shared.store.conversation_recoverable_routes(human,entry,id)?.into_iter()
        .filter(|i|super::routing::instruction_available(&app.shared,i))
        .map(|i|json!({"instruction":i.id,"label":super::routing::label(&app.shared,i.target),"target":i.target})).collect::<Vec<_>>();
    if !recoveries.is_empty() {
        value["binding"] = app
            .shared
            .store
            .conversation_request_binding(human, entry)?["binding"]
            .clone();
    }
    value["recoveries"] = json!(recoveries);
    Ok(())
}
fn choices(app: &App) -> Result<Value> {
    let profile = super::routing::profile(&app.shared)?;
    Ok(json!(
        profile
            .targets
            .iter()
            .map(|t| json!({"selector":format!("t{}",t.topic_id),"label":t.name}))
            .collect::<Vec<_>>()
    ))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Resolve {
    binding: String,
    id: String,
    selector: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Recover {
    binding: String,
    id: String,
    instruction: String,
}

pub(super) async fn command(app: &App, human: i64, args: &str) -> Result<Value> {
    let cfg = app
        .shared
        .config
        .interaction
        .as_ref()
        .context("Missing integrating entry")?;
    if cfg.human_id != human {
        bail!("Conversation input owner mismatch");
    }
    if let Some(body) = args.strip_prefix("voice native attach ") {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Selected {
            binding: String,
            native_thread: String,
            native_turn: String,
        }
        let selected: Selected = serde_json::from_str(body)?;
        if !app.shared.config.codex.shared_app_server
            || selected.native_thread.len() > 128
            || selected.native_turn.is_empty()
            || selected.native_turn.len() > 128
            || selected.native_turn.chars().any(char::is_whitespace)
        {
            bail!("Select one existing native voice writer");
        }
        let current = app
            .shared
            .store
            .conversation_request_binding(human, cfg.entry())?;
        if current["binding"] != selected.binding
            || current["entry_binding"][3] != selected.native_thread
        {
            bail!("Native voice entry changed");
        }
        app.shared
            .store
            .validate_owned_binding(cfg.entry(), human, &selected.native_thread)?;
        if app.shared.store.stop_fenced(cfg.entry())?
            || app.shared.store.maintenance_writer_held(cfg.entry())?
        {
            bail!("Native voice collection cannot release a writer hold");
        }
        if app
            .shared
            .codex
            .live_native_turn(&selected.native_thread)
            .await?
            .as_deref()
            != Some(selected.native_turn.as_str())
        {
            return Ok(
                json!({"binding":current["binding"],"entry_binding":current["entry_binding"],"state":"not_current","native_turn":selected.native_turn,
                "meaning":"Writer changed or completed; no input or replacement was started"}),
            );
        }
        let worker = app.workers.lock().await.get(&cfg.entry()).cloned();
        if let Some(worker) =
            worker.filter(|w| w.cancel.lock().expect("cancel mutex poisoned").is_some())
        {
            let local = worker
                .steer
                .lock()
                .expect("steer mutex poisoned")
                .as_ref()
                .map(|s| s.turn_id);
            let collecting = local.and_then(|local| {
                super::controller::collecting_native_turn(&app.shared, human, cfg.entry(), local)
            });
            return Ok(
                json!({"binding":current["binding"],"entry_binding":current["entry_binding"],"state":if collecting.as_deref()==Some(selected.native_turn.as_str()) {"collecting"}else{"pending"},
                "native_turn":selected.native_turn,
                "meaning":"Existing collector observation only; no duplicate worker or input"}),
            );
        }
        // Reuse the exact-current writer attachment. It never kicks off work,
        // alters a goal or replays the voice delegation already admitted by Core.
        let mut result = super::goals::attach_active(
            app,
            human,
            &format!(
                "{} {} {} {}",
                cfg.chat_id, cfg.topic_id, selected.native_thread, selected.native_turn
            ),
        )
        .await?;
        result["binding"] = current["binding"].clone();
        result["entry_binding"] = current["entry_binding"].clone();
        Ok(result)
    } else if matches!(args, "voice native capabilities" | "voice native current") {
        let mut result = app
            .shared
            .store
            .conversation_request_binding(human, cfg.entry())?;
        let native = result["entry_binding"][3]
            .as_str()
            .context("Native voice requires an enrolled thread")?
            .to_owned();
        app.shared
            .store
            .validate_owned_binding(cfg.entry(), human, &native)?;
        if app.shared.store.stop_fenced(cfg.entry())?
            || app.shared.store.maintenance_writer_held(cfg.entry())?
        {
            bail!("Native voice cannot release a writer hold");
        }
        result["native_codex_voice"] = json!(if app.shared.config.codex.shared_app_server {
            Some("v1")
        } else {
            None
        });
        if args == "voice native current" {
            if !app.shared.config.codex.shared_app_server {
                bail!("Native voice requires the shared owner");
            }
            result["native_turn"] = json!(app.shared.codex.live_native_turn(&native).await?);
        }
        Ok(result)
    } else {
        command_input(app, human, args).await
    }
}

async fn command_input(app: &App, human: i64, args: &str) -> Result<Value> {
    let cfg = app
        .shared
        .config
        .interaction
        .as_ref()
        .context("Missing integrating entry")?;
    if args == "workspace" {
        return app
            .shared
            .store
            .conversation_workspace_destinations(human, cfg.entry());
    }
    if let Some(body) = args.strip_prefix("foreground context ") {
        let selected: crate::store::LiveContextCommand = serde_json::from_str(body)?;
        if !matches!(
            selected,
            crate::store::LiveContextCommand::Open { .. }
                | crate::store::LiveContextCommand::Append { .. }
                | crate::store::LiveContextCommand::Close { .. }
                | crate::store::LiveContextCommand::Sync { .. }
                | crate::store::LiveContextCommand::CheckpointNeeded { .. }
                | crate::store::LiveContextCommand::Guidance { .. }
                | crate::store::LiveContextCommand::GuidanceBegin { .. }
                | crate::store::LiveContextCommand::GuidanceOutcome { .. }
                | crate::store::LiveContextCommand::RolloverRead { .. }
                | crate::store::LiveContextCommand::ResumeRead { .. }
                | crate::store::LiveContextCommand::PinRead { .. }
                | crate::store::LiveContextCommand::RolloverCommit { .. }
                | crate::store::LiveContextCommand::RolloverStatus { .. }
                | crate::store::LiveContextCommand::RolloverAbort { .. }
        ) {
            bail!("Semantic incorporation belongs to the native integrator");
        }
        let dialogue = match &selected {
            crate::store::LiveContextCommand::Open { dialogue, .. }
            | crate::store::LiveContextCommand::Append { dialogue, .. }
            | crate::store::LiveContextCommand::Close { dialogue, .. }
            | crate::store::LiveContextCommand::Sync { dialogue, .. }
            | crate::store::LiveContextCommand::CheckpointNeeded { dialogue, .. }
            | crate::store::LiveContextCommand::Guidance { dialogue, .. }
            | crate::store::LiveContextCommand::GuidanceBegin { dialogue, .. }
            | crate::store::LiveContextCommand::GuidanceOutcome { dialogue, .. }
            | crate::store::LiveContextCommand::RolloverRead { dialogue, .. }
            | crate::store::LiveContextCommand::ResumeRead { dialogue, .. }
            | crate::store::LiveContextCommand::PinRead { dialogue, .. }
            | crate::store::LiveContextCommand::RolloverCommit { dialogue, .. }
            | crate::store::LiveContextCommand::RolloverStatus { dialogue, .. }
            | crate::store::LiveContextCommand::RolloverAbort { dialogue, .. } => dialogue.clone(),
            _ => unreachable!(),
        };
        let publishes_context = matches!(
            selected,
            crate::store::LiveContextCommand::Open { .. }
                | crate::store::LiveContextCommand::Append { .. }
                | crate::store::LiveContextCommand::Sync { .. }
                | crate::store::LiveContextCommand::Close { .. }
                | crate::store::LiveContextCommand::CheckpointNeeded { .. }
        );
        let result = app
            .shared
            .store
            .live_context(human, cfg.entry(), selected)?;
        if publishes_context {
            super::workflows::foreground(app, human, &dialogue).await?;
        }
        return Ok(result);
    }
    if let Some(body) = args.strip_prefix("foreground retain ") {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Retain {
            binding: String,
            id: String,
            text: String,
            dialogue_id: String,
            #[serde(default)]
            capture_questions: Option<std::collections::BTreeMap<String, String>>,
        }
        let selected: Retain = serde_json::from_str(body)?;
        let _ingress = app.shared.conversation_ingress.lock().await;
        let (input, fresh) = app.shared.store.conversation_foreground_capture(
            human,
            cfg.entry(),
            &selected.binding,
            &selected.id,
            &selected.text,
            &selected.dialogue_id,
            selected.capture_questions,
        )?;
        // Retention never calls deliver/submit, selects a worker or answers work.
        return response(app, &input, fresh);
    }
    #[cfg(unix)]
    if let Some(body) = args.strip_prefix("foreground interpret ") {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Interpret {
            binding: String,
            id: String,
            dialogue_id: String,
            audio_sha256: String,
            model: String,
            text: String,
            audio_millis: u64,
            transcription_millis: u64,
        }
        let selected: Interpret = serde_json::from_str(body)?;
        if selected.model != "gpt-transcribe"
            || Uuid::parse_str(&selected.id)
                .ok()
                .is_none_or(|v| v.to_string() != selected.id)
            || selected.text.trim().is_empty()
            || selected.text.len() > 16000
            || selected.text.contains('\0')
        {
            bail!("Select one completed source-bound OpenAI interpretation");
        }
        let _ingress = app.shared.conversation_ingress.lock().await;
        let input = app
            .shared
            .store
            .conversation_input_read(human, cfg.entry(), &selected.id)?;
        if input.foreground_dialogue.as_deref() != Some(&selected.dialogue_id)
            || input
                .voice
                .as_ref()
                .is_none_or(|v| v.audio_sha256 != selected.audio_sha256)
        {
            bail!("Public interpretation source is not this foreground original");
        }
        if let Some(proof) = input
            .voice
            .as_ref()
            .and_then(|v| v.transcription.as_ref())
            .cloned()
        {
            if proof.actual_transcriber.as_deref() != Some("gpt-transcribe")
                || proof.audio_millis != selected.audio_millis
            {
                bail!("A committed interpretation cannot be replaced");
            }
            let (input, fresh) = app.shared.store.conversation_foreground_interpretation(
                human,
                cfg.entry(),
                &selected.binding,
                &selected.id,
                &selected.dialogue_id,
                &selected.text,
                proof,
            )?;
            return response(app, &input, fresh);
        }
        let path =
            std::path::PathBuf::from(format!("{}.voice", app.shared.config.db_path.display()))
                .join(&selected.id);
        let id = selected.id.clone();
        let hash = selected.audio_sha256.clone();
        let proof = tokio::task::spawn_blocking(move || {
            crate::voice::public_interpretation_source(
                &path,
                &id,
                &hash,
                selected.audio_millis,
                selected.transcription_millis,
            )
        })
        .await??;
        let (input, fresh) = app.shared.store.conversation_foreground_interpretation(
            human,
            cfg.entry(),
            &selected.binding,
            &selected.id,
            &selected.dialogue_id,
            &selected.text,
            proof,
        )?;
        return response(app, &input, fresh);
    }
    if let Some(body) = args.strip_prefix("foreground delegate ") {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Delegate {
            binding: String,
            id: String,
            intent_id: String,
            formulation: String,
            source_ids: Vec<String>,
            #[serde(default)]
            live_window: Option<LiveWindow>,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct LiveWindow {
            path: String,
            proof: crate::voice::PublicLiveWindow,
        }
        let selected: Delegate = serde_json::from_str(body)?;
        let _ingress = app.shared.conversation_ingress.lock().await;
        let (input, fresh) = if let Some(window) = selected.live_window {
            #[cfg(unix)]
            {
                let proof = window.proof;
                let checked = proof.clone();
                let path = std::path::PathBuf::from(window.path);
                let text = tokio::task::spawn_blocking(move || {
                    crate::voice::public_live_window_source(&path, &checked)
                })
                .await??;
                app.shared.store.conversation_foreground_live_delegate(
                    human,
                    cfg.entry(),
                    &selected.binding,
                    &selected.id,
                    &selected.intent_id,
                    &selected.formulation,
                    &selected.source_ids,
                    &text,
                    proof,
                )?
            }
            #[cfg(not(unix))]
            {
                bail!("Private Live journal reader unavailable on this receiver");
            }
        } else {
            app.shared.store.conversation_foreground_delegate(
                human,
                cfg.entry(),
                &selected.binding,
                &selected.id,
                &selected.intent_id,
                &selected.formulation,
                &selected.source_ids,
            )?
        };
        if fresh {
            // Bypass voice-selected routing and automatic question answers.
            // Only the existing integrator decides downstream work.
            submit(app.clone(), input.clone()).await?;
        }
        return response(
            app,
            &app.shared
                .store
                .conversation_input_read(human, cfg.entry(), &input.id)?,
            fresh,
        );
    }
    if args == "voice capabilities" {
        let mut result = app
            .shared
            .store
            .conversation_request_binding(human, cfg.entry())?;
        result["voice_available"] = json!(app.shared.config.voice.is_some());
        result["voice_original_hold"] = json!("v1");
        result["foreground_retention"] = json!("v1");
        #[cfg(unix)]
        {
            result["foreground_interpretation"] = json!("gpt-transcribe/v1");
        }
        result["voice_default_transcription_profile"] = json!(
            app.shared
                .config
                .voice
                .as_ref()
                .and_then(|voice| voice.default_transcription_profile.as_deref())
        );
        result["voice_transcription_profiles"] = json!(
            app.shared
                .config
                .voice
                .as_ref()
                .map(|v| v.transcription_profiles.keys().cloned().collect::<Vec<_>>())
                .unwrap_or_default()
        );
        result["foreground_context"] = json!("v1");
        result["foreground_trace_results"] = json!("v1");
        result["foreground_public_live_transcripts"] = json!("v1");
        #[cfg(unix)]
        {
            result["foreground_live_window"] = json!("journal-input/v1");
        }
        result["foreground_audio_observations"] = json!("v1");
        result["foreground_derived_captions"] = json!("v1");
        result["foreground_guidance"] = json!("v1");
        result["foreground_rollover"] = json!("v1");
        result["foreground_resume"] = json!("v1");
        result["foreground_resume_compaction"] = json!("v1");
        result["foreground_continuation"] = json!("v1");
        result["foreground_completed_reader"] = json!(
            app.shared
                .config
                .voice
                .as_ref()
                .is_some_and(|v| v.completed_transcription_command.is_some())
        );
        result["max_bytes"] = json!(crate::voice::MAX_BYTES);
        result["max_seconds"] = json!(120);
        return Ok(result);
    }
    if let Some(body) = args.strip_prefix("voice submit ") {
        return voice_submit(app, human, cfg.entry(), body, false).await;
    }
    if let Some(body) = args.strip_prefix("voice recover ") {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Recovery {
            binding: String,
            id: String,
        }
        let selected: Recovery = serde_json::from_str(body)?;
        let input = app
            .shared
            .store
            .conversation_input_read(human, cfg.entry(), &selected.id)?;
        if !matches!(
            input.phase.as_str(),
            "preparation_unconfirmed" | "foreground_captured"
        ) {
            return response(app, &input, false);
        }
        let voice = input.voice.context("Original voice capture unavailable")?;
        let mut payload = json!({"binding":selected.binding,"id":selected.id,
            "audio_sha256":voice.audio_sha256,"mime":voice.mime,"capture_stop":voice.capture_stop,"files":input.files,"visual":input.visual,"reply":input.reply,"playback":input.playback,"capture_questions":input.capture_questions});
        if let Some(profile) = voice.transcription_profile {
            payload["transcription_profile"] = json!(profile);
        }
        if let Some(dialogue) = input.foreground_dialogue {
            payload["foreground_dialogue"] = json!(dialogue);
        }
        return voice_submit(app, human, cfg.entry(), &payload.to_string(), true).await;
    }
    if let Some(body) = args.strip_prefix("retry ") {
        let selected: Recover = serde_json::from_str(body)?;
        let _ingress = app.shared.conversation_ingress.lock().await;
        let binding = app
            .shared
            .store
            .conversation_request_binding(human, cfg.entry())?;
        if binding["binding"] != selected.binding {
            bail!("Entry changed before recovery");
        }
        let current = app
            .shared
            .store
            .interaction_instruction(&selected.instruction, human)?
            .context("Selected recovery unavailable")?;
        if !super::routing::instruction_available(&app.shared, &current) {
            bail!("Recovery target no longer enrolled");
        }
        let (changed, _) = app.shared.store.conversation_recover_route(
            human,
            cfg.entry(),
            &selected.id,
            &selected.instruction,
        )?;
        if changed
            && super::dialogue::dispatch_original(
                app,
                &selected.instruction,
                human,
                &crate::interaction::InputReference::Conversation(selected.id.clone()),
            )
            .await
            .is_err()
        {
            app.shared
                .store
                .interaction_unfinished(&selected.instruction, human)?;
        }
        return response(
            app,
            &app.shared
                .store
                .conversation_input_read(human, cfg.entry(), &selected.id)?,
            false,
        );
    }
    if let Some(body) = args.strip_prefix("route ") {
        let selected: Resolve = serde_json::from_str(body)?;
        let _ingress = app.shared.conversation_ingress.lock().await;
        let binding = app
            .shared
            .store
            .conversation_request_binding(human, cfg.entry())?;
        if binding["binding"] != selected.binding {
            bail!("Entry changed before routing selection");
        }
        let input = app
            .shared
            .store
            .conversation_input_read(human, cfg.entry(), &selected.id)?;
        deliver(app, input, Some(&selected.selector)).await?;
        return response(
            app,
            &app.shared
                .store
                .conversation_input_read(human, cfg.entry(), &selected.id)?,
            false,
        );
    }
    if let Some(page) = args.strip_prefix("list ") {
        let parts: Vec<_> = page.split_whitespace().collect();
        if parts.is_empty()
            || parts.len() > 2
            || parts
                .get(1)
                .is_some_and(|value| !matches!(*value, "before" | "after"))
        {
            bail!("Expected input list CURSOR [before|after]");
        }
        let mut page = app.shared.store.conversation_input_page(
            human,
            cfg.entry(),
            parts[0].parse()?,
            parts.get(1) != Some(&"after"),
        )?;
        if let Some(items) = page["items"].as_array_mut() {
            for item in items {
                if let Some(id) = item["id"].as_str().map(str::to_owned) {
                    decorate_recovery(app, human, cfg.entry(), &id, item)?;
                }
            }
        }
        page["routing_choices"] = choices(app)?;
        return Ok(page);
    }
    if let Some(args) = args.strip_prefix("trace-text ") {
        let fields: Vec<_> = args.split_whitespace().collect();
        let [id, source, offset] = fields.as_slice() else {
            bail!("Expected original, trace source and offset");
        };
        return app.shared.store.conversation_trace_text(
            human,
            cfg.entry(),
            id,
            source,
            offset.parse()?,
        );
    }
    if let Some(args) = args.strip_prefix("telegram-list ") {
        let fields: Vec<_> = args.split_whitespace().collect();
        let [cursor, direction] = fields.as_slice() else {
            bail!("Expected Telegram cursor and direction");
        };
        if !matches!(*direction, "before" | "after") {
            bail!("Invalid Telegram direction");
        }
        return app.shared.store.conversation_telegram_page(
            human,
            cfg.entry(),
            cursor.parse()?,
            *direction == "before",
        );
    }
    if let Some(args) = args.strip_prefix("trace-results ") {
        let fields: Vec<_> = args.split_whitespace().collect();
        let [id, instruction, before] = fields.as_slice() else {
            bail!("Expected trace original, instruction and result cursor");
        };
        return app.shared.store.conversation_input_trace_results(
            human,
            cfg.entry(),
            id,
            instruction,
            before.parse()?,
        );
    }
    if let Some(args) = args.strip_prefix("trace-result ") {
        let fields: Vec<_> = args.split_whitespace().collect();
        let [id, source] = fields.as_slice() else {
            bail!("Expected trace original and canonical delivery");
        };
        return app
            .shared
            .store
            .conversation_input_trace_result(human, cfg.entry(), id, source);
    }
    if let Some(id) = args.strip_prefix("trace ") {
        let mut trace = app
            .shared
            .store
            .conversation_input_trace(human, cfg.entry(), id)?;
        if let Some(routes) = trace["routes"].as_array_mut() {
            for route in routes {
                let target: SessionKey = serde_json::from_value(route["target"].clone())?;
                route["label"] = json!(super::routing::label(&app.shared, target));
            }
        }
        return Ok(trace);
    }
    if let Some(id) = args.strip_prefix("status ") {
        return response(
            app,
            &app.shared
                .store
                .conversation_input_read(human, cfg.entry(), id)?,
            false,
        );
    }
    let request: Submit = serde_json::from_str(
        args.strip_prefix("submit ")
            .context("Expected input submit JSON, status UUID or list cursor")?,
    )?;
    // Preserve capture/handoff order for this configured integrating entry. The
    // lock is released before native acknowledgments, so later steering proceeds.
    if crate::interaction::explicit_selector(&request.text).is_none()
        && app
            .shared
            .store
            .conversation_input_read(human, cfg.entry(), &request.id)
            .is_err()
    {
        super::conversation_requests::validate_reply(app, human, request.reply.as_ref()).await?;
    }
    let interruption_targets = super::voice::snapshot(app).await;
    let _ingress = app.shared.conversation_ingress.lock().await;
    let (input, fresh) = app.shared.store.conversation_input_capture_files(
        human,
        cfg.entry(),
        &request.binding,
        &request.id,
        &request.text,
        request.reply,
        request.visual,
        request.playback,
        request.files,
    )?;
    if fresh && input.phase == "retained" {
        if let Err(error) = super::voice::INTERRUPT_TARGETS
            .scope(interruption_targets, deliver(app, input.clone(), None))
            .await
        {
            app.shared
                .store
                .conversation_input_finish(human, &input.id)?;
            return Err(error);
        }
    }
    response(
        app,
        &app.shared
            .store
            .conversation_input_read(human, cfg.entry(), &input.id)?,
        fresh,
    )
}

/// Owner-local authenticated Tribu admission shares the existing original,
/// controller, native writer and return surface. It is not a browser endpoint.
pub(super) async fn admit_tribu(app: &App, record: Value) -> Result<Value> {
    let p = app.shared.config.tribu.as_ref().context("Tribu disabled")?;
    let _ingress = app.shared.conversation_ingress.lock().await;
    let (input, fresh) = app.shared.store.conversation_tribu_capture(
        p.human_id,
        p.key(),
        crate::interaction::TribuSource { record },
        p.max_pending,
    )?;
    if fresh && input.phase == "retained" {
        if let Err(error) = deliver(app, input.clone(), None).await {
            app.shared
                .store
                .conversation_input_finish(input.human, &input.id)?;
            return Err(error);
        }
    }
    let current = app
        .shared
        .store
        .conversation_input_read(input.human, input.entry, &input.id)?;
    Ok(json!({"id":current.id,"state":current.phase,"duplicate":!fresh}))
}

async fn deliver(app: &App, input: ConversationInput, resolve: Option<&str>) -> Result<()> {
    if input
        .reply
        .as_ref()
        .is_some_and(|r| r.source.starts_with("request:") && !r.context_only)
        && crate::interaction::explicit_selector(&input.text).is_none()
        && resolve.is_none()
    {
        return super::conversation_requests::answer_original(app, &input).await;
    }
    let profile = super::routing::profile(&app.shared)?;
    let action = app
        .shared
        .store
        .conversation_route(input.human, &input.id, &profile, resolve)?;
    apply_route(app, input, action).await
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Clarification {
    pending_input: String,
    input_ref: crate::interaction::InputReference,
    selector: String,
}
pub(super) async fn clarify(
    app: &App,
    human: i64,
    native: &str,
    args: Value,
    closed: &CancellationToken,
) -> Result<Value> {
    let selected: Clarification = serde_json::from_value(args)?;
    let profile = super::routing::profile(&app.shared)?;
    if closed.is_cancelled() {
        bail!("Clarification request closed");
    }
    let action = app.shared.store.conversation_route_clarified(
        human,
        &selected.pending_input,
        &profile,
        &selected.selector,
        (native, &selected.input_ref, closed),
    )?;
    let input = app.shared.store.conversation_input_read(
        human,
        profile.entry(),
        &selected.pending_input,
    )?;
    apply_route(app, input, action).await?;
    response(
        app,
        &app.shared.store.conversation_input_read(
            human,
            profile.entry(),
            &selected.pending_input,
        )?,
        false,
    )
}

async fn apply_route(
    app: &App,
    input: ConversationInput,
    action: Option<crate::store::ConversationRouteAction>,
) -> Result<()> {
    match action {
        Some(crate::store::ConversationRouteAction::Worker(instruction, fresh)) => {
            if fresh
                && super::dialogue::dispatch_original(
                    app,
                    &instruction.id,
                    input.human,
                    &crate::interaction::InputReference::Conversation(input.id.clone()),
                )
                .await
                .is_err()
            {
                app.shared
                    .store
                    .interaction_unfinished(&instruction.id, input.human)?;
            }
            return Ok(());
        }
        Some(crate::store::ConversationRouteAction::Interrupt(expected)) => {
            app.shared
                .store
                .conversation_interruption_apply(input.human, &input.id, |target| {
                    if target == expected {
                        super::voice::interrupt_snapshot(target)
                    } else {
                        None
                    }
                })?;
            return Ok(());
        }
        None => {}
    }
    let current = app
        .shared
        .store
        .conversation_input_read(input.human, input.entry, &input.id)?;
    if current.phase != "retained" {
        return Ok(());
    }
    app.shared
        .store
        .conversation_input_event(input.human, &input.id, E::Queue)?;
    submit(app.clone(), input).await
}

async fn submit(app: App, input: ConversationInput) -> Result<()> {
    let handle = app.worker_for(input.entry).await?;
    let active = handle.steer.lock().expect("steer mutex poisoned").clone();
    let Some(active) = active else {
        return enqueue(&app, &input, handle.sender);
    };
    app.shared.store.conversation_input_event(
        input.human,
        &input.id,
        E::Begin {
            local_turn: active.turn_id,
            steer: true,
        },
    )?;
    let (send, receive) = oneshot::channel();
    let shared = app.shared.clone();
    let id = input.id.clone();
    let human = input.human;
    let entry = input.entry;
    let retained_text = format!(
        "{}{}",
        input.rendered(),
        crate::files::rendered(&app.shared.config.db_path, &input.files)?
    );
    let packet = CodexSteerRequest {
        tool_output: None,
        observation: None,
        images: crate::visual::attachments(&app.shared.config.db_path, input.visual.as_ref())?
            .into_iter()
            .map(|a| a.path)
            .collect(),
        admission_check: Some(crate::codex::SteerInputAdmission::Async(Arc::new(
            move || {
                let shared = shared.clone();
                let id = id.clone();
                Box::pin(async move {
                    super::tribu::validate_conversation(&shared, human, entry, &id).await?;
                    shared.store.conversation_input_validate(human, &id)
                })
            },
        ))),
        client_message_id: Some(format!("conversation:{}", input.id)),
        text: match &active.controller_hint {
            Some(hint) => {
                format!("{retained_text}\n\n[Controller access for this execution]{hint}")
            }
            None => retained_text,
        },
        goal: None,
        response: send,
    };
    if active.sender.send(packet).is_err() {
        app.shared.store.conversation_input_event(
            human,
            &input.id,
            E::Rejected {
                local_turn: active.turn_id,
            },
        )?;
        app.shared
            .store
            .conversation_input_event(human, &input.id, E::Queue)?;
        return enqueue(&app, &input, handle.sender);
    }
    tokio::spawn(async move {
        let result: Result<()> = async {
            match tokio::time::timeout(Duration::from_secs(10), receive).await {
                Ok(Ok(Ok(_))) => {
                    app.shared.store.conversation_input_event(
                        human,
                        &input.id,
                        E::Accepted {
                            local_turn: active.turn_id,
                        },
                    )?;
                }
                Ok(Ok(Err(CodexSteerError::Rejected(_)))) => {
                    app.shared.store.conversation_input_event(
                        human,
                        &input.id,
                        E::Rejected {
                            local_turn: active.turn_id,
                        },
                    )?;
                    app.shared
                        .store
                        .conversation_input_event(human, &input.id, E::Queue)?;
                    enqueue(&app, &input, handle.sender)?;
                }
                _ => {
                    app.shared.store.conversation_input_event(
                        human,
                        &input.id,
                        E::Uncertain {
                            local_turn: active.turn_id,
                        },
                    )?;
                }
            }
            Ok(())
        }
        .await;
        if result.is_err() {
            let _ = app.shared.store.conversation_input_finish(human, &input.id);
            tracing::warn!(
                "Conversation input outcome retained without confirmed submission; no automatic replay"
            );
        }
    });
    Ok(())
}

fn enqueue(
    app: &App,
    input: &ConversationInput,
    sender: mpsc::UnboundedSender<QueuedTurn>,
) -> Result<()> {
    app.shared
        .store
        .conversation_input_validate(input.human, &input.id)?;
    sender
        .send(QueuedTurn {
            request: TurnRequest {
                session_key: input.entry,
                from_user_id: input.human,
                prompt: format!(
                    "{}{}",
                    input.rendered(),
                    crate::files::rendered(&app.shared.config.db_path, &input.files)?
                ),
                runtime_instructions: None,
                attachments: crate::visual::attachments(
                    &app.shared.config.db_path,
                    input.visual.as_ref(),
                )?
                .into_iter()
                .chain(crate::files::attachments(
                    &app.shared.config.db_path,
                    &input.files,
                )?)
                .collect(),
                review_mode: None,
                override_search_mode: None,
            },
            chat_kind: "conversation".into(),
            update_id: None,
            conversation_input: Some(input.id.clone()),
            workflow_return: None,
            tribu_admission: None,
            goal: None,
            nexus: None,
            merge: None,
            stop_resume: None,
            interaction: None,
            admission_epoch: input.epoch.clone(),
        })
        .map_err(|_| anyhow!("Conversation worker unavailable"))?;
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VoiceSubmit {
    #[serde(default)]
    transcription_profile: Option<String>,
    #[serde(default)]
    preserve_original: bool,
    binding: String,
    #[serde(default)]
    foreground_dialogue: Option<String>,
    #[serde(default)]
    defer_foreground: bool,
    id: String,
    audio_sha256: String,
    mime: String,
    #[serde(default)]
    capture_stop: Option<String>,
    #[serde(default)]
    visual: Option<crate::visual::VisualSelection>,
    #[serde(default)]
    files: Vec<crate::files::FileReference>,
    #[serde(default)]
    reply: Option<crate::store::ConversationReply>,
    #[serde(default)]
    playback: Option<crate::store::ConversationPlayback>,
    #[serde(default)]
    capture_questions: Option<std::collections::BTreeMap<String, String>>,
}

async fn voice_submit(
    app: &App,
    human: i64,
    entry: SessionKey,
    body: &str,
    recover: bool,
) -> Result<Value> {
    use crate::store::ConversationVoice;
    let mut request: VoiceSubmit = serde_json::from_str(body)?;
    // Classic clients and unfinished local recordings carry no profile. Keep
    // their original route; new clients freeze the selected default explicitly.
    if request.transcription_profile.is_none() {
        let existing = app
            .shared
            .store
            .conversation_input_read(human, entry, &request.id)
            .ok();
        request.transcription_profile = if let Some(original) = existing {
            original.voice.and_then(|voice| voice.transcription_profile)
        } else {
            None
        };
    }
    if request.defer_foreground && request.foreground_dialogue.is_none() {
        bail!("Deferred completion requires a foreground capture");
    }
    let mut config = app
        .shared
        .config
        .voice
        .as_ref()
        .context("Voice input is not configured")?
        .select_profile(request.transcription_profile.as_deref())?;
    // A deferred acoustic reservation starts no recognizer and therefore does
    // not require an unused completed-transcript command. Ordinary foreground
    // recovery still selects only its configured completed reader.
    if recover || (request.foreground_dialogue.is_some() && !request.defer_foreground) {
        config.transcription_command = config
            .completed_transcription_command
            .clone()
            .context("Completed-transcript recovery is not configured")?;
    }
    if Uuid::parse_str(&request.id)
        .ok()
        .is_none_or(|v| v.to_string() != request.id)
    {
        bail!("Invalid voice capture identity");
    }
    let voice = ConversationVoice {
        transcription_profile: request.transcription_profile,
        preserve_original: request.preserve_original.then_some(true),
        audio_sha256: request.audio_sha256,
        mime: request.mime,
        capture_stop: request.capture_stop,
        transcription: None,
    };
    voice.validate()?;
    let directory =
        std::path::PathBuf::from(format!("{}.voice", app.shared.config.db_path.display()));
    let path = directory.join(&request.id);
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let folder = std::fs::symlink_metadata(&directory)?;
        let file = std::fs::symlink_metadata(&path)?;
        if !folder.is_dir()
            || folder.uid() != unsafe { libc::geteuid() }
            || folder.mode() & 0o077 != 0
            || !file.is_file()
            || file.uid() != unsafe { libc::geteuid() }
            || file.mode() & 0o077 != 0
            || file.len() == 0
            || file.len() > crate::voice::MAX_BYTES as u64
        {
            bail!("Voice capture file is not owner-private and bounded");
        }
    }
    if app
        .shared
        .store
        .conversation_input_read(human, entry, &request.id)
        .is_err()
    {
        super::conversation_requests::validate_reply(app, human, request.reply.as_ref()).await?;
    }
    let interruption_targets = if request.foreground_dialogue.is_some() {
        Default::default()
    } else {
        super::voice::snapshot(app).await
    };
    let permit = if request.defer_foreground {
        None
    } else {
        app.shared
            .voice_preparations
            .clone()
            .try_acquire_owned()
            .ok()
    };
    let _ingress = app.shared.conversation_ingress.lock().await;
    if recover && permit.is_none() {
        bail!("Voice preparation busy; recovery was not started");
    }
    let (mut input, mut fresh) = if let Some(dialogue) = request.foreground_dialogue.as_ref() {
        if request.reply.is_some()
            || request.visual.is_some()
            || request.playback.is_some()
            || !request.files.is_empty()
        {
            bail!("Foreground capture metadata must come from its own acoustic activity");
        }
        app.shared.store.conversation_foreground_voice_capture(
            human,
            entry,
            &request.binding,
            &request.id,
            voice,
            permit.is_some(),
            dialogue,
            request.capture_questions,
        )?
    } else {
        app.shared.store.conversation_voice_capture_files(
            human,
            entry,
            &request.binding,
            &request.id,
            voice,
            permit.is_some(),
            request.reply,
            request.visual,
            request.playback,
            request.capture_questions,
            request.files,
        )?
    };
    if recover {
        (input, fresh) = app.shared.store.conversation_voice_resume(
            human,
            entry,
            &request.binding,
            &request.id,
        )?;
    }
    if fresh && input.phase == "preparing" {
        let worker = app.clone();
        let captured = input.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let preparation = super::voice::INTERRUPT_TARGETS.scope(interruption_targets, async {
                worker
                    .shared
                    .store
                    .conversation_voice_validate(human, &captured.id)?;
                let expected = &captured
                    .voice
                    .as_ref()
                    .context("Missing voice capture")?
                    .audio_sha256;
                let (text, proof) = crate::voice::transcribe_committed(
                    &config,
                    &path,
                    None,
                    Some(&captured.id),
                    Some(expected),
                )
                .await?;
                let _ingress = worker.shared.conversation_ingress.lock().await;
                let ready = worker.shared.store.conversation_voice_commit(
                    human,
                    &captured.id,
                    &text,
                    proof,
                )?;
                // The persisted capture, not a later retry's policy argument,
                // owns this hold. Python may retire it only after exact archive
                // handoff. Process restart/ASR completion cannot drop that fence.
                if captured
                    .voice
                    .as_ref()
                    .is_none_or(|v| v.preserve_original != Some(true))
                    && crate::voice::retire_transcribed_clip(&path, expected).is_err()
                {
                    // Durable text is already committed. A later client read
                    // can finish exact cleanup without repeating ASR or work.
                    tracing::warn!("Committed conversation voice cleanup deferred");
                }
                if ready.foreground_dialogue.is_none()
                    && let Err(error) = deliver(&worker, ready, None).await
                {
                    worker
                        .shared
                        .store
                        .conversation_input_finish(human, &captured.id)?;
                    return Err(error);
                }
                Ok::<_, anyhow::Error>(())
            });
            let result = tokio::select! {biased;_ = worker.shared.voice_shutdown.cancelled()=>Err(anyhow!("Voice preparation ended for listener restart")),result=preparation=>result};
            if let Err(error) = result {
                let _ = worker
                    .shared
                    .store
                    .conversation_voice_fail(human, &captured.id);
                tracing::warn!(
                    error = %error, "Committed conversation voice preparation unconfirmed; no automatic retry"
                );
            }
        });
    }
    response(
        app,
        &app.shared
            .store
            .conversation_input_read(human, entry, &input.id)?,
        fresh && !recover,
    )
}
