//! Owner-local publication in the existing Conversation store, before native egress.
//! No inference, Matrix transmission, new listener or human-input fabrication.
use super::*;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use ring::signature::{Ed25519KeyPair, KeyPair};
use std::{io::Read, path::PathBuf};

const MAX_PARTS: i64 = 4096;
const MAX_BYTES: i64 = 64 * 1024 * 1024;
const MAX_REQUEST: usize = 65536;
// Confirmed technical copies remain readable for a day after native expiry.
// Unknown/pending acknowledgments are never retired by this clock.
const RETAIN_MS: i64 = 24 * 60 * 60 * 1000;
const RETIRE_BATCH: i64 = 64;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PublicationConfig {
    pub surface_ref: String,
    pub audience: Vec<String>,
    pub signing_key_file: PathBuf,
}
impl PublicationConfig {
    pub(crate) fn validate(&self) -> Result<()> {
        let bounded = |s: &str| !s.is_empty() && s.chars().count() <= 256;
        anyhow::ensure!(
            bounded(&self.surface_ref)
                && !self.audience.is_empty()
                && self.audience.len() <= 256
                && self.audience.iter().all(|s| bounded(s))
                && self.audience.windows(2).all(|v| v[0] < v[1])
                && serde_json::to_vec(&self.audience)?.len() <= 32768
                && self.signing_key_file.is_absolute(),
            "Invalid selected publication resource"
        );
        Ok(())
    }
    #[cfg(unix)]
    fn signer(&self) -> Result<Ed25519KeyPair> {
        use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
        self.validate()?;
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(&self.signing_key_file)
            .context("Publication signing custody unavailable")?;
        let m = file.metadata()?;
        anyhow::ensure!(
            m.is_file()
                && m.uid() == unsafe { libc::geteuid() }
                && m.mode() & 0o077 == 0
                && m.len() == 32,
            "Unsafe publication signing custody"
        );
        let mut seed = [0u8; 32];
        file.read_exact(&mut seed)?;
        let key = Ed25519KeyPair::from_seed_unchecked(&seed);
        seed.fill(0);
        key.map_err(|_| anyhow::anyhow!("Invalid publication signing custody"))
    }
    #[cfg(not(unix))]
    fn signer(&self) -> Result<Ed25519KeyPair> {
        bail!("Owner publication requires Unix custody")
    }
    pub(crate) fn descriptor(&self) -> Result<Value> {
        let key = self.signer()?;
        Ok(
            json!({"kind":"conversation-journal/v1","surface_ref":self.surface_ref,
            "audience":self.audience,"receipt_key":URL_SAFE_NO_PAD.encode(key.public_key().as_ref())}),
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PublicationRequest {
    schema: String,
    publication_id: String,
    binding_sha256: String,
    not_after_ms: i64,
    surface_ref: String,
    audience: Vec<String>,
    part_index: u32,
    part_count: u32,
    text: String,
}
impl PublicationRequest {
    fn validate(&self, cfg: &PublicationConfig) -> Result<()> {
        cfg.validate()?;
        let id = Uuid::parse_str(&self.publication_id)?;
        let expected = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "dm:visibility:{}:{}:{}",
                self.binding_sha256, self.not_after_ms, self.part_index
            )
            .as_bytes(),
        );
        anyhow::ensure!(
            self.schema == "dm.visibility.publication/v1"
                && canonical_uuid(&self.publication_id)
                && id == expected
                && hash(&self.binding_sha256)
                && (1..(1i64 << 52)).contains(&self.not_after_ms)
                && self.surface_ref == cfg.surface_ref
                && self.audience == cfg.audience
                && (1..=32).contains(&self.part_count)
                && self.part_index < self.part_count
                && !self.text.is_empty()
                && self.text.len() <= 16384
                && serde_json::to_vec(self)?.len() <= MAX_REQUEST,
            "Publication differs from selected resource or exact bounded part"
        );
        Ok(())
    }
}
// Match Matrix's sorted, compact UTF-8 JSON regardless of serde feature unification.
fn canonical(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys = map.keys().collect::<Vec<_>>();
            keys.sort();
            format!(
                "{{{}}}",
                keys.into_iter()
                    .map(|key| format!(
                        "{}:{}",
                        serde_json::to_string(key).unwrap(),
                        canonical(&map[key])
                    ))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(canonical).collect::<Vec<_>>().join(",")
        ),
        _ => value.to_string(),
    }
}
fn publication_digest(value: &Value) -> String {
    format!("{:x}", Sha256::digest(canonical(value).as_bytes()))
}
fn signed(body: &Value, key: &Ed25519KeyPair) -> Result<Value> {
    let mut receipt = body.clone();
    receipt["signature"] =
        json!(URL_SAFE_NO_PAD.encode(key.sign(canonical(body).as_bytes()).as_ref()));
    Ok(receipt)
}
impl Store {
    pub(in crate::store) fn init_matrix_publications(&self) -> Result<()> {
        self.conn.lock().expect("store mutex poisoned").execute_batch(
            "CREATE TABLE IF NOT EXISTS conversation_matrix_publications(
             sequence INTEGER PRIMARY KEY AUTOINCREMENT,publication_id TEXT NOT NULL UNIQUE,human_id INTEGER NOT NULL,entry_session INTEGER NOT NULL REFERENCES sessions(id),
             binding TEXT NOT NULL,resource TEXT NOT NULL,receipt_key TEXT NOT NULL,request TEXT NOT NULL,
             request_sha256 TEXT NOT NULL,receipt TEXT,committed_at_ms INTEGER NOT NULL,
             not_after_ms INTEGER NOT NULL,confirmed_at_ms INTEGER);
             CREATE INDEX IF NOT EXISTS conversation_matrix_publication_owner
             ON conversation_matrix_publications(human_id,entry_session);
             CREATE TABLE IF NOT EXISTS conversation_matrix_publication_retention(
             human_id INTEGER NOT NULL,entry_session INTEGER NOT NULL REFERENCES sessions(id),
             retired_deadline_ms INTEGER NOT NULL,PRIMARY KEY(human_id,entry_session));")?;
        Ok(())
    }
    pub(crate) fn matrix_publication_commit(
        &self,
        human: i64,
        entry: SessionKey,
        cfg: &PublicationConfig,
        request: &PublicationRequest,
    ) -> Result<Value> {
        self.matrix_publication_commit_with_clock(human, entry, cfg, request, None)
    }
    #[cfg(test)]
    fn matrix_publication_commit_at(
        &self,
        human: i64,
        entry: SessionKey,
        cfg: &PublicationConfig,
        request: &PublicationRequest,
        at: i64,
    ) -> Result<Value> {
        self.matrix_publication_commit_with_clock(human, entry, cfg, request, Some(at))
    }
    fn matrix_publication_commit_with_clock(
        &self,
        human: i64,
        entry: SessionKey,
        cfg: &PublicationConfig,
        request: &PublicationRequest,
        clock: Option<i64>,
    ) -> Result<Value> {
        request.validate(cfg)?;
        let key = cfg.signer()?;
        let public = URL_SAFE_NO_PAD.encode(key.public_key().as_ref());
        let not_after = request.not_after_ms;
        let request = serde_json::to_value(request)?;
        let raw = canonical(&request);
        let sha = publication_digest(&request);
        let id = request["publication_id"]
            .as_str()
            .context("Publication identity missing")?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let at = clock.unwrap_or_else(|| Utc::now().timestamp_millis());
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let binding = super::super::presentation::entry_binding(&tx, human, entry, session)?;
        let prior: Option<(i64,i64,String,String,String,Option<String>)> = tx.query_row(
            "SELECT human_id,entry_session,binding,request,receipt_key,receipt FROM conversation_matrix_publications WHERE publication_id=?1",
            [id], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional()?;
        if let Some((owner, own_session, old_binding, previous, old_key, receipt)) = prior {
            anyhow::ensure!(
                owner == human
                    && own_session == session
                    && old_binding == binding
                    && previous == raw
                    && old_key == public,
                "Existing publication belongs to another resource, binding, key or content"
            );
            let body: Value = serde_json::from_str(
                &receipt.context("Committed publication receipt unavailable")?,
            )?;
            tx.commit()?;
            return signed(&body, &key);
        }
        anyhow::ensure!(
            !super::super::stopping::fenced_on(&tx, entry)?
                && !super::super::maintenance_writer_held_on(&tx, entry)?,
            "Publication admission is paused for this conversation"
        );
        anyhow::ensure!(
            at < not_after,
            "Fresh publication deadline expired; never republish a retired request"
        );
        let retired: i64=tx.query_row("SELECT COALESCE((SELECT retired_deadline_ms
            FROM conversation_matrix_publication_retention WHERE human_id=?1 AND entry_session=?2),0)",
            params![human,session],|r|r.get(0))?;
        anyhow::ensure!(
            not_after > retired,
            "Publication belongs to a retired deadline; never re-create it after clock rollback"
        );
        retire_on(&tx, human, session, at)?;
        let (count,bytes):(i64,i64) = tx.query_row(
            "SELECT count(*),COALESCE(sum(length(CAST(request AS BLOB))+COALESCE(length(CAST(receipt AS BLOB)),0)),0)
             FROM conversation_matrix_publications WHERE human_id=?1 AND entry_session=?2",
            params![human,session],|r| Ok((r.get(0)?,r.get(1)?)))?;
        anyhow::ensure!(
            count < MAX_PARTS && bytes + raw.len() as i64 + 16384 <= MAX_BYTES,
            "Conversation publication storage capacity reached"
        );
        anyhow::ensure!(
            (0..(1i64 << 52)).contains(&at),
            "Publication commit time out of range"
        );
        tx.execute("INSERT INTO conversation_matrix_publications(publication_id,human_id,entry_session,binding,resource,receipt_key,request,request_sha256,committed_at_ms,not_after_ms)
            VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",params![id,human,session,binding,cfg.surface_ref,public,raw,sha,at,not_after])?;
        let sequence = tx.last_insert_rowid();
        anyhow::ensure!(
            (1..(1i64 << 52)).contains(&sequence),
            "Publication sequence exhausted"
        );
        let body = json!({"schema":"dm.visibility.publication-receipt/v1","request_sha256":sha,
            "publication_id":id,"surface_ref":cfg.surface_ref,"audience":cfg.audience,
            "text_sha256":format!("{:x}",Sha256::digest(request["text"].as_str().unwrap().as_bytes())),
            "committed_at_ms":at,"sequence":sequence,"durable":true});
        tx.execute(
            "UPDATE conversation_matrix_publications SET receipt=?1 WHERE publication_id=?2",
            params![body.to_string(), id],
        )?;
        // Signing happens after the same immutable content/audience/receipt body commits.
        tx.commit()?;
        signed(&body, &key)
    }
}

