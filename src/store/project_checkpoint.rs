//! Durable shadow project links. Original source and effect owners remain authoritative.
use super::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProjectLink {
    pub project: Uuid,
    pub locator: String,
    pub commit: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum CheckpointSource {
    Observer {
        native: String,
        revision: i64,
        source_revision: String,
    },
    Conversation {
        source: String,
        revision: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProjectDelta {
    pub operation: Uuid,
    pub expected_revision: i64,
    pub workspace: String,
    pub link: ProjectLink,
    pub sources: Vec<CheckpointSource>,
}

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct ProjectCheckpoint {
    pub revision: i64,
    pub author: i64,
    pub local_turn: i64,
    pub delta: ProjectDelta,
}

#[derive(Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub(crate) enum ProjectDeltaOutcome {
    Accepted { checkpoint: ProjectCheckpoint },
    Retained { checkpoint: ProjectCheckpoint },
    Conflict { revision: i64 },
}

impl ProjectDelta {
    fn validate(&self) -> Result<()> {
        anyhow::ensure!(
            self.expected_revision >= 0
                && !self.operation.is_nil()
                && !self.link.project.is_nil()
                && self.link.locator.starts_with("git:")
                && self.link.locator.len() > 4
                && self.link.locator.len() <= 1024
                && !self.link.locator.chars().any(char::is_control)
                && matches!(self.link.commit.len(), 40 | 64)
                && self
                    .link
                    .commit
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                && !self.sources.is_empty()
                && self.sources.len() <= 8
                && serde_json::to_vec(self)?.len() <= 4096,
            "Invalid project checkpoint delta"
        );
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum ProjectShadowCommand {
    Workspace,
    Read {
        workspace: String,
        checkout: PathBuf,
    },
    Apply {
        delta: ProjectDelta,
        checkout: PathBuf,
    },
}

struct CheckpointScope<'a> {
    key: SessionKey,
    entry: SessionKey,
    human: i64,
    invocation: &'a crate::execution::ToolInvocation,
    closed: &'a tokio_util::sync::CancellationToken,
}

impl CheckpointScope<'_> {
    fn authorize(&self, conn: &Connection, instance: &str) -> Result<()> {
        anyhow::ensure!(!self.closed.is_cancelled(), "Checkpoint invocation closed");
        if self.invocation.harness.is_portable() {
            let parent =
                interaction::instruction_on(conn, &self.invocation.native_turn, self.human)?
                    .context("Routed checkpoint original unavailable")?;
            anyhow::ensure!(
                routed_portable::controller_parent_on(
                    conn,
                    &parent,
                    self.key,
                    self.human,
                    &self.invocation.native_session,
                    &self.invocation.native_turn,
                    self.invocation.local_turn,
                    instance,
                )?,
                "Routed checkpoint execution changed"
            );
            return Ok(());
        }
        let binding = execution::controller_execution_on(
            conn,
            self.invocation.local_turn,
            self.key,
            self.human,
            instance,
        )?;
        anyhow::ensure!(
            binding.matches(self.invocation.harness, &self.invocation.native_session),
            "Checkpoint execution changed"
        );
        Ok(())
    }
}

fn workspace_on(
    conn: &Connection,
    key: SessionKey,
    human: i64,
    claim: &str,
) -> Result<(i64, PathBuf)> {
    conn.query_row(
        "SELECT s.id,s.topic_folder FROM sessions s JOIN users u ON u.tg_user_id=s.creator_user_id
         WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1
           AND s.topic_folder_owner=?3 AND s.topic_folder_claim=?4 AND s.topic_folder IS NOT NULL",
        params![key.chat_id, key.thread_id, human, claim],
        |row| Ok((row.get(0)?, PathBuf::from(row.get::<_, String>(1)?))),
    )
    .optional()?
    .context("Current owned topic workspace unavailable")
}

fn check_sources(
    conn: &Connection,
    key: SessionKey,
    entry: SessionKey,
    human: i64,
    sources: &[CheckpointSource],
) -> Result<()> {
    for source in sources {
        let current = match source {
            CheckpointSource::Observer {
                native,
                revision,
                source_revision,
            } => {
                let session = observer_cards::binding(conn, key, human, native)?;
                conn.query_row(
                    "SELECT 1 FROM interaction_observer_cards c
                     JOIN interaction_observer_attempts a ON a.id=c.attempt_id
                     WHERE c.session_id=?1 AND c.native_thread=?2 AND c.revision=?3
                       AND a.human_id=?4 AND a.source_revision=?5",
                    params![session, native, revision, human, source_revision],
                    |_| Ok(()),
                )
                .optional()?
                .is_some()
            }
            CheckpointSource::Conversation { source, revision } => {
                presentation::source_on(conn, human, entry, source)?.is_some_and(|view| {
                    (key == entry || view["target"] == serde_json::json!(key))
                        && view["revision"].as_str() == Some(revision)
                        && view["current"].as_bool() != Some(false)
                        && view["native_binding_current"].as_bool() != Some(false)
                })
            }
        };
        anyhow::ensure!(
            current,
            "Checkpoint source is unavailable at the selected revision"
        );
    }
    Ok(())
}

fn verify_checkout(folder: &Path, checkout: &Path, commit: &str) -> Result<()> {
    anyhow::ensure!(
        checkout.components().all(|part| matches!(
            part,
            std::path::Component::Normal(_) | std::path::Component::CurDir
        )),
        "Select a checkout relative to the topic workspace"
    );
    let folder = folder
        .canonicalize()
        .context("Topic workspace unavailable")?;
    let checkout = folder
        .join(checkout)
        .canonicalize()
        .context("Selected checkout unavailable")?;
    anyhow::ensure!(
        checkout.starts_with(&folder),
        "Selected checkout is outside the topic workspace"
    );

    let inspect = |args: &[&str]| -> Result<Vec<u8>> {
        let output = std::process::Command::new("git")
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .env("GIT_TERMINAL_PROMPT", "0")
            .env("GIT_NO_REPLACE_OBJECTS", "1")
            .env("GIT_NO_LAZY_FETCH", "1")
            .env("GIT_ALLOW_PROTOCOL", "")
            .env("GIT_CEILING_DIRECTORIES", &folder)
            .current_dir(&checkout)
            .args(args)
            .stdin(std::process::Stdio::null())
            .output()
            .context("Git inspection unavailable")?;
        anyhow::ensure!(output.status.success(), "Selected Git revision unavailable");
        Ok(output.stdout)
    };
    anyhow::ensure!(
        inspect(&["rev-parse", "--show-prefix"])? == b"\n"
            && inspect(&["rev-parse", "--show-object-format"])?
                == if commit.len() == 40 {
                    b"sha1\n".as_slice()
                } else {
                    b"sha256\n".as_slice()
                }
            && inspect(&["cat-file", "-t", commit])? == b"commit\n",
        "Select an exact commit at the checkout root"
    );
    Ok(())
}

impl Store {
    pub(super) fn init_project_checkpoints(&self) -> Result<()> {
        self.conn
            .lock()
            .expect("store mutex poisoned")
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS project_checkpoint_deltas(
                session_id INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                operation TEXT NOT NULL,
                doc TEXT NOT NULL,
                PRIMARY KEY(session_id,revision),
                UNIQUE(session_id,operation));",
            )?;
        Ok(())
    }

    pub(crate) fn project_shadow(
        &self,
        key: SessionKey,
        entry: SessionKey,
        human: i64,
        invocation: &crate::execution::ToolInvocation,
        closed: &tokio_util::sync::CancellationToken,
        command: ProjectShadowCommand,
    ) -> Result<serde_json::Value> {
        let scope = CheckpointScope {
            key,
            entry,
            human,
            invocation,
            closed,
        };
        match command {
            ProjectShadowCommand::Workspace => {
                let conn = self.conn.lock().expect("store mutex poisoned");
                scope.authorize(&conn, &self.instance_id)?;
                let claim: Option<String> = conn
                    .query_row(
                        "SELECT topic_folder_claim FROM sessions WHERE chat_id=?1 AND thread_id=?2
                     AND creator_user_id=?3 AND topic_folder_owner=?3 AND topic_folder IS NOT NULL
                     AND topic_folder_claim IS NOT NULL",
                        params![key.chat_id, key.thread_id, human],
                        |row| row.get(0),
                    )
                    .optional()?;
                Ok(serde_json::json!({"workspace":claim}))
            }
            ProjectShadowCommand::Read {
                workspace,
                checkout,
            } => Ok(serde_json::to_value(
                self.project_checkpoint(&scope, &workspace, &checkout)?,
            )?),
            ProjectShadowCommand::Apply { delta, checkout } => Ok(serde_json::to_value(
                self.apply_project_delta(&scope, delta, &checkout)?,
            )?),
        }
    }

    fn project_checkpoint(
        &self,
        scope: &CheckpointScope,
        workspace: &str,
        checkout: &Path,
    ) -> Result<Option<ProjectCheckpoint>> {
        let inspect = || -> Result<(PathBuf, Option<ProjectCheckpoint>)> {
            let mut conn = self.conn.lock().expect("store mutex poisoned");
            let tx = conn.transaction()?;
            scope.authorize(&tx, &self.instance_id)?;
            let CheckpointScope {
                key, entry, human, ..
            } = *scope;
            let (session, folder) = workspace_on(&tx, key, human, workspace)?;
            let raw: Option<String> = tx.query_row(
                "SELECT doc FROM project_checkpoint_deltas WHERE session_id=?1 ORDER BY revision DESC LIMIT 1",
                [session], |row| row.get(0),
            ).optional()?;
            let checkpoint = raw
                .map(|raw| serde_json::from_str::<ProjectCheckpoint>(&raw))
                .transpose()?;
            if let Some(checkpoint) = &checkpoint {
                anyhow::ensure!(
                    checkpoint.author == human && checkpoint.delta.workspace == workspace,
                    "Checkpoint belongs to a prior topic binding"
                );
                check_sources(&tx, key, entry, human, &checkpoint.delta.sources)?;
            }
            tx.commit()?;
            Ok((folder, checkpoint))
        };
        let (folder, selected) = inspect()?;
        let Some(selected) = selected else {
            return Ok(None);
        };
        verify_checkout(&folder, checkout, &selected.delta.link.commit)?;
        let (current_folder, current) = inspect()?;
        anyhow::ensure!(
            current_folder == folder && current.as_ref() == Some(&selected),
            "Checkpoint changed during Git inspection"
        );
        Ok(current)
    }

    fn apply_project_delta(
        &self,
        scope: &CheckpointScope,
        delta: ProjectDelta,
        checkout: &Path,
    ) -> Result<ProjectDeltaOutcome> {
        delta.validate()?;
        let CheckpointScope {
            key, entry, human, ..
        } = *scope;
        let folder = {
            let mut conn = self.conn.lock().expect("store mutex poisoned");
            let tx = conn.transaction()?;
            scope.authorize(&tx, &self.instance_id)?;
            let (_, folder) = workspace_on(&tx, key, human, &delta.workspace)?;
            tx.commit()?;
            folder
        };
        let verification = verify_checkout(&folder, checkout, &delta.link.commit);
        let mut conn = self.conn.lock().expect("store mutex poisoned");
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        scope.authorize(&tx, &self.instance_id)?;
        let (session, current_folder) = workspace_on(&tx, key, human, &delta.workspace)?;
        anyhow::ensure!(
            current_folder == folder,
            "Workspace changed during Git inspection"
        );
        let retained: Option<String> = tx
            .query_row(
                "SELECT doc FROM project_checkpoint_deltas WHERE session_id=?1 AND operation=?2",
                params![session, delta.operation.to_string()],
                |row| row.get(0),
            )
            .optional()?;
        if let Some(retained) = retained.as_deref() {
            let checkpoint: ProjectCheckpoint = serde_json::from_str(retained)?;
            anyhow::ensure!(
                checkpoint.author == human && checkpoint.delta.workspace == delta.workspace,
                "Operation belongs to a prior topic binding"
            );
            check_sources(&tx, key, entry, human, &checkpoint.delta.sources)?;
            if checkpoint.delta == delta {
                verification?;
                return Ok(ProjectDeltaOutcome::Retained { checkpoint });
            }
        } else {
            check_sources(&tx, key, entry, human, &delta.sources)?;
        }
        let revision: i64 = tx.query_row(
            "SELECT COALESCE(MAX(revision),0) FROM project_checkpoint_deltas WHERE session_id=?1",
            [session],
            |row| row.get(0),
        )?;
        if delta.expected_revision != revision || retained.is_some() {
            return Ok(ProjectDeltaOutcome::Conflict { revision });
        }
        anyhow::ensure!(revision < 4096, "Topic checkpoint history capacity reached");
        verification?;
        let checkpoint = ProjectCheckpoint {
            revision: revision + 1,
            author: human,
            local_turn: scope.invocation.local_turn,
            delta,
        };
        tx.execute(
            "INSERT INTO project_checkpoint_deltas(session_id,revision,operation,doc) VALUES (?1,?2,?3,?4)",
            params![session, checkpoint.revision, checkpoint.delta.operation.to_string(), serde_json::to_string(&checkpoint)?],
        )?;
        tx.commit()?;
        Ok(ProjectDeltaOutcome::Accepted { checkpoint })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::UserRole;

    fn git(dir: &Path, args: &[&str]) -> String {
        let result = std::process::Command::new("git")
            .current_dir(dir)
            .env("GIT_AUTHOR_NAME", "Fixture")
            .env("GIT_COMMITTER_NAME", "Fixture")
            .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
            .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
            .args(args)
            .output()
            .unwrap();
        assert!(result.status.success(), "{:?}", result);
        String::from_utf8(result.stdout).unwrap().trim().into()
    }

    #[test]
    fn canonical_conversation_source_requires_current_audience_and_exact_revision() {
        let db = tempfile::NamedTempFile::new().unwrap();
        let defaults = super::super::tests::defaults();
        let store = Store::open(db.path(), &[100], &defaults).unwrap();
        let entry = SessionKey::new(100, Some(8));
        let worker = SessionKey::new(100, Some(9));
        let session = store.ensure_session(entry, 100, &defaults).unwrap();
        store.ensure_session(worker, 100, &defaults).unwrap();
        store
            .set_session_codex_thread(entry, "entry-native")
            .unwrap();
        let local = store
            .record_turn_started(
                session.id,
                &TurnRequest {
                    session_key: entry,
                    from_user_id: 100,
                    prompt: "Pick a project".into(),
                    runtime_instructions: None,
                    attachments: vec![],
                    review_mode: None,
                    override_search_mode: None,
                },
            )
            .unwrap();
        store
            .record_turn_native_thread(local, "entry-native")
            .unwrap();
        store
            .record_native_message(
                local,
                "entry-native",
                "entry-turn",
                "answer",
                Some("final_answer"),
                "The selected story.",
            )
            .unwrap();

        let page = store
            .interaction_presentation_list(100, entry, 0, 0)
            .unwrap();
        let item = &page["items"][0];
        let sources = [CheckpointSource::Conversation {
            source: item["id"].as_str().unwrap().into(),
            revision: item["revision"].as_str().unwrap().into(),
        }];
        {
            let conn = store.conn.lock().unwrap();
            assert!(check_sources(&conn, entry, entry, 100, &sources).is_ok());
            assert!(check_sources(&conn, worker, entry, 100, &sources).is_err());
        }
        store
            .set_session_codex_thread(entry, "replacement")
            .unwrap();
        let conn = store.conn.lock().unwrap();
        assert!(check_sources(&conn, entry, entry, 100, &sources).is_err());
    }

    #[test]
    fn shadow_retains_one_authorized_revision_when_a_checkout_moves() {
        use crate::store::observer_cards::ObserverPreparation;

        let db = tempfile::NamedTempFile::new().unwrap();
        let workspace = tempfile::tempdir().unwrap();
        let checkout = workspace.path().join("story");
        std::fs::create_dir(&checkout).unwrap();
        git(&checkout, &["init", "-q", "--object-format=sha1"]);
        std::fs::write(checkout.join("story.txt"), "Once upon a time").unwrap();
        git(&checkout, &["add", "story.txt"]);
        git(
            &checkout,
            &["-c", "commit.gpgsign=false", "commit", "-qm", "First story"],
        );
        let commit = git(&checkout, &["rev-parse", "HEAD"]);
        std::fs::write(checkout.join("story.txt"), "An unfinished chapter").unwrap();
        git(&checkout, &["add", "story.txt"]);
        let staged = git(&checkout, &["diff", "--cached"]);

        let defaults = super::super::tests::defaults();
        let store = Store::open(db.path(), &[100, 101], &defaults).unwrap();
        let topic = SessionKey::new(100, Some(7));
        let entry = SessionKey::new(100, Some(8));
        store.ensure_session(entry, 100, &defaults).unwrap();
        store.ensure_session(topic, 100, &defaults).unwrap();
        let claim = store
            .reserve_topic_folder(topic, 100, workspace.path(), None)
            .unwrap();
        store
            .set_session_codex_thread(topic, "fixture-native")
            .unwrap();
        let native_request = TurnRequest {
            session_key: topic,
            from_user_id: 100,
            prompt: "Continue the story".into(),
            runtime_instructions: None,
            attachments: vec![],
            review_mode: None,
            override_search_mode: None,
        };
        let session = store.execution_binding(topic, 100).unwrap().unwrap();
        let local_turn = store
            .record_turn_started(session.conversation_id, &native_request)
            .unwrap();
        store
            .record_turn_native_thread(local_turn, "fixture-native")
            .unwrap();
        let mut invocation = crate::execution::ToolInvocation {
            local_turn,
            harness: crate::execution::Harness::Codex,
            native_session: "fixture-native".into(),
            native_turn: "fixture-turn".into(),
            tool: "interaction_controller".into(),
            namespace: None,
            arguments: serde_json::json!({}),
        };
        let closed = tokio_util::sync::CancellationToken::new();
        let scope = CheckpointScope {
            key: topic,
            entry,
            human: 100,
            invocation: &invocation,
            closed: &closed,
        };
        let snapshot = serde_json::json!({
            "native": "fixture-native", "revision": "retained-source", "boundary": "fixture-turn",
            "turn_ids": ["fixture-turn"], "entries": ["A story was committed"],
            "in_progress_entries": [], "bounded": false, "text_truncated": false
        });
        let ObserverPreparation::Ready(attempt) = store
            .observer_prepare(topic, 100, &snapshot, 0, false)
            .unwrap()
        else {
            panic!("fixture should have one retained Observer attempt")
        };
        let card = store
            .observer_commit(topic, 100, &attempt, "The story can be reviewed", &[0])
            .unwrap();
        let delta = ProjectDelta {
            operation: Uuid::now_v7(),
            expected_revision: 0,
            workspace: claim.clone(),
            link: ProjectLink {
                project: Uuid::now_v7(),
                locator: "git:story".into(),
                commit,
            },
            sources: vec![CheckpointSource::Observer {
                native: "fixture-native".into(),
                revision: card.revision,
                source_revision: card.source_revision,
            }],
        };
        let mut missing = delta.clone();
        missing.link.commit = "0".repeat(40);
        assert!(
            store
                .apply_project_delta(&scope, missing, Path::new("story"))
                .is_err()
        );
        assert!(
            store
                .project_checkpoint(&scope, &claim, Path::new("story"))
                .unwrap()
                .is_none()
        );
        assert!(matches!(
            store.apply_project_delta(&scope, delta.clone(), Path::new("story")).unwrap(),
            ProjectDeltaOutcome::Accepted { checkpoint } if checkpoint.revision == 1
        ));
        let mut competing = delta.clone();
        competing.operation = Uuid::now_v7();
        let mut different = delta.clone();
        different.link.locator = "git:different".into();
        for conflict in [competing, different] {
            assert!(matches!(
                store
                    .apply_project_delta(&scope, conflict, Path::new("story"))
                    .unwrap(),
                ProjectDeltaOutcome::Conflict { revision: 1 }
            ));
        }
        drop(store);
        let store = Store::open(db.path(), &[100, 101], &defaults).unwrap();
        let resumed = store
            .record_turn_started(session.conversation_id, &native_request)
            .unwrap();
        store
            .record_turn_native_thread(resumed, "fixture-native")
            .unwrap();
        invocation.local_turn = resumed;
        let scope = CheckpointScope {
            key: topic,
            entry,
            human: 100,
            invocation: &invocation,
            closed: &closed,
        };
        let moved = workspace.path().join("moved");
        std::fs::rename(checkout, &moved).unwrap();
        assert!(matches!(
            store.apply_project_delta(&scope, delta.clone(), Path::new("moved")).unwrap(),
            ProjectDeltaOutcome::Retained { checkpoint } if checkpoint.revision == 1
        ));
        assert_eq!(
            store
                .project_checkpoint(&scope, &claim, Path::new("moved"))
                .unwrap()
                .unwrap()
                .delta,
            delta
        );
        assert_eq!(git(&moved, &["diff", "--cached"]), staged);
        assert!(
            store
                .project_checkpoint(
                    &CheckpointScope {
                        human: 101,
                        ..scope
                    },
                    &claim,
                    Path::new("moved")
                )
                .is_err()
        );
        store.set_session_codex_thread(topic, "new-native").unwrap();
        assert!(
            store
                .project_checkpoint(&scope, &claim, Path::new("moved"))
                .is_err()
        );
        assert!(
            store
                .apply_project_delta(&scope, delta.clone(), Path::new("moved"))
                .is_err()
        );
        store.upsert_user(100, UserRole::Admin, false).unwrap();
        assert!(
            store
                .project_checkpoint(&scope, &claim, Path::new("moved"))
                .is_err()
        );
    }
}
