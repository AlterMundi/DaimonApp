//! Bounded, attributable local observations. A snapshot is not complete native history.
use super::*;
use crate::interaction::{Delivery, Instruction};

pub struct ObservedDelivery {
    pub value: Delivery,
    pub native_thread: String,
    pub native_turn: String,
    pub item_id: String,
}

#[derive(serde::Serialize)]
pub(crate) struct ObservedExecution {
    harness: String,
    local_turn: i64,
    phase: String,
    turn_at: String,
    current_generation: Option<bool>,
}

pub struct SessionObservation {
    pub sampled_at: String,
    pub(crate) latest_executions: Vec<ObservedExecution>,
    pub session_id: i64,
    pub(crate) execution: crate::execution::ExecutionBinding,
    pub native_thread: Option<String>,
    pub input_cut: i64,
    pub latest_input: Option<Instruction>,
    pub latest_delivery: Option<ObservedDelivery>,
    pub local_turn: Option<(i64, String, String)>,
    pub native_item: Option<(String, String, String)>,
    pub pending: interactions::InteractionPage,
    pub presentation_gaps: usize,
    pub semantic: Option<(super::observer_cards::ObserverCard, ObserverFreshness)>,
}

impl Store {
    /// Every local field shares one SQLite read snapshot. No native writer,
    /// instruction admission, recovery or delivery is triggered by observation.
    pub fn interaction_observation(
        &self,
        key: SessionKey,
        human: i64,
    ) -> Result<Option<SessionObservation>> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction()?;
        let Some(binding) = super::execution::binding_on(&tx, key, human)? else {
            return Ok(None);
        };
        let execution = binding.execution;
        let session_id = execution.conversation_id;
        let native_thread = binding.legacy_native_session;
        let input: Option<(String, String)> = tx.query_row(
            "SELECT i.doc,i.phase FROM interaction_instructions i JOIN interaction_sources s ON s.id=i.input_id WHERE i.session_id=?1 AND s.human_id=?2 ORDER BY i.sequence DESC LIMIT 1",
            params![session_id,human], |r| Ok((r.get(0)?,r.get(1)?)),
        ).optional()?;
        let latest_input = input
            .map(|(doc, phase)| -> Result<Instruction> {
                let mut i: Instruction = serde_json::from_str(&doc)?;
                i.phase = phase.as_str().try_into()?;
                Ok(i)
            })
            .transpose()?;
        let input_cut = latest_input.as_ref().map_or(0, |i| i.sequence);
        let result: Option<(String, String, String, String, String)> = tx.query_row(
            "SELECT d.doc,d.phase,o.native_thread,o.native_turn,o.item_id FROM interaction_deliveries d JOIN interaction_results o ON o.id=d.result_id JOIN interaction_requests r ON r.id=d.request_id WHERE r.session_id=?1 AND d.human_id=?2 ORDER BY d.rowid DESC LIMIT 1",
            params![session_id,human], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?)),
        ).optional()?;
        let latest_delivery = result
            .map(
                |(doc, phase, native_thread, native_turn, item_id)| -> Result<ObservedDelivery> {
                    let mut d: Delivery = serde_json::from_str(&doc)?;
                    d.phase = phase;
                    (d.current, d.correction_pending) = routing::delivery_freshness(&tx, &d)?;
                    Ok(ObservedDelivery {
                        value: d,
                        native_thread,
                        native_turn,
                        item_id,
                    })
                },
            )
            .transpose()?;
        let local_turn = tx.query_row(
            "SELECT id,status,COALESCE(completed_at,started_at) FROM turns WHERE session_id=?1 AND from_user_id=?2 AND (native_thread_id IS NULL OR native_thread_id IS ?3) ORDER BY id DESC LIMIT 1",
            params![session_id,human,native_thread], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?)),
        ).optional()?;
        let native_item = tx.query_row(
            "SELECT m.native_turn,m.item_id,m.observed_at FROM interaction_native_messages m JOIN turns t ON t.id=m.local_turn WHERE t.session_id=?1 AND t.from_user_id=?2 AND m.native_thread IS ?3 ORDER BY m.rowid DESC LIMIT 1",
            params![session_id,human,native_thread], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?)),
        ).optional()?;
        let presentation_gaps = tx.query_row(
            "SELECT COUNT(*) FROM bot_state b JOIN turns t ON b.key='interaction_presentation_gap:'||t.id WHERE t.session_id=?1 AND t.from_user_id=?2 AND t.native_thread_id IS ?3",
            params![session_id,human,native_thread], |r| r.get(0),
        )?;
        let pending = interactions::interaction_page_on(&tx, key, human, 0, false)?;
        let semantic = if let Some(native) = native_thread.as_deref() {
            super::observer_cards::head(&tx, session_id, native)?
                .map(|card| {
                    let freshness = super::observer_freshness::freshness_on(
                        &tx,
                        session_id,
                        native,
                        &card.source_revision,
                        &self.instance_id,
                    )?;
                    Ok::<_, anyhow::Error>((card, freshness))
                })
                .transpose()?
        } else {
            None
        };
        // A native session may not exist yet. Read the Gateway attempts in
        // the same snapshot without fetching any harness-native history.
        let latest_executions = {
            let mut query = tx.prepare(
                "SELECT t.execution_harness,t.id,COALESCE(c.phase,t.status),
                        COALESCE(t.completed_at,t.started_at),
                        t.execution_generation=g.generation
                 FROM turns t
                 JOIN conversation_entry_generations g ON g.session_id=t.session_id
                 LEFT JOIN conversation_inputs c ON c.local_turn=t.id
                   AND c.session_id=t.session_id AND c.human_id=t.from_user_id
                   AND json_type(c.doc,'$.portable')='object'
                 WHERE t.id IN (
                     SELECT MAX(id) FROM turns
                     WHERE session_id=?1 AND from_user_id=?2
                     GROUP BY execution_harness
                 )
                 ORDER BY t.id DESC",
            )?;
            query
                .query_map(params![session_id, human], |row| {
                    Ok(ObservedExecution {
                        harness: row.get(0)?,
                        local_turn: row.get(1)?,
                        phase: row.get(2)?,
                        turn_at: row.get(3)?,
                        current_generation: row.get(4)?,
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        let sampled_at = now_string();
        tx.commit()?;
        Ok(Some(SessionObservation {
            sampled_at,
            latest_executions,
            session_id,
            execution,
            native_thread,
            input_cut,
            latest_input,
            latest_delivery,
            local_turn,
            native_item,
            pending,
            presentation_gaps,
            semantic,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::interaction::{RequestRelation, ReturnRoute, SourceInput};
    use tempfile::NamedTempFile;

    #[test]
    fn observation_retains_both_harnesses_and_portable_uncertainty() {
        let file = NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        store.set_session_codex_thread(key, "codex-native").unwrap();
        let request = TurnRequest {
            session_key: key,
            from_user_id: 100,
            prompt: "Work".into(),
            runtime_instructions: None,
            attachments: vec![],
            review_mode: None,
            override_search_mode: None,
        };
        let codex = store.record_turn_started(session.id, &request).unwrap();
        store
            .record_turn_native_thread(codex, "codex-native")
            .unwrap();
        store
            .record_turn_finished(codex, "completed", Some("Done"))
            .unwrap();

        let binding = store.execution_binding(key, 100).unwrap().unwrap().revision;
        let id = uuid::Uuid::new_v4().to_string();
        let (input, fresh) = store
            .capture_portable_turn(
                100,
                key,
                &binding,
                &id,
                &request.prompt,
                &crate::interaction::MatrixDestination::Body {
                    being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
                    embodiment_id: format!("embodiment:{}", uuid::Uuid::new_v4()),
                },
            )
            .unwrap();
        assert!(fresh && store.queue_portable_turn(&input).unwrap());
        assert!(
            store
                .conversation_input_claim_queue_start(100, &id)
                .unwrap()
        );
        let claude = store.begin_portable_turn(&input, &request).unwrap();
        let latest = || {
            store
                .interaction_observation(key, 100)
                .unwrap()
                .unwrap()
                .latest_executions
        };
        let preparing = latest();
        assert_eq!(preparing.len(), 2);
        assert_eq!(
            (
                preparing[0].harness.as_str(),
                preparing[0].local_turn,
                preparing[0].phase.as_str()
            ),
            ("claude", claude, "queued")
        );
        assert_eq!(
            (preparing[1].harness.as_str(), preparing[1].local_turn),
            ("codex", codex)
        );
        assert!(
            preparing
                .iter()
                .all(|attempt| attempt.current_generation == Some(true))
        );
        let prepared = serde_json::json!({
            "native_session_id": uuid::Uuid::new_v4(),
            "native_session_scope": "a".repeat(64),
        });
        assert!(
            store
                .expose_portable_turn(&input, claude, &serde_json::json!({}), &prepared)
                .unwrap()
        );
        assert_eq!(latest()[0].phase, "sending");
        store
            .finish_portable_turn(&input, claude, None, false)
            .unwrap();
        assert_eq!(latest()[0].phase, "claude_unconfirmed");
        store.set_session_codex_thread(key, "replacement").unwrap();
        assert!(
            latest()
                .iter()
                .all(|attempt| attempt.current_generation == Some(false))
        );
        assert!(store.interaction_observation(key, 101).unwrap().is_none());
    }

    #[test]
    fn observation_is_read_only_scoped_and_preserves_incomplete_source_evidence() {
        let file = NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(file.path(), &[100, 101], &defaults).unwrap();
        let key = SessionKey::new(100, Some(7));
        let session = store.ensure_session(key, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(key, "native-source")
            .unwrap();
        let turn = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: key,
                    from_user_id: 100,
                    prompt: "Work".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(turn, "native-source")
            .unwrap();
        store
            .record_native_message(
                turn,
                "native-source",
                "physical",
                "item",
                Some("commentary"),
                "Still working",
            )
            .unwrap();
        let (instruction, _) = store
            .interaction_admit(
                &SourceInput {
                    tribu_source: None,
                    transcription: None,
                    channel: "fixture".into(),
                    event_id: "1".into(),
                    update_id: Some(1),
                    human_id: 100,
                    target_sessions: vec![session.id],
                    origin: ReturnRoute {
                        chat_id: 100,
                        thread_id: 1,
                        message_id: Some(1),
                    },
                    text: "Keep the revised requirement".into(),
                },
                key,
                RequestRelation::New,
            )
            .unwrap();
        store
            .interaction_transport(
                &instruction.id,
                100,
                turn,
                crate::interaction::TransportPhase::Submitting,
                None,
            )
            .unwrap();
        store
            .interaction_transport(
                &instruction.id,
                100,
                turn,
                crate::interaction::TransportPhase::Accepted,
                Some("physical"),
            )
            .unwrap();
        let answer = format!(
            "Answer\n<daimon-result>{}</daimon-result>",
            serde_json::json!({"requests":instruction.requests,"covered":[instruction.id],"completed":instruction.requests})
        );
        store
            .interaction_record_result(
                &instruction.id,
                100,
                turn,
                "native-source",
                "physical",
                "final-item",
                &answer,
                true,
            )
            .unwrap();
        let task = HumanInteraction {
            id: "external-observation".into(),
            kind: "task".into(),
            state: "pending".into(),
            requester: 100,
            native_thread: "native-source".into(),
            local_turn: turn,
            title: "Observe the device".into(),
            action: "Report the actual observation".into(),
            blocking: false,
            source: serde_json::json!({}),
        };
        store
            .save_interaction(key, &task, Some("external-observation"))
            .unwrap();
        store
            .save_bot_state(
                &format!("interaction_presentation_gap:{turn}"),
                "retained-native-items",
            )
            .unwrap();
        let changes = store.conn.lock().unwrap().total_changes();
        for _ in 0..2 {
            let observed = store.interaction_observation(key, 100).unwrap().unwrap();
            assert_eq!(observed.input_cut, instruction.sequence);
            assert_eq!(observed.latest_input.unwrap().id, instruction.id);
            assert_eq!(observed.local_turn.unwrap().1, "running");
            assert_eq!(observed.native_item.unwrap().1, "final-item");
            assert_eq!(observed.presentation_gaps, 1);
            assert_eq!(observed.pending.actionable_total, 1);
            assert_eq!(observed.pending.items[0].id, task.id);
            assert_eq!(
                observed.latest_delivery.unwrap().native_thread,
                "native-source"
            );
        }
        assert_eq!(store.conn.lock().unwrap().total_changes(), changes);
        assert!(store.interaction_observation(key, 101).unwrap().is_none());
        assert!(
            store
                .interaction_observation(SessionKey::new(100, Some(8)), 100)
                .unwrap()
                .is_none()
        );
        store.set_session_codex_thread(key, "replacement").unwrap();
        let observed = store.interaction_observation(key, 100).unwrap().unwrap();
        assert!(observed.native_item.is_none() && observed.local_turn.is_none());
        assert_eq!(
            observed.latest_input.unwrap().native_thread.as_deref(),
            Some("native-source")
        );
        assert_eq!(
            observed.latest_delivery.unwrap().native_thread,
            "native-source"
        );
        assert_eq!(observed.pending.actionable_total, 0);
        assert_eq!(observed.pending.history_total, 1);
        assert_eq!(observed.presentation_gaps, 0);
        store
            .conn
            .lock()
            .unwrap()
            .execute("UPDATE users SET allowed=0 WHERE tg_user_id=100", [])
            .unwrap();
        assert!(store.interaction_observation(key, 100).unwrap().is_none());
    }
}