fn retire_on(conn: &Connection, human: i64, session: i64, at: i64) -> Result<usize> {
    // Constant-size deadline fence replaces per-message tombstones. Keep it in
    // the same caller transaction as deletion, including on clock regression.
    conn.execute("INSERT INTO conversation_matrix_publication_retention(human_id,entry_session,retired_deadline_ms)
        SELECT ?1,?2,COALESCE(max(not_after_ms),0) FROM (
        SELECT not_after_ms FROM conversation_matrix_publications
        WHERE human_id=?1 AND entry_session=?2 AND confirmed_at_ms IS NOT NULL
        AND not_after_ms<=?3 AND confirmed_at_ms<=?3 ORDER BY sequence LIMIT ?4) WHERE true
        ON CONFLICT(human_id,entry_session) DO UPDATE SET retired_deadline_ms=max(retired_deadline_ms,excluded.retired_deadline_ms)",
        params![human,session,at.saturating_sub(RETAIN_MS),RETIRE_BATCH])?;
    Ok(conn.execute(
        "DELETE FROM conversation_matrix_publications WHERE sequence IN (
        SELECT sequence FROM conversation_matrix_publications
        WHERE human_id=?1 AND entry_session=?2 AND confirmed_at_ms IS NOT NULL
        AND not_after_ms <= ?3 AND confirmed_at_ms <= ?3
        ORDER BY sequence LIMIT ?4)",
        params![human, session, at.saturating_sub(RETAIN_MS), RETIRE_BATCH],
    )?)
}

