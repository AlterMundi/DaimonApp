//! Retained creation intents and enrollment in the existing interaction registry.
use super::*;
use crate::interaction::{
    InputReference, InteractionConfig, RequestRelation, ReturnRoute, SourceInput, Target,
};
use anyhow::bail;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

impl Store {
    pub const CREATION_CONTEXT_MAX_BYTES: usize = 48_000;

    pub(super) fn init_interaction_creation(&self) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute_batch("CREATE TABLE IF NOT EXISTS interaction_creations(id TEXT PRIMARY KEY,human_id INTEGER NOT NULL,entry_chat INTEGER NOT NULL,entry_topic INTEGER NOT NULL,input_update INTEGER NOT NULL,phase TEXT NOT NULL,doc TEXT NOT NULL,topic INTEGER,instance_id TEXT NOT NULL,UNIQUE(human_id,entry_chat,entry_topic,input_update));
        CREATE TABLE IF NOT EXISTS interaction_enrollments(human_id INTEGER NOT NULL,entry_chat INTEGER NOT NULL,entry_topic INTEGER NOT NULL,target_topic INTEGER NOT NULL,session_id INTEGER NOT NULL,name TEXT NOT NULL,creation_id TEXT NOT NULL UNIQUE REFERENCES interaction_creations(id),PRIMARY KEY(human_id,entry_chat,entry_topic,target_topic));")?;
        conn.execute_batch("CREATE TABLE IF NOT EXISTS interaction_creation_receipts(creation_id TEXT PRIMARY KEY REFERENCES interaction_creations(id),event_update INTEGER NOT NULL UNIQUE REFERENCES incoming_updates(update_id),chat_id INTEGER NOT NULL,topic_id INTEGER NOT NULL,bot_id INTEGER NOT NULL,payload_sha256 TEXT NOT NULL,UNIQUE(chat_id,topic_id));")?;
        conn.execute("UPDATE interaction_creations SET phase=CASE phase WHEN 'prepared' THEN 'retained_unsent' WHEN 'creating_topic' THEN 'uncertain' ELSE 'retained_topic' END WHERE instance_id!=?1 AND phase IN ('prepared','creating_topic','topic_known')",[&self.instance_id])?;
        Ok(())
    }

