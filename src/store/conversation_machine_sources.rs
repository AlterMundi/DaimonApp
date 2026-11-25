//! Owner-local machine source offers and their atomic link to an original.
use super::*;
use crate::files::FileReference;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::Read;

const MAX_PENDING: i64 = 32;
const SOURCE_BYTES: u64 = 48 * 1024;
const UNAVAILABLE: &str = "Machine source receipt unavailable";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MachineSourceOffer {
    pub binding: String,
    pub id: Uuid,
    pub observation_id: Uuid,
    pub file: FileReference,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MachineSourceStatus {
    pub binding: String,
    pub id: Uuid,
}

impl Store {
    pub(super) fn init_conversation_machine_sources(&self) -> Result<()> {
        self.conn
            .lock()
            .expect("store mutex poisoned")
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS conversation_machine_sources (
               original TEXT PRIMARY KEY, receipt TEXT NOT NULL UNIQUE, human INTEGER NOT NULL,
               session INTEGER NOT NULL, binding TEXT NOT NULL, epoch TEXT NOT NULL,
               observation TEXT NOT NULL, file TEXT NOT NULL, expires INTEGER NOT NULL,
               retained INTEGER NOT NULL DEFAULT 0 CHECK(retained IN (0,1)));
             CREATE INDEX IF NOT EXISTS conversation_machine_sources_pending
             ON conversation_machine_sources(session,expires) WHERE retained=0;",
            )?;
        Ok(())
    }

    pub(crate) fn conversation_machine_source_reserve(
        &self,
        human: i64,
        entry: SessionKey,
        offer: MachineSourceOffer,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (session, _) = super::presentation::entry_on(&tx, human, entry)?;
        if offer.binding != super::presentation::entry_binding(&tx, human, entry, session)? {
            anyhow::bail!(UNAVAILABLE);
        }
        let epoch = super::stopping::admission_epoch_on(&tx, entry)?;
        let id = offer.id.to_string();
        let observation = offer.observation_id.to_string();
        let file = serde_json::to_string(&offer.file)?;
        let now = Utc::now().timestamp();
        let original: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM conversation_inputs WHERE id=?1)",
            [&id],
            |r| r.get(0),
        )?;
        // Do not recreate a receipt for an original retained by an older writer.
        if original {
            let exact: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM conversation_machine_sources WHERE original=?1
                   AND human=?2 AND session=?3 AND binding=?4
                   AND observation=?5 AND file=?6 AND retained=1)",
                params![id, human, session, offer.binding, observation, file],
                |r| r.get(0),
            )?;
            if !exact {
                anyhow::bail!(UNAVAILABLE);
            }
            return source_status_on(&tx, human, entry, &offer.binding, &id);
        }
        tx.execute(
            "DELETE FROM conversation_machine_sources WHERE retained=0 AND (
               (session=?1 AND (expires<=?2 OR binding<>?3 OR epoch<>?4
                OR EXISTS(SELECT 1 FROM conversation_inputs WHERE id=original))) OR (original=?5 AND expires<=?2))",
            params![session, now, offer.binding, epoch, id],
        )?;
        let existing: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM conversation_machine_sources WHERE original=?1)",
            [&id],
            |r| r.get(0),
        )?;
        if existing {
            let exact: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM conversation_machine_sources WHERE original=?1 AND human=?2
                 AND session=?3 AND binding=?4 AND epoch=?5 AND observation=?6 AND file=?7 AND retained=0)",
                params![id,human,session,offer.binding,epoch,observation,file], |r| r.get(0),
            )?;
            if !exact {
                anyhow::bail!(UNAVAILABLE);
            }
        } else {
            if super::stopping::fenced_on(&tx, entry)?
                || super::maintenance_writer_held_on(&tx, entry)?
            {
                anyhow::bail!(UNAVAILABLE);
            }
            let pending: i64 = tx.query_row(
                "SELECT count(*) FROM conversation_machine_sources WHERE session=?1 AND retained=0",
                [session],
                |r| r.get(0),
            )?;
            if pending >= MAX_PENDING {
                anyhow::bail!("Machine source reservation capacity reached");
            }
            verify_source(&tx, &offer)?;
            tx.execute(
                "INSERT INTO conversation_machine_sources(original,receipt,human,session,binding,epoch,observation,file,expires)
                 VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
                params![id,Uuid::new_v4().to_string(),human,session,offer.binding,epoch,observation,file,now+86400],
            )?;
        }
        let status = source_status_on(&tx, human, entry, &offer.binding, &id)?;
        tx.commit()?;
        Ok(status)
    }

    pub(crate) fn conversation_machine_source_status(
        &self,
        human: i64,
        entry: SessionKey,
        status: MachineSourceStatus,
    ) -> Result<Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        source_status_on(&conn, human, entry, &status.binding, &status.id.to_string())
    }
    pub(crate) fn conversation_machine_source_retained(
        &self,
        input: &super::conversation_inputs::ConversationInput,
    ) -> Result<Option<Uuid>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let receipt: Option<String> = conn
            .query_row(
                "SELECT receipt FROM conversation_machine_sources WHERE original=?1
             AND human=?2 AND session=?3 AND retained=1",
                params![input.id, input.human, input.session],
                |r| r.get(0),
            )
            .optional()?;
        Ok(receipt.as_deref().map(Uuid::parse_str).transpose()?)
    }
}