impl Store {
    /// Trusted host only, after native journal confirmation has itself committed.
    /// This acknowledges visibility proof retention, never recipient delivery.
    pub(crate) fn matrix_publication_confirm(
        &self,
        human: i64,
        entry: SessionKey,
        cfg: &PublicationConfig,
        id: &str,
        sha: &str,
    ) -> Result<Value> {
        anyhow::ensure!(
            canonical_uuid(id) && hash(sha),
            "Exact publication identity/hash required"
        );
        // Revalidate the selected owner/resource/key against its retained proof.
        let proof = self.matrix_publication_receipt(human, entry, cfg, id)?;
        anyhow::ensure!(
            proof["request_sha256"] == sha,
            "Publication acknowledgment differs"
        );
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, _) = super::super::presentation::entry_on(&conn, human, entry)?;
        let n = conn.execute(
            "UPDATE conversation_matrix_publications
            SET confirmed_at_ms=COALESCE(confirmed_at_ms,?1)
            WHERE publication_id=?2 AND human_id=?3 AND entry_session=?4 AND request_sha256=?5",
            params![Utc::now().timestamp_millis(), id, human, session, sha],
        )?;
        anyhow::ensure!(n == 1, "Publication acknowledgment lost its exact record");
        Ok(
            json!({"publication_id":id,"publication_acknowledged":true,"receiving_delivery":"not-established"}),
        )
    }
    pub(crate) fn matrix_publication_retire(&self, human: i64, entry: SessionKey) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let n = retire_on(&tx, human, session, Utc::now().timestamp_millis())?;
        tx.commit()?;
        Ok(
            json!({"retired":n,"batch_limit":RETIRE_BATCH,"retention_ms":RETAIN_MS,"pending":"preserved"}),
        )
    }
    pub(crate) fn matrix_publication_receipt(
        &self,
        human: i64,
        entry: SessionKey,
        cfg: &PublicationConfig,
        id: &str,
    ) -> Result<Value> {
        anyhow::ensure!(canonical_uuid(id), "Canonical publication UUID required");
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, _) = super::super::presentation::entry_on(&conn, human, entry)?;
        let row: Option<(String, String, String)> = conn
            .query_row(
                "SELECT request,receipt,receipt_key FROM conversation_matrix_publications
             WHERE publication_id=?1 AND human_id=?2 AND entry_session=?3",
                params![id, human, session],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        let (raw, body, public) = row.context("Committed publication unavailable")?;
        let request: PublicationRequest = serde_json::from_str(&raw)?;
        request.validate(cfg)?;
        let key = cfg.signer()?;
        anyhow::ensure!(
            URL_SAFE_NO_PAD.encode(key.public_key().as_ref()) == public,
            "Retained publication signer changed; preserve its original custody"
        );
        signed(&serde_json::from_str(&body)?, &key)
    }
    pub(crate) fn matrix_publications(
        &self,
        human: i64,
        entry: SessionKey,
        after: i64,
    ) -> Result<Value> {
        anyhow::ensure!(after >= 0, "Nonnegative publication cursor required");
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, _) = super::super::presentation::entry_on(&conn, human, entry)?;
        let mut q = conn.prepare(
            "SELECT rowid,publication_id FROM conversation_matrix_publications
            WHERE human_id=?1 AND entry_session=?2 AND rowid>?3 ORDER BY rowid LIMIT 9",
        )?;
        let rows = q
            .query_map(params![human, session, after], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let mut items = Vec::new();
        for (sequence, id) in rows.iter().take(8) {
            if let Some(mut source) = super::super::presentation::source_on(
                &conn,
                human,
                entry,
                &format!("matrix-publication:{id}"),
            )? {
                let text = source["text"].as_str().unwrap_or("");
                let preview: String = text.chars().take(512).collect();
                source.as_object_mut().unwrap().remove("text");
                source["preview"] = json!(preview);
                source["sequence"] = json!(sequence);
                items.push(source);
            }
        }
        Ok(
            json!({"schema":"dm.visibility.publication-page/v1","items":items,
            "next_after":rows.iter().take(8).next_back().map(|v|v.0).unwrap_or(after),"more":rows.len()>8}),
        )
    }
}
pub(in crate::store) fn source_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    id: &str,
) -> Result<Option<Value>> {
    anyhow::ensure!(canonical_uuid(id), "Canonical publication UUID required");
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let row:Option<(String,String,String,i64)>=conn.query_row("SELECT request,request_sha256,binding,committed_at_ms
        FROM conversation_matrix_publications WHERE publication_id=?1 AND human_id=?2 AND entry_session=?3",
        params![id,human,session],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
    let Some((raw, sha, binding, at)) = row else {
        return Ok(None);
    };
    let r: PublicationRequest = serde_json::from_str(&raw)?;
    let current =
        super::super::presentation::entry_binding(conn, human, entry, session)? == binding;
    Ok(Some(
        json!({"id":format!("matrix-publication:{id}"),"kind":"matrix_visibility",
        "text":r.text,"label":"Communication record","current":current,"native_binding_current":current,"completed":Value::Null,
        "publication_id":id,"publication_resource":r.surface_ref,"publication_request_sha256":sha,
        "part_index":r.part_index,"part_count":r.part_count,"observed_at_ms":at,
        "observed_at":chrono::DateTime::from_timestamp_millis(at).map(|t|t.to_rfc3339()),
        "verification":"Committed owner-local visibility publication; neither human speech, model execution authority nor receiving delivery proof."}),
    ))
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    #[test]
    fn receipt_bytes_match_the_native_matrix_verifier_fixture() {
        let (_dir, _store, _entry, cfg, _) = setup();
        let v: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/matrix-publication-v1.json"
        ))
        .unwrap();
        let r: PublicationRequest = serde_json::from_value(v["request"].clone()).unwrap();
        r.validate(&cfg).unwrap();
        assert_eq!(
            publication_digest(&v["request"]),
            v["receipt"]["request_sha256"]
        );
        let mut body = v["receipt"].clone();
        body.as_object_mut().unwrap().remove("signature");
        assert_eq!(signed(&body, &cfg.signer().unwrap()).unwrap(), v["receipt"]);
        assert_eq!(cfg.descriptor().unwrap(), v["policy"]["publication"]);
    }
    fn setup() -> (
        tempfile::TempDir,
        Store,
        SessionKey,
        PublicationConfig,
        PublicationRequest,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let key = dir.path().join("publication.key");
        std::fs::write(&key, [b'p'; 32]).unwrap();
        std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600)).unwrap();
        let store = Store::open(
            &dir.path().join("app.sqlite"),
            &[100, 200],
            &crate::store::tests::defaults(),
        )
        .unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &crate::store::tests::defaults())
            .unwrap();
        let cfg = PublicationConfig {
            surface_ref: "fixture:general-conversation".into(),
            audience: vec!["human:local:00000000-0000-4000-8000-000000000100".into()],
            signing_key_file: key,
        };
        let binding = "a".repeat(64);
        let request = PublicationRequest {
            schema: "dm.visibility.publication/v1".into(),
            publication_id: Uuid::new_v5(
                &Uuid::NAMESPACE_URL,
                format!("dm:visibility:{binding}:4102444800000:0").as_bytes(),
            )
            .to_string(),
            binding_sha256: binding,
            not_after_ms: 4102444800000,
            surface_ref: cfg.surface_ref.clone(),
            audience: cfg.audience.clone(),
            part_index: 0,
            part_count: 1,
            text: "Complete attributed projection 😀\n<not human speech>".into(),
        };
        (dir, store, entry, cfg, request)
    }
    #[test]
    fn commit_then_signature_reopens_and_repeated_commit_keeps_one_publication() {
        let (dir, store, entry, cfg, r) = setup();
        let receipt = store
            .matrix_publication_commit(100, entry, &cfg, &r)
            .unwrap();
        assert_eq!(receipt["durable"], true);
        let mut body = receipt.clone();
        let sig = body.as_object_mut().unwrap().remove("signature").unwrap();
        ring::signature::UnparsedPublicKey::new(
            &ring::signature::ED25519,
            cfg.signer().unwrap().public_key().as_ref(),
        )
        .verify(
            body.to_string().as_bytes(),
            &URL_SAFE_NO_PAD.decode(sig.as_str().unwrap()).unwrap(),
        )
        .unwrap();
        assert_eq!(
            receipt["request_sha256"],
            publication_digest(&serde_json::to_value(&r).unwrap())
        );
        assert_eq!(
            store
                .matrix_publication_commit(100, entry, &cfg, &r)
                .unwrap(),
            receipt
        );
        drop(store);
        let reopened = Store::open(
            &dir.path().join("app.sqlite"),
            &[100, 200],
            &crate::store::tests::defaults(),
        )
        .unwrap();
        assert_eq!(
            reopened
                .matrix_publication_receipt(100, entry, &cfg, &r.publication_id)
                .unwrap(),
            receipt
        );
        let page = reopened.matrix_publications(100, entry, 0).unwrap();
        assert_eq!(page["items"].as_array().unwrap().len(), 1);
        assert!(page["items"][0]["revision"].as_str().is_some());
        let feed = reopened
            .interaction_presentation_page_publications(
                100,
                entry,
                0,
                0,
                Some(0),
                Some(0),
                Some(0),
                Some(0),
                false,
            )
            .unwrap();
        assert_eq!(feed["items"][0]["kind"], "matrix_visibility");
        assert!(feed["items"][0]["observed_at"].as_str().is_some());
        assert_eq!(
            reopened
                .interaction_presentation_page_publications(
                    100,
                    entry,
                    0,
                    0,
                    Some(0),
                    Some(0),
                    Some(0),
                    Some(feed["cursor"]["publications"].as_i64().unwrap()),
                    false
                )
                .unwrap()["items"],
            json!([])
        );

        let conn = reopened.conn.lock().unwrap();
        assert_eq!(
            source_on(&conn, 100, entry, &r.publication_id)
                .unwrap()
                .unwrap()["text"],
            r.text
        );
        assert_eq!(
            conn.query_row("SELECT count(*) FROM turns", [], |row| row.get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
    #[test]
    fn foreign_owner_scope_changed_content_and_binding_refuse_without_new_row() {
        let (_dir, store, entry, cfg, r) = setup();
        store
            .matrix_publication_commit(100, entry, &cfg, &r)
            .unwrap();
        assert!(store.matrix_publications(200, entry, 0).is_err());
        let mut wrong = r.clone();
        wrong.audience = vec!["fixture:other-human".into()];
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &wrong)
                .is_err()
        );
        wrong = r.clone();
        wrong.surface_ref = "fixture:other-conversation".into();
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &wrong)
                .is_err()
        );
        wrong = r.clone();
        wrong.text = "Different content under the same ID".into();
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &wrong)
                .is_err()
        );
        store.clear_session_conversation(entry).unwrap();
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &r)
                .is_err()
        );
        assert_eq!(
            store.matrix_publications(100, entry, 0).unwrap()["items"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
    }
    #[test]
    fn uncommitted_and_over_capacity_publications_never_receive_a_signature() {
        let (_dir, store, entry, cfg, r) = setup();
        assert!(
            store
                .matrix_publication_receipt(100, entry, &cfg, &r.publication_id)
                .is_err()
        );
        {
            let conn = store.conn.lock().unwrap();
            conn.execute_batch("CREATE TRIGGER fixture_no_commit BEFORE INSERT ON conversation_matrix_publications BEGIN SELECT RAISE(ABORT,'fixture storage refusal');END;").unwrap();
        }
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &r)
                .is_err()
        );
        assert_eq!(
            store.matrix_publications(100, entry, 0).unwrap()["items"],
            json!([])
        );
        {
            let conn = store.conn.lock().unwrap();
            conn.execute_batch("DROP TRIGGER fixture_no_commit")
                .unwrap();
            let session = super::super::super::presentation::entry_on(&conn, 100, entry)
                .unwrap()
                .0;
            conn.execute("INSERT INTO conversation_matrix_publications(publication_id,human_id,entry_session,binding,resource,receipt_key,request,request_sha256,committed_at_ms,not_after_ms)
             VALUES('fixture-capacity',100,?1,'','','',zeroblob(?2),'',1,1)",params![session,MAX_BYTES]).unwrap();
        }
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &r)
                .is_err()
        );
    }
    #[test]
    fn retirement_is_bounded_preserves_unknown_and_fences_expired_republication() {
        let (_dir, store, entry, cfg, template) = setup();
        let at = Utc::now().timestamp_millis();
        let deadline = at + 60_000;
        let mut originals = Vec::new();
        for i in 0..66 {
            let mut r = template.clone();
            r.binding_sha256 = format!("{:x}", Sha256::digest(format!("fixture:{i}")));
            r.not_after_ms = deadline;
            r.publication_id = Uuid::new_v5(
                &Uuid::NAMESPACE_URL,
                format!("dm:visibility:{}:{deadline}:0", r.binding_sha256).as_bytes(),
            )
            .to_string();
            let proof = store
                .matrix_publication_commit_at(100, entry, &cfg, &r, at)
                .unwrap();
            if i < 65 {
                assert!(
                    store
                        .matrix_publication_confirm(
                            100,
                            entry,
                            &cfg,
                            &r.publication_id,
                            &"0".repeat(64)
                        )
                        .is_err()
                );
                assert!(
                    store
                        .matrix_publication_confirm(
                            200,
                            entry,
                            &cfg,
                            &r.publication_id,
                            proof["request_sha256"].as_str().unwrap()
                        )
                        .is_err()
                );
                store
                    .matrix_publication_confirm(
                        100,
                        entry,
                        &cfg,
                        &r.publication_id,
                        proof["request_sha256"].as_str().unwrap(),
                    )
                    .unwrap();
            }
            originals.push(r);
        }
        let retire = |now| {
            let mut conn = store.conn.lock().unwrap();
            let tx = conn
                .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
                .unwrap();
            let (session, _) =
                super::super::super::presentation::entry_on(&tx, 100, entry).unwrap();
            let n = retire_on(&tx, 100, session, now).unwrap();
            tx.commit().unwrap();
            n
        };
        assert_eq!(retire(deadline + RETAIN_MS - 1), 0);
        assert_eq!(retire(deadline + RETAIN_MS), 64);
        assert_eq!(retire(deadline + RETAIN_MS), 1);
        assert_eq!(retire(deadline + RETAIN_MS), 0);
        assert!(
            store
                .matrix_publication_receipt(100, entry, &cfg, &originals[65].publication_id)
                .is_ok()
        );
        // A lost acknowledgment stays recoverable even after deadline/retention.
        assert!(
            store
                .matrix_publication_commit_at(
                    100,
                    entry,
                    &cfg,
                    &originals[65],
                    deadline + RETAIN_MS
                )
                .is_ok()
        );
        assert!(
            store
                .matrix_publication_commit_at(100, entry, &cfg, &originals[0], deadline + RETAIN_MS)
                .is_err()
        );
        // Even a wall-clock rollback cannot recreate a forgotten exact request.
        assert!(
            store
                .matrix_publication_commit_at(100, entry, &cfg, &originals[0], at)
                .is_err()
        );
        let mut changed = originals[0].clone();
        changed.not_after_ms += 1;
        assert!(
            store
                .matrix_publication_commit_at(100, entry, &cfg, &changed, at)
                .is_err()
        );
        changed.publication_id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "dm:visibility:{}:{}:0",
                changed.binding_sha256, changed.not_after_ms
            )
            .as_bytes(),
        )
        .to_string();
        let fresh = store
            .matrix_publication_commit_at(100, entry, &cfg, &changed, at)
            .unwrap();
        assert_eq!(fresh["sequence"], 67);
        let conn = store.conn.lock().unwrap();
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM conversation_matrix_publication_retention",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            1
        );
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM conversation_matrix_publications",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            2
        );
    }

    #[test]
    fn unsafe_signing_custody_unknown_fields_and_malformed_part_refuse() {
        let (_dir, store, entry, cfg, r) = setup();
        let mut value = serde_json::to_value(&r).unwrap();
        value["arbitrary_command"] = json!("ignored?");
        assert!(serde_json::from_value::<PublicationRequest>(value).is_err());
        let mut wrong = r.clone();
        wrong.part_count = 0;
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &wrong)
                .is_err()
        );
        std::fs::set_permissions(
            &cfg.signing_key_file,
            std::fs::Permissions::from_mode(0o644),
        )
        .unwrap();
        assert!(
            store
                .matrix_publication_commit(100, entry, &cfg, &r)
                .is_err()
        );
    }
}