    pub fn interaction_profile(&self, base: &InteractionConfig) -> Result<InteractionConfig> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut cfg = base.clone();
        let mut q=conn.prepare("SELECT e.target_topic,e.name FROM interaction_enrollments e JOIN sessions s ON s.id=e.session_id JOIN users u ON u.tg_user_id=s.creator_user_id WHERE e.human_id=?1 AND e.entry_chat=?2 AND e.entry_topic=?3 AND s.creator_user_id=?1 AND u.allowed=1 AND s.chat_id=e.entry_chat AND s.thread_id=e.target_topic ORDER BY e.target_topic")?;
        let rows = q.query_map(params![base.human_id, base.chat_id, base.topic_id], |r| {
            Ok(Target {
                topic_id: r.get(0)?,
                name: r.get(1)?,
            })
        })?;
        for target in rows {
            let target = target?;
            if !cfg.targets.iter().any(|t| t.topic_id == target.topic_id) {
                cfg.targets.push(target);
            }
        }
        if base.discover_owned_sessions {
            // Discovery is local metadata only: never enumerate unrelated native
            // history, start workers, or grant a client access to new targets.
            let mut q = conn.prepare("SELECT s.thread_id,s.session_title FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.creator_user_id=?1 AND u.allowed=1 AND s.chat_id=?2 AND s.thread_id>0 AND s.thread_id!=?3 AND s.codex_thread_id IS NOT NULL AND s.codex_thread_id!='' AND s.force_fresh_thread=0 ORDER BY s.thread_id")?;
            let rows = q.query_map(params![base.human_id, base.chat_id, base.topic_id], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, Option<String>>(1)?))
            })?;
            for row in rows {
                let (topic_id, title) = row?;
                if cfg.targets.iter().any(|t| t.topic_id == topic_id) {
                    continue;
                }
                let fallback = format!("t{topic_id}");
                let name = title
                    .filter(|name| {
                        !name.is_empty()
                            && name.len() <= 128
                            && !name.chars().any(|c| {
                                c.is_whitespace()
                                    || c.is_control()
                                    || matches!(c, '#' | '`' | '"' | '\'' | '<' | '>')
                            })
                            && name
                                .strip_prefix('t')
                                .or_else(|| name.strip_prefix('T'))
                                .is_none_or(|v| v.parse::<i64>().is_err())
                            && !cfg
                                .matrix_targets
                                .iter()
                                .any(|t| t.name.eq_ignore_ascii_case(name))
                    })
                    .unwrap_or(fallback);
                cfg.targets.push(Target { topic_id, name });
            }
        }
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn interaction_creation(&self, id: &str, human: i64) -> Result<Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        creation_on(&conn, id, human)
    }

    #[cfg(test)]
    pub fn interaction_creation_for_input(
        &self,
        key: SessionKey,
        human: i64,
        update: impl Into<InputReference>,
    ) -> Result<Value> {
        self.interaction_find_creation_for_input(key, human, update)?
            .context("No retained creation for this original input")
    }

    /// Absence is distinct from an unreadable or corrupt retained intent.
    pub fn interaction_find_creation_for_input(
        &self,
        key: SessionKey,
        human: i64,
        update: impl Into<InputReference>,
    ) -> Result<Option<Value>> {
        let update = update.into();
        update.validate()?;
        let conn = self.conn.lock().expect("store mutex poisoned");
        let id:Option<String>=conn.query_row("SELECT id FROM interaction_creations WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND input_update=?4",params![human,key.chat_id,key.thread_id,update],|r|r.get(0)).optional()?;
        id.map(|id| creation_on(&conn, &id, human)).transpose()
    }

    /// Freeze one original, attributed context package before a topic RPC.
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_prepare_creation(
        &self,
        key: SessionKey,
        human: i64,
        native: &str,
        update: impl Into<InputReference>,
        name: &str,
        reason: &str,
        context: &Value,
        capacity: usize,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<(Value, bool)> {
        let update = update.into();
        update.validate()?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let (source, _) =
            super::dialogue::original_on(&tx, key, human, native, &update, "", false)?;
        let text = source.text;
        let transcription = source.transcription;
        let tribu_source = source.tribu_source;
        if text.trim().is_empty()
            || text.trim_start().starts_with('/')
            || context.to_string().len() > Self::CREATION_CONTEXT_MAX_BYTES
        {
            return Err(anyhow!("Unsupported original input or context"));
        }
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!(
                "interaction-create:{human}:{}:{}:{update}",
                key.chat_id, key.thread_id
            )
            .as_bytes(),
        )
        .to_string();
        let mut doc = json!({"id":id,"human":human,"entry":key,"entry_native":native,"input_update":update,"name":name,"reason":reason,"context":context,"original_text":text,"origin":source.origin});
        if let Some(source) = tribu_source {
            doc["tribu_source"] = serde_json::to_value(source)?;
        }
        if let Some(transcription) = &transcription {
            doc["transcription"] = serde_json::to_value(transcription)?;
        }
        if let Some(existing) = tx
            .query_row(
                "SELECT doc FROM interaction_creations WHERE id=?1",
                [&id],
                |r| r.get::<_, String>(0),
            )
            .optional()?
        {
            let frozen: Value = serde_json::from_str(&existing)?;
            // An exact retry reuses the pre-RPC scope. A normal creation may
            // itself have since enrolled this source; do not reinterpret that
            // as a new prior dispatch or replace an existing split's scope.
            if let Some(prior) = frozen.get("prior_dispatch") {
                doc["prior_dispatch"] = prior.clone();
                if let Some(object) = doc["context"].as_object_mut() {
                    object
                        .entry("creation_scope")
                        .or_insert_with(|| frozen["context"]["creation_scope"].clone());
                }
            }
            if frozen != doc {
                return Err(anyhow!("Creation intent is immutable"));
            }
            return Ok((creation_on(&tx, &id, human)?, false));
        }
        // A mixed original may already have an immutable dispatch. Creation
        // adds exactly its confirmed topic; it never rewrites that source plan.
        let prior: Option<(String, String)> = tx.query_row(
            "SELECT id,doc FROM interaction_sources WHERE human_id=?1 AND ((update_id=?2 AND ?2 IS NOT NULL) OR (channel='conversation' AND event_id=?3 AND ?2 IS NULL))",
            params![human, update.update(), update.event()],
            |r| Ok((r.get(0)?, r.get(1)?)),
        ).optional()?;
        if let Some((source_id, raw)) = prior {
            let prior: SourceInput = serde_json::from_str(&raw)?;
            if prior.human_id != human
                || prior.text != doc["original_text"]
                || serde_json::to_value(&prior.origin)? != doc["origin"]
                || prior.transcription != transcription
                || prior.target_sessions.len() >= 64
            {
                bail!("Creation must preserve the exact routed original and target bound");
            }
            doc["prior_dispatch"] = json!({"source_id":source_id,
                "source_sha256":format!("{:x}",Sha256::digest(raw.as_bytes())),
                "meaning":"Existing dispatch and accepted work remain unchanged; this creation adds only its distinct new topic."});
            let scope = json!({"kind":"additional_creation_from_same_original",
                "name":name,"reason":reason,"prior_dispatch":doc["prior_dispatch"],
                "authority":"Owner-selected scope for the remaining distinct clause, not new human speech. Existing dispatched work remains with its receivers and must not be replayed."});
            doc["context"]
                .as_object_mut()
                .context("Scoped creation needs an object context")?
                .insert("creation_scope".into(), scope);
            if doc["context"].to_string().len() > Self::CREATION_CONTEXT_MAX_BYTES {
                bail!("Scoped creation context exceeds its existing bound");
            }
        }
        let duplicate: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM interaction_creations WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND lower(json_extract(doc,'$.name'))=lower(?4))",
            params![human,key.chat_id,key.thread_id,name], |r|r.get(0),
        )?;
        if duplicate {
            return Err(anyhow!(
                "A retained creation already reserves this title; inspect it instead of duplicating it"
            ));
        }
        let reserved:i64=tx.query_row("SELECT count(*) FROM interaction_creations WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3",params![human,key.chat_id,key.thread_id],|r|r.get(0))?;
        if reserved >= capacity as i64 {
            return Err(anyhow!("Creation capacity is already reserved"));
        }
        tx.execute("INSERT INTO interaction_creations(id,human_id,entry_chat,entry_topic,input_update,phase,doc,instance_id) VALUES(?1,?2,?3,?4,?5,'prepared',?6,?7)",params![id,human,key.chat_id,key.thread_id,update,doc.to_string(),self.instance_id])?;
        if closed.is_cancelled() {
            return Err(anyhow!("Native request closed before creation commitment"));
        }
        tx.commit()?;
        drop(conn);
        Ok((self.interaction_creation(&id, human)?, true))
    }

    /// Claim only a known-unsent mutation or a confirmed topic for explicit
    /// recovery. Concurrent calls, completed plans and unknown effects only inspect.
    pub fn interaction_creation_resume(
        &self,
        key: SessionKey,
        human: i64,
        update: impl Into<InputReference>,
        closed: &tokio_util::sync::CancellationToken,
    ) -> Result<(Value, bool)> {
        let update = update.into();
        update.validate()?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let id:String=tx.query_row("SELECT id FROM interaction_creations WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND input_update=?4",params![human,key.chat_id,key.thread_id,update],|r|r.get(0))?;
        let operation = creation_on(&tx, &id, human)?;
        let phase = match operation["phase"].as_str() {
            Some("retained_unsent") => "prepared",
            Some("retained_topic") => "topic_known",
            _ => return Ok((operation, false)),
        };
        eligible(&tx, &operation)?;
        tx.execute(
            "UPDATE interaction_creations SET phase=?1,instance_id=?2 WHERE id=?3",
            params![phase, self.instance_id, id],
        )?;
        if closed.is_cancelled() {
            return Err(anyhow!("Native request closed before recovery commitment"));
        }
        let operation = creation_on(&tx, &id, human)?;
        tx.commit()?;
        Ok((operation, true))
    }

    /// Associate an operator-selected retained own-bot service event, never
    /// manufacture an RPC receipt or retry an uncertain createForumTopic call.
    pub fn interaction_creation_reconcile(
        &self,
        id: &str,
        human: i64,
        bot: i64,
        event: i64,
        reserved: &[i64],
    ) -> Result<(Value, bool)> {
        anyhow::ensure!(
            bot > 0 && reserved.len() <= 128 && reserved.iter().all(|v| *v > 0),
            "Invalid receipt selection"
        );
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let op = creation_on(&tx, id, human)?;
        let selected: Option<(i64, i64)> = tx.query_row("SELECT event_update,bot_id FROM interaction_creation_receipts WHERE creation_id=?1", [id], |r| Ok((r.get(0)?,r.get(1)?))).optional()?;
        if let Some(prior) = selected {
            anyhow::ensure!(
                prior == (event, bot),
                "Retained creation evidence is immutable"
            );
            return Ok((op, false));
        }
        eligible(&tx, &op)?;
        anyhow::ensure!(
            op["phase"] == "uncertain" && op["topic"].is_null(),
            "Creation does not need receipt reconciliation"
        );
        let key: SessionKey = serde_json::from_value(op["intent"]["entry"].clone())?;
        let original: InputReference =
            serde_json::from_value(op["intent"]["input_update"].clone())?;
        let original = original
            .update()
            .context("Telegram receipt requires an original Telegram input")?;
        anyhow::ensure!(
            event > original,
            "Service event predates the selected original"
        );
        let name = op["intent"]["name"]
            .as_str()
            .context("Missing retained title")?;
        let raw: String = tx.query_row(
            "SELECT payload_json FROM incoming_updates WHERE update_id=?1",
            [event],
            |r| r.get(0),
        )?;
        anyhow::ensure!(raw.len() <= 16384, "Service evidence exceeds bound");
        let update: crate::telegram::Update = serde_json::from_str(&raw)?;
        let m = update.message.context("Missing service message")?;
        let topic = m.message_thread_id.context("Missing service topic")?;
        anyhow::ensure!(
            update.update_id == event
                && m.chat.id == key.chat_id
                && m.message_id > 0
                && topic > 0
                && topic != key.thread_id,
            "Service event does not match this entry"
        );
        anyhow::ensure!(
            m.from.as_ref().is_some_and(|u| u.id == bot && u.is_bot),
            "Service author is not the configured bot"
        );
        anyhow::ensure!(
            m.forum_topic_created
                .as_ref()
                .is_some_and(|t| t.name == name && t.is_name_implicit != Some(true)),
            "Service title does not match the retained creation"
        );
        anyhow::ensure!(
            !reserved.contains(&topic),
            "Topic already belongs to the configured registry"
        );
        let matching: i64 = tx.query_row("SELECT count(*) FROM incoming_updates WHERE update_id>?1 AND json_extract(payload_json,'$.message.chat.id')=?2 AND json_extract(payload_json,'$.message.from.id')=?3 AND json_extract(payload_json,'$.message.from.is_bot')=1 AND json_extract(payload_json,'$.message.forum_topic_created.name')=?4", params![original,key.chat_id,bot,name], |r| r.get(0))?;
        let intents: i64 = tx.query_row("SELECT count(*) FROM interaction_creations WHERE entry_chat=?1 AND lower(json_extract(doc,'$.name'))=lower(?2)",params![key.chat_id,name],|r|r.get(0))?;
        anyhow::ensure!(
            matching == 1 && intents == 1,
            "Retained creation correlation is ambiguous"
        );
        let used: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM sessions WHERE chat_id=?1 AND thread_id=?2) OR EXISTS(SELECT 1 FROM interaction_creations WHERE entry_chat=?1 AND topic=?2) OR EXISTS(SELECT 1 FROM interaction_enrollments WHERE entry_chat=?1 AND target_topic=?2)",params![key.chat_id,topic],|r|r.get(0))?;
        anyhow::ensure!(!used, "Service topic already has an owner or receipt");
        for target in [key, SessionKey::new(key.chat_id, Some(topic))] {
            anyhow::ensure!(
                !super::stopping::fenced_on(&tx, target)?
                    && !super::maintenance_writer_held_on(&tx, target)?,
                "Selected creation is held"
            );
        }
        tx.execute("INSERT INTO interaction_creation_receipts(creation_id,event_update,chat_id,topic_id,bot_id,payload_sha256) VALUES(?1,?2,?3,?4,?5,?6)",params![id,event,key.chat_id,topic,bot,format!("{:x}",Sha256::digest(raw.as_bytes()))])?;
        anyhow::ensure!(tx.execute("UPDATE interaction_creations SET phase='retained_topic',topic=?1 WHERE id=?2 AND human_id=?3 AND phase='uncertain' AND topic IS NULL",params![topic,id,human])? == 1, "Creation changed before reconciliation");
        tx.execute("INSERT INTO audit_log(actor_user_id,action,details_json,created_at) VALUES(NULL,'creation_receipt_reconciled',?1,?2)",params![json!({"creation":id,"event_update":event,"actor":"authenticated_owner_local_operator","authority":"retained_original","rpc_response_observed":false}).to_string(),now_string()])?;
        let value = creation_on(&tx, id, human)?;
        tx.commit()?;
        Ok((value, true))
    }

    pub fn interaction_creation_suspend(&self, id: &str, human: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute("UPDATE interaction_creations SET phase=CASE phase WHEN 'prepared' THEN 'retained_unsent' WHEN 'creating_topic' THEN 'uncertain' ELSE 'retained_topic' END WHERE id=?1 AND human_id=?2 AND instance_id=?3 AND phase IN ('prepared','creating_topic','topic_known')",params![id,human,self.instance_id])?;
        Ok(())
    }

    /// Mark the external mutation before sending it. Unknown RPC outcomes never retry.
    pub fn interaction_creation_start(&self, id: &str, human: i64) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let operation = creation_on(&tx, id, human)?;
        eligible(&tx, &operation)?;
        if tx.execute("UPDATE interaction_creations SET phase='creating_topic' WHERE id=?1 AND human_id=?2 AND phase='prepared' AND instance_id=?3",params![id,human,self.instance_id])?!=1 {return Err(anyhow!("Creation cannot be replayed"));}
        tx.commit()?;
        Ok(())
    }

    /// Allocate a destination in this standalone receiver, without a Telegram
    /// effect. Reservation and receipt share one transaction, so a lost return
    /// resumes the same destination rather than allocating another one.
    pub fn interaction_creation_local_topic(
        &self,
        id: &str,
        human: i64,
        reserved: &[i64],
    ) -> Result<i64> {
        if reserved.len() > 64 || reserved.iter().any(|id| *id <= 0) {
            bail!("Invalid configured destination reservations");
        }
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let operation = creation_on(&tx, id, human)?;
        eligible(&tx, &operation)?;
        let current: bool = tx.query_row(
            "SELECT instance_id=?1 FROM interaction_creations WHERE id=?2 AND human_id=?3",
            params![self.instance_id, id, human],
            |r| r.get(0),
        )?;
        if !current {
            bail!("Creation is not claimed by this receiver");
        }
        if operation["phase"] == "topic_known" {
            return operation["topic"]
                .as_i64()
                .context("Local destination receipt missing");
        }
        if operation["phase"] != "prepared" {
            bail!("Local creation is not claimed for execution");
        }
        let chat = operation["intent"]["entry"]["chat_id"]
            .as_i64()
            .context("Missing entry")?;
        let previous: i64 = tx.query_row(
            "SELECT MAX(value) FROM (SELECT 0 AS value UNION ALL SELECT thread_id FROM sessions WHERE chat_id=?1 UNION ALL SELECT topic FROM interaction_creations WHERE entry_chat=?1 AND topic IS NOT NULL)",
            [chat], |r| r.get(0),
        )?;
        let previous = previous.max(reserved.iter().copied().max().unwrap_or(0));
        let topic = previous
            .checked_add(1)
            .context("Local destination namespace exhausted")?;
        if tx.execute("UPDATE interaction_creations SET topic=?1,phase='topic_known' WHERE id=?2 AND human_id=?3 AND phase='prepared' AND instance_id=?4",params![topic,id,human,self.instance_id])? != 1 {
            bail!("Local destination reservation changed");
        }
        tx.commit()?;
        Ok(topic)
    }

    pub fn interaction_creation_topic(&self, id: &str, human: i64, topic: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        if topic<=0 || conn.execute("UPDATE interaction_creations SET topic=?1,phase='topic_known' WHERE id=?2 AND human_id=?3 AND phase='creating_topic' AND instance_id=?4",params![topic,id,human,self.instance_id])?!=1 {return Err(anyhow!("Creation topic receipt unavailable"));}
        Ok(())
    }

    /// Enroll the actual owned destination and admit its original input atomically.
    pub fn interaction_creation_finish(
        &self,
        id: &str,
        human: i64,
        channel: &str,
    ) -> Result<crate::interaction::Instruction> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let operation = creation_on(&tx, id, human)?;
        eligible(&tx, &operation)?;
        if operation["phase"] != "topic_known" {
            return Err(anyhow!("Creation has no confirmed topic"));
        }
        let d = &operation["intent"];
        let entry: SessionKey = serde_json::from_value(d["entry"].clone())?;
        let topic = operation["topic"].as_i64().context("Missing topic")?;
        let session:i64=tx.query_row("SELECT id FROM sessions WHERE chat_id=?1 AND thread_id=?2 AND creator_user_id=?3 AND codex_thread_id IS NULL AND force_fresh_thread=1",params![entry.chat_id,topic,human],|r|r.get(0))?;
        let source = SourceInput {
            tribu_source: serde_json::from_value(
                d.get("tribu_source").cloned().unwrap_or(Value::Null),
            )?,
            transcription: serde_json::from_value(
                d.get("transcription").cloned().unwrap_or(Value::Null),
            )?,
            channel: if d["input_update"].is_string() {
                "conversation".into()
            } else {
                channel.into()
            },
            event_id: serde_json::from_value::<InputReference>(d["input_update"].clone())?.event(),
            update_id: d["input_update"].as_i64(),
            human_id: human,
            target_sessions: vec![session],
            origin: serde_json::from_value::<ReturnRoute>(d["origin"].clone())?,
            text: d["original_text"]
                .as_str()
                .context("Missing original text")?
                .into(),
        };
        let source = if let Some(prior) = d.get("prior_dispatch") {
            let raw: String = tx.query_row(
                "SELECT doc FROM interaction_sources WHERE id=?1 AND human_id=?2",
                params![
                    prior["source_id"]
                        .as_str()
                        .context("Missing prior dispatch")?,
                    human
                ],
                |r| r.get(0),
            )?;
            if prior["source_sha256"] != format!("{:x}", Sha256::digest(raw.as_bytes())) {
                bail!("Prior dispatch changed; preserve creation without another topic RPC");
            }
            serde_json::from_str::<SourceInput>(&raw)?
        } else {
            source
        };
        let (instruction, _) = super::interaction::admit_on(
            &tx,
            &source,
            SessionKey::new(entry.chat_id, Some(topic)),
            RequestRelation::New,
            &self.instance_id,
        )?;
        tx.execute("INSERT INTO interaction_enrollments(human_id,entry_chat,entry_topic,target_topic,session_id,name,creation_id) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![human,entry.chat_id,entry.thread_id,topic,session,if d["name"].as_str().is_some_and(|name|name.contains(' ')) {format!("t{topic}")} else {d["name"].as_str().context("Missing retained name")?.to_owned()},id])?;
        tx.execute(
            "UPDATE interaction_creations SET phase='ready' WHERE id=?1",
            [id],
        )?;
        tx.commit()?;
        Ok(instruction)
    }

    pub fn interaction_creation_context(
        &self,
        key: SessionKey,
        human: i64,
    ) -> Result<Option<Value>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let doc:Option<String>=conn.query_row("SELECT c.doc FROM interaction_enrollments e JOIN interaction_creations c ON c.id=e.creation_id JOIN sessions s ON s.id=e.session_id WHERE e.human_id=?1 AND s.creator_user_id=?1 AND s.chat_id=?2 AND s.thread_id=?3",params![human,key.chat_id,key.thread_id],|r|r.get(0)).optional()?;
        doc.map(|d| Ok(serde_json::from_str::<Value>(&d)?["context"].clone()))
            .transpose()
    }
}

