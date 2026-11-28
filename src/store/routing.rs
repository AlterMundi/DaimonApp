//! Publication reservations and reply bindings for the interaction controller.
use super::*;
use crate::interaction::{Delivery, Instruction, ReturnRoute, worker_result};
use std::collections::HashSet;

pub(super) fn delivery_freshness(conn: &Connection, delivery: &Delivery) -> Result<(bool, bool)> {
    let local = conn.query_row(
        "SELECT r.local_turn FROM interaction_deliveries d JOIN interaction_results r ON r.id=d.result_id
         WHERE d.id=?1",
        [&delivery.id],
        |row| row.get(0),
    ).optional()?;
    delivery_freshness_at(conn, delivery, local)
}

fn delivery_freshness_at(
    conn: &Connection,
    delivery: &Delivery,
    local: Option<i64>,
) -> Result<(bool, bool)> {
    let mut current = delivery.declared;
    let mut correction = false;
    for request in delivery.requests() {
        let (fresh, pending) =
            freshness_at(conn, request, &delivery.covered, delivery.declared, local)?;
        current &= fresh;
        correction |= pending;
    }
    Ok((current, correction))
}

pub(super) fn freshness(
    conn: &Connection,
    request: &str,
    covered: &[String],
    declared: bool,
) -> Result<(bool, bool)> {
    freshness_at(conn, request, covered, declared, None)
}

fn freshness_at(
    conn: &Connection,
    request: &str,
    covered: &[String],
    declared: bool,
    local: Option<i64>,
) -> Result<(bool, bool)> {
    let mut stmt=conn.prepare("SELECT i.id,i.phase,i.doc FROM interaction_request_links l JOIN interaction_instructions i ON i.id=l.instruction_id WHERE l.request_id=? AND i.phase NOT IN ('rejected','cancelled') ORDER BY i.sequence")?;
    let rows = stmt
        .query_map([request], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let mut current = declared && !rows.is_empty();
    let mut correction = false;
    for (id, phase, doc) in rows {
        let i: Instruction = serde_json::from_str(&doc)?;
        let included = phase == "accepted" && covered.contains(&id);
        current &= included;
        if matches!(i.relation, crate::interaction::RequestRelation::Amends(_)) && !included {
            // Prior publication can settle this correction for the same request
            // without changing what the current result actually declared.
            let settled = if declared && phase == "accepted" {
                if let Some(local) = local {
                    confirmed_prior_correction(conn, request, &i, local)?
                } else {
                    false
                }
            } else {
                false
            };
            correction |= !settled;
        }
    }
    Ok((current, correction))
}

fn confirmed_prior_correction(
    conn: &Connection,
    request: &str,
    instruction: &Instruction,
    current: i64,
) -> Result<bool> {
    conn.query_row(
        "SELECT EXISTS(
             SELECT 1 FROM interaction_delivery_requests member
             JOIN interaction_public_deliveries d ON d.id=member.delivery_id
             JOIN interaction_results r ON r.id=d.result_id
             JOIN turns prior ON prior.id=r.local_turn
             JOIN turns next ON next.id=?1 AND next.session_id=prior.session_id
                AND next.from_user_id=prior.from_user_id
                AND next.execution_generation=prior.execution_generation
             JOIN conversation_entry_generations g ON g.session_id=next.session_id
                AND g.generation=next.execution_generation
             WHERE member.request_id=?2 AND d.human_id=?3 AND d.phase='delivered'
               AND prior.id=?4 AND prior.id<next.id AND prior.status='completed'
               AND r.native_thread=?5 AND r.native_turn=?6
               AND EXISTS(SELECT 1 FROM interaction_delivery_parts p
                   WHERE p.delivery_id=d.id AND p.message_id=d.message_id)
               AND EXISTS(SELECT 1 FROM json_each(r.claim,'$.completed') c WHERE c.value=?2)
               AND EXISTS(SELECT 1 FROM json_each(r.claim,'$.covered') c WHERE c.value=?7)
         )",
        params![
            current,
            request,
            instruction.human_id,
            instruction.local_turn,
            instruction.native_thread,
            instruction.native_turn,
            instruction.id
        ],
        |row| row.get(0),
    )
    .map_err(Into::into)
}

