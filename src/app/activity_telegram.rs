//! Transport for the existing owner-local Activity receipts.
use super::*;
use crate::tele_daimon::projection::{self, JsonMethod};
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::Read;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    chat: i64,
    topic: i64,
    native_thread: String,
    credential_fingerprint: String,
    background: bool,
    operation: Operation,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Operation {
    Send {
        text: String,
        reply_to: Option<i64>,
        pending_requests: bool,
    },
    Edit {
        message_id: i64,
        text: String,
        pending_requests: bool,
    },
    Delete {
        message_id: i64,
    },
    TopicName {
        name: String,
    },
}

pub(super) async fn project(app: &App, request: Request) -> Result<Value> {
    let shared = &app.shared;
    anyhow::ensure!(
        shared.config.telegram.external_polling && shared.telegram.is_available(),
        "External Telegram projection is unavailable"
    );
    anyhow::ensure!(
        request.chat != 0
            && request.topic >= 0
            && request.credential_fingerprint.len() == 64
            && request
                .credential_fingerprint
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "Invalid Activity receiver"
    );
    let key = SessionKey::new(request.chat, (request.topic > 0).then_some(request.topic));
    let human = shared.store.session_creator(key)?;
    let state = shared
        .config
        .activity_projection_state
        .as_ref()
        .context("Activity receipt state is not selected")?;
    let proof = match &request.operation {
        Operation::Edit { message_id, .. } | Operation::Delete { message_id } => {
            Some(Receipt::Card(*message_id))
        }
        Operation::TopicName { name } => Some(Receipt::Marker(name.clone())),
        Operation::Send { .. } => None,
    };
    let authorize = || {
        shared
            .store
            .validate_owned_binding(key, human, &request.native_thread)?;
        if let Some(proof) = &proof {
            proof.validate(state, request.chat, request.topic, &request.native_thread)?;
        }
        Ok(())
    };
    if authorize().is_err() {
        return Ok(json!({"ok":false,"not_submitted":true}));
    }
    let (method, mut document) = match request.operation {
        Operation::Send {
            text,
            reply_to,
            pending_requests,
        } => {
            check_text(&text)?;
            let mut data = json!({
                "chat_id":request.chat,"text":text,"parse_mode":"HTML",
                "disable_notification":true,"reply_markup":markup(pending_requests)
            });
            if let Some(reply) = reply_to {
                anyhow::ensure!(reply > 0, "Invalid Activity reply");
                data["reply_parameters"] = json!({"message_id":reply});
            }
            (JsonMethod::SendMessage, data)
        }
        Operation::Edit {
            message_id,
            text,
            pending_requests,
        } => {
            check_text(&text)?;
            anyhow::ensure!(message_id > 0, "Invalid Activity message");
            (
                JsonMethod::EditMessageText,
                json!({
                    "chat_id":request.chat,"message_id":message_id,"text":text,
                    "parse_mode":"HTML","reply_markup":markup(pending_requests)
                }),
            )
        }
        Operation::Delete { message_id } => {
            anyhow::ensure!(message_id > 0, "Invalid Activity message");
            (
                JsonMethod::DeleteMessage,
                json!({"chat_id":request.chat,"message_id":message_id}),
            )
        }
        Operation::TopicName { name } => {
            anyhow::ensure!(
                request.topic > 0 && !name.trim().is_empty() && name.chars().count() <= 128,
                "Invalid Activity topic name"
            );
            (
                JsonMethod::EditForumTopic,
                json!({"chat_id":request.chat,"message_thread_id":request.topic,"name":name}),
            )
        }
    };
    if matches!(method, JsonMethod::SendMessage) && request.topic > 0 {
        document["message_thread_id"] = json!(request.topic);
    }
    let socket = &shared
        .config
        .session_control
        .as_ref()
        .context("Missing owner control socket")?
        .socket_path;
    // The existing Activity observer and Bot API meter retain their pacing.
    let result = projection::json(
        socket,
        shared.bot_id,
        method,
        Some(document),
        Some(request.credential_fingerprint),
        Some(request.background),
        authorize,
    )
    .await;
    match result {
        Ok(value) => {
            if matches!(
                method,
                JsonMethod::SendMessage | JsonMethod::EditMessageText
            ) {
                anyhow::ensure!(
                    value["chat"]["id"].as_i64() == Some(request.chat)
                        && value["message_thread_id"].as_i64().unwrap_or(0) == request.topic
                        && value["message_id"].as_i64().is_some_and(|id| id > 0),
                    "Activity message outcome unconfirmed"
                );
            }
            Ok(json!({"ok":true,"result":value}))
        }
        Err(error) if error.is::<projection::JsonNotSubmitted>() => {
            Ok(json!({"ok":false,"not_submitted":true}))
        }
        Err(error) => {
            let provider = error
                .downcast_ref::<crate::telegram::TelegramError>()
                .context("Activity Telegram operation unconfirmed")?;
            let description = provider.description.to_ascii_lowercase();
            let detail = [
                "message to edit not found",
                "message is not modified",
                "message to delete not found",
            ]
            .into_iter()
            .find(|pattern| description.contains(pattern));
            Ok(json!({"ok":false,"error_code":provider.status.as_u16(),
                "parameters":{"retry_after":provider.retry_after.unwrap_or(30)},"description":detail.unwrap_or("")}))
        }
    }
}