fn creation_on(conn: &Connection, id: &str, human: i64) -> Result<Value> {
    let (doc, phase, topic): (String, String, Option<i64>) = conn.query_row(
        "SELECT doc,phase,topic FROM interaction_creations WHERE id=?1 AND human_id=?2",
        params![id, human],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    )?;
    let intent: Value = serde_json::from_str(&doc)?;
    let reference: InputReference = serde_json::from_value(intent["input_update"].clone())?;
    let mut q=conn.prepare("SELECT i.id,i.phase FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id JOIN sessions destination ON destination.id=i.session_id WHERE s.human_id=?1 AND ((s.update_id=?2 AND ?2 IS NOT NULL) OR (s.channel='conversation' AND s.event_id=?5 AND ?2 IS NULL)) AND destination.chat_id=?3 AND destination.thread_id=?4 ORDER BY i.sequence LIMIT 1")?;
    let rows = q.query_map(
        params![
            human,
            reference.update(),
            intent["entry"]["chat_id"].as_i64(),
            topic,
            reference.event()
        ],
        |r| Ok(json!({"id":r.get::<_,String>(0)?,"phase":r.get::<_,String>(1)?})),
    )?;
    let instructions = rows.collect::<rusqlite::Result<Vec<_>>>()?;
    let receipt: Option<Value> = conn.query_row("SELECT event_update,payload_sha256 FROM interaction_creation_receipts WHERE creation_id=?1",[id],|r|Ok(json!({"event_update":r.get::<_,i64>(0)?,"payload_sha256":r.get::<_,String>(1)?,"correlation":"owner_selected_unique_retained_own_bot_service_event","rpc_response_observed":false}))).optional()?;
    Ok(
        json!({"id":id,"intent":intent,"phase":phase,"topic":topic,"instructions":instructions,"receipt_evidence":receipt,"uncertainty":"A recorded intent or topic is not proof of worker incorporation; never replay an unconfirmed topic creation. Inspect retained instruction IDs for downstream delivery recovery."}),
    )
}
/// Additional scoped work reuses a confirmed creation's accepted primary only.
/// No topic, enrollment, instruction or original is changed here.
pub(super) fn workflow_continuation_on(
    conn: &Connection,
    human: i64,
    entry: SessionKey,
    native: &str,
    reference: &InputReference,
    primary: &str,
) -> Result<()> {
    let id: String = conn.query_row(
        "SELECT id FROM interaction_creations WHERE human_id=?1 AND entry_chat=?2 AND entry_topic=?3 AND input_update=?4",
        params![human,entry.chat_id,entry.thread_id,reference],|r|r.get(0),
    )?;
    let operation = creation_on(conn, &id, human)?;
    anyhow::ensure!(
        operation["phase"] == "ready"
            && operation["intent"]["entry_native"].as_str() == Some(native),
        "Creation continuation needs its confirmed current entry"
    );
    eligible(conn, &operation)?;
    let accepted = operation["instructions"].as_array().is_some_and(|rows| {
        rows.iter()
            .any(|row| row["id"] == primary && row["phase"] == "accepted")
    });
    let enrolled:bool=conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM interaction_enrollments e JOIN interaction_instructions i ON i.session_id=e.session_id WHERE e.creation_id=?1 AND e.human_id=?2 AND e.entry_chat=?3 AND e.entry_topic=?4 AND e.target_topic=?5 AND i.id=?6)",
        params![id,human,entry.chat_id,entry.thread_id,operation["topic"].as_i64(),primary],|r|r.get(0),
    )?;
    anyhow::ensure!(
        accepted && enrolled,
        "Creation continuation needs its exact accepted enrolled primary"
    );
    Ok(())
}

