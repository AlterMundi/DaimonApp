//! Read-only cold-start projection of one explicitly selected shadow revision.
use super::*;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct Selection {
    pub workspace: String,
    pub projects: Vec<CheckoutSelection>,
    pub effects: Vec<Uuid>,
}

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CheckoutSelection {
    pub project: Uuid,
    pub repository: Uuid,
    pub revision: i64,
    pub checkout: PathBuf,
}

impl CheckoutSelection {
    fn selector(&self) -> LinkSelector<'_> {
        LinkSelector {
            project: Some(self.project),
            repository: Some(self.repository),
            commit: None,
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
struct Recovery {
    folder: PathBuf,
    selection: Selection,
    checkpoints: Vec<ProjectCheckpoint>,
    effects: Vec<Value>,
}

fn effect_on(
    conn: &Connection,
    session: i64,
    topic: SessionKey,
    human: i64,
    id: Uuid,
) -> Result<Value> {
    let original = interaction::instruction_on(conn, &id.to_string(), human)?
        .filter(|original| original.target == topic && original.target_session == session)
        .context("Original effect is outside this topic")?;
    let mut receipt = None;
    if original.phase == crate::interaction::TransportPhase::Accepted {
        let mut query = conn.prepare(
            "SELECT d.doc,r.id,t.status FROM interaction_delivery_requests members
             JOIN interaction_request_links original ON original.request_id=members.request_id
             JOIN interaction_deliveries d ON d.id=members.delivery_id
             JOIN interaction_results r ON r.id=d.result_id JOIN turns t ON t.id=r.local_turn
             WHERE original.instruction_id=?1 AND d.human_id=?2 AND t.session_id=?3 AND t.from_user_id=?2
               AND EXISTS(SELECT 1 FROM json_each(r.claim,'$.covered') WHERE value=?1)
             ORDER BY r.rowid DESC LIMIT 32",
        )?;
        let mut rows = query.query(params![id.to_string(), human, session])?;
        while let Some(row) = rows.next()? {
            let delivery: crate::interaction::Delivery =
                serde_json::from_str(&row.get::<_, String>(0)?)?;
            let (current, correction) = routing::delivery_freshness(conn, &delivery)?;
            if delivery.target == topic && current && !correction {
                let result: String = row.get(1)?;
                let terminal = row.get::<_, String>(2)? == "completed";
                receipt = Some((result, delivery.completed && terminal));
                break;
            }
        }
    }
    // A canonical result confirms a retained return, never an external
    // side effect asserted in its text.
    let request_completed = receipt.as_ref().is_some_and(|(_, completed)| *completed);
    Ok(json!({
        "original": id, "transport": original.phase, "result": receipt.as_ref().map(|(result, _)| result),
        "requestCompleted": request_completed,
        "disposition": if receipt.is_some() { "result_retained" } else { "unresolved" }
    }))
}

fn paired_original_on(conn: &Connection, scope: &CheckpointScope) -> Result<bool> {
    let id: Option<String> = conn
        .query_row(
            "SELECT json_extract(value,'$') FROM bot_state WHERE key=?1",
            [format!("execution_root:{}", scope.invocation.local_turn)],
            |row| row.get(0),
        )
        .optional()?
        .flatten();
    let Some(id) = id.or_else(|| {
        scope
            .invocation
            .harness
            .is_portable()
            .then(|| scope.invocation.native_turn.clone())
    }) else {
        return Ok(false);
    };
    let Some(original) = interaction::instruction_on(conn, &id, scope.human)?
        .filter(|i| i.target == scope.key && i.local_turn == Some(scope.invocation.local_turn))
    else {
        return Ok(false);
    };
    paired_source_on(conn, &original)
}

pub(in crate::store) fn paired_source_on(
    conn: &Connection,
    original: &crate::interaction::Instruction,
) -> Result<bool> {
    if session_requests::author_on(conn, &original.input_id)?.is_some() {
        return Ok(false);
    }
    let source = routing::source_on(conn, &original.id, original.human_id)?;
    if source.channel == "conversation" {
        let input = conversation_inputs::read_on(conn, &source.event_id, original.human_id)?;
        return Ok(input.paired_actor && !input.retired && input.tribu_source.is_none());
    }
    if source.channel.starts_with("telegram:") {
        return Ok(
            routed_portable::telegram_original_epoch(conn, &source, original.target)?.is_some(),
        );
    }
    Ok(false)
}

fn inspect_recovery(
    conn: &Connection,
    key: SessionKey,
    entry: SessionKey,
    human: i64,
    selection: Selection,
) -> Result<Recovery> {
    let (session, folder) = workspace_on(conn, key, human, &selection.workspace)?;
    let checkpoints = selection
        .projects
        .iter()
        .map(|selected| {
            checkpoint_on(
                conn,
                key,
                entry,
                human,
                session,
                &selection.workspace,
                selected.selector(),
            )?
            .filter(|checkpoint| checkpoint.revision == selected.revision)
            .context("Recovery selection is no longer current for this repository")
        })
        .collect::<Result<Vec<_>>>()?;
    let effects = selection
        .effects
        .iter()
        .map(|id| effect_on(conn, session, key, human, *id))
        .collect::<Result<Vec<_>>>()?;
    Ok(Recovery {
        folder,
        selection,
        checkpoints,
        effects,
    })
}

impl Store {
    pub(super) fn select_project_recovery(
        &self,
        scope: &CheckpointScope,
        selection: Selection,
    ) -> Result<Value> {
        let mut links = std::collections::HashSet::new();
        anyhow::ensure!(
            selection.effects.len() <= 8
                && !selection.projects.is_empty()
                && selection.projects.iter().all(|selected| {
                    selected.checkout.as_os_str().len() <= 1024
                        && links.insert((selected.project, selected.repository))
                }),
            "Invalid recovery selection"
        );
        let checkpoints = selection
            .projects
            .iter()
            .map(|selected| {
                self.project_checkpoint(
                    scope,
                    &selection.workspace,
                    &selected.checkout,
                    selected.selector(),
                )?
                .filter(|checkpoint| checkpoint.revision == selected.revision)
                .context("Select each current verified repository revision for recovery")
            })
            .collect::<Result<Vec<_>>>()?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        scope.authorize(&tx, &self.instance_id)?;
        anyhow::ensure!(
            paired_original_on(&tx, scope)?,
            "Recovery selection requires a current paired-human original"
        );
        let selected = inspect_recovery(&tx, scope.key, scope.entry, scope.human, selection)?;
        anyhow::ensure!(
            selected.checkpoints == checkpoints,
            "Checkpoint changed before selection"
        );
        anyhow::ensure!(
            verified_context(&selected).len() <= 8 * 1024,
            "Select a smaller startup context; all repository links remain retained"
        );
        let (session, _) =
            workspace_on(&tx, scope.key, scope.human, &selected.selection.workspace)?;
        tx.execute(
            "INSERT INTO project_checkpoint_recovery(session_id,doc) VALUES (?1,?2)
             ON CONFLICT(session_id) DO UPDATE SET doc=excluded.doc",
            params![session, serde_json::to_string(&selected.selection)?],
        )?;
        tx.commit()?;
        Ok(
            json!({"revisions":checkpoints.iter().map(|checkpoint|checkpoint.revision).collect::<Vec<_>>(),
            "selected":true,"effects":selected.effects}),
        )
    }

    /// Retain an exact refusal observed by the native adapter. This receipt
    /// fences recovery to one original and one verified project selection.
    pub(crate) fn retain_codex_project_refusal(
        &self,
        entry: SessionKey,
        human: i64,
        original_id: &str,
        local: i64,
        previous_native: &str,
        context: &str,
    ) -> Result<()> {
        use crate::interaction::{CodexRecoveryRefusal, TransportPhase};

        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let original = interaction::instruction_on(&tx, original_id, human)?
            .context("Cold recovery original missing")?;
        let bound: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id
             JOIN conversation_entry_generations g ON g.session_id=s.id
             JOIN bot_state b ON b.key='execution_root:'||t.id
             WHERE t.id=?1 AND t.status='running' AND t.execution_harness='codex'
               AND t.execution_generation=g.generation AND t.native_thread_id IS NULL
               AND t.from_user_id=?2 AND s.creator_user_id=?2 AND s.codex_thread_id=?3
               AND s.force_fresh_thread=0 AND json_extract(b.value,'$')=?4
               AND EXISTS(SELECT 1 FROM interaction_instructions i
                 WHERE i.id=?4 AND i.session_id=s.id AND i.instance_id=?5))",
            params![local, human, previous_native, original_id, self.instance_id],
            |row| row.get(0),
        )?;
        if !bound
            || original.phase != TransportPhase::Queued
            || !interaction::target_execution_allowed_on(&tx, &original)?
            || stopping::fenced_on(&tx, original.target)?
            || maintenance_writer_held_on(&tx, original.target)?
            || !paired_source_on(&tx, &original)?
        {
            return Ok(());
        }
        let Some(current) = recovery_on(&tx, original.target, entry, human)? else {
            return Ok(());
        };
        if verified_context(&current) != context {
            return Ok(());
        }
        let mut retained = interaction::transport_on(
            &tx,
            original_id,
            human,
            local,
            TransportPhase::RetainedUnsent,
            None,
        )?;
        retained.codex_recovery_refusal = Some(CodexRecoveryRefusal {
            local_turn: local,
            previous_native: previous_native.to_owned(),
            checkpoint_sha256: format!("{:x}", Sha256::digest(context.as_bytes())),
        });
        tx.execute(
            "UPDATE interaction_instructions SET doc=?2 WHERE id=?1",
            params![original_id, serde_json::to_string(&retained)?],
        )?;
        tx.execute(
            "INSERT INTO audit_log(actor_user_id,action,details_json,created_at)
             VALUES(?1,'codex_project_recovery_refusal',?2,?3)",
            params![
                human,
                json!({
                    "instruction": original_id,
                    "receipt": retained.codex_recovery_refusal
                })
                .to_string(),
                now_string()
            ],
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Advance the exact reservation once before thread/start and persist the
    /// observed candidate before the adapter can submit an input.
    pub(crate) fn advance_codex_successor(
        &self,
        entry: SessionKey,
        human: i64,
        original_id: &str,
        local: i64,
        previous: &str,
        candidate: Option<&str>,
    ) -> Result<bool> {
        use crate::interaction::TransportPhase;

        let Some(original) = self.interaction_instruction(original_id, human)? else {
            return Ok(false);
        };
        if original.codex_successor_reservation.is_none() {
            return Ok(false);
        }
        let startup = self.project_startup(original.target, entry, human);
        let digest = startup
            .is_verified()
            .then(|| startup.context())
            .flatten()
            .map(|context| format!("{:x}", Sha256::digest(context.as_bytes())));
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let Some(mut original) = interaction::instruction_on(&tx, original_id, human)? else {
            return Ok(false);
        };
        let Some(mut reservation) = original.codex_successor_reservation.take() else {
            return Ok(false);
        };
        let bound: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id
             JOIN conversation_entry_generations g ON g.session_id=s.id
             JOIN bot_state b ON b.key='execution_root:'||t.id
             JOIN interaction_instructions i ON i.id=json_extract(b.value,'$') AND i.session_id=s.id
             WHERE t.id=?1 AND t.status='running' AND t.execution_harness='codex'
               AND t.execution_generation=g.generation AND t.native_thread_id IS NULL
               AND t.from_user_id=?2 AND s.creator_user_id=?2 AND s.codex_thread_id=?3
               AND s.force_fresh_thread=0 AND i.id=?4 AND i.instance_id=?5)",
            params![local, human, previous, original_id, self.instance_id],
            |row| row.get(0),
        )?;
        let authorized = bound
            && original.phase == TransportPhase::Queued
            && reservation.previous_native == previous
            && digest.as_deref() == Some(reservation.checkpoint_sha256.as_str())
            && interaction::target_execution_allowed_on(&tx, &original)?
            && !stopping::fenced_on(&tx, original.target)?
            && !maintenance_writer_held_on(&tx, original.target)?
            && startup.current_on(&tx, entry, &original).unwrap_or(false);
        match candidate {
            None if authorized && reservation.creation_turn.is_none() => {
                reservation.creation_turn = Some(local);
            }
            Some(native)
                if reservation.creation_turn == Some(local)
                    && reservation.candidate_native.is_none()
                    && reservation.previous_native == previous
                    && native != previous
                    && Uuid::parse_str(native).is_ok() =>
            {
                let claimed: bool = tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM sessions WHERE codex_thread_id=?1)
                         OR EXISTS(SELECT 1 FROM turns WHERE native_thread_id=?1)",
                    [native],
                    |row| row.get(0),
                )?;
                if claimed {
                    return Ok(false);
                }
                reservation.candidate_native = Some(native.to_owned());
                if authorized {
                    tx.execute(
                        "UPDATE turns SET native_thread_id=?2 WHERE id=?1",
                        params![local, native],
                    )?;
                }
            }
            _ => return Ok(false),
        }
        let audit = json!({"instruction":original_id,"reservation":reservation});
        original.codex_successor_reservation = Some(reservation);
        tx.execute(
            "UPDATE interaction_instructions SET doc=?2 WHERE id=?1",
            params![original_id, serde_json::to_string(&original)?],
        )?;
        tx.execute(
            "INSERT INTO audit_log(actor_user_id,action,details_json,created_at)
             VALUES(?1,?2,?3,?4)",
            params![
                human,
                if candidate.is_some() {
                    "codex_project_successor_observed"
                } else {
                    "codex_project_successor_creation_started"
                },
                audit.to_string(),
                now_string()
            ],
        )?;
        tx.commit()?;
        Ok(authorized)
    }

    pub(in crate::store) fn init_codex_project_lineage(&self) -> Result<()> {
        self.conn
            .lock()
            .expect("store mutex poisoned")
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS codex_project_lineage(
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                generation TEXT NOT NULL, previous_native TEXT NOT NULL,
                successor_native TEXT NOT NULL UNIQUE, instruction TEXT NOT NULL UNIQUE,
                local_turn INTEGER NOT NULL UNIQUE, sealed INTEGER NOT NULL,
                PRIMARY KEY(session_id,generation,previous_native)
             );",
            )?;
        Ok(())
    }

    /// Select only a completed successor whose input and final item were
    /// recorded against this exact owned original.
    pub(crate) fn adopt_codex_project_successor(
        &self,
        human: i64,
        id: &str,
        local: i64,
        assistant_text: Option<&str>,
    ) -> Result<bool> {
        use crate::interaction::TransportPhase;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let Some(original) = interaction::instruction_on(&tx, id, human)? else {
            return Ok(false);
        };
        let Some(reservation) = original
            .codex_successor_reservation
            .as_ref()
            .filter(|reservation| reservation.creation_turn == Some(local))
        else {
            return Ok(false);
        };
        let Some(native) = reservation.candidate_native.as_deref() else {
            return Ok(false);
        };
        if original.phase != TransportPhase::Accepted
            || original.local_turn != Some(local)
            || original.native_thread.as_deref() != Some(native)
            || !interaction::target_execution_allowed_on(&tx, &original)?
            || stopping::fenced_on(&tx, original.target)?
            || maintenance_writer_held_on(&tx, original.target)?
            || !paired_source_on(&tx, &original)?
        {
            return Ok(false);
        }
        let generation: Option<String> = tx.query_row(
            "SELECT g.generation FROM turns t JOIN sessions s ON s.id=t.session_id
             JOIN conversation_entry_generations g ON g.session_id=s.id AND g.generation=t.execution_generation
             JOIN bot_state b ON b.key='execution_root:'||t.id
             WHERE t.id=?1 AND t.session_id=?2 AND t.from_user_id=?3 AND s.creator_user_id=?3
               AND s.force_fresh_thread=0 AND s.codex_thread_id=?4 AND t.native_thread_id=?5
               AND t.execution_harness='codex' AND t.status='running'
               AND json_extract(b.value,'$')=?6
               AND EXISTS(SELECT 1 FROM interaction_native_messages m
                  WHERE m.local_turn=t.id AND m.native_thread=?5 AND m.native_turn=?7
                    AND m.phase='final_answer')",
            params![local, original.target_session, human, reservation.previous_native, native, id, original.native_turn],
            |row| row.get(0),
        ).optional()?;
        let Some(generation) = generation else {
            return Ok(false);
        };
        tx.execute(
            "INSERT INTO codex_project_lineage
                (session_id,generation,previous_native,successor_native,instruction,local_turn,sealed)
             VALUES(?1,?2,?3,?4,?5,?6,0)",
            params![original.target_session,generation,reservation.previous_native,native,id,local],
        )?;
        let changed = tx.execute(
            "UPDATE sessions SET codex_thread_id=?2,updated_at=?3
             WHERE id=?1 AND creator_user_id=?4 AND force_fresh_thread=0 AND codex_thread_id=?5",
            params![
                original.target_session,
                native,
                now_string(),
                human,
                reservation.previous_native
            ],
        )?;
        anyhow::ensure!(
            changed == 1,
            "Codex predecessor changed before successor adoption"
        );
        tx.execute(
            "UPDATE codex_project_lineage SET sealed=1 WHERE local_turn=?1",
            [local],
        )?;
        self.record_turn_finished_on(&tx, local, "completed", assistant_text)?;
        tx.commit()?;
        Ok(true)
    }

    /// Called only by existing paired-human startup paths. It never dispatches
    /// or writes another copy of an original effect.
    pub(crate) fn project_startup(
        &self,
        key: SessionKey,
        entry: SessionKey,
        human: i64,
    ) -> ProjectStartup {
        let inspect = || {
            let conn = self.conn.lock().expect("store mutex poisoned");
            recovery_on(&conn, key, entry, human)
        };
        let selected = match inspect() {
            Ok(Some(selected)) => selected,
            Ok(None) => {
                return ProjectStartup {
                    selected: false,
                    witness: None,
                };
            }
            Err(_) => {
                return ProjectStartup {
                    selected: true,
                    witness: None,
                };
            }
        };
        let valid = selected
            .checkpoints
            .iter()
            .zip(&selected.selection.projects)
            .all(|(checkpoint, checkout)| {
                verify_checkout(
                    &selected.folder,
                    &selected.selection.workspace,
                    &checkout.checkout,
                    &checkpoint.delta.link,
                )
                .is_ok()
            })
            && matches!(inspect(), Ok(Some(current)) if current == selected);
        ProjectStartup {
            selected: true,
            witness: valid.then_some(selected),
        }
    }
}

