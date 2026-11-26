//! Read current execution authority from the existing conversation journal.
use super::*;
use crate::execution::{ExecutionBinding, Harness};

pub(super) struct BindingRead {
    pub execution: ExecutionBinding,
    pub legacy_native_session: Option<String>,
}

/// The Codex adapter's compatibility reader. The native value is meaningful
/// only in the selected harness. No new binding or conversation is created.
pub(super) fn binding_on(
    conn: &Connection,
    key: SessionKey,
    human: i64,
) -> Result<Option<BindingRead>> {
    let selected: Option<(i64, Option<String>, bool)> = conn
        .query_row(
            "SELECT s.id,s.codex_thread_id,s.force_fresh_thread
             FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1",
            params![key.chat_id, key.thread_id, human],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    selected
        .map(|(conversation_id, native_session, reset)| {
            let revision = super::presentation::entry_binding(conn, human, key, conversation_id)?;
            let execution = ExecutionBinding {
                conversation_id,
                revision,
                harness: Harness::Codex,
                native_session: if reset { None } else { native_session.clone() },
            };
            // Existing Observer history may still contain an old Codex ID
            // after reset. It is evidence, never current execution authority.
            Ok(BindingRead {
                execution,
                legacy_native_session: native_session,
            })
        })
        .transpose()
}

impl Store {
    pub(crate) fn execution_binding(
        &self,
        key: SessionKey,
        human: i64,
    ) -> Result<Option<ExecutionBinding>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let binding = binding_on(&tx, key, human)?.map(|read| read.execution);
        tx.commit()?;
        Ok(binding)
    }

    /// Authorize a live controller lease using the existing exact running turn.
    pub(crate) fn controller_execution(
        &self,
        local: i64,
        key: SessionKey,
        human: i64,
    ) -> Result<ExecutionBinding> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let binding = binding_on(&tx, key, human)?
            .context("Controller conversation is no longer owned")?
            .execution;
        let native: String = tx
            .query_row(
                "SELECT native_thread_id FROM turns WHERE id=?1 AND session_id=?2
                 AND from_user_id=?3 AND status='running' AND completed_at IS NULL
                 AND native_thread_id IS NOT NULL",
                params![local, binding.conversation_id, human],
                |row| row.get(0),
            )
            .optional()?
            .context("Controller turn is no longer running")?;
        anyhow::ensure!(
            binding.matches(Harness::Codex, &native),
            "Controller execution or native binding changed"
        );
        tx.commit()?;
        Ok(binding)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::UserRole;

    #[test]
    fn logical_identity_survives_materialization_and_fences_replaced_turns() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let key = SessionKey::new(100, Some(17));
        let owned = store.ensure_session(key, 100, &defaults).unwrap();
        let initial = store.execution_binding(key, 100).unwrap().unwrap();
        assert_eq!(initial.conversation_id, owned.id);
        assert_eq!(initial.native_session, None);
        assert!(store.execution_binding(key, 101).unwrap().is_none());
        let turn = store
            .record_turn_started(
                owned.id,
                &TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: "Original".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();

        store.set_session_codex_thread(key, "first").unwrap();
        assert!(store.controller_execution(turn, key, 100).is_err());
        store.record_turn_native_thread(turn, "first").unwrap();
        let active = store.controller_execution(turn, key, 100).unwrap();
        assert_eq!(active.conversation_id, initial.conversation_id);
        assert_eq!(active.revision, initial.revision);
        assert!(active.matches(Harness::Codex, "first"));
        assert!(!active.matches(Harness::Claude, "first"));
        assert_eq!(
            store
                .interaction_observation(key, 100)
                .unwrap()
                .unwrap()
                .execution,
            active
        );

        store.set_session_codex_thread(key, "second").unwrap();
        let replaced = store.execution_binding(key, 100).unwrap().unwrap();
        assert_eq!(replaced.conversation_id, initial.conversation_id);
        assert_ne!(replaced.revision, initial.revision);
        assert!(store.controller_execution(turn, key, 100).is_err());
        // Old databases and defensive recovery can retain an opaque native
        // ID during reset. Preserve that evidence without granting it control.
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE sessions SET force_fresh_thread=1 WHERE id=?1",
                [owned.id],
            )
            .unwrap();
        let reset = store.execution_binding(key, 100).unwrap().unwrap();
        let observed = store.interaction_observation(key, 100).unwrap().unwrap();
        assert_eq!(reset.conversation_id, initial.conversation_id);
        assert_ne!(reset.revision, replaced.revision);
        assert_eq!(reset.native_session, None);
        assert_eq!(observed.execution, reset);
        assert_eq!(observed.native_thread.as_deref(), Some("second"));
        assert!(store.validate_owned_binding(key, 100, "second").is_err());
        drop(store);
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        assert_eq!(store.execution_binding(key, 100).unwrap().unwrap(), reset);

        store.upsert_user(100, UserRole::Admin, false).unwrap();
        assert!(store.execution_binding(key, 100).unwrap().is_none());
        assert!(store.interaction_observation(key, 100).unwrap().is_none());

        // Opening a compatible reader does not rewrite historical native IDs.
        drop(store);
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let conn = store.conn.lock().unwrap();
        let retained: String = conn
            .query_row(
                "SELECT native_thread_id FROM turns WHERE id=?1",
                [turn],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(retained, "first");
    }
}
