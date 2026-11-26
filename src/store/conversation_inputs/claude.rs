//! Direct Claude execution uses the same owned original and result record.
use super::*;
use crate::{
    interaction::MatrixDestination,
    store::{ClaudeContinuation, valid_claude_scope},
};
use serde_json::{Value, json};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct DirectClaude {
    body: MatrixDestination,
    binding: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    native: Option<ClaudeContinuation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    identity: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    reply: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    resume_unavailable: bool,
}

impl DirectClaude {
    pub(super) fn new(body: MatrixDestination, binding: String) -> Self {
        Self {
            body,
            binding,
            native: None,
            identity: None,
            reply: None,
            resume_unavailable: false,
        }
    }
}

impl ConversationInput {
    pub(crate) fn targets_claude(&self) -> bool {
        self.private_matrix.is_some() || self.claude.is_some()
    }

    pub(crate) fn claude_reply(&self) -> Option<Value> {
        if let Some(reply) = self.direct_claude_reply_text() {
            let text: String = reply.chars().take(super::TRACE_TEXT_PART).collect();
            let next = (text.len() < reply.len()).then_some(super::TRACE_TEXT_PART);
            return Some(json!({"text":text,"message_id":self.id,"next_offset":next}));
        }
        self.private_matrix_reply
            .as_ref()
            .map(|reply| json!({"text":reply.text,"message_id":reply.event_id}))
    }

    pub(super) fn direct_claude_reply_text(&self) -> Option<&str> {
        self.claude.as_ref()?.reply.as_deref()
    }

    pub(super) fn same_claude_destination(
        &self,
        matrix: Option<&PrivateMatrixSelection>,
        matrix_access: bool,
        direct: Option<&DirectClaude>,
    ) -> bool {
        if let Some(direct) = direct {
            // A retry across cutover can read an exact paired-human original;
            // it cannot migrate, reauthorize or dispatch the old selection.
            self.claude
                .as_ref()
                .is_some_and(|previous| previous.body == direct.body)
                || self.private_matrix.as_ref().is_some_and(|previous| {
                    self.private_matrix_host_access && previous.recipient == direct.body
                })
        } else {
            self.claude.is_none()
                && self.private_matrix.as_ref() == matrix
                && self.private_matrix_host_access == matrix_access
        }
    }
}

impl Store {
    pub(crate) fn conversation_claude_capture(
        &self,
        human: i64,
        entry: SessionKey,
        binding: &str,
        id: &str,
        text: &str,
        body: &MatrixDestination,
    ) -> Result<(ConversationInput, bool)> {
        body.validate()?;
        anyhow::ensure!(
            matches!(body, MatrixDestination::Body { .. }) && text.len() <= 16384,
            "Invalid Claude text or destination"
        );
        self.capture_original_mode(
            human,
            entry,
            binding,
            id,
            text,
            None,
            true,
            None,
            None,
            None,
            None,
            Vec::new(),
            None,
            None,
            Some(ClaudeDestination::Direct(body.clone())),
        )
    }