/// Read-only lineage. It does not make an old native binding a current writer.
pub(in crate::store) fn ancestor_session_on(
    conn: &Connection,
    key: SessionKey,
    human: i64,
    native: &str,
) -> Result<Option<i64>> {
    Ok(conn
        .query_row(
            "SELECT s.id FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id
         JOIN conversation_entry_generations g ON g.session_id=s.id
         JOIN codex_project_lineage p ON p.session_id=s.id AND p.generation=g.generation
         WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1
           AND s.force_fresh_thread=0 AND p.previous_native=?4 AND p.sealed=1",
            params![key.chat_id, key.thread_id, human, native],
            |row| row.get(0),
        )
        .optional()?)
}

fn selected_on(conn: &Connection, key: SessionKey, human: i64) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT r.doc FROM project_checkpoint_recovery r JOIN sessions s ON s.id=r.session_id
         JOIN users u ON u.tg_user_id=s.creator_user_id
         WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1",
            params![key.chat_id, key.thread_id, human],
            |row| row.get(0),
        )
        .optional()?)
}

fn recovery_on(
    conn: &Connection,
    key: SessionKey,
    entry: SessionKey,
    human: i64,
) -> Result<Option<Recovery>> {
    selected_on(conn, key, human)?
        .map(|raw| inspect_recovery(conn, key, entry, human, serde_json::from_str(&raw)?))
        .transpose()
}

