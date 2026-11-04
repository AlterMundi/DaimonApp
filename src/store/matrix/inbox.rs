//! Retain an authenticated owner-host inbox page before advancing its cursor.
//! Peer text is canonical source data, never a human original or admission.
use super::*;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Selection {
    human: i64,
    entry: SessionKey,
    session: i64,
    binding: String,
    epoch: String,
    native: String,
    pub owner: MatrixAuthor,
    pub channel: String,
    pub after: u64,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Item {
    inbox_sequence: u64,
    message_id: String,
    message_hash: String,
    author: MatrixAuthor,
    thread_id: String,
    destination: Value,
    response_context: Value,
    coordination: Value,
    text: Option<String>,
    state: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Page {
    schema: String,
    source: MatrixAuthor,
    channel_id: String,
    after: u64,
    next_cursor: u64,
    items: Vec<Item>,
    page_full: bool,
    meaning: String,
}
impl Selection {
    pub(in crate::store) fn belongs(
        &self,
        human: i64,
        entry: SessionKey,
        source: &crate::store::HeartbeatInboxSource,
    ) -> bool {
        self.human == human
            && self.entry == entry
            && self.owner == source.source
            && self.channel == source.channel_id
    }
}
fn key(s: &Selection) -> String {
    format!(
        "matrix-inbox-cursor:{}",
        digest(&json!([
            s.human, s.session, s.binding, s.epoch, s.owner, s.channel
        ]))
    )
}
fn author(value: &MatrixAuthor) -> Result<()> {
    MatrixDestination::Body {
        being_ref: value.being_ref.clone(),
        embodiment_id: value.embodiment_id.clone(),
    }
    .validate()
}
fn cursor(conn: &Connection, s: &Selection) -> Result<u64> {
    Ok(conn
        .query_row("SELECT value FROM bot_state WHERE key=?1", [key(s)], |r| {
            r.get::<_, String>(0)
        })
        .optional()?
        .map(|v| v.parse::<u64>())
        .transpose()?
        .unwrap_or(0))
}
fn current(conn: &Connection, s: &Selection) -> Result<bool> {
    let (session, native) = super::super::presentation::entry_on(conn, s.human, s.entry)?;
    Ok(session == s.session
        && native == s.native
        && super::super::presentation::entry_binding(conn, s.human, s.entry, session)? == s.binding
        && super::super::stopping::admission_epoch_on(conn, s.entry)? == s.epoch
        && !super::super::stopping::fenced_on(conn, s.entry)?
        && !super::super::maintenance_writer_held_on(conn, s.entry)?)
}
fn identity(item: &Item) -> Result<Value> {
    let mut value = serde_json::to_value(item)?;
    value
        .as_object_mut()
        .context("Inbox source object")?
        .remove("inbox_sequence");
    Ok(value)
}
impl Store {
    /// Internal owner selection, not model-supplied channel or SDK credentials.
    pub(crate) fn matrix_inbox_selection(
        &self,
        human: i64,
        entry: SessionKey,
        owner: MatrixAuthor,
        channel: &str,
    ) -> Result<Selection> {
        author(&owner)?;
        anyhow::ensure!(
            !channel.is_empty() && channel.len() <= 128,
            "Select one bounded inbox channel"
        );
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (session, native) = super::super::presentation::entry_on(&conn, human, entry)?;
        let mut selected = Selection {
            human,
            entry,
            session,
            binding: super::super::presentation::entry_binding(&conn, human, entry, session)?,
            epoch: super::super::stopping::admission_epoch_on(&conn, entry)?,
            native,
            owner,
            channel: channel.into(),
            after: 0,
        };
        anyhow::ensure!(current(&conn, &selected)?, "Inbox owner unavailable");
        let (count,bytes):(i64,i64)=conn.query_row("SELECT count(*),COALESCE(sum(length(CAST(doc AS BLOB))),0) FROM interaction_matrix_inbox WHERE entry_session=?1",[session],|r|Ok((r.get(0)?,r.get(1)?)))?;
        anyhow::ensure!(
            count < 256 && bytes < 4 * 1024 * 1024,
            "Inbox source capacity reached; no new source read"
        );
        selected.after = cursor(&conn, &selected)?;
        Ok(selected)
    }
    /// One SQLite transaction owns immutable events and cursor. A failed page,
    /// changed owner, capacity failure or conflicting identity advances neither.
    pub(crate) fn matrix_inbox_retain(&self, selected: &Selection, page: Page) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let value = retain_on(&tx, selected, page)?;
        tx.commit()?;
        Ok(value)
    }
}
pub(in crate::store) fn retain_on(
    conn: &Connection,
    selected: &Selection,
    page: Page,
) -> Result<Value> {
    anyhow::ensure!(
        page.schema == "daimon.matrix-inbox-page/v1"
            && page.source == selected.owner
            && page.channel_id == selected.channel
            && page.after == selected.after
            && page.items.len() <= 3
            && page.page_full == (page.items.len() == 3)
            && page.meaning.len() <= 256,
        "Inbox page differs from selected owner/channel/cursor"
    );
    let mut sequence = page.after;
    for item in &page.items {
        author(&item.author)?;
        anyhow::ensure!(
            item.inbox_sequence > sequence
                && item.inbox_sequence <= 9_007_199_254_740_991
                && canonical_uuid(&item.message_id)
                && hash(&item.message_hash)
                && canonical_uuid(&item.thread_id)
                && ((item.state == "available"
                    && item
                        .text
                        .as_ref()
                        .is_some_and(|t| !t.trim().is_empty() && t.len() <= 16384))
                    || (item.state == "unsupported_payload" && item.text.is_none()))
                && serde_json::to_vec(item)?.len() <= 65536,
            "Invalid bounded native inbox event"
        );
        sequence = item.inbox_sequence;
    }
    anyhow::ensure!(
        page.next_cursor == sequence,
        "Inbox page cursor omits retained events"
    );
    anyhow::ensure!(
        current(conn, selected)?,
        "Inbox entry retired during source read"
    );
    let prior = cursor(conn, selected)?;
    anyhow::ensure!(
        prior == page.after || prior == page.next_cursor,
        "Inbox cursor changed; inspect current selection"
    );
    for item in &page.items {
        let doc = serde_json::to_string(item)?;
        let previous:Option<String>=conn.query_row("SELECT doc FROM interaction_matrix_inbox WHERE entry_session=?1 AND human_id=?2 AND message_id=?3",params![selected.session,selected.human,item.message_id],|r|r.get(0)).optional()?;
        if let Some(previous) = previous {
            let previous: Item = serde_json::from_str(&previous)?;
            anyhow::ensure!(
                identity(&previous)? == identity(item)?,
                "Native inbox identity changed"
            );
            continue;
        }
        anyhow::ensure!(
            prior == page.after,
            "Retried page contains an unretained event"
        );
        let (count,bytes):(i64,i64)=conn.query_row("SELECT count(*),COALESCE(sum(length(CAST(doc AS BLOB))),0) FROM interaction_matrix_inbox WHERE entry_session=?1",[selected.session],|r|Ok((r.get(0)?,r.get(1)?)))?;
        anyhow::ensure!(
            count < 256 && bytes + doc.len() as i64 <= 4 * 1024 * 1024,
            "Inbox source capacity reached; native originals and cursor preserved"
        );
        conn.execute("INSERT INTO interaction_matrix_inbox(entry_session,human_id,message_id,binding,epoch,native,channel,owner,doc,created_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",params![selected.session,selected.human,item.message_id,selected.binding,selected.epoch,selected.native,selected.channel,serde_json::to_string(&selected.owner)?,doc,now_string()])?;
    }
    conn.execute("INSERT INTO bot_state(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",params![key(selected),page.next_cursor.to_string()])?;
    let mut items = vec![];
    for item in &page.items {
        let source = super::super::presentation::source_on(
            conn,
            selected.human,
            selected.entry,
            &format!("matrix-inbox:{}", item.message_id),
        )?
        .context("Retained inbox source missing")?;
        items.push(json!({"source":source["id"],"revision":source["revision"],"current":source["current"],"payload_state":source["payload_state"]}));
    }
    Ok(
        json!({"schema":"daimon.matrix-inbox-retained/v1","after":page.after,"next_cursor":page.next_cursor,"items":items,"page_full":page.page_full,"model_started":false,"peer_reply_sent":false}),
    )
}

pub(in crate::store) fn source_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    id: &str,
) -> Result<Option<Value>> {
    anyhow::ensure!(canonical_uuid(id), "Canonical native inbox source required");
    let (session, native) = super::super::presentation::entry_on(conn, human, entry)?;
    let row:Option<(String,String,String,String,String)>=conn.query_row("SELECT doc,binding,epoch,native,created_at FROM interaction_matrix_inbox WHERE entry_session=?1 AND human_id=?2 AND message_id=?3",params![session,human,id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
    let Some((raw, binding, epoch, original, observed)) = row else {
        return Ok(None);
    };
    let item: Item = serde_json::from_str(&raw)?;
    let current = native == original
        && binding == super::super::presentation::entry_binding(conn, human, entry, session)?
        && epoch == super::super::stopping::admission_epoch_on(conn, entry)?
        && !super::super::stopping::fenced_on(conn, entry)?
        && !super::super::maintenance_writer_held_on(conn, entry)?;
    Ok(Some(
        json!({"id":format!("matrix-inbox:{id}"),"kind":"matrix_inbox","text":item.text.unwrap_or_default(),"payload_state":item.state,"source_author":item.author,"matrix_message_hash":item.message_hash,"thread_id":item.thread_id,"destination":item.destination,"response_context":item.response_context,"coordination":item.coordination,"current":current,"native_binding_current":current,"completed":Value::Null,"observed_at":observed,"verification":"Owner host reports a native SDK-authenticated source; raw peer text is not human speech, receiving execution approval or a response receipt"}),
    ))
}

pub(in crate::store) fn offers_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    selected: &crate::store::HeartbeatInboxSource,
    seen: &std::collections::BTreeMap<String, String>,
) -> Result<Vec<crate::store::heartbeat::producer::Offer>> {
    let (session, native) = super::super::presentation::entry_on(conn, human, entry)?;
    let binding = super::super::presentation::entry_binding(conn, human, entry, session)?;
    let epoch = super::super::stopping::admission_epoch_on(conn, entry)?;
    let mut query=conn.prepare("SELECT m.message_id FROM interaction_matrix_inbox m WHERE m.entry_session=?1 AND m.human_id=?2 AND m.binding=?3 AND m.epoch=?4 AND m.native=?5 AND m.owner=?6 AND m.channel=?7 AND NOT EXISTS(SELECT 1 FROM json_each(?8) x WHERE x.key='matrix-inbox:'||m.message_id) AND NOT EXISTS(SELECT 1 FROM interaction_matrix_results r WHERE r.message_id=m.message_id AND r.human_id=m.human_id) AND NOT(json_extract(m.doc,'$.author.being_ref')=?9 AND json_extract(m.doc,'$.author.embodiment_id')=?10) ORDER BY m.rowid LIMIT 16")?;
    let ids = query
        .query_map(
            params![
                session,
                human,
                binding,
                epoch,
                native,
                serde_json::to_string(&selected.source)?,
                selected.channel_id,
                serde_json::to_string(seen)?,
                selected.source.being_ref,
                selected.source.embodiment_id
            ],
            |r| r.get::<_, String>(0),
        )?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let mut offers = vec![];
    for id in ids {
        let key = format!("matrix-inbox:{id}");
        let source = super::super::presentation::source_on(conn, human, entry, &key)?
            .context("Native inbox source unavailable")?;
        anyhow::ensure!(source["current"] == true, "Native inbox source retired");
        let unavailable = source["payload_state"] == "unsupported_payload";
        offers.push(crate::store::heartbeat::producer::Offer {key:key.clone(),revision:source["revision"].as_str().context("Native inbox source revision")?.into(),evidence:json!({"source":key,"revision":source["revision"],"author":source["source_author"],"message_hash":source["matrix_message_hash"],"payload_state":source["payload_state"],"text_characters":source["text_characters"],"reason":"matrix_original_available","completed":Value::Null,"source_complete":unavailable,"reader":if unavailable {Value::Null}else{json!({"operation":"conversation_part","arguments":{"source":key,"revision":source["revision"],"offset":0}})},"meaning":"Raw SDK-authenticated peer original, not human speech or execution authority; batch review is not a response or completion"})});
    }
    Ok(offers)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn setup() -> (tempfile::NamedTempFile, Store, SessionKey, MatrixAuthor) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store =
            Store::open(file.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        let entry = SessionKey::new(100, Some(1));
        store
            .ensure_session(entry, 100, &crate::store::tests::defaults())
            .unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        (
            file,
            store,
            entry,
            MatrixAuthor {
                being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
                embodiment_id: "embodiment:source".into(),
            },
        )
    }
    fn item(sequence: u64) -> Value {
        json!({"inbox_sequence":sequence,"message_id":Uuid::now_v7().to_string(),"message_hash":"a".repeat(64),"author":{"being_ref":format!("dm:being:v1:{}","B".repeat(43)),"embodiment_id":"embodiment:peer"},"thread_id":Uuid::now_v7().to_string(),"destination":null,"response_context":null,"coordination":null,"text":"Native peer α; not a human instruction.","state":"available"})
    }
    fn page(s: &Selection, items: Vec<Value>) -> Page {
        serde_json::from_value(json!({"schema":"daimon.matrix-inbox-page/v1","source":s.owner,"channel_id":s.channel,"after":s.after,"next_cursor":items.last().and_then(|i|i["inbox_sequence"].as_u64()).unwrap_or(s.after),"page_full":items.len()==3,"items":items,"meaning":"Authenticated fixture source; not execution authority"})).unwrap()
    }
    #[test]
    fn inbox_page_is_atomic_immutable_restart_safe_and_exactly_readable() {
        let (file, store, entry, owner) = setup();
        let s = store
            .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
            .unwrap();
        let first = item(1);
        let second = item(2);
        let retained = store
            .matrix_inbox_retain(&s, page(&s, vec![first.clone(), second.clone()]))
            .unwrap();
        assert_eq!(retained["next_cursor"], 2);
        assert_eq!(
            store
                .matrix_inbox_retain(&s, page(&s, vec![first.clone(), second.clone()]))
                .unwrap(),
            retained
        );
        let id = retained["items"][0]["source"].as_str().unwrap();
        let revision = retained["items"][0]["revision"].as_str().unwrap();
        let part = store
            .interaction_presentation_part(100, entry, id, revision, 0)
            .unwrap();
        assert_eq!(part["text"], first["text"]);
        assert_eq!(part["kind"], "matrix_inbox");
        assert_eq!(part["completed"], Value::Null);
        assert!(
            store
                .interaction_presentation_part(101, entry, id, revision, 0)
                .is_err()
        );
        drop(store); // Exercise a real owner exit before the supported reopen.
        let reopened =
            Store::open(file.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        let next = reopened
            .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
            .unwrap();
        assert_eq!(next.after, 2);
        // A new first item must roll back if a later identity conflicts.
        let third = item(3);
        let mut changed = first.clone();
        changed["inbox_sequence"] = json!(4);
        changed["text"] = json!("Changed bytes under the same native event");
        assert!(
            reopened
                .matrix_inbox_retain(&next, page(&next, vec![third, changed]))
                .is_err()
        );
        assert_eq!(
            reopened
                .matrix_inbox_selection(100, entry, owner, "tribe")
                .unwrap()
                .after,
            2
        );
        assert_eq!(
            reopened
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            2
        );
    }
    #[test]
    fn inbox_manual_read_survives_heartbeat_pause_but_not_entry_rebinding() {
        let (_file, store, entry, owner) = setup();
        store
            .heartbeat_control(100, entry, crate::store::HeartbeatCommand::Pause)
            .unwrap();
        let s = store
            .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
            .unwrap();
        store
            .matrix_inbox_retain(&s, page(&s, vec![item(1)]))
            .unwrap();
        let selected = store
            .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
            .unwrap();
        store
            .set_session_codex_thread(entry, "replacement-native")
            .unwrap();
        assert!(
            store
                .matrix_inbox_retain(&selected, page(&selected, vec![item(2)]))
                .is_err()
        );
        assert_eq!(
            store
                .matrix_inbox_selection(100, entry, owner, "tribe")
                .unwrap()
                .after,
            0
        );
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            1
        );
    }
    #[test]
    fn unsupported_payload_retains_native_identity_and_explicit_unavailability() {
        let (_file, store, entry, owner) = setup();
        let s = store
            .matrix_inbox_selection(100, entry, owner, "tribe")
            .unwrap();
        let mut unknown = item(1);
        unknown["text"] = Value::Null;
        unknown["state"] = json!("unsupported_payload");
        let saved = store
            .matrix_inbox_retain(&s, page(&s, vec![unknown.clone()]))
            .unwrap();
        assert_eq!(saved["next_cursor"], 1);
        assert_eq!(saved["items"][0]["payload_state"], "unsupported_payload");
        assert_eq!(
            saved["items"][0]["source"],
            format!("matrix-inbox:{}", unknown["message_id"].as_str().unwrap())
        );
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            1
        );
    }

    #[test]
    fn inbox_capacity_refuses_whole_page_and_keeps_original_cursor() {
        let (_file, store, entry, owner) = setup();
        for n in 0..85 {
            let s = store
                .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
                .unwrap();
            store
                .matrix_inbox_retain(&s, page(&s, (1..=3).map(|i| item(n * 3 + i)).collect()))
                .unwrap();
        }
        let s = store
            .matrix_inbox_selection(100, entry, owner.clone(), "tribe")
            .unwrap();
        assert_eq!(s.after, 255);
        assert!(
            store
                .matrix_inbox_retain(&s, page(&s, vec![item(256), item(257)]))
                .is_err()
        );
        assert_eq!(
            store
                .matrix_inbox_selection(100, entry, owner, "tribe")
                .unwrap()
                .after,
            255
        );
        assert_eq!(
            store
                .conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            255
        );
    }
}