fn check_text(text: &str) -> Result<()> {
    anyhow::ensure!(
        !text.trim().is_empty() && text.len() <= 16 * 1024,
        "Invalid Activity text"
    );
    Ok(())
}

fn markup(pending_requests: bool) -> Value {
    if pending_requests {
        json!({"inline_keyboard":[[{"text":"Open human requests","callback_data":"qpending"}]]})
    } else {
        json!({"inline_keyboard":[]})
    }
}

enum Receipt {
    Card(i64),
    Marker(String),
}

impl Receipt {
    fn validate(&self, root: &Path, chat: i64, topic: i64, native: &str) -> Result<()> {
        let meta = fs::symlink_metadata(root)?;
        let uid = unsafe { libc::geteuid() };
        anyhow::ensure!(
            root.is_absolute() && meta.is_dir() && meta.uid() == uid && meta.mode() & 0o077 == 0,
            "Unsafe Activity receipt directory"
        );
        let file = match self {
            Self::Card(_) => "messages.json",
            Self::Marker(_) => "topic-markers.json",
        };
        let opened = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(root.join(file))?;
        let meta = opened.metadata()?;
        anyhow::ensure!(
            meta.is_file()
                && meta.uid() == uid
                && meta.mode() & 0o077 == 0
                && meta.len() <= 1_048_576,
            "Unsafe Activity receipt file"
        );
        let mut raw = Vec::new();
        opened.take(1_048_577).read_to_end(&mut raw)?;
        anyhow::ensure!(raw.len() <= 1_048_576, "Activity receipt exceeds bound");
        let record: Value = serde_json::from_slice(&raw).context("Malformed Activity receipt")?;
        let key = format!("{chat}:{topic}");
        let item = match self {
            Self::Card(_) => &record[&key],
            Self::Marker(_) => {
                anyhow::ensure!(
                    record["schema"] == "telecodex.topic-markers/v1",
                    "Unknown Activity marker receipt schema"
                );
                &record["items"][&key]
            }
        };
        let matches = match self {
            Self::Card(id) => {
                item["chat_id"] == chat && item["topic"] == topic && item["message_id"] == *id
            }
            Self::Marker(name) => {
                item["phase"] == "attempting" && item["desired"].as_str() == Some(name)
            }
        };
        anyhow::ensure!(
            matches && item["native_thread"].as_str() == Some(native),
            "Selected Activity receipt belongs to another message, topic or native session"
        );
        Ok(())
    }
}