#[derive(PartialEq, Eq)]
pub(crate) struct ProjectStartup {
    selected: bool,
    witness: Option<Recovery>,
}

impl ProjectStartup {
    pub(crate) fn context(&self) -> Option<String> {
        if !self.selected {
            return None;
        }
        if let Some(selected) = &self.witness {
            let context = verified_context(selected);
            if context.len() <= 8 * 1024 {
                return Some(context);
            }
        }
        Some(json!({
            "kind":"gateway_project_recovery", "status":"unavailable",
            "guidance":"The selected project evidence could not be revalidated. Keep earlier effects unresolved and inspect their original receipts before any new work."
        }).to_string())
    }

    pub(crate) fn is_selected(&self) -> bool {
        self.selected
    }

    pub(crate) fn is_verified(&self) -> bool {
        self.witness
            .as_ref()
            .is_some_and(|selected| verified_context(selected).len() <= 8 * 1024)
    }

    pub(in crate::store) fn successor_reservation_on(
        &self,
        conn: &Connection,
        entry: SessionKey,
        original: &crate::interaction::Instruction,
    ) -> Result<Option<crate::interaction::CodexSuccessorReservation>> {
        use crate::interaction::{CodexSuccessorReservation, TransportPhase};
        let Some(refusal) = original.codex_recovery_refusal.as_ref() else {
            return Ok(None);
        };
        if original.phase != TransportPhase::RetainedUnsent
            || original.local_turn != Some(refusal.local_turn)
            || original.native_turn.is_some()
            || !self.is_verified()
            || !self.current_on(conn, entry, original)?
        {
            return Ok(None);
        }
        let context = self.context().context("Verified checkpoint unavailable")?;
        let digest = format!("{:x}", Sha256::digest(context.as_bytes()));
        if digest != refusal.checkpoint_sha256 {
            return Ok(None);
        }
        let binding = execution::binding_on(conn, original.target, original.human_id)?;
        if !binding.is_some_and(|binding| {
            binding.execution.native_session.as_deref() == Some(&refusal.previous_native)
        }) {
            return Ok(None);
        }
        if let Some(retained) = original.codex_successor_reservation.as_ref()
            && retained.previous_native == refusal.previous_native
            && retained.checkpoint_sha256 == digest
        {
            return Ok(Some(retained.clone()));
        }
        Ok(Some(CodexSuccessorReservation {
            id: Uuid::now_v7(),
            previous_native: refusal.previous_native.clone(),
            checkpoint_sha256: digest,
            creation_turn: None,
            candidate_native: None,
        }))
    }

