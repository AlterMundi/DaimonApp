//! Nonblocking secondary delivery using canonical native/input identities.
use super::*;
use crate::tele_daimon::{Delivery, ProjectedFile, Projection, projection_parts};

struct Lease {
    shared: Arc<AppShared>,
    id: i64,
}
impl Drop for Lease {
    fn drop(&mut self) {
        let _ = self.shared.store.topic_publication_release(self.id);
    }
}

pub(super) fn enabled(shared: &AppShared, key: SessionKey, human: i64) -> bool {
    shared.config.telegram.enabled
        && shared.config.interaction.as_ref().is_some_and(|c| {
            c.human_id == human
                && ((c.telegram_projection && super::routing::enrolled(shared, key))
                    || (c.telegram_entry_projection && c.entry() == key))
        })
}

pub(super) fn recover(shared: Arc<AppShared>) -> Result<()> {
    if !shared.config.telegram.enabled {
        return Ok(());
    }
    for key in shared.store.topic_publication_targets()? {
        wake(shared.clone(), key);
    }
    Ok(())
}

pub(super) fn wake(shared: Arc<AppShared>, key: SessionKey) {
    if !shared.config.telegram.enabled {
        return;
    }
    let Ok(Some(human)) = shared.store.topic_publication_owner(key) else {
        return;
    };
    if let Some(c) = shared.config.interaction.as_ref()
        && c.entry() != key
        && enabled(&shared, c.entry(), c.human_id)
    {
        wake(shared.clone(), c.entry());
    }
    for files in [false, true] {
        let shared = shared.clone();
        tokio::spawn(async move {
            if drain(&shared, key, human, files).await.is_err() {
                tracing::warn!("Topic projection retained without confirmed publication");
            }
        });
    }
}

async fn drain(shared: &Arc<AppShared>, key: SessionKey, human: i64, files: bool) -> Result<()> {
    'queue: while let Some(publication) = if files {
        shared.store.topic_publication_claim_files(key, human)?
    } else {
        shared.store.topic_publication_claim(key, human)?
    } {
        let _lease = Lease {
            shared: shared.clone(),
            id: publication.id,
        };
        if !publication.direct && !enabled(shared, key, human) {
            shared
                .store
                .topic_publication_not_selected(publication.id)?;
            continue;
        }
        let chunks = if publication.kind == "artifact" {
            vec![publication.body.clone()]
        } else {
            projection_parts(&publication.body, shared.config.max_text_chunk)
        };
        let parts = shared
            .store
            .topic_publication_parts(publication.id, &chunks)?;
        let transport = Projection {
            client: &shared.telegram,
            chat: publication.target.chat_id,
            topic: Some(publication.target.thread_id).filter(|id| *id > 0),
        };
        for (part, body) in parts {
            let result = if publication.kind == "artifact" {
                send_file(shared, key, human, &publication, part, &transport).await
            } else {
                transport
                    .text(&body, || {
                        // A goal control can select the integrating return on an
                        // already-running direct turn. Its opted-in source-topic
                        // projection still uses this same canonical publication.
                        if !shared
                            .store
                            .workflow_native_visible(publication.local_turn)?
                        {
                            return Ok(false);
                        }
                        if (!enabled(shared, key, human)
                            && (!publication.direct
                                || shared
                                    .store
                                    .conversation_turn_return(publication.local_turn)?))
                            || !shared
                                .store
                                .topic_publication_reserve(publication.id, part)?
                        {
                            return Ok(false);
                        }
                        Ok(true)
                    })
                    .await
            };
            match result? {
                Delivery::Acknowledged(message_id) => {
                    shared.store.topic_publication_receipt(
                        publication.id,
                        part,
                        Some(message_id),
                        false,
                    )?;
                }
                Delivery::Unsent => break,
                Delivery::CoolingDown => {
                    shared.store.topic_publication_retry(publication.id, part)?;
                    continue 'queue; // Telegram transport owns the cooldown.
                }
                unacknowledged @ (Delivery::Rejected | Delivery::Unconfirmed) => {
                    shared.store.topic_publication_receipt(
                        publication.id,
                        part,
                        None,
                        matches!(unacknowledged, Delivery::Rejected),
                    )?;
                    break;
                }
            }
        }
        shared.store.topic_publication_finish(publication.id)?;
    }
    Ok(())
}

// Limit frozen upload buffers independently of native workers. A slow secondary
// network request must never reserve a native execution slot.
static FILE_UPLOADS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(2);

async fn send_file(
    shared: &Arc<AppShared>,
    key: SessionKey,
    human: i64,
    publication: &crate::store::topic_publications::TopicPublication,
    part: i64,
    transport: &Projection<'_>,
) -> Result<Delivery> {
    let _permit = FILE_UPLOADS.acquire().await?;
    let Some(cfg) = shared
        .config
        .interaction
        .as_ref()
        .and_then(|c| c.artifact_store.clone())
    else {
        return Ok(Delivery::Unsent);
    };
    let file = match shared.store.artifact_get(human, key, &publication.source) {
        Ok(file) => file,
        Err(_) => return Ok(Delivery::Unsent),
    };
    let bytes = match tokio::task::spawn_blocking(move || {
        super::artifact_outputs::verified_bytes(&cfg, &file)
    })
    .await?
    {
        Ok(bytes) => bytes,
        Err(_) => {
            tracing::warn!("Retained file unavailable before publication; no upload attempted");
            return Ok(Delivery::Unsent);
        }
    };
    let mime = super::turns::mime_type_for_path(Path::new(&publication.body));
    let caption = shared.store.topic_file_caption(publication.id)?;
    transport
        .file(
            ProjectedFile {
                bytes,
                name: &publication.body,
                mime: mime.as_deref(),
                caption: &caption,
            },
            || {
                // Immutable file audiences and the explicit source projection
                // are independent of a later text return-surface selection.
                if !enabled(shared, key, human)
                    || shared
                        .store
                        .artifact_get(human, key, &publication.source)
                        .is_err()
                {
                    return Ok(false);
                }
                shared.store.topic_publication_reserve(publication.id, part)
            },
        )
        .await
}
