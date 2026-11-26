//! One read-only display contract for an owned session's selected execution.
use super::*;
use crate::interaction::{ForegroundEngine, InteractionConfig};
use serde_json::{Value, json};
use std::io::Read;

fn portable_metadata(config: &InteractionConfig) -> Vec<(ForegroundEngine, Value)> {
    [
        ForegroundEngine::Claude,
        ForegroundEngine::Antigravity,
        ForegroundEngine::Goose,
    ]
    .into_iter()
    .filter_map(|engine| {
        let selected = config
            .foreground(engine)
            .filter(|profile| profile.interaction_direct)?;
        let mut runtime = json!({"harness":engine.name(),"model":null,"effort":null});
        // The selected owner command already passes the worker this profile.
        if let Some(path) = selected
            .worker_command
            .windows(2)
            .find_map(|args| (args[0] == "--profile").then_some(&args[1]))
            .filter(|path| std::path::Path::new(path).is_absolute())
        {
            if let Ok(file) = std::fs::File::open(path)
                && file
                    .metadata()
                    .is_ok_and(|metadata| metadata.is_file() && metadata.len() <= 65536)
                && let Ok(profile) = serde_json::from_reader::<_, Value>(file.take(65536))
            {
                for field in ["model", "effort"] {
                    if let Some(value) = profile[field].as_str().filter(|value| {
                        !value.trim().is_empty()
                            && value.len() <= 128
                            && !value.chars().any(char::is_control)
                    }) {
                        runtime[field] = json!(value);
                    }
                }
            }
        }
        Some((engine, runtime))
    })
    .collect()
}

pub(super) fn workspace(app: &App, human: i64, config: &InteractionConfig) -> Result<Value> {
    let mut view = app
        .shared
        .store
        .conversation_workspace_destinations(human, config.entry())?;
    let profiles = portable_metadata(config);
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
    Ok(view)
}