    pub(in crate::store) fn current_on(
        &self,
        conn: &Connection,
        entry: SessionKey,
        original: &crate::interaction::Instruction,
    ) -> Result<bool> {
        if !paired_source_on(conn, original)? {
            return Ok(false);
        }
        if let Some(expected) = &self.witness {
            return Ok(
                recovery_on(conn, original.target, entry, original.human_id)?.as_ref()
                    == Some(expected),
            );
        }
        Ok(selected_on(conn, original.target, original.human_id)?.is_some() == self.selected)
    }
}

fn verified_context(selected: &Recovery) -> String {
    let repositories = selected
        .checkpoints
        .iter()
        .zip(&selected.selection.projects)
        .map(|(checkpoint, checkout)| {
            let mut repository = json!({
                "revision": checkout.revision,
                "link": checkpoint.delta.link,
                "checkout": checkout.checkout,
                "sources": checkpoint.delta.sources
            });
            if let Some(work) = &checkpoint.delta.work {
                repository["work"] = json!(work);
            }
            repository
        })
        .collect::<Vec<_>>();
    json!({
        "kind":"gateway_project_recovery", "status":"verified","repositories":repositories,
        "effectReceipts":selected.effects,
        "guidance":"Use these original references to continue the selected projects. Unresolved effects stay unresolved. Never dispatch an old original from this checkpoint."
    }).to_string()
}
