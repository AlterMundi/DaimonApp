//! Shared read-only display contract for an owned session's selected execution.
use super::*;
use crate::interaction::{ForegroundEngine, InteractionConfig};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::Read;

#[derive(Default)]
pub(super) struct ClaudeRuntimeCache {
    observation: Option<([u8; 32], Instant, Value)>,
}

fn profile_bytes(path: &str) -> Option<Vec<u8>> {
    let mut file = std::fs::File::open(path).ok()?.take(65537);
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).ok()?;
    (bytes.len() <= 65536).then_some(bytes)
}

fn safe_label(value: &Value) -> Option<&str> {
    value.as_str().filter(|text| {
        !text.trim().is_empty() && text.len() <= 128 && !text.chars().any(char::is_control)
    })
}

async fn observe_claude(
    shared: &AppShared,
    command: &[String],
    index: usize,
    key: [u8; 32],
) -> Value {
    let mut cache = shared.claude_runtime_cache.lock().await;
    if let Some((cached, until, value)) = cache.observation.as_ref()
        && *cached == key
        && *until > Instant::now()
    {
        return value.clone();
    }
    let mut invocation = command.to_owned();
    invocation[index] = "--observe-runtime".into();
    let mut child = tokio::process::Command::new(&invocation[0]);
    child
        .args(&invocation[1..])
        .env_clear()
        .stdin(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .kill_on_drop(true);
    let sample = tokio::time::timeout(Duration::from_secs(12), child.output()).await;
    let observed = match sample {
        Ok(Ok(output)) if output.status.success() && output.stdout.len() <= 2048 => {
            serde_json::from_slice::<Value>(&output.stdout).ok()
        }
        _ => None,
    }
    .filter(|_| {
        profile_bytes(&command[index + 1]).is_some_and(|bytes| fingerprint(command, &bytes) == key)
    })
    .unwrap_or(Value::Null);
    let ttl = if observed.is_object() { 90 } else { 20 };
    cache.observation = Some((
        key,
        Instant::now() + Duration::from_secs(ttl),
        observed.clone(),
    ));
    observed
}

fn fingerprint(command: &[String], bytes: &[u8]) -> [u8; 32] {
    let mut digest = Sha256::new();
    for part in command {
        digest.update(part.as_bytes());
        digest.update([0]);
    }
    digest.update(bytes);
    digest.finalize().into()
}

pub(super) async fn portable_runtime(
    shared: &AppShared,
    config: &InteractionConfig,
    engine: ForegroundEngine,
) -> Value {
    let mut runtime = json!({"harness":engine.name(),"model":null,"effort":null});
    let Some(selected) = config
        .foreground(engine)
        .filter(|profile| profile.interaction_direct)
    else {
        return runtime;
    };
    let command = &selected.worker_command;
    let Some(index) = command
        .windows(2)
        .position(|args| args[0] == "--profile" && std::path::Path::new(&args[1]).is_absolute())
    else {
        return runtime;
    };
    let Some(bytes) = profile_bytes(&command[index + 1]) else {
        return runtime;
    };
    let Ok(profile) = serde_json::from_slice::<Value>(&bytes) else {
        return runtime;
    };
    for field in ["model", "effort"] {
        if let Some(value) = safe_label(&profile[field]) {
            runtime[field] = json!(value);
        }
    }
    if engine != ForegroundEngine::Claude || profile["subscriptionEmail"].as_str().is_none() {
        return runtime;
    }
    let observed = observe_claude(shared, command, index, fingerprint(command, &bytes)).await;
    if let Some(model) = safe_label(&observed["model"]).filter(|model| model.starts_with("claude-"))
    {
        runtime["model"] = json!(model);
    }
    for window in ["weekly", "session"] {
        if let (Some(available), Some(resets_at)) = (
            observed[window]["available"]
                .as_f64()
                .filter(|value| (0.0..=100.0).contains(value)),
            observed[window]["resets_at"]
                .as_i64()
                .filter(|time| *time > Utc::now().timestamp()),
        ) {
            runtime[format!("{window}_available_percent")] = json!(available);
            runtime[format!("{window}_resets_at")] = json!(resets_at);
        }
    }
    runtime
}

pub(super) async fn workspace(app: &App, human: i64, config: &InteractionConfig) -> Result<Value> {
    let mut view = app
        .shared
        .store
        .conversation_workspace_destinations(human, config.entry())?;
    let mut profiles = Vec::new();
    for engine in [
        ForegroundEngine::Claude,
        ForegroundEngine::Antigravity,
        ForegroundEngine::Goose,
    ] {
        if config
            .foreground(engine)
            .is_some_and(|profile| profile.interaction_direct)
        {
            profiles.push((engine, portable_runtime(&app.shared, config, engine).await));
        }
    }
    let codex = &app.shared.config.codex;
    let apply = |key, runtime: &mut Value| {
        if let Some((engine, _)) = config.portable_route(key)
            && let Some((_, current)) = profiles.iter().find(|(candidate, _)| *candidate == engine)
        {
            *runtime = current.clone();
            return;
        }
        if !runtime.is_object() {
            *runtime = json!({"harness":"codex"});
        }
        if runtime["model"].is_null() {
            runtime["model"] = json!(codex.default_model);
        }
        if runtime["effort"].is_null() {
            runtime["effort"] = json!(codex.default_reasoning_effort);
        }
        if !codex
            .session_profiles
            .iter()
            .any(|profile| profile.key() == key)
        {
            runtime["quota_source"] = json!("codex");
        }
    };
    apply(config.entry(), &mut view["entry_runtime"]);
    if let Some(items) = view["items"].as_array_mut() {
        for item in items {
            let key = item["audio_key"].as_str().and_then(|raw| {
                let (chat, topic) = raw.split_once(':')?;
                Some(SessionKey::new(
                    chat.parse().ok()?,
                    Some(topic.parse().ok()?),
                ))
            });
            if let Some(key) = key {
                apply(key, &mut item["runtime"]);
            }
        }
    }
    let mut portable_status = serde_json::Map::new();
    for target in &config.targets {
        let key = SessionKey::new(config.chat_id, Some(target.topic_id));
        let Some((engine, _)) = config.portable_route(key) else {
            continue;
        };
        let Some(binding) = app.shared.store.execution_binding(key, human)? else {
            continue;
        };
        let Some((_, runtime)) = profiles.iter().find(|(candidate, _)| *candidate == engine) else {
            continue;
        };
        let (started, waiting) = app.shared.store.routed_portable_status(
            binding.conversation_id,
            human,
            engine.name(),
        )?;
        let execution = match (started, waiting) {
            (Some(_), _) => "working",
            (None, 0) => "idle",
            (None, _) => "queued",
        };
        portable_status.insert(
            format!("{}:{}", key.chat_id, key.thread_id),
            json!({"session":binding.conversation_id,"runtime":runtime,"execution":execution,
                "observed_at":Utc::now().timestamp_millis() as f64 / 1000.0}),
        );
    }
    view["portable_status"] = Value::Object(portable_status);
    Ok(view)
}