fn verify_source(conn: &Connection, offer: &MachineSourceOffer) -> Result<()> {
    if offer.file.name != "holodeck-situation.json"
        || offer.file.mime != "application/json"
        || offer.file.size == 0
        || offer.file.size > SOURCE_BYTES
    {
        anyhow::bail!("Invalid Holodeck source envelope");
    }
    let entries = crate::files::attachments(
        Path::new(conn.path().context("File storage unavailable")?),
        std::slice::from_ref(&offer.file),
    )?;
    // Read the same bounded, digest-pinned bytes checked by the file authority.
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(&entries[0].path)?;
    if !file.metadata()?.is_file() {
        anyhow::bail!("Machine source bytes changed");
    }
    let mut reader = file.take(SOURCE_BYTES + 1);
    let mut raw = Vec::new();
    reader.read_to_end(&mut raw)?;
    if raw.len() as u64 != offer.file.size
        || format!("{:x}", Sha256::digest(&raw)) != offer.file.sha256
    {
        anyhow::bail!("Machine source bytes changed");
    }
    let source: Value = serde_json::from_slice(&raw)?;
    let id = offer.id.to_string();
    let observation = &source["observation"];
    if source["schema"] != "holodeck.native-situation-source/v1"
        || source["human_input_id"] != id
        || observation["schema"] != "holodeck.situation/v1"
        || observation["id"] != offer.observation_id.to_string()
        || observation["inputAssociation"]["humanInputId"] != id
        || source["speaker"]
            .as_str()
            .and_then(|s| s.strip_prefix("human:"))
            .is_none_or(|speaker| {
                speaker.is_empty()
                    || speaker.len() > 240
                    || !speaker
                        .bytes()
                        .all(|ch| ch.is_ascii_alphanumeric() || b":._/-".contains(&ch))
            })
        || observation["observer"] != source["speaker"]
    {
        anyhow::bail!("Machine source does not match this original");
    }
    Ok(())
}

fn source_status_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    binding: &str,
    id: &str,
) -> Result<Value> {
    let (session, native) = super::presentation::entry_on(conn, human, entry)?;
    if binding != super::presentation::entry_binding(conn, human, entry, session)? {
        anyhow::bail!(UNAVAILABLE);
    }
    let epoch = super::stopping::admission_epoch_on(conn, entry)?;
    let result = conn.query_row(
        "SELECT s.receipt,s.observation,s.file,s.retained FROM conversation_machine_sources s
         LEFT JOIN conversation_inputs i ON i.id=s.original
         WHERE s.original=?1 AND s.human=?2 AND s.session=?3 AND s.binding=?5
           AND ((s.retained=0 AND i.id IS NULL AND s.epoch=?6 AND s.expires>?7)
             OR (s.retained=1 AND i.human_id=s.human AND i.session_id=s.session AND i.native_thread=?4 AND i.retired=0))",
        params![id,human,session,native,binding,epoch,Utc::now().timestamp()],
        |r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,bool>(3)?)),
    ).optional()?.context(UNAVAILABLE)?;
    let file: FileReference = serde_json::from_str(&result.2)?;
    Ok(
        json!({"schema":"telecodex.conversation-machine-source/v1","id":id,"receipt":result.0,
        "observation_id":result.1,"source_sha256":file.sha256,"retained_original":result.3,
        "speaker_verification":"asserted-by-owner-local-source","entry_binding":[human,entry,session,native]}),
    )
}