fn eligible(conn: &Connection, operation: &Value) -> Result<()> {
    let d = &operation["intent"];
    let key: SessionKey = serde_json::from_value(d["entry"].clone())?;
    let reference: InputReference = serde_json::from_value(d["input_update"].clone())?;
    let (original, _) = super::dialogue::original_on(
        conn,
        key,
        d["human"].as_i64().context("Missing human")?,
        d["entry_native"].as_str().context("Missing native")?,
        &reference,
        "",
        true,
    )?;
    if let Some(prior) = d.get("prior_dispatch") {
        let raw: String = conn.query_row(
            "SELECT doc FROM interaction_sources WHERE id=?1 AND human_id=?2",
            params![
                prior["source_id"]
                    .as_str()
                    .context("Missing prior dispatch")?,
                d["human"].as_i64().context("Missing human")?
            ],
            |r| r.get(0),
        )?;
        if prior["source_sha256"] != format!("{:x}", Sha256::digest(raw.as_bytes())) {
            bail!("Prior dispatch changed before creation effect");
        }
    }
    let origin: ReturnRoute = serde_json::from_value(d["origin"].clone())?;
    if Some(original.text.as_str()) != d["original_text"].as_str()
        || serde_json::to_value(original.transcription)?
            != d.get("transcription").cloned().unwrap_or(Value::Null)
        || serde_json::to_value(original.tribu_source)?
            != d.get("tribu_source").cloned().unwrap_or(Value::Null)
        || original.origin != origin
    {
        bail!("Retained creation original changed");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn uncertain_receipt_fixture() -> (tempfile::NamedTempFile, Store, SessionKey, String) {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let entry = SessionKey::new(100, Some(1));
        let session = store.ensure_session(entry, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        let update:crate::telegram::Update=serde_json::from_value(json!({"update_id":20,"message":{"message_id":20,"message_thread_id":1,"from":{"id":100,"is_bot":false,"first_name":"Human"},"chat":{"id":100,"type":"private"},"text":"Start a distinct new task"}})).unwrap();
        store.admit_update(&update).unwrap();
        store.begin_update(20).unwrap();
        store.mark_update_queued(20).unwrap();
        let turn = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "runtime".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(turn, "entry-native")
            .unwrap();
        store.link_update_turn(20, turn).unwrap();
        let (op, _) = store
            .interaction_prepare_creation(
                entry,
                100,
                "entry-native",
                20,
                "Gamma",
                "Distinct task",
                &json!({"sources":[]}),
                2,
                &tokio_util::sync::CancellationToken::new(),
            )
            .unwrap();
        let id = op["id"].as_str().unwrap().to_owned();
        store.interaction_creation_start(&id, 100).unwrap();
        store.interaction_creation_suspend(&id, 100).unwrap();
        let event:crate::telegram::Update=serde_json::from_value(json!({"update_id":22,"message":{"message_id":30,"message_thread_id":77,"from":{"id":888,"is_bot":true,"first_name":"Bot"},"chat":{"id":100,"type":"private"},"forum_topic_created":{"name":"Gamma","icon_color":7322096}}})).unwrap();
        store.admit_update(&event).unwrap();
        (file, store, entry, id)
    }

    #[test]
    fn retained_own_bot_receipt_recovers_same_topic_and_original_once_across_restart() {
        let (file, store, entry, id) = uncertain_receipt_fixture();
        assert!(
            store
                .interaction_creation_reconcile(&id, 101, 888, 22, &[])
                .is_err()
        );
        assert!(
            store
                .interaction_creation_reconcile(&id, 100, 999, 22, &[])
                .is_err()
        );
        assert!(
            store
                .interaction_creation_reconcile(&id, 100, 888, 19, &[])
                .is_err()
        );
        assert!(
            store
                .interaction_creation_reconcile(&id, 100, 888, 22, &[77])
                .is_err()
        );
        let original = store.interaction_creation(&id, 100).unwrap()["intent"].clone();
        let (op, fresh) = store
            .interaction_creation_reconcile(&id, 100, 888, 22, &[])
            .unwrap();
        assert!(fresh);
        assert_eq!(op["phase"], "retained_topic");
        assert_eq!(op["topic"], 77);
        assert_eq!(op["intent"], original);
        assert_eq!(op["receipt_evidence"]["rpc_response_observed"], false);
        drop(store);
        let store =
            Store::open(file.path(), &[100, 101], &super::super::tests::defaults()).unwrap();
        assert!(
            !store
                .interaction_creation_reconcile(&id, 100, 888, 22, &[])
                .unwrap()
                .1
        );
        assert!(
            store
                .interaction_creation_reconcile(&id, 100, 888, 23, &[])
                .is_err()
        );
        assert!(store.interaction_creation_start(&id, 100).is_err());
        assert!(
            store
                .interaction_creation_resume(
                    entry,
                    100,
                    20,
                    &tokio_util::sync::CancellationToken::new()
                )
                .unwrap()
                .1
        );
        let target = SessionKey::new(100, Some(77));
        store
            .ensure_session(target, 100, &super::super::tests::defaults())
            .unwrap();
        let mut template = store.get_session(entry).unwrap().unwrap();
        template.codex_thread_id = None;
        template.force_fresh_thread = true;
        template.session_title = Some("Gamma".into());
        store
            .apply_empty_session_template(target, &template, 100)
            .unwrap();
        let i = store
            .interaction_creation_finish(&id, 100, "telegram:fixture")
            .unwrap();
        assert_eq!(i.text, "Start a distinct new task");
        assert_eq!(i.target, target);
        assert!(
            !store
                .interaction_creation_reconcile(&id, 100, 888, 22, &[])
                .unwrap()
                .1
        );
        assert_eq!(
            store.interaction_creation(&id, 100).unwrap()["instructions"][0]["id"],
            i.id
        );
        assert!(
            store
                .interaction_creation_finish(&id, 100, "telegram:fixture")
                .is_err()
        );
    }

    #[test]
    fn retained_receipt_refuses_ambiguous_events_existing_targets_and_rebound_original() {
        for case in ["duplicate_event", "existing_target", "rebound", "held"] {
            let (_file, store, entry, id) = uncertain_receipt_fixture();
            match case {
                "duplicate_event" => {
                    let mut conn = store.conn.lock().unwrap();
                    let tx = conn.transaction().unwrap();
                    tx.execute("INSERT INTO incoming_updates(update_id,payload_json,status,instance_id,updated_at) SELECT 23,json_set(payload_json,'$.update_id',23,'$.message.message_id',31,'$.message.message_thread_id',78),status,instance_id,updated_at FROM incoming_updates WHERE update_id=22",[]).unwrap();
                    tx.commit().unwrap();
                }
                "existing_target" => {
                    store
                        .ensure_session(
                            SessionKey::new(100, Some(77)),
                            101,
                            &super::super::tests::defaults(),
                        )
                        .unwrap();
                }
                "rebound" => {
                    store
                        .set_session_codex_thread(entry, "other-native")
                        .unwrap();
                }
                "held" => {
                    store.stop_begin(100, "receipt-test-stop").unwrap();
                }
                _ => unreachable!(),
            }
            assert!(
                store
                    .interaction_creation_reconcile(&id, 100, 888, 22, &[])
                    .is_err(),
                "{case}"
            );
            let op = store.interaction_creation(&id, 100).unwrap();
            assert!(op["topic"].is_null());
            assert_eq!(op["phase"], "uncertain");
            assert!(op["receipt_evidence"].is_null());
        }
    }

    #[test]
    fn discovery_is_opt_in_owned_bound_current_and_preserves_explicit_names() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        for (chat, topic, owner, title) in [
            (100, 1, 100, "Entry"),
            (100, 2, 100, "Duplicate"),
            (100, 3, 100, "Duplicate"),
            (100, 4, 101, "OtherHuman"),
            (101, 5, 100, "OtherChat"),
            (100, 6, 100, "Unbound"),
            (100, 7, 100, "t999"),
            (100, 8, 100, "Two Words"),
            (100, 9, 100, "Retired"),
            (100, 10, 100, "OriginalTitle"),
        ] {
            let key = SessionKey::new(chat, Some(topic));
            store.ensure_session(key, owner, &defaults).unwrap();
            store.set_session_title(key, Some(title)).unwrap();
            if topic != 6 {
                store
                    .set_session_codex_thread(key, &format!("native-{topic}"))
                    .unwrap();
            }
        }
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE sessions SET force_fresh_thread=1 WHERE thread_id=9",
                [],
            )
            .unwrap();
        let mut cfg = InteractionConfig {
            human_id: 100,
            chat_id: 100,
            topic_id: 1,
            telegram_ingress: false,
            telegram_projection: false,
            telegram_entry_projection: false,
            native_workflow_returns: false,
            native_routed_returns: false,
            artifact_store: None,
            max_active_workers: 2,
            discover_owned_sessions: false,
            observer_model: None,
            expression_pack: None,
            observer_reasoning_effort: None,
            matrix_targets: vec![],
            matrix_transport: None,
            matrix_inbox_channel: None,
            matrix_publication: None,
            targets: vec![Target {
                name: "Explicit".into(),
                topic_id: 10,
            }],
        };
        assert_eq!(store.interaction_profile(&cfg).unwrap().targets.len(), 1);
        cfg.discover_owned_sessions = true;
        let discovered = store.interaction_profile(&cfg).unwrap();
        assert_eq!(
            discovered
                .targets
                .iter()
                .map(|t| t.topic_id)
                .collect::<Vec<_>>(),
            vec![10, 2, 3, 7, 8]
        );
        assert_eq!(discovered.resolve("Duplicate").len(), 2);
        assert_eq!(
            discovered.resolve("t3"),
            vec![SessionKey::new(100, Some(3))]
        );
        assert_eq!(discovered.targets[0].name, "Explicit");
        assert_eq!(discovered.targets[3].name, "t7");
        assert_eq!(discovered.targets[4].name, "t8");
        assert!(discovered.resolve("t999").is_empty());
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE sessions SET creator_user_id=101 WHERE thread_id=2",
                [],
            )
            .unwrap();
        assert!(
            store
                .interaction_profile(&cfg)
                .unwrap()
                .resolve("t2")
                .is_empty()
        );
        // A sixty-fifth owned conversation must not take down the whole entry.
        // One entry + 127 destinations matches the existing web reader ceiling.
        for topic in 100..223 {
            let key = SessionKey::new(100, Some(topic));
            store.ensure_session(key, 100, &defaults).unwrap();
            store
                .set_session_codex_thread(key, &format!("native-{topic}"))
                .unwrap();
            if topic == 160 {
                assert_eq!(store.interaction_profile(&cfg).unwrap().targets.len(), 65);
            }
        }
        assert_eq!(store.interaction_profile(&cfg).unwrap().targets.len(), 127);
        let extra = SessionKey::new(100, Some(223));
        store.ensure_session(extra, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(extra, "native-over-capacity")
            .unwrap();
        assert!(store.interaction_profile(&cfg).is_err());
        store
            .conn
            .lock()
            .unwrap()
            .execute("UPDATE users SET allowed=0 WHERE tg_user_id=100", [])
            .unwrap();
        assert_eq!(store.interaction_profile(&cfg).unwrap().targets.len(), 1);
    }

    #[test]
    fn standalone_creation_retains_one_local_destination_across_restart() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let entry = SessionKey::new(100, Some(1));
        let source = store.ensure_session(entry, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        let update:crate::telegram::Update=serde_json::from_value(json!({"update_id":20,"message":{"message_id":20,"message_thread_id":1,"from":{"id":100,"is_bot":false,"first_name":"Human"},"chat":{"id":100,"type":"private"},"text":"Start a distinct new task"}})).unwrap();
        store.admit_update(&update).unwrap();
        store.begin_update(20).unwrap();
        store.mark_update_queued(20).unwrap();
        let turn = store
            .record_turn_started(
                source.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Runtime envelope differs from original".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(turn, "entry-native")
            .unwrap();
        store.link_update_turn(20, turn).unwrap();
        let token = tokio_util::sync::CancellationToken::new();
        token.cancel();
        let prepare = |token: &tokio_util::sync::CancellationToken| {
            store.interaction_prepare_creation(
                entry,
                100,
                "entry-native",
                20,
                "Gamma",
                "This is a distinct task",
                &json!({"sources":[]}),
                2,
                token,
            )
        };
        assert!(prepare(&token).is_err());
        let token = tokio_util::sync::CancellationToken::new();
        let (intent, fresh) = prepare(&token).unwrap();
        assert!(fresh);
        let id = intent["id"].as_str().unwrap();
        assert!(!prepare(&token).unwrap().1);

        // Reserve against both current sessions and other retained creations.
        store
            .ensure_session(SessionKey::new(100, Some(90)), 100, &defaults)
            .unwrap();
        assert!(
            store
                .interaction_creation_local_topic(id, 101, &[100])
                .is_err()
        );
        let topic = store
            .interaction_creation_local_topic(id, 100, &[100])
            .unwrap();
        assert_eq!(topic, 101);
        assert!(
            store
                .get_session(SessionKey::new(100, Some(100)))
                .unwrap()
                .is_none()
        );
        assert_eq!(
            store
                .interaction_creation_local_topic(id, 100, &[100])
                .unwrap(),
            topic
        );
        store.interaction_creation_suspend(id, 100).unwrap();
        assert_eq!(
            store.interaction_creation(id, 100).unwrap()["phase"],
            "retained_topic"
        );
        assert!(
            store
                .interaction_creation_local_topic(id, 100, &[100])
                .is_err()
        );
        let id = id.to_owned();
        drop(store);
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let (retained, claimed) = store
            .interaction_creation_resume(entry, 100, 20, &token)
            .unwrap();
        assert!(claimed);
        assert_eq!(retained["topic"], topic);
        assert_eq!(
            store
                .interaction_creation_local_topic(&id, 100, &[100])
                .unwrap(),
            topic
        );
        let key = SessionKey::new(100, Some(topic));
        store.ensure_session(key, 100, &defaults).unwrap();
        let mut template = source;
        template.codex_thread_id = None;
        template.force_fresh_thread = true;
        template.session_title = Some("Gamma".into());
        store
            .apply_empty_session_template(key, &template, 100)
            .unwrap();
        let instruction = store
            .interaction_creation_finish(&id, 100, "unused-disabled-telegram")
            .unwrap();
        assert_eq!(instruction.text, "Start a distinct new task");
        assert_eq!(instruction.target, key);
        assert_eq!(
            store.interaction_creation(&id, 100).unwrap()["phase"],
            "ready"
        );
        assert!(
            store
                .interaction_creation_local_topic(&id, 100, &[100])
                .is_err()
        );
        let cfg: InteractionConfig = serde_json::from_value(json!({
            "human_id":100,"chat_id":100,"topic_id":1,
            "targets":[{"topic_id":100,"name":"Existing"}]
        }))
        .unwrap();
        let profile = store.interaction_profile(&cfg).unwrap();
        assert_eq!(
            profile.resolve("Existing"),
            vec![SessionKey::new(100, Some(100))]
        );
        assert_eq!(profile.resolve("Gamma"), vec![key]);
    }

    #[test]
    fn creation_after_dispatch_preserves_source_and_only_adds_its_topic() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let entry = SessionKey::new(100, Some(1));
        let source = store.ensure_session(entry, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        let update:crate::telegram::Update=serde_json::from_value(json!({"update_id":20,"message":{"message_id":20,"message_thread_id":1,"from":{"id":100,"is_bot":false,"first_name":"Human"},"chat":{"id":100,"type":"private"},"text":"Start a distinct new task"}})).unwrap();
        store.admit_update(&update).unwrap();
        store.begin_update(20).unwrap();
        store.mark_update_queued(20).unwrap();
        let turn = store
            .record_turn_started(
                source.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Runtime envelope differs from original".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(turn, "entry-native")
            .unwrap();
        store.link_update_turn(20, turn).unwrap();

        let old = SessionKey::new(100, Some(7));
        let oldrow = store.ensure_session(old, 100, &defaults).unwrap();
        store.set_session_codex_thread(old, "old-native").unwrap();
        let input = SourceInput {
            tribu_source: None,
            transcription: None,
            channel: "telegram:fixture".into(),
            event_id: "20".into(),
            update_id: Some(20),
            human_id: 100,
            target_sessions: vec![oldrow.id],
            origin: ReturnRoute {
                chat_id: 100,
                thread_id: 1,
                message_id: Some(20),
            },
            text: "Start a distinct new task".into(),
        };
        let (first, fresh) = store
            .interaction_admit(&input, old, RequestRelation::New)
            .unwrap();
        assert!(fresh);
        let frozen: String = store
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT doc FROM interaction_sources WHERE id=?1",
                [&first.input_id],
                |r| r.get(0),
            )
            .unwrap();
        let token = tokio_util::sync::CancellationToken::new();
        let prepare = || {
            store.interaction_prepare_creation(
                entry,
                100,
                "entry-native",
                20,
                "Identidad",
                "Distinct remaining identity clause; existing routed work stays put",
                &json!({"sources":[]}),
                2,
                &token,
            )
        };
        let (operation, fresh) = prepare().unwrap();
        assert!(fresh);
        let id = operation["id"].as_str().unwrap();
        assert!(operation["intent"]["prior_dispatch"].is_object());
        assert!(!prepare().unwrap().1);
        assert_eq!(
            store
                .interaction_admit(&input, old, RequestRelation::New)
                .unwrap()
                .0
                .id,
            first.id
        );
        let topic = store
            .interaction_creation_local_topic(id, 100, &[100])
            .unwrap();
        let key = SessionKey::new(100, Some(topic));
        store.ensure_session(key, 100, &defaults).unwrap();
        let mut template = source;
        template.codex_thread_id = None;
        template.force_fresh_thread = true;
        template.session_title = Some("Identidad".into());
        store
            .apply_empty_session_template(key, &template, 100)
            .unwrap();
        let added = store
            .interaction_creation_finish(id, 100, "telegram:fixture")
            .unwrap();
        assert_eq!(added.input_id, first.input_id);
        assert_eq!(added.text, first.text);
        assert_eq!(added.target, SessionKey::new(100, Some(topic)));
        assert_ne!(added.id, first.id);
        assert_eq!(
            store
                .interaction_admit(&input, old, RequestRelation::New)
                .unwrap()
                .0
                .id,
            first.id
        );
        assert!(
            store
                .interaction_creation_finish(id, 100, "telegram:fixture")
                .is_err()
        );
        let outside = SessionKey::new(100, Some(999));
        let other = store.ensure_session(outside, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(outside, "outside-native")
            .unwrap();
        assert!(
            store
                .interaction_admit(&input, outside, RequestRelation::New)
                .is_err()
        );
        let changed = SourceInput {
            target_sessions: vec![oldrow.id, other.id],
            ..input
        };
        assert!(
            store
                .interaction_admit(&changed, outside, RequestRelation::New)
                .is_err()
        );
        let after: String = store
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT doc FROM interaction_sources WHERE id=?1",
                [&first.input_id],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(after, frozen);
        assert_eq!(
            store.interaction_creation(id, 100).unwrap()["phase"],
            "ready"
        );
    }

    #[test]
    fn creation_reserves_one_plan_and_atomically_enrolls_original() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let entry = SessionKey::new(100, Some(1));
        let source = store.ensure_session(entry, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        let update:crate::telegram::Update=serde_json::from_value(json!({"update_id":20,"message":{"message_id":20,"message_thread_id":1,"from":{"id":100,"is_bot":false,"first_name":"Human"},"chat":{"id":100,"type":"private"},"text":"Start a distinct new task"}})).unwrap();
        store.admit_update(&update).unwrap();
        store.begin_update(20).unwrap();
        store.mark_update_queued(20).unwrap();
        let turn = store
            .record_turn_started(
                source.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Runtime envelope differs from original".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(turn, "entry-native")
            .unwrap();
        store.link_update_turn(20, turn).unwrap();
        let token = tokio_util::sync::CancellationToken::new();
        token.cancel();
        let prepare = |token: &tokio_util::sync::CancellationToken| {
            store.interaction_prepare_creation(
                entry,
                100,
                "entry-native",
                20,
                "Gamma",
                "This is a distinct task",
                &json!({"sources":[]}),
                2,
                token,
            )
        };
        assert!(prepare(&token).is_err());
        let token = tokio_util::sync::CancellationToken::new();
        let (intent, fresh) = prepare(&token).unwrap();
        assert!(fresh);
        let id = intent["id"].as_str().unwrap();
        assert!(!prepare(&token).unwrap().1);
        let old = SessionKey::new(100, Some(7));
        let oldrow = store.ensure_session(old, 100, &defaults).unwrap();
        store.set_session_codex_thread(old, "old-native").unwrap();
        let input = SourceInput {
            tribu_source: None,
            transcription: None,
            channel: "telegram:fixture".into(),
            event_id: "20".into(),
            update_id: Some(20),
            human_id: 100,
            target_sessions: vec![oldrow.id],
            origin: ReturnRoute {
                chat_id: 100,
                thread_id: 1,
                message_id: Some(20),
            },
            text: "Start a distinct new task".into(),
        };
        assert!(
            store
                .interaction_admit(&input, old, RequestRelation::New)
                .is_err(),
            "Original creation input became a different dispatch plan"
        );
        store.interaction_creation_suspend(id, 100).unwrap();
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE incoming_updates SET status='undetermined' WHERE update_id=20",
                [],
            )
            .unwrap();
        assert!(
            store
                .interaction_entry_inputs(entry, 100, "entry-native", Some(20))
                .unwrap()
                .is_empty(),
            "Ordinary new dispatch accepted uncertain ingress"
        );
        let cancelled = tokio_util::sync::CancellationToken::new();
        cancelled.cancel();
        assert!(
            store
                .interaction_creation_resume(entry, 100, 20, &cancelled)
                .is_err()
        );
        assert_eq!(
            store
                .interaction_creation_for_input(entry, 100, 20)
                .unwrap()["phase"],
            "retained_unsent"
        );
        assert!(
            store
                .interaction_creation_resume(entry, 100, 20, &token)
                .unwrap()
                .1
        );
        assert!(
            !store
                .interaction_creation_resume(entry, 100, 20, &token)
                .unwrap()
                .1
        );
        store.interaction_creation_start(id, 100).unwrap();
        assert!(
            store.interaction_creation_start(id, 100).is_err(),
            "External topic mutation was replayed"
        );
        store.interaction_creation_topic(id, 100, 77).unwrap();
        store.interaction_creation_suspend(id, 100).unwrap();
        assert_eq!(
            store
                .interaction_creation_for_input(entry, 100, 20)
                .unwrap()["phase"],
            "retained_topic"
        );
        assert!(
            store
                .interaction_creation_resume(entry, 100, 20, &token)
                .unwrap()
                .1
        );
        assert!(
            !store
                .interaction_creation_resume(entry, 100, 20, &token)
                .unwrap()
                .1
        );

        let key = SessionKey::new(100, Some(77));
        store.ensure_session(key, 100, &defaults).unwrap();
        let mut template = source;
        template.codex_thread_id = None;
        template.force_fresh_thread = true;
        template.session_title = Some("Gamma".into());
        store
            .apply_empty_session_template(key, &template, 100)
            .unwrap();
        let instruction = store
            .interaction_creation_finish(id, 100, "telegram:fixture")
            .unwrap();
        assert_eq!(instruction.text, "Start a distinct new task");
        assert_eq!(instruction.target, key);
        assert!(
            !store
                .interaction_creation_resume(entry, 100, 20, &token)
                .unwrap()
                .1
        );
        let status = store
            .interaction_creation_for_input(entry, 100, 20)
            .unwrap();
        assert_eq!(status["instructions"][0]["id"], instruction.id);

        assert!(
            store
                .interaction_creation_finish(id, 100, "telegram:fixture")
                .is_err()
        );
        let cfg = InteractionConfig {
            human_id: 100,
            chat_id: 100,
            topic_id: 1,
            telegram_ingress: false,
            telegram_projection: false,
            telegram_entry_projection: false,
            native_workflow_returns: false,
            native_routed_returns: false,
            artifact_store: None,
            max_active_workers: 2,
            discover_owned_sessions: false,
            observer_model: None,
            expression_pack: None,
            observer_reasoning_effort: None,
            matrix_targets: vec![],
            matrix_transport: None,
            matrix_inbox_channel: None,
            matrix_publication: None,
            targets: vec![Target {
                name: "Alpha".into(),
                topic_id: 7,
            }],
        };
        assert_eq!(
            store.interaction_profile(&cfg).unwrap().resolve("Gamma"),
            vec![key]
        );
        let empty = InteractionConfig {
            targets: vec![],
            ..cfg.clone()
        };
        empty.validate().unwrap();
        assert_eq!(
            store.interaction_profile(&empty).unwrap().resolve("Gamma"),
            vec![key]
        );
        assert_eq!(
            store
                .interaction_creation_for_input(entry, 100, 20)
                .unwrap()["phase"],
            "ready"
        );
        assert!(
            store
                .interaction_creation_for_input(entry, 101, 20)
                .is_err()
        );
    }
}
