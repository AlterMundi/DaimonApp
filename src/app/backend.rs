//! Existing receiving adapters for the transport-neutral backend lifecycle.
use super::*;
use crate::backend::{Maintenance, Ownership, Recovery};

impl Maintenance for App {
    fn renew_owner(&self) -> Ownership {
        match self.shared.store.heartbeat_instance() {
            Ok(()) => Ownership::Held,
            Err(error) => {
                tracing::error!("database instance heartbeat failed: {error:#}");
                if error.to_string() == INSTANCE_LOCK_LOST_ERROR {
                    Ownership::Lost
                } else {
                    Ownership::Unavailable
                }
            }
        }
    }

    async fn recover(&self, phase: Recovery) {
        match phase {
            Recovery::OptionalProjection => {
                if self.shared.config.telegram.enabled
                    && topic_publications::recover(self.shared.clone()).is_err()
                {
                    tracing::warn!("Retained topic publication recovery unconfirmed");
                }
            }
            Recovery::NativeOutput => {
                if self.shared.config.codex.shared_app_server
                    && native_recovery::tick(self).await.is_err()
                {
                    tracing::warn!("Native output recovery remains pending; no input replayed");
                }
            }
            Recovery::KnownUnsentReturns => {
                if workflows::recover_unsent(self).await.is_err() {
                    tracing::warn!("Known-unsent workflow return recovery remains pending");
                }
            }
            Recovery::Artifacts => {
                if artifact_outputs::recover(self.shared.clone()).is_err() {
                    tracing::warn!("Retained file recovery unconfirmed");
                }
            }
        }
    }
}
