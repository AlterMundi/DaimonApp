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
                body: None,
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

/// Pin the turn to its existing logical generation before native exposure.
pub(super) fn pin_codex_turn_on(conn: &Connection, local: i64) -> Result<()> {
    let changed = conn.execute(
        "UPDATE turns SET execution_generation=(
             SELECT g.generation FROM conversation_entry_generations g WHERE g.session_id=turns.session_id)
         WHERE id=?1 AND execution_harness='codex'
           AND EXISTS(SELECT 1 FROM conversation_entry_generations g WHERE g.session_id=turns.session_id
              AND (turns.execution_generation IS NULL OR turns.execution_generation=g.generation))",
        [local],
    )?;
    anyhow::ensure!(changed == 1, "Native turn execution binding changed");
    Ok(())
}

impl Store {
    /// Adopt Codex's observed native session for this turn. A legitimate
    /// replacement may advance the generation, but cannot revive an old turn.
    pub(crate) fn bind_codex_turn(&self, local: i64, native: &str) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let session: i64 = tx.query_row(
            "SELECT t.session_id FROM turns t JOIN conversation_entry_generations g ON g.session_id=t.session_id
             WHERE t.id=?1 AND t.native_thread_id=?2 AND t.execution_harness='codex'
               AND t.status='running' AND t.completed_at IS NULL AND t.execution_generation=g.generation",
            params![local, native], |row| row.get(0),
        ).optional()?.context("Codex turn binding changed before native session adoption")?;
        anyhow::ensure!(
            super::interaction::routed_native_allowed_on(&tx, local, native)?,
            "Native writer differs from the selected routed execution"
        );
        tx.execute(
            "UPDATE sessions SET codex_thread_id=?1,force_fresh_thread=0,updated_at=?2 WHERE id=?3",
            params![native, now_string(), session],
        )?;
        tx.execute("UPDATE turns SET execution_generation=(SELECT generation FROM conversation_entry_generations WHERE session_id=?2)
            WHERE id=?1", params![local, session])?;
        tx.commit()?;
        Ok(())
    }

    /// Check immediately before exposure, after the adapter's async admission
    /// preparation. Explicit isolated reviews retain their own native context.
    pub(crate) fn validate_codex_submission(
        &self,
        local: i64,
        selected_session: bool,
        routed: Option<(&str, i64)>,
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.unchecked_transaction()?;
        let valid: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id
             JOIN conversation_entry_generations g ON g.session_id=t.session_id
             WHERE t.id=?1 AND t.status='running' AND t.completed_at IS NULL
               AND t.execution_harness='codex' AND t.execution_generation=g.generation
               AND t.native_thread_id IS NOT NULL
               AND (NOT ?2 OR (t.native_thread_id=s.codex_thread_id AND s.force_fresh_thread=0)))",
            params![local, selected_session],
            |row| row.get(0),
        )?;
        anyhow::ensure!(valid, "Codex native submission binding changed");
        if let Some((id, human)) = routed {
            anyhow::ensure!(
                super::dialogue::dispatched_source_on(&tx, id, human, &self.instance_id)?
                    && super::session_requests::session_input_allowed_on(&tx, id, human)?,
                "Routed original or handoff retired before Codex submission"
            );
        }
        tx.commit()?;
        Ok(())
    }

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
        let mut binding = binding_on(&tx, key, human)?
            .context("Controller conversation is no longer owned")?
            .execution;
        let (harness, native): (String, String) = tx
            .query_row(
                "SELECT t.execution_harness,t.native_thread_id FROM turns t
                 JOIN conversation_entry_generations g ON g.session_id=t.session_id
                 WHERE t.id=?1 AND t.session_id=?2 AND t.from_user_id=?3
                   AND t.status='running' AND t.completed_at IS NULL
                   AND t.native_thread_id IS NOT NULL
                   AND (t.execution_generation=g.generation
                     OR (t.execution_harness='codex' AND t.execution_generation IS NULL))",
                params![local, binding.conversation_id, human],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?
            .context("Controller turn is no longer running")?;
        if harness == Harness::Codex.name() {
            anyhow::ensure!(
                binding.matches(Harness::Codex, &native),
                "Controller execution or native binding changed"
            );
        } else {
            binding.harness = super::conversation_inputs::portable_controller_input_on(
                &tx,
                local,
                key,
                human,
                &self.instance_id,
            )?
            .portable
            .context("Portable selection unavailable")?
            .harness;
            anyhow::ensure!(
                binding.harness.name() == harness,
                "Controller harness changed"
            );
            binding.native_session = Some(native);
        }
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
        let request = TurnRequest {
            session_key: key,
            from_user_id: 100,
            prompt: "Original".into(),
            runtime_instructions: None,
            attachments: vec![],
            review_mode: None,
            override_search_mode: None,
        };
        let turn = store.record_turn_started(owned.id, &request).unwrap();

        store.set_session_codex_thread(key, "first").unwrap();
        assert!(store.controller_execution(turn, key, 100).is_err());
        store.record_turn_native_thread(turn, "first").unwrap();
        let active = store.controller_execution(turn, key, 100).unwrap();
        assert_eq!(active.conversation_id, initial.conversation_id);
        store.native_collection_submitting(turn, None).unwrap();
        // Exercise the collector's active recovery query on this same stamp.
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE native_collections SET phase='open' WHERE local_turn=?1",
                [turn],
            )
            .unwrap();
        let recovering = store.native_collection_next().unwrap().unwrap();
        assert_eq!(recovering.local, turn);
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
        store.set_session_codex_thread(key, "first").unwrap();
        assert!(store.controller_execution(turn, key, 100).is_err());
        assert!(store.native_collection_submitting(turn, None).is_err());
        assert!(store.bind_codex_turn(turn, "first").is_err());
        assert!(store.validate_codex_submission(turn, true, None).is_err());
        assert!(store.native_collection_next().unwrap().is_none());
        assert!(
            store
                .native_collection_observed(&recovering, &[], false)
                .is_err()
        );
        assert!(
            store
                .record_collector_attachment(turn, key, 100, "first", "physical")
                .is_err()
        );
        store.set_session_codex_thread(key, "second").unwrap();
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

        let successor = store.record_turn_started(owned.id, &request).unwrap();
        store
            .record_turn_native_thread(successor, "new-native")
            .unwrap();
        assert!(
            store
                .validate_codex_submission(successor, true, None)
                .is_err()
        );
        store.bind_codex_turn(successor, "new-native").unwrap();
        store
            .validate_codex_submission(successor, true, None)
            .unwrap();
        let current = store.controller_execution(successor, key, 100).unwrap();
        assert_ne!(current.revision, reset.revision);
        assert!(current.matches(Harness::Codex, "new-native"));

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