pub(super) fn bind_message(
    conn: &Connection,
    route: &ReturnRoute,
    human: i64,
    session: i64,
    requests: &[String],
) -> Result<()> {
    let doc = serde_json::to_string(requests)?;
    if conn.execute(
        "INSERT OR IGNORE INTO interaction_message_bindings VALUES(?1,?2,?3,?4,?5,?6)",
        params![
            route.chat_id,
            route.thread_id,
            route.message_id,
            human,
            session,
            doc
        ],
    )? == 0
    {
        let original:(i64,i64,String)=conn.query_row("SELECT human_id,session_id,requests FROM interaction_message_bindings WHERE chat_id=?1 AND thread_id=?2 AND message_id=?3",params![route.chat_id,route.thread_id,route.message_id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        if original != (human, session, doc) {
            return Err(anyhow!("Interaction reply binding is immutable"));
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) fn result_on(
    tx: &Connection,
    instance: &str,
    root_id: &str,
    human: i64,
    local_turn: i64,
    thread: &str,
    turn: &str,
    item: &str,
    text: &str,
    capture: bool,
    allow_unreported: bool,
) -> Result<Vec<Delivery>> {
    let root = super::interaction::instruction_on(tx, root_id, human)?
        .context("Interaction root missing")?;
    let (body, claim) = worker_result(text);
    if capture {
        super::interaction::record_native_message_on(
            tx,
            local_turn,
            thread,
            turn,
            item,
            Some("final_answer"),
            text,
        )?;
    }
    let bound:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_native_messages m JOIN turns t ON t.id=m.local_turn WHERE m.native_thread=?1 AND m.native_turn=?2 AND m.item_id=?3 AND m.local_turn=?4 AND m.text=?5 AND t.session_id=?6 AND t.from_user_id=?7)",params![thread,turn,item,local_turn,text,root.target_session,human],|r|r.get(0))?;
    if !bound {
        return Err(anyhow!(
            "Interaction result is not a recorded native item of this execution"
        ));
    }
    let mut valid_claim = claim.is_some();
    if let Some(claim) = &claim {
        for request in &claim.requests {
            let allowed:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_requests WHERE id=?1 AND human_id=?2 AND session_id=?3)",params![request,human,root.target_session],|r|r.get(0))?;
            valid_claim &= allowed;
        }
        for id in claim.covered.iter().chain(&claim.deferred) {
            let allowed:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_instructions WHERE id=?1 AND session_id=?2)",params![id,root.target_session],|r|r.get(0))?;
            valid_claim &= allowed;
        }
    }
    let claim = claim.filter(|_| valid_claim);
    if claim.is_none() && !allow_unreported {
        // Preserve the actual native item without pretending a legacy
        // answer addressed an instruction attached while it was running.
        return Ok(vec![]);
    }
    let covered = claim
        .as_ref()
        .map(|c| c.covered.clone())
        .unwrap_or_default();
    let result_id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        serde_json::to_string(&(thread, turn, item))?.as_bytes(),
    )
    .to_string();
    if tx.execute("INSERT OR IGNORE INTO interaction_results(id,local_turn,native_thread,native_turn,item_id,body,claim) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![result_id,local_turn,thread,turn,item,body,claim.as_ref().map(serde_json::to_string).transpose()?])? == 0 {
            // A repeated observation must not retarget an already reserved item
            // after later instructions arrive. All reservations commit together.
            return Ok(vec![]);
        }
    let mut query=tx.prepare("SELECT i.doc,s.doc FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id WHERE i.session_id=?1 AND s.human_id=?2 AND i.phase='accepted' AND json_extract(i.doc,'$.local_turn')=?3 AND (?4 IS NULL OR json_extract(i.doc,'$.native_turn')=?4) AND NOT EXISTS(SELECT 1 FROM interaction_direct_parents p WHERE p.instruction=i.id) ORDER BY i.sequence DESC")?;
    let inputs = query
        .query_map(
            params![
                root.target_session,
                human,
                local_turn,
                turn.starts_with("gateway:claude:").then_some(turn)
            ],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    drop(query);
    let inputs = inputs
        .into_iter()
        .map(|(input, source)| {
            Ok((
                serde_json::from_str::<Instruction>(&input)?,
                serde_json::from_str::<crate::interaction::SourceInput>(&source)?,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    let requests = claim
        .as_ref()
        .map(|c| c.requests.clone())
        .unwrap_or_else(|| {
            if turn.starts_with("gateway:claude:") {
                let mut seen = HashSet::new();
                inputs
                    .iter()
                    .flat_map(|(input, _)| &input.requests)
                    .filter(|request| seen.insert(*request))
                    .cloned()
                    .collect()
            } else {
                root.requests.clone()
            }
        });
    let mut selected = Vec::new();
    for request in requests {
        let mut candidates = Vec::new();
        for (input, source) in &inputs {
            if input.requests.contains(&request) {
                candidates.push((
                    super::dialogue::original_order_on(tx, source)?,
                    input.sequence,
                    input,
                    source,
                ));
            }
        }
        candidates.sort_by_key(|(order, sequence, _, _)| (*order, *sequence));
        let historical;
        let (order, sequence, source) = if let Some((order, sequence, _, source)) = candidates.pop()
        {
            (order, sequence, source)
        } else if let Some(claim) = claim.as_ref()
            && let Some(input) = super::session_requests::later_completion_source_on(
                tx, human, local_turn, thread, &request, claim,
            )?
        {
            historical = source_on(tx, &input.id, human)?;
            (
                super::dialogue::original_order_on(tx, &historical)?,
                input.sequence,
                &historical,
            )
        } else {
            continue;
        };
        let original:String=tx.query_row("SELECT s.doc FROM interaction_requests r JOIN interaction_sources s ON s.id=r.input_id WHERE r.id=?1 AND r.human_id=?2",params![request,human],|r|r.get(0))?;
        let original: crate::interaction::SourceInput = serde_json::from_str(&original)?;
        let origin = if source.channel == original.channel
            && source.origin.chat_id == original.origin.chat_id
            && source.origin.thread_id == original.origin.thread_id
        {
            original.origin
        } else {
            source.origin.clone()
        };
        // Session dependencies retain their own correlation/return behavior;
        // human requests share one response per actual requesting carrier.
        // A helper request always stays internal. A return-only wakeup may
        // address the parent's IDs, but needs an actual covered human input
        // in this execution before producing another human-facing answer.
        let original_internal = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM interaction_requests q JOIN interaction_session_authors a ON a.input_id=q.input_id WHERE q.id=?1)",
                [&request], |r|r.get::<_,bool>(0),
            )?;
        let mut internal_input = false;
        let mut human_input = false;
        for (candidate, _) in &inputs {
            if candidate.requests.contains(&request) {
                let internal =
                    super::session_requests::author_on(tx, &candidate.input_id)?.is_some();
                internal_input |= internal;
                human_input |= !internal && (claim.is_none() || covered.contains(&candidate.id));
            }
        }
        // A deferred logical task can genuinely finish after its original
        // physical turn. It must complete current cumulative human coverage,
        // rather than merely narrating the returned context or re-announcing
        // a human request already completed before this wakeup.
        if !human_input
            && !original_internal
            && claim
                .as_ref()
                .is_some_and(|c| c.completed.contains(&request))
        {
            let (fresh, pending) = freshness(tx, &request, &covered, true)?;
            let already_completed: bool=tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM interaction_deliveries prior JOIN interaction_delivery_requests member ON member.delivery_id=prior.id JOIN interaction_results z ON z.id=prior.result_id WHERE member.request_id=?1 AND prior.human_id=?2 AND EXISTS(SELECT 1 FROM json_each(z.claim,'$.completed') done WHERE done.value=?1) AND COALESCE(json_extract(prior.doc,'$.internal'),0)=0
                     AND NOT EXISTS(SELECT 1 FROM interaction_request_links l JOIN interaction_instructions i ON i.id=l.instruction_id WHERE l.request_id=?1 AND i.phase='accepted'
                       AND NOT EXISTS(SELECT 1 FROM interaction_session_authors a WHERE a.input_id=i.input_id)
                       AND NOT EXISTS(SELECT 1 FROM json_each(prior.doc,'$.covered') cov WHERE cov.value=i.id)))",
                    params![request,human],|r|r.get(0),
                )?;
            human_input = fresh && !pending && !already_completed;
        }
        let internal = original_internal || (internal_input && !human_input);
        let authored = if internal {
            Some(request.clone())
        } else {
            None
        };
        selected.push((order, sequence, origin, authored, internal, request));
    }
    selected.sort_by_key(|(order, sequence, _, _, _, _)| std::cmp::Reverse((*order, *sequence)));
    // An explicitly shared entry is one requesting conversation across both carriers.
    let shared_entry: Option<(i64, i64)> = tx
        .query_row(
            "SELECT json_extract(value,'$[1]'),json_extract(value,'$[2]') FROM bot_state
             WHERE key='telegram_entry_projection' AND json_extract(value,'$[0]')=?1",
            [human],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let mut groups: Vec<(ReturnRoute, Option<String>, bool, Vec<String>)> = Vec::new();
    for (_, _, origin, authored, internal, request) in selected {
        if let Some((_, _, _, requests)) = groups.iter_mut().find(|(prior, kind, audience, _)| {
            prior.chat_id == origin.chat_id
                && prior.thread_id == origin.thread_id
                && (prior.message_id.is_some() == origin.message_id.is_some()
                    || shared_entry == Some((origin.chat_id, origin.thread_id)))
                && *kind == authored
                && *audience == internal
        }) {
            if !requests.contains(&request) {
                requests.push(request);
            }
        } else {
            groups.push((origin, authored, internal, vec![request]));
        }
    }
    let mut deliveries = Vec::new();
    for (origin, _, internal, requests) in groups {
        let request = requests[0].clone();
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("{result_id}:{request}").as_bytes(),
        )
        .to_string();
        let mut delivery = Delivery {
            id: id.clone(),
            request_id: request,
            request_ids: requests,
            target: root.target,
            origin,
            body: body.to_owned(),
            covered: covered.clone(),
            declared: claim.is_some(),
            completed: false,
            current: false,
            correction_pending: false,
            phase: "reserved".into(),
            internal: Some(internal),
        };
        delivery.completed = claim.as_ref().is_some_and(|c| {
            delivery
                .requests()
                .iter()
                .all(|request| c.completed.contains(request))
        });
        (delivery.current, delivery.correction_pending) =
            delivery_freshness_at(tx, &delivery, Some(local_turn))?;
        tx.execute("INSERT INTO interaction_deliveries(id,result_id,request_id,human_id,phase,doc,instance_id) VALUES(?1,?2,?3,?4,'reserved',?5,?6)",params![id,result_id,delivery.request_id,human,serde_json::to_string(&delivery)?,instance])?;
        for request in delivery.requests() {
            tx.execute(
                "INSERT INTO interaction_delivery_requests VALUES(?1,?2)",
                params![id, request],
            )?;
        }
        deliveries.push(delivery);
    }
    Ok(deliveries)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn later_completion_result_on(
    tx: &Connection,
    instance: &str,
    human: i64,
    local: i64,
    thread: &str,
    turn: &str,
    item: &str,
    text: &str,
    capture_unlinked: bool,
) -> Result<Vec<Delivery>> {
    let mut root = None;
    if let Some(claim) = worker_result(text).1 {
        for request in &claim.completed {
            root = super::session_requests::later_completion_source_on(
                tx, human, local, thread, request, &claim,
            )?;
            if root.is_some() {
                break;
            }
        }
    }
    if let Some(root) = root {
        result_on(
            tx, instance, &root.id, human, local, thread, turn, item, text, true, false,
        )
    } else {
        if capture_unlinked {
            super::interaction::record_native_message_on(
                tx,
                local,
                thread,
                turn,
                item,
                Some("final_answer"),
                text,
            )?;
        }
        Ok(Vec::new())
    }
}

impl Store {
    /// An ordinary final can finish a specifically declared, still-open helper
    /// dependency without reopening the original native turn.
    pub(crate) fn interaction_record_later_completion(
        &self,
        human: i64,
        local: i64,
        thread: &str,
        turn: &str,
        item: &str,
        text: &str,
    ) -> Result<Vec<Delivery>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let deliveries = later_completion_result_on(
            &tx,
            &self.instance_id,
            human,
            local,
            thread,
            turn,
            item,
            text,
            true,
        )?;
        tx.commit()?;
        Ok(deliveries)
    }

    pub(super) fn init_routing(&self) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute_batch("CREATE TABLE IF NOT EXISTS interaction_results(id TEXT PRIMARY KEY,local_turn INTEGER NOT NULL,native_thread TEXT NOT NULL,native_turn TEXT NOT NULL,item_id TEXT NOT NULL,body TEXT NOT NULL,claim TEXT,UNIQUE(native_thread,native_turn,item_id));
          CREATE TABLE IF NOT EXISTS interaction_deliveries(id TEXT PRIMARY KEY,result_id TEXT NOT NULL REFERENCES interaction_results(id),request_id TEXT NOT NULL REFERENCES interaction_requests(id),human_id INTEGER NOT NULL,phase TEXT NOT NULL,doc TEXT NOT NULL,message_id INTEGER,instance_id TEXT NOT NULL,UNIQUE(result_id,request_id));
          CREATE TABLE IF NOT EXISTS interaction_delivery_parts(delivery_id TEXT NOT NULL REFERENCES interaction_deliveries(id),part INTEGER NOT NULL,text TEXT NOT NULL,message_id INTEGER,PRIMARY KEY(delivery_id,part));
          CREATE TABLE IF NOT EXISTS interaction_message_bindings(chat_id INTEGER NOT NULL,thread_id INTEGER NOT NULL,message_id INTEGER NOT NULL,human_id INTEGER NOT NULL,session_id INTEGER NOT NULL,requests TEXT NOT NULL,PRIMARY KEY(chat_id,thread_id,message_id));
          CREATE TABLE IF NOT EXISTS interaction_clarifications(id TEXT PRIMARY KEY,human_id INTEGER NOT NULL,doc TEXT NOT NULL,phase TEXT NOT NULL,question_chat INTEGER,question_thread INTEGER,question_message INTEGER);")?;
        let tx = conn.transaction()?;
        tx.execute_batch("CREATE TABLE IF NOT EXISTS interaction_delivery_requests(delivery_id TEXT NOT NULL REFERENCES interaction_deliveries(id),request_id TEXT NOT NULL REFERENCES interaction_requests(id),PRIMARY KEY(delivery_id,request_id));
          INSERT OR IGNORE INTO interaction_delivery_requests SELECT id,request_id FROM interaction_deliveries;")?;
        tx.execute("UPDATE interaction_deliveries SET phase=CASE WHEN phase='sending' THEN 'uncertain' ELSE 'reserved' END WHERE phase IN ('preparing','sending') AND instance_id!=?",[&self.instance_id])?;
        tx.commit()?;
        Ok(())
    }

    pub(super) fn init_delivery_audiences(&self) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        // Original return coordinates are provenance, not a publication grant.
        // The fallback qualifies old records without rewriting receipts/history.
        conn.execute_batch(r#"CREATE VIEW IF NOT EXISTS interaction_public_deliveries AS
          SELECT d.rowid AS rowid,d.* FROM interaction_deliveries d
          WHERE COALESCE(json_extract(d.doc,'$.internal'),
            EXISTS(SELECT 1 FROM interaction_requests q JOIN interaction_session_authors a ON a.input_id=q.input_id WHERE q.id=d.request_id)
            OR (EXISTS(SELECT 1 FROM interaction_results z JOIN interaction_instructions i ON json_extract(i.doc,'$.local_turn')=z.local_turn
                  JOIN interaction_session_authors a ON a.input_id=i.input_id JOIN json_each(i.doc,'$.requests') req
                  WHERE z.id=d.result_id AND req.value=d.request_id)
                AND NOT EXISTS(SELECT 1 FROM interaction_results z JOIN interaction_instructions i ON (json_extract(i.doc,'$.local_turn')=z.local_turn OR EXISTS(SELECT 1 FROM json_each(z.claim,'$.completed') done WHERE done.value=d.request_id))
                  JOIN json_each(i.doc,'$.requests') req WHERE z.id=d.result_id AND req.value=d.request_id
                  AND NOT EXISTS(SELECT 1 FROM interaction_session_authors a WHERE a.input_id=i.input_id)
                  AND (z.claim IS NULL OR EXISTS(SELECT 1 FROM json_each(z.claim,'$.covered') cov WHERE cov.value=i.id))))
          )=0;"#)?;
        Ok(())
    }

    /// Reserve a canonical result before any external publication. The worker can
    /// report request coverage, but cannot supply a different recipient or scope.
    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_reserve_result(
        &self,
        root_id: &str,
        human: i64,
        local_turn: i64,
        thread: &str,
        turn: &str,
        item: &str,
        text: &str,
    ) -> Result<Vec<Delivery>> {
        self.interaction_result(
            root_id, human, local_turn, thread, turn, item, text, false, true,
        )
    }

    /// Commit the canonical final and all return reservations together.
    #[allow(clippy::too_many_arguments)]
    pub fn interaction_record_result(
        &self,
        root_id: &str,
        human: i64,
        local_turn: i64,
        thread: &str,
        turn: &str,
        item: &str,
        text: &str,
        allow_unreported: bool,
    ) -> Result<Vec<Delivery>> {
        self.interaction_result(
            root_id,
            human,
            local_turn,
            thread,
            turn,
            item,
            text,
            true,
            allow_unreported,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn interaction_result(
        &self,
        root_id: &str,
        human: i64,
        local_turn: i64,
        thread: &str,
        turn: &str,
        item: &str,
        text: &str,
        capture: bool,
        allow_unreported: bool,
    ) -> Result<Vec<Delivery>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let deliveries = result_on(
            &tx,
            &self.instance_id,
            root_id,
            human,
            local_turn,
            thread,
            turn,
            item,
            text,
            capture,
            allow_unreported,
        )?;
        tx.commit()?;
        Ok(deliveries)
    }

    pub(crate) fn interaction_ready_telegram_deliveries(
        &self,
        human: i64,
        entry: SessionKey,
        project_entry: bool,
    ) -> Result<Vec<Delivery>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut query = conn.prepare(
            "SELECT d.doc FROM interaction_public_deliveries d
             JOIN users u ON u.tg_user_id=d.human_id AND u.allowed=1
             WHERE d.human_id=?1 AND d.phase='reserved'
               AND json_extract(d.doc,'$.telegram_publication_selected')=1
               AND NOT EXISTS(SELECT 1 FROM interaction_delivery_parts p WHERE p.delivery_id=d.id)
               AND (json_type(d.doc,'$.origin.message_id')='integer' OR
                    (?2 AND json_extract(d.doc,'$.origin.chat_id')=?3
                        AND json_extract(d.doc,'$.origin.thread_id')=?4))
             ORDER BY d.rowid LIMIT 32",
        )?;
        let docs = query.query_map(
            params![human, project_entry, entry.chat_id, entry.thread_id],
            |row| row.get::<_, String>(0),
        )?;
        docs.map(|doc| Ok(serde_json::from_str(&doc?)?)).collect()
    }

    /// Release the first reservation only with evidence that the sender never
    /// crossed its submission boundary.
    pub(crate) fn interaction_first_part_not_submitted(
        &self,
        id: &str,
        human: i64,
    ) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let changed = tx.execute(
            "UPDATE interaction_deliveries SET phase='reserved',
               doc=json_set(doc,'$.phase','reserved','$.telegram_publication_selected',1)
             WHERE id=?1 AND human_id=?2 AND instance_id=?3 AND phase='sending'
               AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)
               AND message_id IS NULL
               AND (SELECT count(*) FROM interaction_delivery_parts p WHERE p.delivery_id=?1)=1
               AND EXISTS(SELECT 1 FROM interaction_delivery_parts p WHERE p.delivery_id=?1
                          AND p.part=0 AND p.message_id IS NULL)",
            params![id, human, self.instance_id],
        )? == 1;
        if changed {
            tx.execute(
                "DELETE FROM interaction_delivery_parts WHERE delivery_id=?1 AND part=0",
                [id],
            )?;
        }
        tx.commit()?;
        Ok(changed)
    }

    /// This transaction is the last check before transmission may begin.
    pub fn interaction_begin_delivery(&self, id: &str, human: i64) -> Result<Option<Delivery>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let raw:Option<String>=tx.query_row("SELECT d.doc FROM interaction_public_deliveries d JOIN users u ON u.tg_user_id=d.human_id WHERE d.id=?1 AND d.human_id=?2 AND u.allowed=1 AND d.phase='reserved' AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3) AND NOT EXISTS(SELECT 1 FROM interaction_delivery_parts p WHERE p.delivery_id=d.id)",params![id,human,self.instance_id],|r|r.get(0)).optional()?;
        let Some(raw) = raw else {
            return Ok(None);
        };
        let mut d: Delivery = serde_json::from_str(&raw)?;
        (d.current, d.correction_pending) = delivery_freshness(&tx, &d)?;
        d.phase = "preparing".into();
        tx.execute(
            "UPDATE interaction_deliveries SET phase='preparing',
                doc=json_set(?2,'$.telegram_publication_selected',1),instance_id=?3 WHERE id=?1",
            params![id, serde_json::to_string(&d)?, self.instance_id],
        )?;
        tx.commit()?;
        Ok(Some(d))
    }

    /// Read-only result inspection refreshes relevance without changing its
    /// original recipient, transmission history or worker declaration.
    pub fn interaction_delivery(&self, id: &str, human: i64) -> Result<Option<Delivery>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let raw:Option<(String,String)>=conn.query_row("SELECT d.doc,d.phase FROM interaction_deliveries d JOIN interaction_requests r ON r.id=d.request_id JOIN sessions s ON s.id=r.session_id JOIN users u ON u.tg_user_id=s.creator_user_id WHERE d.id=?1 AND d.human_id=?2 AND u.tg_user_id=?2 AND u.allowed=1",params![id,human],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        raw.map(|(doc, phase)| {
            let mut d: Delivery = serde_json::from_str(&doc)?;
            d.phase = phase;
            (d.current, d.correction_pending) = delivery_freshness(&conn, &d)?;
            Ok(d)
        })
        .transpose()
    }

    #[cfg(test)]
    pub fn interaction_recent_deliveries(
        &self,
        human: i64,
        target: SessionKey,
    ) -> Result<Vec<Delivery>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let mut stmt=conn.prepare("SELECT d.id FROM interaction_deliveries d JOIN interaction_requests r ON r.id=d.request_id JOIN sessions s ON s.id=r.session_id WHERE d.human_id=?1 AND s.chat_id=?2 AND s.thread_id=?3 ORDER BY d.rowid DESC LIMIT 8")?;
        let ids = stmt
            .query_map(params![human, target.chat_id, target.thread_id], |r| {
                r.get::<_, String>(0)
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        drop(stmt);
        drop(conn);
        ids.into_iter()
            .map(|id| self.interaction_delivery(&id, human))
            .collect::<Result<Vec<_>>>()
            .map(|rows| rows.into_iter().flatten().collect())
    }

    pub fn interaction_finish_delivery(
        &self,
        id: &str,
        human: i64,
        message: Option<i64>,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let phase: String = tx.query_row(
            "SELECT phase FROM interaction_deliveries WHERE id=?1 AND human_id=?2
             AND (instance_id=?3 OR ?4)
             AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)",
            params![id, human, self.instance_id, message.is_some()],
            |r| r.get(0),
        )?;
        if matches!(phase.as_str(), "delivered" | "withheld") {
            return Ok(());
        }
        if phase == "preparing" && message.is_none() {
            tx.execute("UPDATE interaction_deliveries SET phase='reserved' WHERE id=?1 AND NOT EXISTS(SELECT 1 FROM interaction_delivery_parts WHERE delivery_id=?1)",[id])?;
            tx.commit()?;
            return Ok(());
        }
        if !matches!(phase.as_str(), "sending" | "uncertain") {
            return Err(anyhow!(
                "Interaction publication is not an active transmission"
            ));
        }
        let confirmed_phase = if let Some(message) = message {
            let received:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM interaction_delivery_parts WHERE delivery_id=?1 AND message_id=?2)",params![id,message],|r|r.get(0))?;
            if !received {
                return Err(anyhow!(
                    "Result completion requires a retained part receipt"
                ));
            }
            let raw: String = tx.query_row(
                "SELECT doc FROM interaction_deliveries WHERE id=?",
                [id],
                |r| r.get(0),
            )?;
            let frozen: Delivery = serde_json::from_str(&raw)?;
            if frozen.correction_pending {
                "withheld"
            } else {
                "delivered"
            }
        } else {
            "uncertain"
        };
        tx.execute("UPDATE interaction_deliveries SET phase=?2,message_id=COALESCE(?3,message_id) WHERE id=?1",params![id,confirmed_phase,message])?;
        tx.commit()?;
        Ok(())
    }

    /// Retain each part before sending it; known receipts bind replies even when
    /// a later part's transmission is uncertain. No part is automatically replayed.
    pub fn interaction_reserve_part(
        &self,
        id: &str,
        human: i64,
        part: i64,
        text: &str,
        pending_text: &str,
    ) -> Result<Option<(Delivery, String)>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let raw:Option<String>=tx.query_row("SELECT doc FROM interaction_public_deliveries WHERE id=?1 AND human_id=?2 AND phase IN ('preparing','sending') AND instance_id=?3 AND EXISTS(SELECT 1 FROM users WHERE tg_user_id=?2 AND allowed=1) AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)",params![id,human,self.instance_id],|r|r.get(0)).optional()?;
        let Some(raw) = raw else {
            return Ok(None);
        };
        let mut d: Delivery = serde_json::from_str(&raw)?;
        (d.current, d.correction_pending) = delivery_freshness(&tx, &d)?;
        let selected = if d.correction_pending {
            pending_text
        } else {
            text
        }
        .to_owned();
        if tx.execute("INSERT OR IGNORE INTO interaction_delivery_parts(delivery_id,part,text) VALUES(?1,?2,?3)",params![id,part,selected])?!=1 {return Ok(None);}
        d.phase = "sending".into();
        tx.execute(
            "UPDATE interaction_deliveries SET phase='sending',doc=?2,instance_id=?3 WHERE id=?1",
            params![id, serde_json::to_string(&d)?, self.instance_id],
        )?;
        tx.commit()?;
        Ok(Some((d, selected)))
    }

    pub(crate) fn interaction_can_publish_part(
        &self,
        id: &str,
        human: i64,
        part: i64,
    ) -> Result<bool> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let raw: Option<String> = conn.query_row(
            "SELECT d.doc FROM interaction_public_deliveries d
              JOIN users u ON u.tg_user_id=d.human_id AND u.allowed=1
              JOIN interaction_delivery_parts p ON p.delivery_id=d.id AND p.part=?3 AND p.message_id IS NULL
              WHERE d.id=?1 AND d.human_id=?2 AND d.phase='sending' AND d.instance_id=?4
                AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?4)",
            params![id, human, part, self.instance_id],
            |row| row.get(0),
        ).optional()?;
        let Some(raw) = raw else {
            return Ok(false);
        };
        let delivery: Delivery = serde_json::from_str(&raw)?;
        // Preparation and the adapter's submission acknowledgment are separate.
        // Authorize the frozen text only while its correction decision still holds.
        Ok(delivery_freshness(&conn, &delivery)?.1 == delivery.correction_pending)
    }

    pub fn interaction_part_receipt(
        &self,
        id: &str,
        human: i64,
        part: i64,
        message: i64,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let (raw, phase): (String, String) = tx.query_row(
            "SELECT doc,phase FROM interaction_deliveries WHERE id=?1 AND human_id=?2
             AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)",
            params![id, human, self.instance_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        if !matches!(phase.as_str(), "sending" | "uncertain") {
            return Err(anyhow!("Publication receipt has no corresponding attempt"));
        }
        let d: Delivery = serde_json::from_str(&raw)?;
        if tx.execute("UPDATE interaction_delivery_parts SET message_id=?3 WHERE delivery_id=?1 AND part=?2 AND (message_id IS NULL OR message_id=?3)",params![id,part,message])?!=1 {return Err(anyhow!("Publication part receipt conflicts"));}
        let session: i64 = tx.query_row(
            "SELECT session_id FROM interaction_requests WHERE id=?",
            [&d.request_id],
            |r| r.get(0),
        )?;
        bind_message(
            &tx,
            &ReturnRoute {
                message_id: Some(message),
                ..d.origin
            },
            human,
            session,
            d.requests(),
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn interaction_message_target(
        &self,
        route: &ReturnRoute,
        human: i64,
    ) -> Result<Option<(SessionKey, Vec<String>)>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let raw:Option<(i64,i64,String)>=conn.query_row("SELECT s.chat_id,s.thread_id,b.requests FROM interaction_message_bindings b JOIN sessions s ON s.id=b.session_id JOIN users u ON u.tg_user_id=s.creator_user_id WHERE b.chat_id=?1 AND b.thread_id=?2 AND b.message_id=?3 AND b.human_id=?4 AND u.tg_user_id=?4 AND u.allowed=1",params![route.chat_id,route.thread_id,route.message_id,human],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        raw.map(|(chat, thread, requests)| {
            Ok((
                SessionKey::new(chat, Some(thread)),
                serde_json::from_str(&requests)?,
            ))
        })
        .transpose()
    }
    pub fn interaction_bind_message(
        &self,
        human: i64,
        route: &ReturnRoute,
        target: SessionKey,
        requests: &[String],
    ) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let session:i64=conn.query_row("SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id WHERE s.chat_id=?1 AND s.thread_id=?2 AND u.tg_user_id=?3 AND u.allowed=1",params![target.chat_id,target.thread_id,human],|r|r.get(0))?;
        for request in requests {
            let allowed:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM interaction_requests WHERE id=?1 AND session_id=?2 AND human_id=?3)",params![request,session,human],|r|r.get(0))?;
            if !allowed {
                return Err(anyhow!("Reply binding crosses request scope"));
            }
        }
        bind_message(&conn, route, human, session, requests)?;
        Ok(())
    }

    pub fn interaction_hold(
        &self,
        source: &crate::interaction::SourceInput,
        inherited: &[(SessionKey, Vec<String>)],
    ) -> Result<String> {
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("pending:{}:{}", source.channel, source.event_id).as_bytes(),
        )
        .to_string();
        let doc = serde_json::json!({"source":source,"inherited":inherited}).to_string();
        if doc.len() > 512 * 1024 {
            return Err(anyhow!("Routing clarification exceeds input bound"));
        }
        let conn = self.conn.lock().expect("store mutex poisoned");
        let allowed: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM users WHERE tg_user_id=? AND allowed=1)",
            [source.human_id],
            |r| r.get(0),
        )?;
        if !allowed {
            return Err(anyhow!("Routing input is no longer authorized"));
        }
        if conn.execute("INSERT OR IGNORE INTO interaction_clarifications(id,human_id,doc,phase) VALUES(?1,?2,?3,'awaiting_target')",params![id,source.human_id,doc])?==0 {
            let original:String=conn.query_row("SELECT doc FROM interaction_clarifications WHERE id=?",[&id],|r|r.get(0))?;
            if original!=doc {return Err(anyhow!("Pending routing source is immutable"));}
        }
        Ok(id)
    }

    pub fn interaction_hold_state(&self, id: &str, human: i64) -> Result<Option<String>> {
        Ok(self
            .conn
            .lock()
            .expect("store mutex poisoned")
            .query_row(
                "SELECT phase FROM interaction_clarifications WHERE id=?1 AND human_id=?2",
                params![id, human],
                |r| r.get(0),
            )
            .optional()?)
    }

    pub fn interaction_hold_message(
        &self,
        id: &str,
        human: i64,
        route: &ReturnRoute,
    ) -> Result<()> {
        self.conn.lock().expect("store mutex poisoned").execute("UPDATE interaction_clarifications SET question_chat=?3,question_thread=?4,question_message=?5 WHERE id=?1 AND human_id=?2 AND question_message IS NULL",params![id,human,route.chat_id,route.thread_id,route.message_id])?;
        Ok(())
    }

    pub fn interaction_hold_reply(
        &self,
        route: &ReturnRoute,
        human: i64,
    ) -> Result<Option<serde_json::Value>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let raw:Option<(String,String,String)>=conn.query_row("SELECT id,doc,phase FROM interaction_clarifications WHERE human_id=?1 AND ((question_chat=?2 AND question_thread=?3 AND question_message=?4) OR (json_extract(doc,'$.source.origin.chat_id')=?2 AND json_extract(doc,'$.source.origin.thread_id')=?3 AND json_extract(doc,'$.source.origin.message_id')=?4)) ORDER BY rowid DESC LIMIT 1",params![human,route.chat_id,route.thread_id,route.message_id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        raw.map(|(id, doc, phase)| {
            let mut doc: serde_json::Value = serde_json::from_str(&doc)?;
            doc["id"] = id.into();
            doc["phase"] = phase.into();
            Ok(doc)
        })
        .transpose()
    }

    pub fn interaction_close_hold(&self, id: &str, human: i64, resolved: bool) -> Result<bool> {
        Ok(self.conn.lock().expect("store mutex poisoned").execute("UPDATE interaction_clarifications SET phase=?3 WHERE id=?1 AND human_id=?2 AND phase='awaiting_target'",params![id,human,if resolved{"resolved"}else{"cancelled"}])?==1)
    }

    /// Definite native rejection permits a continuation of the same retained
    /// instruction. It never authorizes another destination or uncertain replay.
    pub fn interaction_requeue_rejected(&self, id: &str, human: i64) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let raw:Option<String>=tx.query_row("SELECT i.doc FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id WHERE i.id=?1 AND s.human_id=?2 AND i.phase='rejected'",params![id,human],|r|r.get(0)).optional()?;
        let Some(raw) = raw else {
            return Ok(false);
        };
        let mut i: Instruction = serde_json::from_str(&raw)?;
        i.phase = crate::interaction::TransportPhase::Queued;
        i.local_turn = None;
        i.native_turn = None;
        tx.execute(
            "UPDATE interaction_instructions SET phase='queued',doc=?2,instance_id=?3 WHERE id=?1",
            params![id, serde_json::to_string(&i)?, self.instance_id],
        )?;
        tx.commit()?;
        Ok(true)
    }

    pub fn interaction_unfinished(&self, id: &str, human: i64) -> Result<()> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        conn.execute("UPDATE interaction_instructions SET phase=CASE WHEN phase='queued' THEN 'retained_unsent' ELSE 'uncertain' END WHERE id=?1 AND input_id IN (SELECT id FROM interaction_sources WHERE human_id=?2) AND phase IN ('queued','submitting','steering')",params![id,human])?;
        Ok(())
    }

    pub fn interaction_source(
        &self,
        id: &str,
        human: i64,
    ) -> Result<crate::interaction::SourceInput> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        source_on(&conn, id, human)
    }
}

