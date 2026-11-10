//! Logical conversation identity also exists before its first native context.
use super::*;
use anyhow::bail;
use serde_json::{Value, json};

const MAX_VOICE_INITIALIZATION_RECEIPTS: usize = 64;
const MAX_VOICE_INITIALIZATION_BYTES: usize = 64 * 1024;

impl Store {
    pub(super) fn init_conversation_entry(&self) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute_batch("CREATE TABLE IF NOT EXISTS conversation_entry_generations(
            session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            generation TEXT NOT NULL);
            INSERT OR IGNORE INTO conversation_entry_generations(session_id,generation)
            SELECT id,lower(hex(randomblob(16))) FROM sessions;
            CREATE TRIGGER IF NOT EXISTS conversation_entry_created AFTER INSERT ON sessions BEGIN
            INSERT INTO conversation_entry_generations(session_id,generation) VALUES(NEW.id,lower(hex(randomblob(16)))); END;
            CREATE TRIGGER IF NOT EXISTS conversation_entry_replaced AFTER UPDATE OF codex_thread_id,force_fresh_thread,creator_user_id ON sessions
            WHEN OLD.creator_user_id!=NEW.creator_user_id OR NEW.force_fresh_thread=1 OR
                (OLD.codex_thread_id IS NOT NULL AND OLD.codex_thread_id IS NOT NEW.codex_thread_id) BEGIN
            UPDATE conversation_entry_generations SET generation=lower(hex(randomblob(16))) WHERE session_id=NEW.id; END;
            CREATE TRIGGER IF NOT EXISTS conversation_entry_grant_revoked AFTER UPDATE OF allowed ON users WHEN NEW.allowed=0 BEGIN
            UPDATE conversation_entry_generations SET generation=lower(hex(randomblob(16))) WHERE session_id IN
                (SELECT id FROM sessions WHERE creator_user_id=NEW.tg_user_id); END;")?;
        add_column_if_missing(
            &conn,
            "conversation_entry_generations",
            "native_initialization",
            "TEXT",
        )?;
        Ok(())
    }

    pub fn conversation_initial_binding(
        &self,
        human: i64,
        entry: SessionKey,
    ) -> Result<Option<String>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, native) = super::presentation::entry_on(&conn, human, entry)?;
        if !native.is_empty() {
            return Ok(None);
        }
        Ok(Some(super::presentation::entry_binding(
            &conn, human, entry, session,
        )?))
    }

    /// Reserve at most one metadata creation for this logical entry. A lost
    /// response stays retained across restart; another request cannot recreate it.
    pub fn conversation_voice_initialize_claim(
        &self,
        human: i64,
        entry: SessionKey,
        expected: &str,
        token: &str,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, native) = super::presentation::entry_on(&tx, human, entry)?;
        let busy: bool = tx.query_row(
            "SELECT busy OR EXISTS(SELECT 1 FROM turns WHERE session_id=sessions.id AND status IN ('queued','running')) OR EXISTS(SELECT 1 FROM conversation_inputs WHERE session_id=sessions.id AND retired=0 AND phase IN ('queued','sending','steering')) FROM sessions WHERE id=?1",
            [session],
            |r| r.get(0),
        )?;
        if !native.is_empty()
            || busy
            || super::presentation::entry_binding(&tx, human, entry, session)? != expected
            || super::stopping::fenced_on(&tx, entry)?
            || super::maintenance_writer_held_on(&tx, entry)?
        {
            bail!("Voice entry is unavailable or changed before initialization");
        }
        let old: Option<String> = tx.query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [session],
            |r| r.get(0),
        )?;
        let mut previous = Vec::new();
        if let Some(raw) = old {
            anyhow::ensure!(
                raw.len() <= MAX_VOICE_INITIALIZATION_BYTES,
                "Native initialization metadata is unavailable"
            );
            let mut prior: Value = serde_json::from_str(&raw)?;
            // Only a different logical generation may make a fresh creation.
            // An unknown in-flight outcome remains retained even after Reset.
            anyhow::ensure!(
                prior["binding"]
                    .as_str()
                    .is_some_and(|value| value != expected)
                    && matches!(prior["phase"].as_str(), Some("bound" | "observed_unbound"))
                    && prior["native_thread"]
                        .as_str()
                        .is_some_and(|value| !value.is_empty()),
                "Native initialization is retained; do not create another thread"
            );
            if let Some(history) = prior.as_object_mut().and_then(|doc| doc.remove("previous")) {
                previous = history
                    .as_array()
                    .context("Native initialization history is unavailable")?
                    .clone();
                anyhow::ensure!(
                    previous
                        .iter()
                        .all(|doc| doc.is_object() && doc.get("previous").is_none()),
                    "Native initialization history is not flat"
                );
            }
            previous.push(prior);
        }
        anyhow::ensure!(
            previous.len() < MAX_VOICE_INITIALIZATION_RECEIPTS,
            "Native initialization retention is full; existing receipts are preserved"
        );
        let mut doc = json!({"schema":"telecodex.native-voice-initialization/v1","token":token,"human":human,"binding":expected,"phase":"creating","epoch":super::stopping::admission_epoch_on(&tx,entry)?});
        if !previous.is_empty() {
            doc["previous"] = json!(previous);
        }
        let raw = doc.to_string();
        // Reserve the bounded native ID/phase fields before thread/start so an
        // observed result always fits the same receipt, even if binding loses.
        anyhow::ensure!(
            raw.len() + 256 <= MAX_VOICE_INITIALIZATION_BYTES,
            "Native initialization retention is full; existing receipts are preserved"
        );
        tx.execute("UPDATE conversation_entry_generations SET native_initialization=?1 WHERE session_id=?2",params![raw,session])?;
        tx.commit()?;
        Ok(())
    }

    /// Keep the observed native ID even if Stop, a new owner or later work wins
    /// the binding race. This never creates a turn, goal, prompt or input receipt.
    pub fn conversation_voice_initialize_observe(
        &self,
        human: i64,
        entry: SessionKey,
        session: i64,
        token: &str,
        native: &str,
    ) -> Result<bool> {
        if native.is_empty()
            || native.len() > 128
            || !native
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
        {
            bail!("Invalid observed native initialization");
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let raw: String = tx.query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [session],
            |r| r.get(0),
        )?;
        let mut doc: Value = serde_json::from_str(&raw)?;
        if doc["token"] != token || doc["human"] != human || doc["phase"] != "creating" {
            bail!("Native initialization receipt changed");
        }
        doc["native_thread"] = json!(native);
        doc["phase"] = json!("observed_unbound");
        let eligible = super::presentation::entry_on(&tx, human, entry)
            .ok()
            .is_some_and(|(id, current)| id == session && current.is_empty())
            && super::presentation::entry_binding(&tx, human, entry, session)? == doc["binding"]
            && !super::stopping::fenced_on(&tx, entry)?
            && !super::maintenance_writer_held_on(&tx, entry)?
            && super::stopping::admission_epoch_on(&tx, entry)? == doc["epoch"]
            && tx.query_row(
                "SELECT NOT (busy OR EXISTS(SELECT 1 FROM turns WHERE session_id=sessions.id AND status IN ('queued','running')) OR EXISTS(SELECT 1 FROM conversation_inputs WHERE session_id=sessions.id AND retired=0 AND phase IN ('queued','sending','steering'))) FROM sessions WHERE id=?1",
                [session],
                |r| r.get::<_, bool>(0),
            )?;
        if eligible {
            let epoch = super::stopping::admission_epoch_on(&tx, entry)?;
            bind_initial_context_on(&tx, session, human, native, &epoch, &self.instance_id)?;
            doc["phase"] = json!("bound");
        }
        tx.execute("UPDATE conversation_entry_generations SET native_initialization=?1 WHERE session_id=?2",params![doc.to_string(),session])?;
        tx.commit()?;
        Ok(eligible)
    }

    /// Only the existing writer's first native-context event establishes this
    /// binding. No prompt is invented and no native operation occurs here.
    pub fn conversation_bind_initial(
        &self,
        human: i64,
        entry: SessionKey,
        local_turn: i64,
        expected: &str,
        native: &str,
    ) -> Result<bool> {
        if native.is_empty() {
            bail!("Native context identity is missing");
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, current) = super::presentation::entry_on(&tx, human, entry)?;
        if super::presentation::entry_binding(&tx, human, entry, session)? != expected
            || super::stopping::fenced_on(&tx, entry)?
            || super::maintenance_writer_held_on(&tx, entry)?
        {
            bail!("Initial conversation generation retired");
        }
        let owned:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM turns WHERE id=?1 AND session_id=?2 AND from_user_id=?3 AND status='running' AND (native_thread_id IS NULL OR native_thread_id=?4))",params![local_turn,session,human,native],|r|r.get(0))?;
        if !owned {
            bail!("Initial native context does not belong to this writer");
        }
        if !current.is_empty() {
            if current != native {
                bail!("Another native context already owns this entry");
            }
            return Ok(false);
        }
        let epoch = super::stopping::admission_epoch_on(&tx, entry)?;
        bind_initial_context_on(&tx, session, human, native, &epoch, &self.instance_id)?;
        tx.commit()?;
        Ok(true)
    }
}