    pub(crate) fn conversation_claude_claim(&self, input: &ConversationInput) -> Result<bool> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let current = read_on(&tx, &input.id, input.human)?;
        let changed = if current.phase == "retained" && current.claude.is_some() {
            let busy: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM conversation_inputs
                 WHERE human_id=?1 AND session_id=?2 AND instance_id=?3
                   AND phase IN ('claude_preparing','claude_running'))",
                params![input.human, input.session, self.instance_id],
                |row| row.get(0),
            )?;
            let phase = if busy || !eligible_direct_on(&tx, &current)? {
                "retained_unsent"
            } else {
                "claude_preparing"
            };
            tx.execute(
                "UPDATE conversation_inputs SET phase=?1
                 WHERE id=?2 AND phase='retained' AND instance_id=?3
                   AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)",
                params![phase, input.id, self.instance_id],
            )? == 1
                && phase == "claude_preparing"
        } else {
            false
        };
        tx.commit()?;
        Ok(changed)
    }

    pub(crate) fn conversation_claude_prior(
        &self,
        input: &ConversationInput,
        body: &MatrixDestination,
        observed: &Value,
    ) -> Result<Option<ClaudeContinuation>> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let binding = input
            .claude
            .as_ref()
            .context("Direct Claude input required")?
            .binding
            .as_str();
        let last: Option<(i64, String, String)> = conn.query_row(
            "SELECT rowid,phase,doc FROM conversation_inputs
             WHERE human_id=?1 AND session_id=?2 AND id<>?3 AND json_extract(doc,'$.claude.binding')=?4
               AND (json_type(doc,'$.claude.native')='object' OR json_extract(doc,'$.claude.resume_unavailable')=1)
             ORDER BY rowid DESC LIMIT 1",
            params![input.human,input.session,input.id,binding],
            |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)),
        ).optional()?;
        let last_direct = last.as_ref().map_or(0, |(row, _, _)| *row);
        // Continue the pre-cutover native context only through an exact
        // paired-human original and confirmed signed return. New inputs do not
        // execute any part of the old Matrix messaging route.
        let signed: Option<(String, String, Option<String>, String)> = conn
            .query_row(
                "SELECT input.doc, request.doc, request.submission, request.phase
             FROM conversation_inputs AS input
             JOIN interaction_matrix_requests AS request ON request.claude_input=input.id
                 AND request.human_id=input.human_id AND request.entry_session=input.session_id
             WHERE input.human_id=?1 AND input.session_id=?2
               AND json_extract(request.doc,'$.entry_generation')=?3 AND input.rowid>?4
               AND json_extract(input.doc,'$.private_matrix_host_access')=1
               AND request.source_channel='/we'
               AND (request.phase NOT IN ('starting','rejected')
                    OR json_extract(request.submission,'$.reason')='claude_resume_session_missing')
             ORDER BY input.rowid DESC LIMIT 1",
                params![input.human, input.session, binding, last_direct],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        let Some((original, request, outcome, phase)) = signed else {
            let Some((_, phase, raw)) = last else {
                return Ok(None);
            };
            if phase != "claude_replied" {
                return Ok(None);
            }
            let previous: ConversationInput = serde_json::from_str(&raw)?;
            return Ok(previous
                .claude
                .filter(|claude| {
                    &claude.body == body
                        && claude.identity.as_ref() == Some(&body_revision(observed))
                })
                .and_then(|claude| claude.native));
        };
        let Some(outcome) = outcome.filter(|_| phase == "delivered") else {
            return Ok(None);
        };
        let original: ConversationInput = serde_json::from_str(&original)?;
        let request: Value = serde_json::from_str(&request)?;
        let outcome: Value = serde_json::from_str(&outcome)?;
        let matches_origin = original
            .private_matrix
            .is_some_and(|selection| &selection.recipient == body)
            && original
                .private_matrix_origin
                .as_ref()
                .is_some_and(|origin| {
                    request["original"]["event_id"] == origin.message_id
                        && request["original"]["receipt_event_id"] == origin.receipt_event_id
                })
            && original.private_matrix_reply.as_ref().is_some_and(|reply| {
                outcome["delivery"]["message_id"] == reply.event_id
                    && outcome["delivery"]["receipt_event_id"] == reply.receipt_event_id
            })
            && body_revision(&request["body"]) == body_revision(observed);
        if !matches_origin {
            return Ok(None);
        }
        Ok(outcome["native_session_id"]
            .as_str()
            .filter(|v| Uuid::parse_str(v).is_ok_and(|id| id.to_string() == *v))
            .zip(
                outcome["native_session_scope"]
                    .as_str()
                    .filter(|v| valid_claude_scope(v)),
            )
            .map(|(session_id, scope)| ClaudeContinuation {
                session_id: session_id.into(),
                scope: scope.into(),
            }))
    }

    /// Commit the observed native session before acknowledging provider exposure.
    pub(crate) fn conversation_claude_expose(
        &self,
        input: &ConversationInput,
        body: &MatrixDestination,
        observed: &Value,
        prepared: &Value,
    ) -> Result<bool> {
        let session = prepared["native_session_id"]
            .as_str()
            .filter(|v| Uuid::parse_str(v).is_ok_and(|id| id.to_string() == *v))
            .context("Claude requires a native session identity")?;
        let scope = prepared["native_session_scope"]
            .as_str()
            .filter(|v| valid_claude_scope(v))
            .context("Claude requires a native authorization scope")?;
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let mut current = read_on(&tx, &input.id, input.human)?;
        if current.phase != "claude_preparing" || !eligible_direct_on(&tx, &current)? {
            return Ok(false);
        }
        let claude = current
            .claude
            .as_mut()
            .filter(|claude| &claude.body == body)
            .context("Claude body differs from the retained destination")?;
        claude.identity = Some(body_revision(observed));
        claude.native = Some(ClaudeContinuation {
            session_id: session.into(),
            scope: scope.into(),
        });
        let changed = tx.execute(
            "UPDATE conversation_inputs SET phase='claude_running',doc=?1
             WHERE id=?2 AND phase='claude_preparing' AND instance_id=?3
               AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?3)",
            params![serde_json::to_string(&current)?, input.id, self.instance_id],
        )? == 1;
        tx.commit()?;
        Ok(changed)
    }

    pub(crate) fn conversation_claude_finish(
        &self,
        input: &ConversationInput,
        reply: Option<&str>,
        resume_unavailable: bool,
    ) -> Result<()> {
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let mut current = read_on(&tx, &input.id, input.human)?;
        let phase = match (current.phase.as_str(), reply) {
            ("claude_preparing", None) => {
                current
                    .claude
                    .as_mut()
                    .context("Direct Claude input required")?
                    .resume_unavailable = resume_unavailable;
                "claude_rejected"
            }
            ("claude_running", None) => "claude_unconfirmed",
            ("claude_running", Some(answer)) => {
                current
                    .claude
                    .as_mut()
                    .context("Direct Claude input required")?
                    .reply = Some(answer.into());
                "claude_replied"
            }
            _ => return Ok(()),
        };
        tx.execute(
            "UPDATE conversation_inputs SET phase=?1,doc=?2
             WHERE id=?3 AND phase=?4 AND instance_id=?5
               AND EXISTS(SELECT 1 FROM app_instance_lock WHERE key='main' AND instance_id=?5)",
            params![
                phase,
                serde_json::to_string(&current)?,
                input.id,
                current.phase,
                self.instance_id
            ],
        )?;
        tx.commit()?;
        Ok(())
    }
}

/// Keep the resume binding to the exact signed incarnation and manifest.
fn body_revision(status: &Value) -> Value {
    json!({
        "incarnation_id":status["local_origin"]["incarnation_id"],
        "embodiment_id":status["local_origin"]["embodiment_id"],
        "manifest_hash":status["manifest_hash"],
    })
}

/// Claude and Codex can share a logical conversation even before Codex starts.
pub(super) fn binding_is_current(conn: &Connection, input: &ConversationInput) -> Result<bool> {
    let Some(claude) = &input.claude else {
        return Ok(false);
    };
    let Ok((session, _)) = crate::store::presentation::entry_on(conn, input.human, input.entry)
    else {
        return Ok(false);
    };
    Ok(session == input.session
        && crate::store::presentation::entry_binding(conn, input.human, input.entry, session)?
            == claude.binding)
}

fn eligible_direct_on(conn: &Connection, input: &ConversationInput) -> Result<bool> {
    Ok(!input.retired
        && crate::store::stopping::admission_epoch_on(conn, input.entry)? == input.epoch
        && !crate::store::stopping::fenced_on(conn, input.entry)?
        && !crate::store::maintenance_writer_held_on(conn, input.entry)?)
}