pub(super) fn source_on(
    conn: &Connection,
    id: &str,
    human: i64,
) -> Result<crate::interaction::SourceInput> {
    let raw:String=conn.query_row("SELECT s.doc FROM interaction_sources s JOIN interaction_instructions i ON i.input_id=s.id WHERE i.id=?1 AND s.human_id=?2",params![id,human],|r|r.get(0))?;
    Ok(serde_json::from_str(&raw)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::interaction::{RequestRelation as R, SourceInput, TransportPhase as P};
    use crate::models::{SessionRecord, TurnRequest};

    fn target(s: &Store, topic: i64) -> SessionRecord {
        let key = SessionKey::new(100, Some(topic));
        s.ensure_session(key, 100, &super::super::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(key, &format!("native-{topic}"))
            .unwrap();
        s.get_session(key).unwrap().unwrap()
    }
    fn admit(s: &Store, target: &SessionRecord, event: i64, relation: R) -> Instruction {
        s.interaction_admit(
            &SourceInput {
                telegram_files: vec![],
                tribu_source: None,
                transcription: None,
                channel: "fixture".into(),
                event_id: event.to_string(),
                update_id: Some(event),
                human_id: 100,
                target_sessions: vec![target.id],
                origin: ReturnRoute {
                    chat_id: 100,
                    thread_id: 1,
                    message_id: Some(event),
                },
                text: format!("Input {event}"),
            },
            target.key,
            relation,
        )
        .unwrap()
        .0
    }
    #[test]
    fn a_routed_original_keeps_its_admitted_target_execution() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let target = target(&store, 7);
        let original = admit(&store, &target, 11, R::New);
        let request = TurnRequest {
            session_key: target.key,
            from_user_id: 100,
            prompt: original.text.clone(),
            runtime_instructions: None,
            attachments: vec![],
            review_mode: None,
            override_search_mode: None,
        };
        let selected = original.target_execution.as_ref().unwrap();
        assert_eq!(selected.native_session.as_deref(), Some("native-7"));
        assert!(
            store
                .interaction_target_execution_allowed(&original)
                .unwrap()
        );

        store
            .set_session_codex_thread(target.key, "new-writer")
            .unwrap();
        store
            .set_session_codex_thread(target.key, "native-7")
            .unwrap();
        let retried = admit(&store, &target, 11, R::New);
        assert_eq!(retried.id, original.id);
        assert_eq!(retried.target_execution.as_ref(), Some(selected));
        assert!(
            !store
                .interaction_target_execution_allowed(&retried)
                .unwrap()
        );
        assert!(
            store
                .record_turn_started_mode(target.id, &request, Some(&original.id))
                .is_err()
        );

        assert!(!store.get_session(target.key).unwrap().unwrap().busy);

        let later = admit(&store, &target, 12, R::New);
        assert!(store.interaction_target_execution_allowed(&later).unwrap());
        store
            .record_turn_started_mode(target.id, &request, Some(&later.id))
            .unwrap();
    }

    #[test]
    fn queued_targets_can_materialize_the_first_writer_in_the_same_generation() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100], &defaults).unwrap();
        let key = SessionKey::new(100, Some(8));
        let target = store.ensure_session(key, 100, &defaults).unwrap();
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "UPDATE sessions SET force_fresh_thread=1 WHERE id=?1",
                [target.id],
            )
            .unwrap();
        let first = admit(&store, &target, 13, R::New);
        let second = admit(&store, &target, 14, R::New);
        assert!(
            first
                .target_execution
                .as_ref()
                .unwrap()
                .native_session
                .is_none()
        );
        store.set_session_codex_thread(key, "first-native").unwrap();
        assert!(store.interaction_target_execution_allowed(&first).unwrap());
        assert!(store.interaction_target_execution_allowed(&second).unwrap());
        let local = store
            .record_turn_started_mode(
                target.id,
                &TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: second.text.clone(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
                Some(&second.id),
            )
            .unwrap();
        store
            .record_turn_native_thread(local, "wrong-native")
            .unwrap();
        assert!(store.bind_codex_turn(local, "wrong-native").is_err());
        assert_eq!(
            store
                .get_session(key)
                .unwrap()
                .unwrap()
                .codex_thread_id
                .as_deref(),
            Some("first-native")
        );
    }

    fn accept(s: &Store, target: &SessionRecord, i: &Instruction) -> i64 {
        let local = s
            .record_turn_started(
                target.id,
                &TurnRequest {
                    session_key: target.key,
                    from_user_id: 100,
                    prompt: i.text.clone(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        s.record_turn_native_thread(local, target.codex_thread_id.as_deref().unwrap())
            .unwrap();
        s.interaction_transport(&i.id, 100, local, P::Submitting, None)
            .unwrap();
        s.interaction_transport(&i.id, 100, local, P::Accepted, Some("physical-turn"))
            .unwrap();
        local
    }
    fn reserve(
        s: &Store,
        target: &SessionRecord,
        i: &Instruction,
        local: i64,
        item: &str,
    ) -> Delivery {
        let text = format!(
            "Answer\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":i.requests,"covered":[i.id],"completed":i.requests})
        );
        let thread = target.codex_thread_id.as_deref().unwrap();
        s.record_native_message(
            local,
            thread,
            "physical-turn",
            item,
            Some("final_answer"),
            &text,
        )
        .unwrap();
        let deliveries = s
            .interaction_reserve_result(&i.id, 100, local, thread, "physical-turn", item, &text)
            .unwrap();
        assert!(
            s.interaction_reserve_result(&i.id, 100, local, thread, "physical-turn", item, &text)
                .unwrap()
                .is_empty()
        );
        deliveries.into_iter().next().unwrap()
    }

    #[test]
    fn continued_physical_turn_keeps_the_same_admitted_logical_work() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let input = admit(&s, &t, 1, R::New);
        let local = accept(&s, &t, &input);
        let text = format!(
            "Continued work\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":input.requests,"covered":[input.id],"completed":[],"deferred":[]})
        );
        let rows = s
            .interaction_record_result(
                &input.id,
                100,
                local,
                t.codex_thread_id.as_deref().unwrap(),
                "later-goal-turn",
                "continued",
                &text,
                true,
            )
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert!(rows[0].current && !rows[0].completed);
        assert_eq!(
            s.interaction_instruction(&input.id, 100)
                .unwrap()
                .unwrap()
                .native_turn
                .as_deref(),
            Some("physical-turn"),
            "The original native acceptance must stay immutable"
        );
    }

    #[test]
    fn shared_response_keeps_all_requests_and_rechecks_non_primary_corrections() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let a = admit(&s, &t, 1, R::New);
        let b = admit(&s, &t, 2, R::New);
        let local = accept(&s, &t, &a);
        s.interaction_transport(&b.id, 100, local, P::Submitting, None)
            .unwrap();
        s.interaction_transport(&b.id, 100, local, P::Accepted, Some("physical-turn"))
            .unwrap();
        let text = format!(
            "Shared progress\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":[a.id,b.id],"covered":[a.id,b.id],"completed":[],"deferred":[]})
        );
        let thread = t.codex_thread_id.as_deref().unwrap();
        let rows = s
            .interaction_record_result(
                &a.id,
                100,
                local,
                thread,
                "physical-turn",
                "shared",
                &text,
                true,
            )
            .unwrap();
        assert_eq!(rows.len(), 1);
        let d = &rows[0];
        assert_eq!(d.request_id, b.id);
        assert_eq!(d.requests().len(), 2);
        assert!(d.requests().contains(&a.id) && d.requests().contains(&b.id));
        assert!(d.current && !d.completed);
        s.interaction_begin_delivery(&d.id, 100).unwrap().unwrap();
        admit(&s, &t, 3, R::Amends(a.requests.clone()));
        let (pending, body) = s
            .interaction_reserve_part(&d.id, 100, 0, "old shared response", "correction pending")
            .unwrap()
            .unwrap();
        assert!(pending.correction_pending && !pending.current);
        assert_eq!(body, "correction pending");
        assert!(
            s.interaction_record_result(
                &a.id,
                100,
                local,
                thread,
                "physical-turn",
                "shared",
                &text,
                true
            )
            .unwrap()
            .is_empty()
        );
        s.interaction_part_receipt(&d.id, 100, 0, 501).unwrap();
        let binding = s
            .interaction_message_target(
                &ReturnRoute {
                    message_id: Some(501),
                    ..d.origin.clone()
                },
                100,
            )
            .unwrap()
            .unwrap();
        assert_eq!(binding.1, d.requests());
    }

    #[test]
    fn historical_coverage_is_not_republished_and_context_uses_current_return_origin() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let entry = SessionKey::new(100, Some(1));
        s.ensure_session(entry, 100, &super::super::tests::defaults())
            .unwrap();
        s.set_session_codex_thread(entry, "entry-native").unwrap();
        let source = SourceInput {
            telegram_files: vec![],
            tribu_source: None,
            transcription: None,
            channel: "fixture".into(),
            event_id: "old-direct".into(),
            update_id: Some(1),
            human_id: 100,
            target_sessions: vec![t.id],
            origin: ReturnRoute {
                chat_id: 100,
                thread_id: 7,
                message_id: Some(1),
            },
            text: "Historical direct work".into(),
        };
        let old = s.interaction_admit(&source, t.key, R::New).unwrap().0;
        let old_local = accept(&s, &t, &old);
        reserve(&s, &t, &old, old_local, "earlier");
        let current = admit(&s, &t, 2, R::New);
        let local = accept(&s, &t, &current);
        let thread = t.codex_thread_id.as_deref().unwrap();
        let text = format!(
            "Current answer\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":[old.id,current.id],"covered":[old.id,current.id],"completed":[],"deferred":[]})
        );
        let rows = s
            .interaction_record_result(
                &current.id,
                100,
                local,
                thread,
                "physical-turn",
                "current",
                &text,
                true,
            )
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].requests(), current.requests);
        assert_eq!(rows[0].origin, current.origin);
        let follow = admit(&s, &t, 3, R::Context(old.requests.clone()));
        let next = accept(&s, &t, &follow);
        let text = format!(
            "Follow-up answer\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":old.requests,"covered":[old.id,follow.id],"completed":[],"deferred":[]})
        );
        let rows = s
            .interaction_record_result(
                &follow.id,
                100,
                next,
                thread,
                "physical-turn",
                "follow",
                &text,
                true,
            )
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].origin, follow.origin);
        assert_ne!(rows[0].origin.thread_id, old.origin.thread_id);
        let page = s.interaction_presentation_list(100, entry, 0, 0).unwrap();
        let replies = page["items"].as_array().unwrap();
        assert_eq!(
            replies.len(),
            2,
            "The current return must be readable from its requesting entry even though the old request originated in a work topic"
        );
        assert!(
            replies
                .iter()
                .any(|item| item["preview"] == "Follow-up answer")
        );
    }

    #[test]
    fn interaction_dispatch_epoch_changes_only_after_explicit_unsent_recovery() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let i = admit(&s, &t, 1, R::New);
        s.interaction_bind_epoch(&i.id, 100, "original").unwrap();
        assert!(s.interaction_bind_epoch(&i.id, 100, "later").is_err());
        s.interaction_unfinished(&i.id, 100).unwrap();
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .admission_epoch
                .as_deref(),
            Some("original")
        );
        assert!(s.interaction_recover(&i.id, 100, None).unwrap());
        s.interaction_bind_epoch(&i.id, 100, "later").unwrap();
        assert_eq!(
            s.interaction_instruction(&i.id, 100)
                .unwrap()
                .unwrap()
                .admission_epoch
                .as_deref(),
            Some("later")
        );
        assert_eq!(s.interaction_recent(100, t.key).unwrap().len(), 1);
    }

    #[test]
    fn interaction_attached_input_requires_worker_coverage_before_routing_a_legacy_answer() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let i = admit(&s, &t, 1, R::New);
        let local = accept(&s, &t, &i);
        let thread = t.codex_thread_id.as_deref().unwrap();
        assert_eq!(s.interaction_turn_inputs(local, 100).unwrap().len(), 1);
        assert!(s.interaction_turn_inputs(local, 101).unwrap().is_empty());
        assert!(
            s.interaction_record_result(
                &i.id,
                100,
                local,
                thread,
                "physical-turn",
                "legacy",
                "Earlier unrelated work",
                false
            )
            .unwrap()
            .is_empty()
        );
        assert!(
            s.interaction_recent_deliveries(100, t.key)
                .unwrap()
                .is_empty()
        );
        let retained: i64 = s
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM interaction_native_messages WHERE item_id='legacy'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(retained, 1);
        let text = format!(
            "Corrected work\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":i.requests,"covered":[i.id],"completed":i.requests})
        );
        let deliveries = s
            .interaction_record_result(
                &i.id,
                100,
                local,
                thread,
                "physical-turn",
                "covered",
                &text,
                false,
            )
            .unwrap();
        assert_eq!(deliveries.len(), 1);
        assert!(deliveries[0].declared && deliveries[0].current);
        assert_eq!(deliveries[0].origin, i.origin);
    }

    #[test]
    fn interaction_native_capture_and_return_reservation_commit_together() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let i = admit(&s, &t, 1, R::New);
        let local = accept(&s, &t, &i);
        let thread = t.codex_thread_id.as_deref().unwrap();
        s.conn.lock().unwrap().execute_batch("CREATE TRIGGER fail_reservation BEFORE INSERT ON interaction_deliveries BEGIN SELECT RAISE(ABORT,'fixture reservation failure'); END;").unwrap();
        assert!(
            s.interaction_record_result(
                &i.id,
                100,
                local,
                thread,
                "physical-turn",
                "atomic",
                "Actual native answer",
                true
            )
            .is_err()
        );
        let count: i64 = s
            .conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM interaction_native_messages WHERE item_id='atomic'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(
            count, 0,
            "A failed reservation must not commit an orphan canonical final"
        );
        s.conn
            .lock()
            .unwrap()
            .execute_batch("DROP TRIGGER fail_reservation")
            .unwrap();
        let deliveries = s
            .interaction_record_result(
                &i.id,
                100,
                local,
                thread,
                "physical-turn",
                "atomic",
                "Actual native answer",
                true,
            )
            .unwrap();
        assert_eq!(deliveries.len(), 1);
        assert!(
            s.interaction_record_result(
                &i.id,
                100,
                local,
                thread,
                "physical-turn",
                "atomic",
                "Actual native answer",
                true
            )
            .unwrap()
            .is_empty()
        );
        let id = deliveries[0].id.clone();
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            s.interaction_delivery(&id, 100).unwrap().unwrap().phase,
            "reserved"
        );
        assert!(s.interaction_begin_delivery(&id, 100).unwrap().is_some());
    }

    #[test]
    fn telegram_recovery_uses_only_selected_proven_unsent_parts() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let store = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let conversation = target(&store, 7);
        let a = admit(&store, &conversation, 1, R::New);
        let b = admit(&store, &conversation, 2, R::New);
        let local_a = accept(&store, &conversation, &a);
        let local_b = accept(&store, &conversation, &b);
        let selected = reserve(&store, &conversation, &a, local_a, "selected");
        let unselected = reserve(&store, &conversation, &b, local_b, "unselected");
        let entry = SessionKey::new(100, Some(1));
        let ready = || {
            store
                .interaction_ready_telegram_deliveries(100, entry, true)
                .unwrap()
                .into_iter()
                .map(|delivery| delivery.id)
                .collect::<Vec<_>>()
        };

        assert!(ready().is_empty());
        assert!(
            store
                .interaction_begin_delivery(&selected.id, 100)
                .unwrap()
                .is_some()
        );
        assert!(ready().is_empty());
        assert!(
            store
                .interaction_reserve_part(&selected.id, 100, 0, "first", "pending")
                .unwrap()
                .is_some()
        );
        assert!(
            store
                .interaction_first_part_not_submitted(&selected.id, 100)
                .unwrap()
        );
        assert_eq!(ready(), vec![selected.id.clone()]);
        assert!(
            store
                .interaction_begin_delivery(&selected.id, 100)
                .unwrap()
                .is_some()
        );
        assert!(
            store
                .interaction_reserve_part(&selected.id, 100, 0, "first", "pending")
                .unwrap()
                .is_some()
        );
        store
            .interaction_finish_delivery(&selected.id, 100, None)
            .unwrap();
        assert!(
            !store
                .interaction_first_part_not_submitted(&selected.id, 100)
                .unwrap()
        );
        assert!(ready().is_empty());
        assert_eq!(
            store
                .interaction_delivery(&unselected.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            "reserved"
        );
        assert!(
            store
                .interaction_begin_delivery(&unselected.id, 100)
                .unwrap()
                .is_some()
        );
        {
            let conn = store.conn.lock().unwrap();
            conn.execute(
                "UPDATE app_instance_lock SET instance_id='fixture-replacement' WHERE key='main'",
                [],
            )
            .unwrap();
            conn.execute(
                "UPDATE interaction_deliveries SET instance_id='fixture-replacement' WHERE id=?1",
                [&unselected.id],
            )
            .unwrap();
        }
        assert!(
            store
                .interaction_reserve_part(&unselected.id, 100, 0, "stale", "pending")
                .unwrap()
                .is_none()
        );
        assert!(
            !store
                .interaction_can_publish_part(&unselected.id, 100, 0)
                .unwrap()
        );
        assert!(
            store
                .interaction_finish_delivery(&unselected.id, 100, None)
                .is_err()
        );
        assert_eq!(
            store
                .interaction_delivery(&unselected.id, 100)
                .unwrap()
                .unwrap()
                .phase,
            "preparing"
        );
    }

    #[test]
    fn interaction_publication_rechecks_corrections_after_preparing_and_keeps_other_requests_live()
    {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let a = admit(&s, &t, 1, R::New);
        let b = admit(&s, &t, 2, R::New);
        let local_a = accept(&s, &t, &a);
        let local_b = accept(&s, &t, &b);
        let da = reserve(&s, &t, &a, local_a, "a");
        let db = reserve(&s, &t, &b, local_b, "b");
        assert!(da.current && da.completed);
        assert!(
            s.interaction_begin_delivery(&da.id, 100)
                .unwrap()
                .unwrap()
                .current
        );
        assert!(s.interaction_begin_delivery(&da.id, 100).unwrap().is_none());
        let _correction = admit(&s, &t, 3, R::Amends(a.requests.clone()));
        let (fresh, text) = s
            .interaction_reserve_part(&da.id, 100, 0, "obsolete answer", "correction pending")
            .unwrap()
            .unwrap();
        assert!(fresh.correction_pending && !fresh.current);
        assert_eq!(text, "correction pending");
        assert!(
            s.interaction_reserve_part(&da.id, 100, 0, "retry", "retry")
                .unwrap()
                .is_none()
        );
        s.interaction_part_receipt(&da.id, 100, 0, 501).unwrap();
        let reply = ReturnRoute {
            message_id: Some(501),
            ..a.origin.clone()
        };
        assert_eq!(
            s.interaction_message_target(&reply, 100).unwrap(),
            Some((t.key, a.requests.clone()))
        );
        assert!(s.interaction_message_target(&reply, 101).unwrap().is_none());
        let other = target(&s, 8);
        assert!(
            s.interaction_bind_message(100, &reply, other.key, &[])
                .is_err()
        );
        assert!(s.interaction_part_receipt(&da.id, 100, 0, 502).is_err());
        s.interaction_finish_delivery(&da.id, 100, Some(501))
            .unwrap();
        assert!(s.interaction_begin_delivery(&db.id, 101).unwrap().is_none());
        assert!(
            s.interaction_begin_delivery(&db.id, 100)
                .unwrap()
                .unwrap()
                .current
        );
        let (fresh, text) = s
            .interaction_reserve_part(&db.id, 100, 0, "B answer", "pending")
            .unwrap()
            .unwrap();
        assert!(fresh.current && !fresh.correction_pending);
        assert_eq!(text, "B answer");
    }

    #[test]
    fn interaction_late_correction_preserves_uncertain_then_delivered_history_and_new_items() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let a = admit(&s, &t, 1, R::New);
        let local = accept(&s, &t, &a);
        let old = reserve(&s, &t, &a, local, "earlier");
        s.interaction_begin_delivery(&old.id, 100).unwrap();
        s.interaction_reserve_part(
            &old.id,
            100,
            0,
            "Earlier answer already attempting transmission",
            "pending",
        )
        .unwrap();
        let amendment = admit(&s, &t, 2, R::Amends(a.requests.clone()));
        s.interaction_finish_delivery(&old.id, 100, None).unwrap();
        let d = s.interaction_delivery(&old.id, 100).unwrap().unwrap();
        assert_eq!(d.phase, "uncertain");
        assert!(!d.current && d.correction_pending);
        assert_eq!(d.body, "Answer");
        assert!(s.interaction_begin_delivery(&d.id, 100).unwrap().is_none());
        assert!(s.interaction_delivery(&d.id, 101).unwrap().is_none());
        // Inspection is read-only and does not turn uncertainty into a retry.
        for _ in 0..2 {
            assert_eq!(
                s.interaction_recent_deliveries(100, t.key).unwrap()[0].phase,
                "uncertain"
            );
        }
        assert!(
            s.interaction_reserve_part(&d.id, 100, 0, "retry", "pending")
                .unwrap()
                .is_none()
        );
        // Exact late evidence confirms the earlier attempt, not the correction.
        s.interaction_part_receipt(&d.id, 100, 0, 701).unwrap();
        s.interaction_finish_delivery(&d.id, 100, Some(701))
            .unwrap();
        let prior = s.interaction_delivery(&d.id, 100).unwrap().unwrap();
        assert_eq!(prior.phase, "delivered");
        assert!(prior.correction_pending);
        s.interaction_transport(&amendment.id, 100, local, P::Steering, None)
            .unwrap();
        s.interaction_transport(
            &amendment.id,
            100,
            local,
            P::Accepted,
            Some("physical-turn"),
        )
        .unwrap();
        let text = format!(
            "Updated answer\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":a.requests,"covered":[a.id,amendment.id],"completed":a.requests})
        );
        let thread = t.codex_thread_id.as_deref().unwrap();
        s.record_native_message(
            local,
            thread,
            "physical-turn",
            "updated",
            Some("final_answer"),
            &text,
        )
        .unwrap();
        let updated = s
            .interaction_reserve_result(
                &a.id,
                100,
                local,
                thread,
                "physical-turn",
                "updated",
                &text,
            )
            .unwrap();
        assert_eq!(updated.len(), 1);
        assert!(updated[0].current && !updated[0].correction_pending);
        assert_eq!(
            s.interaction_recent_deliveries(100, t.key).unwrap()[0].id,
            updated[0].id
        );
        let unchanged = s.interaction_delivery(&d.id, 100).unwrap().unwrap();
        assert_eq!(unchanged.body, "Answer");
        assert!(unchanged.correction_pending);
    }

    #[test]
    fn interaction_later_result_honors_only_confirmed_corrections_on_the_same_generation() {
        for (acked, changed_generation) in [(true, false), (false, false), (true, true)] {
            let file = tempfile::NamedTempFile::new().unwrap();
            let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
            let topic = target(&s, 7);
            let first = admit(&s, &topic, 1, R::New);
            let prior = admit(&s, &topic, 2, R::Amends(first.requests.clone()));
            let before = accept(&s, &topic, &prior);
            let published = reserve(&s, &topic, &prior, before, "prior-amendment");
            s.interaction_begin_delivery(&published.id, 100).unwrap();
            s.interaction_reserve_part(&published.id, 100, 0, "Answer", "pending")
                .unwrap()
                .unwrap();
            if acked {
                s.interaction_part_receipt(&published.id, 100, 0, 501)
                    .unwrap();
            }
            s.interaction_finish_delivery(&published.id, 100, acked.then_some(501))
                .unwrap();
            let next = admit(&s, &topic, 3, R::Amends(first.requests.clone()));
            let after = accept(&s, &topic, &next);
            {
                let conn = s.conn.lock().unwrap();
                conn.execute(
                    "INSERT INTO conversation_entry_generations(session_id,generation) VALUES(?1,1)
                     ON CONFLICT(session_id) DO UPDATE SET generation=1",
                    [topic.id],
                )
                .unwrap();
                conn.execute(
                    "UPDATE turns SET status='completed',execution_generation=1 WHERE id=?1",
                    [before],
                )
                .unwrap();
                conn.execute(
                    "UPDATE turns SET execution_generation=?1 WHERE id=?2",
                    params![if changed_generation { 2 } else { 1 }, after],
                )
                .unwrap();
            }
            let later = reserve(&s, &topic, &next, after, "later-amendment");
            assert_eq!(later.covered, vec![next.id]);
            assert_eq!(later.correction_pending, !acked || changed_generation);
            assert_eq!(
                s.interaction_delivery(&later.id, 100)
                    .unwrap()
                    .unwrap()
                    .correction_pending,
                !acked || changed_generation
            );

            s.interaction_begin_delivery(&later.id, 100)
                .unwrap()
                .unwrap();
            let (_, published_text) = s
                .interaction_reserve_part(&later.id, 100, 0, "body", "pending")
                .unwrap()
                .unwrap();
            assert_eq!(
                published_text,
                if acked && !changed_generation {
                    "body"
                } else {
                    "pending"
                }
            );
            assert!(s.interaction_can_publish_part(&later.id, 100, 0).unwrap());
            {
                let conn = s.conn.lock().unwrap();
                conn.execute(
                    "UPDATE conversation_entry_generations SET generation=3 WHERE session_id=?1",
                    [topic.id],
                )
                .unwrap();
            }
            assert!(
                s.interaction_delivery(&later.id, 100)
                    .unwrap()
                    .unwrap()
                    .correction_pending
            );
            assert_eq!(
                s.interaction_can_publish_part(&later.id, 100, 0).unwrap(),
                !acked || changed_generation
            );
            {
                let conn = s.conn.lock().unwrap();
                conn.execute(
                    "UPDATE conversation_entry_generations SET generation=1 WHERE session_id=?1",
                    [topic.id],
                )
                .unwrap();
            }
            let _pending = admit(&s, &topic, 4, R::Amends(first.requests.clone()));
            assert_eq!(
                s.interaction_can_publish_part(&later.id, 100, 0).unwrap(),
                !acked || changed_generation
            );
            assert!(
                s.interaction_delivery(&later.id, 100)
                    .unwrap()
                    .unwrap()
                    .correction_pending
            );
            if acked && !changed_generation {
                assert!(
                    s.interaction_first_part_not_submitted(&later.id, 100)
                        .unwrap()
                );
                let ready = s
                    .interaction_ready_telegram_deliveries(
                        100,
                        SessionKey::new(next.origin.chat_id, Some(next.origin.thread_id)),
                        false,
                    )
                    .unwrap();
                assert!(ready.iter().any(|delivery| delivery.id == later.id));
                s.interaction_begin_delivery(&later.id, 100)
                    .unwrap()
                    .unwrap();
                let (_, replacement) = s
                    .interaction_reserve_part(&later.id, 100, 0, "body", "pending")
                    .unwrap()
                    .unwrap();
                assert_eq!(replacement, "pending");
            }
        }
    }

    #[test]
    fn interaction_restart_distinguishes_preparation_from_uncertain_transmission() {
        let file = tempfile::NamedTempFile::new().unwrap();
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        let t = target(&s, 7);
        let a = admit(&s, &t, 1, R::New);
        let b = admit(&s, &t, 2, R::New);
        let local_a = accept(&s, &t, &a);
        let local_b = accept(&s, &t, &b);
        let da = reserve(&s, &t, &a, local_a, "a");
        let db = reserve(&s, &t, &b, local_b, "b");
        s.interaction_begin_delivery(&da.id, 100).unwrap();
        s.interaction_begin_delivery(&db.id, 100).unwrap();
        s.interaction_reserve_part(&db.id, 100, 0, "B", "pending")
            .unwrap();
        drop(s);
        let s = Store::open(file.path(), &[100], &super::super::tests::defaults()).unwrap();
        assert_eq!(
            s.interaction_delivery(&da.id, 100).unwrap().unwrap().phase,
            "reserved"
        );
        assert!(s.interaction_begin_delivery(&da.id, 100).unwrap().is_some());
        assert!(s.interaction_begin_delivery(&db.id, 100).unwrap().is_none());
        s.interaction_finish_delivery(&da.id, 100, None).unwrap();
        assert_eq!(
            s.interaction_delivery(&da.id, 100).unwrap().unwrap().phase,
            "reserved"
        );
        assert!(s.interaction_begin_delivery(&da.id, 100).unwrap().is_some());
        assert!(
            s.interaction_reserve_part(&db.id, 100, 0, "B retry", "pending")
                .unwrap()
                .is_none()
        );
        // A late exact receipt reconciles the original attempt, without replay.
        s.interaction_part_receipt(&db.id, 100, 0, 601).unwrap();
        s.interaction_finish_delivery(&db.id, 100, Some(601))
            .unwrap();
        assert!(
            s.interaction_message_target(
                &ReturnRoute {
                    message_id: Some(601),
                    ..b.origin
                },
                100
            )
            .unwrap()
            .is_some()
        );
    }
}