/// No receipt is inferred from a filename supplied by a device.
pub(super) fn match_machine_source(
    tx: &rusqlite::Transaction<'_>,
    input: &super::conversation_inputs::ConversationInput,
    binding: &str,
    selected: Option<Uuid>,
    existing: bool,
) -> Result<()> {
    let selected = selected.map(|id| id.to_string());
    if existing {
        let retained = tx.query_row(
            "SELECT receipt,binding FROM conversation_machine_sources WHERE original=?1 AND retained=1
                 AND human=?2 AND session=?3",
            params![input.id,input.human,input.session],
            |row|Ok((row.get::<_,String>(0)?, row.get::<_,String>(1)?)),
        ).optional()?;
        if retained != selected.map(|receipt| (receipt, binding.to_owned())) {
            anyhow::bail!("Original conversation machine source is immutable");
        }
    } else if let Some(receipt) = selected {
        let file: String = tx
            .query_row(
                "UPDATE conversation_machine_sources SET retained=1
             WHERE original=?1 AND human=?2 AND session=?3 AND binding=?4 AND epoch=?5
              AND receipt=?6 AND retained=0 AND expires>?7 RETURNING file",
                params![
                    input.id,
                    input.human,
                    input.session,
                    binding,
                    input.epoch,
                    receipt,
                    Utc::now().timestamp()
                ],
                |r| r.get(0),
            )
            .optional()?
            .context(UNAVAILABLE)?;
        let file = serde_json::from_str(&file)?;
        crate::files::attachments(
            Path::new(tx.path().context("File storage unavailable")?),
            &[file],
        )?;
    } else {
        tx.execute("DELETE FROM conversation_machine_sources WHERE original=?1 AND human=?2 AND session=?3 AND retained=0",
            params![input.id,input.human,input.session])?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup_with_native(native: bool) -> (tempfile::TempDir, Store, SessionKey, String) {
        let root = tempfile::tempdir().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(
            root.path().join("control.sqlite").as_path(),
            &[100],
            &defaults,
        )
        .unwrap();
        let entry = SessionKey::new(100, Some(1));
        store.ensure_session(entry, 100, &defaults).unwrap();
        if native {
            store
                .set_session_codex_thread(entry, "entry-native")
                .unwrap();
        }
        let list = store
            .interaction_presentation_list(100, entry, 0, 0)
            .unwrap();
        (
            root,
            store,
            entry,
            list["binding"].as_str().unwrap().to_owned(),
        )
    }

    fn setup() -> (tempfile::TempDir, Store, SessionKey, String) {
        setup_with_native(true)
    }

    fn retained_file(root: &Path, data: &[u8], name: &str) -> FileReference {
        let dir = root.join("control.sqlite.files");
        std::fs::create_dir_all(&dir).unwrap();
        let sha256 = format!("{:x}", Sha256::digest(data));
        let path = dir.join(&sha256);
        std::fs::write(&path, data).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
        FileReference {
            file_id: Uuid::new_v4().to_string(),
            sha256,
            name: name.into(),
            mime: "application/json".into(),
            size: data.len() as u64,
        }
    }

    fn offer(root: &Path, binding: &str, id: Uuid) -> MachineSourceOffer {
        let observation = Uuid::new_v4();
        let raw = serde_json::to_vec(&json!({
            "schema":"holodeck.native-situation-source/v1","human_input_id":id,"speaker":"human:fixture",
            "observation":{"id":observation,"schema":"holodeck.situation/v1","observer":"human:fixture",
            "inputAssociation":{"humanInputId":id}},
        })).unwrap();
        MachineSourceOffer {
            id,
            binding: binding.into(),
            observation_id: observation,
            file: retained_file(root, &raw, "holodeck-situation.json"),
        }
    }

    fn control_status(store: &Store, entry: SessionKey, binding: &str, id: Uuid) -> Result<Value> {
        store.conversation_machine_source_status(
            100,
            entry,
            MachineSourceStatus {
                binding: binding.into(),
                id,
            },
        )
    }

    #[test]
    fn machine_source_seals_once_with_text_without_consuming_a_human_slot() {
        let (root, store, entry, binding) = setup();
        let id = Uuid::new_v4();
        let prepared = store
            .conversation_machine_source_reserve(100, entry, offer(root.path(), &binding, id))
            .unwrap();
        assert_eq!(prepared["retained_original"], false);
        let selected = Uuid::parse_str(prepared["receipt"].as_str().unwrap()).unwrap();
        let eight = (0..8)
            .map(|i| retained_file(root.path(), i.to_string().as_bytes(), "note.json"))
            .collect::<Vec<_>>();
        let capture = |receipt| {
            store.conversation_input_capture_files(
                100,
                entry,
                &binding,
                &id.to_string(),
                "Exact input",
                None,
                None,
                None,
                eight.clone(),
                receipt,
            )
        };
        assert!(capture(Some(Uuid::new_v4())).is_err());
        assert!(
            store
                .conversation_input_read(100, entry, &id.to_string())
                .is_err()
        );
        let ingress: bool = store
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM original_ingress_order WHERE event_id=?1)",
                [id.to_string()],
                |r| r.get(0),
            )
            .unwrap();
        assert!(!ingress);
        assert_eq!(
            control_status(&store, entry, &binding, id).unwrap(),
            prepared
        );
        let (input, fresh) = capture(Some(selected)).unwrap();
        assert!(fresh);
        assert_eq!(input.files, eight);
        let proof = control_status(&store, entry, &binding, id).unwrap();
        assert_eq!(proof["receipt"], prepared["receipt"]);
        assert_eq!(proof["retained_original"], true);
        assert!(capture(None).is_err());
        assert!(capture(Some(Uuid::new_v4())).is_err());
        assert!(!capture(Some(selected)).unwrap().1);
        drop(store);
        let reopened = Store::open(
            root.path().join("control.sqlite").as_path(),
            &[100],
            &super::super::tests::defaults(),
        )
        .unwrap();
        assert_eq!(
            control_status(&reopened, entry, &binding, id).unwrap(),
            proof
        );
    }

    #[test]
    fn machine_source_voice_preserves_audio_identity_and_seals_while_preparing() {
        let (root, store, entry, binding) = setup();
        let id = Uuid::new_v4();
        let prepared = store
            .conversation_machine_source_reserve(100, entry, offer(root.path(), &binding, id))
            .unwrap();
        let receipt = Uuid::parse_str(prepared["receipt"].as_str().unwrap()).unwrap();
        let voice = super::super::conversation_inputs::ConversationVoice {
            transcription_profile: None,
            avatar_interrupt: None,
            preserve_original: None,
            audio_sha256: "a".repeat(64),
            mime: "audio/webm".into(),
            capture_stop: None,
            transcription: None,
        };
        let capture = |voice, receipt| {
            store.conversation_voice_capture_files(
                100,
                entry,
                &binding,
                &id.to_string(),
                voice,
                true,
                None,
                None,
                None,
                None,
                Vec::new(),
                receipt,
            )
        };
        assert!(capture(voice.clone(), Some(Uuid::new_v4())).is_err());
        let (input, fresh) = capture(voice.clone(), Some(receipt)).unwrap();
        assert!(fresh);
        assert_eq!(input.phase, "preparing");
        assert!(input.files.is_empty());
        let proof = control_status(&store, entry, &binding, id).unwrap();
        assert_eq!(proof["retained_original"], true);
        assert_eq!(proof["receipt"], prepared["receipt"]);
        let mut changed = voice.clone();
        changed.audio_sha256 = "b".repeat(64);
        assert!(capture(changed, Some(receipt)).is_err());
        assert!(capture(voice.clone(), None).is_err());
        assert!(!capture(voice, Some(receipt)).unwrap().1);
        drop(store);
        let reopened = Store::open(
            root.path().join("control.sqlite").as_path(),
            &[100],
            &super::super::tests::defaults(),
        )
        .unwrap();
        let original = reopened
            .conversation_input_read(100, entry, &id.to_string())
            .unwrap();
        assert_eq!(original.phase, "preparation_unconfirmed");
        assert_eq!(
            reopened
                .conversation_machine_source_retained(&original)
                .unwrap(),
            Some(receipt)
        );
        let (recovered, resumed) = reopened
            .conversation_voice_resume(100, entry, &binding, &id.to_string())
            .unwrap();
        assert!(resumed);
        assert_eq!(
            reopened
                .conversation_machine_source_retained(&recovered)
                .unwrap(),
            Some(receipt)
        );
    }

    #[test]
    fn machine_source_omission_voids_reservation_and_legacy_can_never_be_resealed() {
        let (root, store, entry, binding) = setup();
        let id = Uuid::new_v4();
        let source = offer(root.path(), &binding, id);
        let retry = MachineSourceOffer {
            id,
            binding: binding.clone(),
            observation_id: source.observation_id,
            file: source.file.clone(),
        };
        store
            .conversation_machine_source_reserve(100, entry, source)
            .unwrap();
        store
            .conversation_input_capture(100, entry, &binding, &id.to_string(), "Legacy")
            .unwrap();
        assert!(control_status(&store, entry, &binding, id).is_err());
        assert!(
            store
                .conversation_machine_source_reserve(100, entry, retry)
                .is_err()
        );
    }

    #[test]
    fn machine_source_cannot_seal_after_expiry_or_loss_of_retained_bytes() {
        let (root, store, entry, binding) = setup();
        for expired in [true, false] {
            let id = Uuid::new_v4();
            let source = offer(root.path(), &binding, id);
            let path = root
                .path()
                .join("control.sqlite.files")
                .join(&source.file.sha256);
            let prepared = store
                .conversation_machine_source_reserve(100, entry, source)
                .unwrap();
            let receipt = Uuid::parse_str(prepared["receipt"].as_str().unwrap()).unwrap();
            if expired {
                store
                    .conn
                    .lock()
                    .unwrap()
                    .execute(
                        "UPDATE conversation_machine_sources SET expires=0 WHERE original=?1",
                        [id.to_string()],
                    )
                    .unwrap();
            } else {
                std::fs::remove_file(path).unwrap();
            }
            assert!(
                store
                    .conversation_input_capture_files(
                        100,
                        entry,
                        &binding,
                        &id.to_string(),
                        "Exact original",
                        None,
                        None,
                        None,
                        Vec::new(),
                        Some(receipt),
                    )
                    .is_err()
            );
            assert!(
                store
                    .conversation_input_read(100, entry, &id.to_string())
                    .is_err()
            );
            if !expired {
                assert_eq!(
                    control_status(&store, entry, &binding, id).unwrap()["retained_original"],
                    false
                );
            }
        }
    }

    #[test]
    fn machine_source_survives_first_native_binding_before_or_after_capture() {
        let (root, store, entry, binding) = setup_with_native(false);
        let mut originals = Vec::new();
        for i in 0..2 {
            let id = Uuid::new_v4();
            let offer = offer(root.path(), &binding, id);
            let proof = store
                .conversation_machine_source_reserve(100, entry, offer)
                .unwrap();
            let receipt = Uuid::parse_str(proof["receipt"].as_str().unwrap()).unwrap();
            if i == 0 {
                assert!(
                    store
                        .conversation_input_capture_files(
                            100,
                            entry,
                            &binding,
                            &id.to_string(),
                            "Scoped original",
                            None,
                            None,
                            None,
                            Vec::new(),
                            Some(receipt)
                        )
                        .unwrap()
                        .1
                );
            }
            originals.push((id, receipt));
        }
        let session = store.get_session(entry).unwrap().unwrap();
        let local = store
            .record_turn_started(
                session.id,
                &crate::models::TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Scoped original".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        assert!(
            store
                .conversation_bind_initial(100, entry, local, &binding, "first-native")
                .unwrap()
        );
        for (i, (id, receipt)) in originals.into_iter().enumerate() {
            let capture = |source| {
                store.conversation_input_capture_files(
                    100,
                    entry,
                    &binding,
                    &id.to_string(),
                    "Scoped original",
                    None,
                    None,
                    None,
                    Vec::new(),
                    source,
                )
            };
            assert_eq!(capture(Some(receipt)).unwrap().1, i == 1);
            assert!(capture(None).is_err());
            let confirmed = control_status(&store, entry, &binding, id).unwrap();
            assert_eq!(confirmed["entry_binding"][3], "first-native");
            assert_eq!(confirmed["receipt"], receipt.to_string());
            assert_eq!(confirmed["retained_original"], true);
        }
    }
}