fn bind_initial_context_on(
    conn: &Connection,
    session: i64,
    human: i64,
    native: &str,
    epoch: &str,
    instance_id: &str,
) -> Result<()> {
    // Carry derived context references before the native-binding retirement
    // triggers run. Phase and process ownership stay unchanged: old listeners
    // cannot replay their work, while retained history stays readable.
    conn.execute("UPDATE conversation_inputs SET native_thread=?1,doc=json_set(doc,'$.native',?1)
            WHERE session_id=?2 AND human_id=?3 AND native_thread='' AND retired=0 AND json_extract(doc,'$.epoch')=?4",
            params![native,session,human,epoch])?;
    conn.execute("UPDATE interaction_voice_inputs SET native=?1 WHERE session_id=?2 AND human_id=?3 AND native IS NULL AND instance_id=?4 AND phase IN ('preparing','committed') AND update_id IN
            (SELECT update_id FROM incoming_updates i JOIN bot_state e ON e.key='stop_input_epoch:'||i.update_id WHERE e.value=?5)",
            params![native,session,human,instance_id,epoch])?;
    conn.execute(
        "UPDATE sessions SET codex_thread_id=?1,force_fresh_thread=0,updated_at=?2 WHERE id=?3",
        params![native, now_string(), session],
    )?;
    conn.execute("INSERT OR IGNORE INTO conversation_returns(human_id,native_thread,source_input,selected_at)
            SELECT human_id,?1,id,?2 FROM conversation_inputs WHERE session_id=?3 AND human_id=?4 AND native_thread=?1 AND retired=0
            AND phase IN ('queued','sending','steering','routed','accepted','uncertain') ORDER BY created_at LIMIT 1",
            params![native,now_string(),session,human])?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::{ConversationInputEvent as E, ConversationVoice};
    fn setup() -> (tempfile::NamedTempFile, Store, SessionKey, String) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let key = SessionKey::new(100, Some(1));
        store
            .ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        store.clear_session_conversation(key).unwrap();
        let binding = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        (file, store, key, binding)
    }
    fn fresh_voice_entry() -> (tempfile::NamedTempFile, Store, SessionKey, String) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let key = SessionKey::new(100, Some(1));
        store
            .ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        let binding = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        (file, store, key, binding)
    }
    #[test]
    fn voice_metadata_initialization_keeps_logical_binding_without_input_or_turn() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "one-attempt")
            .unwrap();
        assert!(
            store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    id,
                    "one-attempt",
                    "native-first-voice"
                )
                .unwrap()
        );
        assert_eq!(
            store.conversation_request_binding(100, key).unwrap()["binding"],
            binding
        );
        assert_eq!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .as_deref(),
            Some("native-first-voice")
        );
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &binding, "second-attempt")
                .is_err()
        );
        let conn = store.conn.lock().unwrap();
        for table in ["turns", "conversation_inputs"] {
            assert_eq!(
                conn.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                    .get::<_, i64>(0))
                    .unwrap(),
                0
            );
        }
    }

    #[test]
    fn voice_initialization_after_explicit_reset_preserves_prior_receipt() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "first")
            .unwrap();
        assert!(
            store
                .conversation_voice_initialize_observe(100, key, id, "first", "native-first")
                .unwrap()
        );
        store.clear_session_conversation(key).unwrap();
        let next = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        assert_ne!(next, binding);
        store
            .conversation_voice_initialize_claim(100, key, &next, "after-reset")
            .unwrap();
        assert!(
            store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    id,
                    "after-reset",
                    "native-after-reset"
                )
                .unwrap()
        );
        let raw: String = store.conn.lock().unwrap().query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [id], |r| r.get(0)).unwrap();
        let doc: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(doc["native_thread"], "native-after-reset");
        assert_eq!(doc["previous"][0]["token"], "first");
        assert_eq!(doc["previous"][0]["binding"], binding);
        assert_eq!(doc["previous"][0]["native_thread"], "native-first");
        assert_eq!(doc["previous"][0]["phase"], "bound");
        assert!(doc["previous"][0].get("previous").is_none());
        for table in ["turns", "conversation_inputs"] {
            assert_eq!(
                store
                    .conn
                    .lock()
                    .unwrap()
                    .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                        .get::<_, i64>(0))
                    .unwrap(),
                0
            );
        }
    }

    #[test]
    fn explicit_reset_can_start_after_retaining_a_known_unbound_creation() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "old")
            .unwrap();
        store.clear_session_conversation(key).unwrap();
        assert!(
            !store
                .conversation_voice_initialize_observe(100, key, id, "old", "known-unbound")
                .unwrap()
        );
        let next = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        store
            .conversation_voice_initialize_claim(100, key, &next, "new")
            .unwrap();
        assert!(
            store
                .conversation_voice_initialize_observe(100, key, id, "new", "known-new")
                .unwrap()
        );
        let raw: String = store.conn.lock().unwrap().query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [id], |r| r.get(0)).unwrap();
        let doc: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(doc["previous"][0]["native_thread"], "known-unbound");
        assert_eq!(doc["previous"][0]["phase"], "observed_unbound");
        assert_eq!(doc["previous"][0]["binding"], binding);
    }

    #[test]
    fn reset_does_not_replay_an_unknown_voice_initialization() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "unknown")
            .unwrap();
        let read = || -> String {
            store.conn.lock().unwrap().query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [id], |r| r.get(0)).unwrap()
        };
        let original = read();
        store.clear_session_conversation(key).unwrap();
        let next = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        assert_ne!(next, binding);
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &next, "not-a-retry")
                .is_err()
        );
        assert_eq!(read(), original);
    }

    #[test]
    fn voice_initialization_history_is_flat_bounded_and_refuses_without_discarding() {
        let (_file, store, key, _) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        for n in 0..MAX_VOICE_INITIALIZATION_RECEIPTS {
            let binding = store.conversation_request_binding(100, key).unwrap()["binding"]
                .as_str()
                .unwrap()
                .to_owned();
            let token = format!("attempt-{n}");
            store
                .conversation_voice_initialize_claim(100, key, &binding, &token)
                .unwrap();
            assert!(
                store
                    .conversation_voice_initialize_observe(
                        100,
                        key,
                        id,
                        &token,
                        &format!("native-{n}")
                    )
                    .unwrap()
            );
            store.clear_session_conversation(key).unwrap();
        }
        let read = || -> String {
            store.conn.lock().unwrap().query_row(
            "SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",
            [id], |r| r.get(0)).unwrap()
        };
        let original = read();
        let doc: Value = serde_json::from_str(&original).unwrap();
        let previous = doc["previous"].as_array().unwrap();
        assert_eq!(previous.len(), MAX_VOICE_INITIALIZATION_RECEIPTS - 1);
        assert_eq!(previous[0]["native_thread"], "native-0");
        assert!(previous.iter().all(|doc| doc.get("previous").is_none()));
        let binding = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &binding, "capacity")
                .is_err()
        );
        assert_eq!(read(), original);
    }

    #[test]
    fn uncertain_voice_initialization_survives_restart_without_another_creation() {
        let (file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "original-attempt")
            .unwrap();
        drop(store);
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &binding, "replacement-attempt")
                .is_err()
        );
        assert!(
            store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    id,
                    "wrong-attempt",
                    "other-native"
                )
                .is_err()
        );
        assert!(
            store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    id,
                    "original-attempt",
                    "original-native"
                )
                .unwrap()
        );
        assert_eq!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .as_deref(),
            Some("original-native")
        );
    }

    #[test]
    fn stop_during_voice_initialization_preserves_observed_thread_without_binding() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "attempt")
            .unwrap();
        store.stop_begin(100, "stop-during-metadata").unwrap();
        assert!(
            !store
                .conversation_voice_initialize_observe(100, key, id, "attempt", "observed-native")
                .unwrap()
        );
        assert!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .is_none()
        );
        let raw:String=store.conn.lock().unwrap().query_row("SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",[id],|r|r.get(0)).unwrap();
        let doc: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(doc["native_thread"], "observed-native");
        assert_eq!(doc["phase"], "observed_unbound");
    }

    #[test]
    fn changed_owner_or_revoked_grant_cannot_bind_an_observed_voice_thread() {
        for change in [
            "UPDATE sessions SET creator_user_id=101",
            "UPDATE users SET allowed=0 WHERE tg_user_id=100",
        ] {
            let (_file, store, key, binding) = fresh_voice_entry();
            let id = store.get_session(key).unwrap().unwrap().id;
            store
                .conversation_voice_initialize_claim(100, key, &binding, "attempt")
                .unwrap();
            store.conn.lock().unwrap().execute(change, []).unwrap();
            assert!(
                !store
                    .conversation_voice_initialize_observe(
                        100,
                        key,
                        id,
                        "attempt",
                        "old-owner-native"
                    )
                    .unwrap()
            );
            assert!(
                store
                    .get_session(key)
                    .unwrap()
                    .unwrap()
                    .codex_thread_id
                    .is_none()
            );
            let raw:String=store.conn.lock().unwrap().query_row("SELECT native_initialization FROM conversation_entry_generations WHERE session_id=?1",[id],|r|r.get(0)).unwrap();
            assert_eq!(
                serde_json::from_str::<Value>(&raw).unwrap()["phase"],
                "observed_unbound"
            );
        }
    }

    #[test]
    fn later_work_keeps_observed_metadata_unbound_and_retains_its_original() {
        let (_file, store, key, binding) = fresh_voice_entry();
        let session = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "before-work")
            .unwrap();
        let id = Uuid::now_v7().to_string();
        store
            .conversation_input_capture(100, key, &binding, &id, "Actual later original")
            .unwrap();
        store.conversation_input_event(100, &id, E::Queue).unwrap();
        assert!(
            !store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    session,
                    "before-work",
                    "observed-native"
                )
                .unwrap()
        );
        assert!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .is_none()
        );
        assert_eq!(
            store.conversation_input_read(100, key, &id).unwrap().text,
            "Actual later original"
        );
    }

    #[test]
    fn explicit_clear_before_voice_starts_a_new_context_but_clear_during_creation_cannot_bind() {
        let (_file, store, key, _) = fresh_voice_entry();
        store.clear_session_conversation(key).unwrap();
        let binding = store.conversation_request_binding(100, key).unwrap()["binding"]
            .as_str()
            .unwrap()
            .to_owned();
        let id = store.get_session(key).unwrap().unwrap().id;
        store
            .conversation_voice_initialize_claim(100, key, &binding, "after-clear")
            .unwrap();
        store.clear_session_conversation(key).unwrap();
        assert!(
            !store
                .conversation_voice_initialize_observe(
                    100,
                    key,
                    id,
                    "after-clear",
                    "observed-before-later-clear"
                )
                .unwrap()
        );
        assert!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .is_none()
        );
    }

    #[test]
    fn busy_or_stopped_entry_refuses_voice_creation_before_claim() {
        let (_file, store, key, binding) = fresh_voice_entry();
        store.set_session_busy(key, true).unwrap();
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &binding, "busy-attempt")
                .is_err()
        );
        store.set_session_busy(key, false).unwrap();
        store.stop_begin(100, "existing-stop").unwrap();
        assert!(
            store
                .conversation_voice_initialize_claim(100, key, &binding, "stopped-attempt")
                .is_err()
        );
    }

    fn turn(store: &Store, key: SessionKey) -> i64 {
        let session = store.get_session(key).unwrap().unwrap();
        store
            .record_turn_started(
                session.id,
                &crate::models::TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: "The actual original human text".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap()
    }
    #[test]
    fn cold_read_and_first_real_turn_preserve_binding_pending_voice_and_original_identity() {
        let (_file, store, key, binding) = setup();
        assert!(
            store.interaction_presentation_list(100, key, 0, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .is_none()
        );
        let id = Uuid::now_v7().to_string();
        store
            .conversation_input_capture(100, key, &binding, &id, "The actual original human text")
            .unwrap();
        let clip = Uuid::now_v7().to_string();
        store
            .conversation_voice_capture(
                100,
                key,
                &binding,
                &clip,
                ConversationVoice {
                    transcription_profile: None,
                    preserve_original: None,
                    audio_sha256: "a".repeat(64),
                    mime: "audio/wav".into(),
                    capture_stop: None,
                    transcription: None,
                },
                true,
            )
            .unwrap();
        store.conversation_input_event(100, &id, E::Queue).unwrap();
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM conversation_returns", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
        let local = turn(&store, key);
        assert!(
            store
                .conversation_bind_initial(100, key, local, &binding, "first-native")
                .unwrap()
        );
        store
            .record_turn_native_thread(local, "first-native")
            .unwrap();
        let observed = store.conversation_input_read(100, key, &id).unwrap();
        assert_eq!(observed.native, "first-native");
        assert!(!observed.retired);
        assert_eq!(observed.text, "The actual original human text");
        let pending = store.conversation_input_read(100, key, &clip).unwrap();
        assert_eq!(pending.phase, "preparing");
        assert_eq!(pending.native, "first-native");
        store.conversation_voice_validate(100, &clip).unwrap();
        assert_eq!(
            store.conversation_request_binding(100, key).unwrap()["binding"],
            binding
        );
        assert!(
            !store
                .conversation_input_capture(100, key, &binding, &id, &observed.text)
                .unwrap()
                .1
        );
        store
            .conversation_input_event(
                100,
                &id,
                E::Begin {
                    local_turn: local,
                    steer: false,
                },
            )
            .unwrap();
        store
            .conversation_input_event(100, &id, E::Accepted { local_turn: local })
            .unwrap();
        assert!(store.conversation_turn_return(local).unwrap());
        assert!(
            !store
                .conversation_bind_initial(100, key, local, &binding, "first-native")
                .unwrap()
        );
    }
    #[test]
    fn empty_entry_clear_and_grant_aba_retire_the_captured_initial_generation() {
        for change in ["clear", "grant"] {
            let (_file, store, key, binding) = setup();
            let id = Uuid::now_v7().to_string();
            store
                .conversation_input_capture(100, key, &binding, &id, "An earlier original")
                .unwrap();
            let local = turn(&store, key);
            if change == "clear" {
                store.clear_session_conversation(key).unwrap();
            } else {
                store.conn.lock().unwrap().execute_batch("UPDATE users SET allowed=0 WHERE tg_user_id=100;UPDATE users SET allowed=1 WHERE tg_user_id=100;").unwrap();
            }
            assert!(
                store
                    .conversation_input_read(100, key, &id)
                    .unwrap()
                    .retired
            );
            assert_ne!(
                store.conversation_request_binding(100, key).unwrap()["binding"],
                binding
            );
            assert!(
                store
                    .conversation_bind_initial(100, key, local, &binding, "late-native")
                    .is_err()
            );
            assert!(
                store
                    .get_session(key)
                    .unwrap()
                    .unwrap()
                    .codex_thread_id
                    .is_none()
            );
        }
    }
    #[test]
    fn restart_preserves_logical_binding_and_unsent_history_without_replay() {
        let (file, store, key, binding) = setup();
        let id = Uuid::now_v7().to_string();
        store
            .conversation_input_capture(100, key, &binding, &id, "Retained before restart")
            .unwrap();
        drop(store);
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            store.conversation_request_binding(100, key).unwrap()["binding"],
            binding
        );
        let local = turn(&store, key);
        store
            .conversation_bind_initial(100, key, local, &binding, "fresh-native")
            .unwrap();
        let retained = store.conversation_input_read(100, key, &id).unwrap();
        assert_eq!(retained.phase, "retained_unsent");
        assert_eq!(retained.native, "fresh-native");
        assert!(!retained.retired);
        assert!(store.conversation_input_event(100, &id, E::Queue).is_err());
    }
}
