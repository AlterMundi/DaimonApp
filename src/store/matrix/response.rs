//! One bounded disposition/response intent per immutable native original.
//! The native SDK owns authoring, audience and delivery. No replay or new fuel.
use super::*;

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Command {
    Status {
        message_id: String,
    },
    Pending {
        after: Option<i64>,
    },
    Defer {
        message_id: String,
        revision: String,
        reason: String,
        condition: String,
    },
    NoReply {
        message_id: String,
        revision: String,
        reason: String,
    },
    Reply {
        message_id: String,
        revision: String,
        text: String,
    },
    Inspect {
        message_id: String,
    },
}

impl Command {
    pub(crate) fn mutates(&self) -> bool {
        matches!(
            self,
            Self::Reply { .. } | Self::Defer { .. } | Self::NoReply { .. }
        )
    }
}
fn load(conn: &Connection, human: i64, session: i64, id: &str) -> Result<Option<Value>> {
    anyhow::ensure!(
        canonical_uuid(id),
        "Canonical native original UUID required"
    );
    let raw: Option<Option<String>> = conn.query_row(
        "SELECT handling FROM interaction_matrix_inbox WHERE entry_session=?1 AND human_id=?2 AND message_id=?3",
        params![session,human,id], |r|r.get(0),
    ).optional()?;
    raw.context("Native original unavailable")?
        .map(|s| serde_json::from_str(&s).map_err(Into::into))
        .transpose()
}
fn save(conn: &Connection, human: i64, session: i64, id: &str, v: &Value) -> Result<()> {
    let raw = serde_json::to_string(v)?;
    anyhow::ensure!(
        raw.len() <= 131072,
        "Bounded native response record required"
    );
    conn.execute("UPDATE interaction_matrix_inbox SET handling=?1 WHERE entry_session=?2 AND human_id=?3 AND message_id=?4",params![raw,session,human,id])?;
    Ok(())
}
fn status(conn: &Connection, human: i64, entry: SessionKey, id: &str) -> Result<Value> {
    let (session, _) = super::super::presentation::entry_on(conn, human, entry)?;
    let source =
        super::super::presentation::source_on(conn, human, entry, &format!("matrix-inbox:{id}"))?
            .context("Native original unavailable")?;
    let mut handling =
        load(conn, human, session, id)?.unwrap_or_else(|| json!({"phase":"pending"}));
    if handling["intent"].is_object() {
        let intent = &handling["intent"];
        handling["intent"] = json!({"send_id":intent["send_id"],"source":intent["source"],"channel_id":intent["channel_id"],"effect_not_after_ms":intent["effect_not_after_ms"]});
    }
    if handling["outcome"].is_object() {
        let native = &handling["outcome"]["delivery"];
        let members = native["members"]
            .as_array()
            .map(|m| m.iter().take(8).cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        handling["outcome"] = json!({"message_id":native["message_id"],"message_hash":native["message_hash"],"thread_id":native["thread_id"],"author":native["author"],"response_context":native["response_context"],"destination":native["destination"],"native_schema":native["schema"],"members":members,"more_members":native["members"].as_array().is_some_and(|m|m.len()>8),"observation":"Authenticated native member receiving-copy receipts, not all-body/model uptake; complete evidence remains in the owning SDK journal"});
    }
    Ok(
        json!({"source":source["id"],"revision":source["revision"],"current":source["current"],"handling":handling,"meaning":"Review/defer and authored response are separate; native receipts do not prove comprehension, completion or human hearing"}),
    )
}
impl Store {
    /// `source` comes only from owner config. The actual physical turn is supplied
    /// by the authenticated tool handler, never model JSON. Claims precede I/O.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn matrix_response_prepare(
        &self,
        human: i64,
        entry: SessionKey,
        native: &str,
        physical: &str,
        command: Command,
        source: &crate::store::HeartbeatInboxSource,
        timeout_seconds: u64,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, bound) = super::super::presentation::entry_on(&tx, human, entry)?;
        anyhow::ensure!(bound == native, "Native response owner changed");
        if let Command::Pending { after } = command {
            let after = after.unwrap_or(0);
            anyhow::ensure!(after >= 0, "Bounded native pending cursor required");
            let mut q=tx.prepare("SELECT rowid,message_id FROM interaction_matrix_inbox WHERE entry_session=?1 AND human_id=?2 AND rowid>?3 AND NOT(json_extract(doc,'$.author.being_ref')=json_extract(owner,'$.being_ref') AND json_extract(doc,'$.author.embodiment_id')=json_extract(owner,'$.embodiment_id')) AND NOT EXISTS(SELECT 1 FROM interaction_matrix_results r WHERE r.message_id=interaction_matrix_inbox.message_id AND r.human_id=interaction_matrix_inbox.human_id) AND (handling IS NULL OR json_extract(handling,'$.phase') IN ('pending','deferred','submitting','submitted','uncertain')) ORDER BY rowid LIMIT 9")?;
            let rows = q
                .query_map(params![session, human, after], |r| {
                    Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            let items = rows
                .iter()
                .take(8)
                .map(|(_, id)| status(&tx, human, entry, id))
                .collect::<Result<Vec<_>>>()?;
            return Ok(
                json!({"items":items,"next_after":if rows.len()>8 {rows.get(7).map(|r|r.0)}else{None},"snapshot":"bounded current pending view, not an immutable snapshot"}),
            );
        }
        let id = match &command {
            Command::Status { message_id }
            | Command::Inspect { message_id }
            | Command::Defer { message_id, .. }
            | Command::NoReply { message_id, .. }
            | Command::Reply { message_id, .. } => message_id,
            Command::Pending { .. } => unreachable!(),
        };
        let previous = load(&tx, human, session, id)?;
        if matches!(command, Command::Status { .. }) {
            return status(&tx, human, entry, id);
        }
        if matches!(command, Command::Inspect { .. }) {
            let previous = previous.context("No retained response intent")?;
            anyhow::ensure!(
                previous["intent"].is_object(),
                "No response to inspect; no send was performed"
            );
            return Ok(
                json!({"inspect":true,"message_id":id,"intent":previous["intent"],"status":status(&tx,human,entry,id)?}),
            );
        }
        // An old owned execution cannot mutate after pause/resume, even if its
        // physical caller still has a live generic controller connection.
        let attention =
            super::super::heartbeat::owner_for_turn_on(&tx, human, entry, native, physical)?;
        let observed = super::super::presentation::source_on(
            &tx,
            human,
            entry,
            &format!("matrix-inbox:{id}"),
        )?
        .context("Native original unavailable")?;
        let revision = match &command {
            Command::Reply { revision, .. }
            | Command::Defer { revision, .. }
            | Command::NoReply { revision, .. } => revision,
            _ => unreachable!(),
        };
        anyhow::ensure!(
            observed["current"] == true && observed["revision"] == *revision,
            "Native original revision retired"
        );
        if previous.as_ref().is_some_and(|p| p["intent"].is_object()) {
            if let Command::Reply { text, .. } = &command {
                anyhow::ensure!(
                    previous.as_ref().unwrap()["intent"]["text"] == *text,
                    "Response intent is immutable; inspect its retained outcome"
                );
                return Ok(json!({"submit":false,"status":status(&tx,human,entry,id)?}));
            }
            bail!("A submitted/uncertain response cannot become a deferral");
        }
        if let Command::Defer {
            reason, condition, ..
        } = &command
        {
            anyhow::ensure!(
                !reason.trim().is_empty()
                    && reason.len() <= 1024
                    && !condition.trim().is_empty()
                    && condition.len() <= 512,
                "Bounded deferral reason and next condition required"
            );
            save(
                &tx,
                human,
                session,
                id,
                &json!({"phase":"deferred","reason":reason,"condition":condition,"source_revision":revision,"at":now_string(),"attention_owner":attention}),
            )?;
            let out = status(&tx, human, entry, id)?;
            tx.commit()?;
            return Ok(out);
        }
        if let Command::NoReply { reason, .. } = &command {
            anyhow::ensure!(
                !reason.trim().is_empty() && reason.len() <= 1024,
                "Bounded no-reply disposition reason required"
            );
            save(
                &tx,
                human,
                session,
                id,
                &json!({"phase":"no_reply","reason":reason,
                "source_revision":revision,"at":now_string(),"attention_owner":attention}),
            )?;
            let out = status(&tx, human, entry, id)?;
            tx.commit()?;
            return Ok(out);
        }
        let Command::Reply { text, .. } = &command else {
            unreachable!()
        };
        anyhow::ensure!(
            !text.trim().is_empty() && text.len() <= 8000 && (1..=60).contains(&timeout_seconds),
            "Bounded response text/deadline required"
        );
        let (raw,owner,channel):(String,String,String)=tx.query_row("SELECT doc,owner,channel FROM interaction_matrix_inbox WHERE entry_session=?1 AND human_id=?2 AND message_id=?3",params![session,human,id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        anyhow::ensure!(
            serde_json::from_str::<MatrixAuthor>(&owner)? == source.source
                && channel == source.channel_id,
            "Response owner/channel differs from retained original"
        );
        let parent: Value = serde_json::from_str(&raw)?;
        anyhow::ensure!(
            parent["state"] == "available"
                && parent["author"] != serde_json::to_value(&source.source)?,
            "Select an available peer original, not an own-body echo"
        );
        let count:i64=tx.query_row("SELECT count(*) FROM interaction_matrix_inbox WHERE entry_session=?1 AND handling IS NOT NULL AND json_type(handling,'$.intent')='object'",[session],|r|r.get(0))?;
        anyhow::ensure!(
            count < 32,
            "Finite response capacity reached; existing intents remain inspectable"
        );
        let now = Utc::now().timestamp_millis();
        let mut deadline = now + i64::try_from(timeout_seconds)? * 1000;
        if attention.is_some() {
            let allocated:i64=tx.query_row("SELECT json_extract(b.value,'$.inference_allowance.deadline_unix_ms') FROM bot_state b JOIN turns t ON b.key='heartbeat_execution:'||t.id WHERE t.session_id=?1 AND t.from_user_id=?2 AND json_extract(b.value,'$.native')=?3 AND json_extract(b.value,'$.physical')=?4",params![session,human,native,physical],|r|r.get(0))?;
            deadline = deadline.min(allocated);
        }
        anyhow::ensure!(deadline > now, "Response execution deadline exhausted");
        let intent = json!({"source":source.source,"channel_id":channel,"parent":parent,"send_id":Uuid::now_v7().to_string(),"text":text,"effect_not_after_ms":deadline});
        save(
            &tx,
            human,
            session,
            id,
            &json!({"phase":"submitting","intent":intent,"source_revision":revision,"at":now_string(),"attention_owner":attention}),
        )?;
        tx.commit()?;
        Ok(json!({"submit":true,"message_id":id,"intent":intent}))
    }
    /// A late observed outcome belongs to its original intent, even if the
    /// caller was paused/rebound. Observing it cannot authorize another send.
    pub(crate) fn matrix_response_outcome(
        &self,
        human: i64,
        entry: SessionKey,
        id: &str,
        send: &str,
        outcome: Option<Value>,
    ) -> Result<Value> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (session, _) = super::super::presentation::entry_on(&tx, human, entry)?;
        let mut previous = load(&tx, human, session, id)?.context("Missing retained response")?;
        anyhow::ensure!(
            previous["intent"]["send_id"] == send,
            "Response outcome belongs to another intent"
        );
        if let Some(result) = outcome {
            let intent = &previous["intent"];
            let parent = &intent["parent"];
            let delivery = &result["delivery"];
            let expected_parent = json!({"message_id":id,"message_hash":parent["message_hash"],"sender_being_ref":parent["author"]["being_ref"],"sender_embodiment_id":parent["author"]["embodiment_id"]});
            anyhow::ensure!(
                result["schema"] == "daimon.matrix-response-outcome/v1"
                    && result["send_id"] == send
                    && result["parent_message_id"] == id
                    && matches!(
                        delivery["schema"].as_str(),
                        Some("dm.tribe.delivery/v1" | "dm.tribe.direct-delivery/v1")
                    )
                    && delivery["send_id"] == send
                    && delivery["author"] == intent["source"]
                    && delivery["thread_id"] == parent["thread_id"]
                    && delivery["response_context"] == expected_parent
                    && delivery["message_id"].as_str().is_some_and(canonical_uuid)
                    && delivery["message_hash"].as_str().is_some_and(hash)
                    && (previous["outcome"].is_null()
                        || (previous["outcome"]["delivery"]["message_id"]
                            == delivery["message_id"]
                            && previous["outcome"]["delivery"]["message_hash"]
                                == delivery["message_hash"]))
                    && serde_json::to_vec(&result)?.len() <= 65536,
                "Invalid owner-host response receipt"
            );
            let peers = delivery["members"]
                .as_array()
                .map(|m| {
                    m.iter()
                        .filter(|p| p["being_ref"] != intent["source"]["being_ref"])
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            let proved = !peers.is_empty() && peers.iter().all(|p| p["receiving_copy"] == "proved");
            if previous["phase"] != "recipient_copy_proved" || proved {
                previous["phase"] = json!(if proved {
                    "recipient_copy_proved"
                } else {
                    "submitted"
                });
                previous["outcome"] = result;
            }
        } else if !matches!(
            previous["phase"].as_str(),
            Some("submitted" | "recipient_copy_proved")
        ) {
            previous["phase"] = json!("uncertain");
        }
        save(&tx, human, session, id, &previous)?;
        let out = status(&tx, human, entry, id)?;
        tx.commit()?;
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn setup() -> (
        tempfile::NamedTempFile,
        Store,
        SessionKey,
        crate::store::HeartbeatInboxSource,
        String,
        String,
    ) {
        let f = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(f.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        let e = SessionKey::new(100, Some(1));
        s.ensure_session(e, 100, &crate::store::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(e, "entry-native").unwrap();
        let owner = crate::store::HeartbeatInboxSource {
            source: MatrixAuthor {
                being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
                embodiment_id: "embodiment:source".into(),
            },
            channel_id: "tribe".into(),
        };
        let selection = s
            .matrix_inbox_selection(100, e, owner.source.clone(), "tribe")
            .unwrap();
        let id = Uuid::now_v7().to_string();
        let page=serde_json::from_value(json!({"schema":"daimon.matrix-inbox-page/v1","source":owner.source,"channel_id":"tribe","after":0,"next_cursor":1,"page_full":false,"meaning":"Signed fixture original, not human authority","items":[{"inbox_sequence":1,"message_id":id,"message_hash":"b".repeat(64),"thread_id":Uuid::now_v7().to_string(),"author":{"being_ref":format!("dm:being:v1:{}","B".repeat(43)),"embodiment_id":"embodiment:peer"},"destination":null,"response_context":null,"coordination":null,"text":"An original question.","state":"available"}]})).unwrap();
        let retained = s.matrix_inbox_retain(&selection, page).unwrap();
        let revision = retained["items"][0]["revision"]
            .as_str()
            .unwrap()
            .to_owned();
        (f, s, e, owner, id, revision)
    }
    fn call(
        s: &Store,
        e: SessionKey,
        owner: &crate::store::HeartbeatInboxSource,
        c: Command,
    ) -> Result<Value> {
        s.matrix_response_prepare(100, e, "entry-native", "human-physical", c, owner, 15)
    }
    fn reply(id: &str, revision: &str) -> Command {
        Command::Reply {
            message_id: id.into(),
            revision: revision.into(),
            text: "An attributed reply.".into(),
        }
    }
    #[test]
    fn no_reply_is_explicit_local_disposition_and_cannot_discard_an_uncertain_send() {
        let (_f, s, e, owner, id, revision) = setup();
        let out = call(
            &s,
            e,
            &owner,
            Command::NoReply {
                message_id: id.clone(),
                revision: revision.clone(),
                reason: "Acknowledgment needs no reply or further work".into(),
            },
        )
        .unwrap();
        assert_eq!(out["handling"]["phase"], "no_reply");
        assert!(out["handling"]["intent"].is_null());
        assert!(out["handling"]["outcome"].is_null());
        let pending = call(&s, e, &owner, Command::Pending { after: None }).unwrap();
        assert_eq!(pending["items"].as_array().unwrap().len(), 0);
        let prepared = call(&s, e, &owner, reply(&id, &revision)).unwrap();
        let send = prepared["intent"]["send_id"].as_str().unwrap();
        s.matrix_response_outcome(100, e, &id, send, None).unwrap();
        assert!(
            call(
                &s,
                e,
                &owner,
                Command::NoReply {
                    message_id: id.clone(),
                    revision,
                    reason: "Do not discard uncertainty".into(),
                }
            )
            .is_err()
        );
        assert_eq!(
            call(&s, e, &owner, Command::Status { message_id: id }).unwrap()["handling"]["phase"],
            "uncertain"
        );
    }
    #[test]
    fn response_intent_survives_uncertainty_restart_and_cannot_be_reauthored() {
        let (f, s, e, owner, id, revision) = setup();
        let prepared = call(&s, e, &owner, reply(&id, &revision)).unwrap();
        let send = prepared["intent"]["send_id"].as_str().unwrap();
        assert_eq!(prepared["submit"], true);
        assert_eq!(
            call(&s, e, &owner, reply(&id, &revision)).unwrap()["submit"],
            false
        );
        assert!(
            call(
                &s,
                e,
                &owner,
                Command::Reply {
                    message_id: id.clone(),
                    revision: revision.clone(),
                    text: "Different speech.".into()
                }
            )
            .is_err()
        );
        assert_eq!(
            s.matrix_response_outcome(100, e, &id, send, None).unwrap()["handling"]["phase"],
            "uncertain"
        );
        drop(s);
        let s = Store::open(f.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        let observed = call(
            &s,
            e,
            &owner,
            Command::Inspect {
                message_id: id.clone(),
            },
        )
        .unwrap();
        assert_eq!(observed["intent"], prepared["intent"]);
        assert_eq!(observed["status"]["handling"]["phase"], "uncertain");
        let parent = &prepared["intent"]["parent"];
        let outcome = json!({"schema":"daimon.matrix-response-outcome/v1","send_id":send,"parent_message_id":id,"delivery":{"schema":"dm.tribe.delivery/v1","send_id":send,"message_id":Uuid::now_v7().to_string(),"message_hash":"c".repeat(64),"author":owner.source,"thread_id":parent["thread_id"],"response_context":{"message_id":id,"message_hash":parent["message_hash"],"sender_being_ref":parent["author"]["being_ref"],"sender_embodiment_id":parent["author"]["embodiment_id"]}}});
        let mut changed = outcome.clone();
        changed["delivery"]["response_context"]["message_hash"] = json!("d".repeat(64));
        assert!(
            s.matrix_response_outcome(100, e, &id, send, Some(changed))
                .is_err()
        );
        assert_eq!(
            s.matrix_response_outcome(100, e, &id, send, Some(outcome.clone()))
                .unwrap()["handling"]["phase"],
            "submitted"
        );
        assert_eq!(
            s.matrix_response_outcome(100, e, &id, send, None).unwrap()["handling"]["phase"],
            "submitted"
        );
        assert_eq!(
            call(&s, e, &owner, reply(&id, &revision)).unwrap()["submit"],
            false
        );
        let mut proved = outcome.clone();
        proved["delivery"]["members"] = json!([{"being_ref":format!("dm:being:v1:{}","B".repeat(43)),"receiving_copy":"proved"}]);
        assert_eq!(
            s.matrix_response_outcome(100, e, &id, send, Some(proved))
                .unwrap()["handling"]["phase"],
            "recipient_copy_proved"
        );
        assert_eq!(
            s.matrix_response_outcome(100, e, &id, send, Some(outcome.clone()))
                .unwrap()["handling"]["phase"],
            "recipient_copy_proved"
        );
        assert!(
            call(&s, e, &owner, Command::Pending { after: None }).unwrap()["items"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        let mut changed = outcome;
        changed["delivery"]["message_id"] = json!(Uuid::now_v7().to_string());
        assert!(
            s.matrix_response_outcome(100, e, &id, send, Some(changed))
                .is_err()
        );
        assert!(
            call(
                &s,
                e,
                &owner,
                Command::Defer {
                    message_id: id,
                    revision,
                    reason: "A later excuse".into(),
                    condition: "No receipt".into()
                }
            )
            .is_err()
        );
    }
    #[test]
    fn deferred_original_stays_unresolved_readable_and_revision_exact() {
        let (f, s, e, owner, id, revision) = setup();
        let defer = Command::Defer {
            message_id: id.clone(),
            revision: revision.clone(),
            reason: "Needs an existing worker result".into(),
            condition: "Review after the correlated workflow returns".into(),
        };
        assert_eq!(
            call(&s, e, &owner, defer).unwrap()["handling"]["phase"],
            "deferred"
        );
        let pending = call(&s, e, &owner, Command::Pending { after: None }).unwrap();
        assert_eq!(pending["items"][0]["revision"], revision);
        assert_eq!(pending["items"][0]["handling"]["phase"], "deferred");
        assert!(
            call(
                &s,
                e,
                &owner,
                Command::Inspect {
                    message_id: id.clone()
                }
            )
            .is_err()
        );
        assert!(call(&s, e, &owner, reply(&id, "stale-revision")).is_err());
        drop(s);
        let s = Store::open(f.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        assert_eq!(
            call(
                &s,
                e,
                &owner,
                Command::Status {
                    message_id: id.clone()
                }
            )
            .unwrap()["handling"]["phase"],
            "deferred"
        );
        assert_eq!(
            call(&s, e, &owner, reply(&id, &revision)).unwrap()["submit"],
            true
        );
        assert!(
            s.matrix_response_prepare(
                101,
                e,
                "entry-native",
                "human-physical",
                Command::Status { message_id: id },
                &owner,
                15
            )
            .is_err()
        );
    }
    #[test]
    fn paused_owned_execution_cannot_reply_and_retains_its_conserved_account() {
        use crate::store::HeartbeatCommand as H;
        let (_f, s, e, owner, id, revision) = setup();
        let paused = s.heartbeat_control(100, e, H::Pause).unwrap();
        s.heartbeat_control(
            100,
            e,
            H::ConfigureResources {
                generation: paused["generation"].as_u64().unwrap(),
                contract: crate::store::heartbeat::test_contract(),
            },
        )
        .unwrap();
        crate::store::heartbeat::enable_test_lanes(&s, 100, e);
        let active = s
            .heartbeat_control(
                100,
                e,
                H::Resume {
                    generation: paused["generation"].as_u64().unwrap(),
                },
            )
            .unwrap();
        let session = s.get_session(e).unwrap().unwrap();
        let local = s
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: e,
                    from_user_id: 100,
                    prompt: String::new(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        {
            let mut c = s.conn.lock().unwrap();
            let tx = c.transaction().unwrap();
            crate::store::heartbeat::execution_claim_on(
                &tx,
                local,
                100,
                e,
                "entry-native",
                active["generation"].as_u64().unwrap(),
                "selected-inbox-source",
                &crate::store::heartbeat::lanes::Activation {
                    lane: crate::store::heartbeat::HeartbeatLane::Messaging,
                    generation: 1,
                },
            )
            .unwrap();
            tx.commit().unwrap();
        }
        s.heartbeat_native_started(local, "exact-physical").unwrap();
        let before = s.heartbeat_control(100, e, H::Status).unwrap()["resources"].clone();
        let deferred = s
            .matrix_response_prepare(
                100,
                e,
                "entry-native",
                "exact-physical",
                Command::Defer {
                    message_id: id.clone(),
                    revision: revision.clone(),
                    reason: "A pending observation".into(),
                    condition: "Review a selected result".into(),
                },
                &owner,
                15,
            )
            .unwrap();
        assert_eq!(deferred["handling"]["phase"], "deferred");
        s.heartbeat_control(100, e, H::Pause).unwrap();
        assert!(
            s.matrix_response_prepare(
                100,
                e,
                "entry-native",
                "exact-physical",
                reply(&id, &revision),
                &owner,
                15
            )
            .is_err()
        );
        assert_eq!(
            call(&s, e, &owner, Command::Status { message_id: id }).unwrap()["handling"]["phase"],
            "deferred"
        );
        assert_eq!(
            s.heartbeat_control(100, e, H::Status).unwrap()["resources"],
            before
        );
    }
    #[test]
    fn response_capacity_survives_restart_without_deleting_or_replaying_originals() {
        let (f, s, e, owner, id, revision) = setup();
        call(&s, e, &owner, reply(&id, &revision)).unwrap();
        let raw: String = s
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT doc FROM interaction_matrix_inbox WHERE message_id=?1",
                [&id],
                |r| r.get(0),
            )
            .unwrap();
        let mut last = String::new();
        let mut last_revision = String::new();
        for index in 2..=33 {
            let selected = s
                .matrix_inbox_selection(100, e, owner.source.clone(), "tribe")
                .unwrap();
            let mut original: Value = serde_json::from_str(&raw).unwrap();
            last = Uuid::now_v7().to_string();
            original["message_id"] = json!(last);
            original["inbox_sequence"] = json!(index);
            let page=serde_json::from_value(json!({"schema":"daimon.matrix-inbox-page/v1","source":owner.source,"channel_id":"tribe","after":selected.after,"next_cursor":index,"page_full":false,"meaning":"A distinct native original","items":[original]})).unwrap();
            let retained = s.matrix_inbox_retain(&selected, page).unwrap();
            last_revision = retained["items"][0]["revision"].as_str().unwrap().into();
            let attempted = call(&s, e, &owner, reply(&last, &last_revision));
            assert_eq!(attempted.is_ok(), index <= 32);
        }
        drop(s);
        let s = Store::open(f.path(), &[100, 101], &crate::store::tests::defaults()).unwrap();
        assert!(call(&s, e, &owner, reply(&last, &last_revision)).is_err());
        assert_eq!(
            call(&s, e, &owner, Command::Status { message_id: last }).unwrap()["handling"]["phase"],
            "pending"
        );
        assert_eq!(
            s.matrix_inbox_selection(100, e, owner.source.clone(), "tribe")
                .unwrap()
                .after,
            33
        );
        assert_eq!(
            s.conn
                .lock()
                .unwrap()
                .query_row("SELECT count(*) FROM interaction_matrix_inbox", [], |r| r
                    .get::<_, i64>(
                    0
                ))
                .unwrap(),
            33
        );
    }
}
