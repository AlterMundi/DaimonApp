//! Durable shadow project links. Original source and effect owners remain authoritative.
use super::*;
use serde::{Deserialize, Serialize};

mod recovery;
pub(crate) use recovery::ProjectStartup;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProjectLink {
    pub project: Uuid,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repository: Option<Uuid>,
    pub locator: String,
    pub commit: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
}

impl ProjectLink {
    fn repository_id(&self) -> Uuid {
        self.repository.unwrap_or(self.project)
    }
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
                && !self.link.repository_id().is_nil()
                && self.link.locator.starts_with("git:")
                && self.link.locator.len() > 4
                && self.link.locator.len() <= 1024
                && !self.link.locator.chars().any(char::is_control)
                && self.link.label.as_ref().is_none_or(|label| {
                    !label.trim().is_empty()
                        && label.chars().count() <= 80
                        && !label.chars().any(char::is_control)
                })
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
        project: Option<Uuid>,
        repository: Option<Uuid>,
    },
    Projects {
        workspace: String,
        before: Option<i64>,
    },
    Apply {
        delta: ProjectDelta,
        checkout: PathBuf,
    },
    SelectRecovery {
        workspace: String,
        projects: Vec<recovery::CheckoutSelection>,
        effects: Vec<Uuid>,
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
    link: &ProjectLink,
) -> Result<()> {
    let mut supported = false;
    for source in sources {
        let matches_link = match source {
            CheckpointSource::Observer {
                native,
                revision,
                source_revision,
            } => {
                let session = observer_cards::binding(conn, key, human, native)?;
                let (card, evidence): (String, String) = conn
                    .query_row(
                        "SELECT c.doc,a.source_doc FROM interaction_observer_cards c
                     JOIN interaction_observer_attempts a ON a.id=c.attempt_id
                     JOIN sessions s ON s.id=c.session_id
                     WHERE c.session_id=?1 AND c.native_thread=?2 AND c.revision=?3
                       AND a.human_id=?4 AND a.source_revision=?5 AND s.force_fresh_thread=0",
                        params![session, native, revision, human, source_revision],
                        |row| Ok((row.get(0)?, row.get(1)?)),
                    )
                    .optional()?
                    .context("Observer evidence unavailable at the selected revision")?;
                let card: observer_cards::ObserverCard = serde_json::from_str(&card)?;
                let evidence: serde_json::Value = serde_json::from_str(&evidence)?;
                let entries = ["entries", "in_progress_entries"]
                    .into_iter()
                    .flat_map(|field| evidence[field].as_array().into_iter().flatten())
                    .collect::<Vec<_>>();
                card.supports.iter().any(|index| {
                    entries
                        .get(*index)
                        .and_then(|value| value.as_str())
                        .is_some_and(|text| cites_project(text, link))
                })
            }
            CheckpointSource::Conversation { source, revision } => {
                let evidence = presentation::source_on(conn, human, entry, source)?
                    .filter(|view| {
                        (key == entry || view["target"] == serde_json::json!(key))
                            && view["revision"].as_str() == Some(revision)
                            && view["current"].as_bool() != Some(false)
                            && view["native_binding_current"].as_bool() != Some(false)
                    })
                    .context("Conversation evidence unavailable at the selected revision")?;
                evidence["text"]
                    .as_str()
                    .is_some_and(|text| cites_project(text, link))
            }
        };
        supported |= matches_link;
    }
    anyhow::ensure!(supported, "No retained source cites the exact project link");
    Ok(())
}

fn cites_project(text: &str, link: &ProjectLink) -> bool {
    text.lines()
        .filter_map(|line| line.trim().strip_prefix("Project link: "))
        .any(|raw| serde_json::from_str::<ProjectLink>(raw).is_ok_and(|cited| cited == *link))
}

fn stable_git_origin(origin: &str) -> bool {
    if Path::new(origin).is_absolute() {
        return true;
    }
    if origin.contains("://") {
        return reqwest::Url::parse(origin).is_ok_and(|url| {
            matches!(url.scheme(), "file" | "git" | "ssh" | "http" | "https")
                && url.password().is_none()
                && (!matches!(url.scheme(), "http" | "https") || url.username().is_empty())
                && url.query().is_none()
                && url.fragment().is_none()
        });
    }
    // In Git's scp-like spelling only a colon before any slash selects a host.
    origin.split_once(':').is_some_and(|(host, repository)| {
        !host.is_empty()
            && host
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"@._-".contains(&b))
            && !repository.is_empty()
            && !repository.starts_with(':')
    })
}

fn verify_checkout(folder: &Path, claim: &str, checkout: &Path, link: &ProjectLink) -> Result<()> {
    anyhow::ensure!(
        crate::files::workspace_marker_matches(folder, claim)?,
        "Topic workspace ownership marker unavailable"
    );
    let commit = &link.commit;
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
    let locator = link
        .locator
        .strip_prefix("git:")
        .context("Missing Git locator")?;
    let (key, expected) = if let Some(local) = locator.strip_prefix("local:") {
        anyhow::ensure!(
            Uuid::parse_str(local).ok() == Some(link.repository_id()),
            "Local repository identity differs"
        );
        ("daimon.project-id", local)
    } else {
        anyhow::ensure!(
            stable_git_origin(locator),
            "Git origin must be stable across checkout moves"
        );
        ("remote.origin.url", locator)
    };
    let actual = inspect(&["config", "--local", "--get-all", key])?;
    anyhow::ensure!(
        actual.strip_suffix(b"\n") == Some(expected.as_bytes()),
        "Checkout does not match the selected Git locator"
    );
    anyhow::ensure!(
        crate::files::workspace_marker_matches(&folder, claim)?,
        "Topic workspace changed during Git inspection"
    );
    Ok(())
}

#[derive(Clone, Copy, Default)]
struct LinkSelector {
    project: Option<Uuid>,
    repository: Option<Uuid>,
}

fn checkpoint_on(
    conn: &Connection,
    key: SessionKey,
    entry: SessionKey,
    human: i64,
    session: i64,
    workspace: &str,
    selector: LinkSelector,
) -> Result<Option<ProjectCheckpoint>> {
    let raw: Option<String> = conn.query_row(
        "SELECT doc FROM project_checkpoint_deltas WHERE session_id=?1
         AND (?2 IS NULL OR json_extract(doc,'$.delta.link.project')=?2)
         AND (?3 IS NULL OR COALESCE(json_extract(doc,'$.delta.link.repository'),json_extract(doc,'$.delta.link.project'))=?3)
         ORDER BY revision DESC LIMIT 1",
        params![session, selector.project.map(|project| project.to_string()), selector.repository.map(|id|id.to_string())], |row| row.get(0),
    ).optional()?;
    let checkpoint = raw
        .map(|raw| serde_json::from_str::<ProjectCheckpoint>(&raw))
        .transpose()?;
    if let Some(checkpoint) = &checkpoint {
        anyhow::ensure!(
            checkpoint.author == human && checkpoint.delta.workspace == workspace,
            "Checkpoint belongs to a prior topic binding"
        );
        check_sources(
            conn,
            key,
            entry,
            human,
            &checkpoint.delta.sources,
            &checkpoint.delta.link,
        )?;
    }
    Ok(checkpoint)
}

fn catalog_on(
    conn: &Connection,
    key: SessionKey,
    entry: SessionKey,
    human: i64,
    session: i64,
    workspace: &str,
    before: Option<i64>,
) -> Result<(Vec<ProjectCheckpoint>, Option<i64>)> {
    let mut query = conn.prepare(
        "SELECT project,repository,tip FROM (
             SELECT json_extract(doc,'$.delta.link.project') AS project,
                    COALESCE(json_extract(doc,'$.delta.link.repository'),json_extract(doc,'$.delta.link.project')) AS repository,
                    MAX(revision) AS tip
             FROM project_checkpoint_deltas WHERE session_id=?1 AND json_extract(doc,'$.delta.workspace')=?2
             GROUP BY project,repository)
         WHERE (?3 IS NULL OR tip<?3) ORDER BY tip DESC LIMIT 9",
    )?;
    let mut rows = query.query(params![session, workspace, before])?;
    let mut links = Vec::new();
    let mut last = None;
    for _ in 0..8 {
        let Some(row) = rows.next()? else {
            break;
        };
        last = Some(row.get::<_, i64>(2)?);
        let selector = LinkSelector {
            project: Some(Uuid::parse_str(&row.get::<_, String>(0)?)?),
            repository: Some(Uuid::parse_str(&row.get::<_, String>(1)?)?),
        };
        if let Ok(Some(checkpoint)) =
            checkpoint_on(conn, key, entry, human, session, workspace, selector)
        {
            links.push(checkpoint);
        }
    }
    let next = if rows.next()?.is_some() { last } else { None };
    Ok((links, next))
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
                UNIQUE(session_id,operation));
                CREATE TABLE IF NOT EXISTS project_checkpoint_recovery(
                session_id INTEGER PRIMARY KEY,
                doc TEXT NOT NULL);",
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
                project,
                repository,
            } => Ok(serde_json::to_value(self.project_checkpoint(
                &scope,
                &workspace,
                &checkout,
                LinkSelector {
                    project,
                    repository,
                },
            )?)?),
            ProjectShadowCommand::Projects { workspace, before } => {
                self.workspace_projects(&scope, &workspace, before)
            }
            ProjectShadowCommand::Apply { delta, checkout } => Ok(serde_json::to_value(
                self.apply_project_delta(&scope, delta, &checkout)?,
            )?),
            ProjectShadowCommand::SelectRecovery {
                workspace,
                projects,
                effects,
            } => self.select_project_recovery(
                &scope,
                recovery::Selection {
                    workspace,
                    projects,
                    effects,
                },
            ),
        }
    }

    fn workspace_projects(
        &self,
        scope: &CheckpointScope,
        workspace: &str,
        before: Option<i64>,
    ) -> Result<serde_json::Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        scope.authorize(&conn, &self.instance_id)?;
        let (session, folder) = workspace_on(&conn, scope.key, scope.human, workspace)?;
        anyhow::ensure!(
            crate::files::workspace_marker_matches(&folder, workspace)?,
            "Topic workspace ownership marker unavailable"
        );
        let revision: i64 = conn.query_row(
            "SELECT COALESCE(MAX(revision),0) FROM project_checkpoint_deltas WHERE session_id=?1",
            [session],
            |row| row.get(0),
        )?;
        let (links, next) = catalog_on(
            &conn,
            scope.key,
            scope.entry,
            scope.human,
            session,
            workspace,
            before,
        )?;
        let links = links.into_iter().map(|checkpoint| {
            serde_json::json!({"revision":checkpoint.revision,"link":checkpoint.delta.link})
        }).collect::<Vec<_>>();
        Ok(serde_json::json!({"revision":revision,"links":links,"nextBefore":next}))
    }

    pub(crate) fn topic_project_projection(
        &self,
        human: i64,
        entry: SessionKey,
        key: SessionKey,
    ) -> Result<serde_json::Value> {
        let conn = self.conn.lock().expect("store mutex poisoned");
        let (entry_session, native) = presentation::entry_on(&conn, human, entry)?;
        let (session, folder, claim): (i64, Option<String>, Option<String>) = conn.query_row(
            "SELECT s.id,s.topic_folder,s.topic_folder_claim FROM sessions s
             JOIN users u ON u.tg_user_id=s.creator_user_id
             WHERE s.chat_id=?1 AND s.thread_id=?2 AND s.creator_user_id=?3 AND u.allowed=1
               AND (s.topic_folder IS NULL OR s.topic_folder_owner=?3)",
            params![key.chat_id, key.thread_id, human],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )?;
        let links = match (folder, claim) {
            (None, None) => Vec::new(),
            (Some(folder), Some(claim)) => {
                anyhow::ensure!(
                    crate::files::workspace_marker_matches(Path::new(&folder), &claim)?,
                    "Topic workspace ownership marker unavailable"
                );
                catalog_on(&conn, key, entry, human, session, &claim, None)?.0
            }
            _ => anyhow::bail!("Current owned topic workspace unavailable"),
        };
        let repositories = links
            .into_iter()
            .map(|checkpoint| {
                let link = checkpoint.delta.link;
                let label = link.label.clone().unwrap_or_else(|| {
                    let locator = link.locator.strip_prefix("git:").unwrap_or_default();
                    if locator.starts_with("local:") {
                        return "Repositorio local".into();
                    }
                    locator
                        .trim_end_matches('/')
                        .rsplit(['/', ':'])
                        .next()
                        .unwrap_or_default()
                        .trim_end_matches(".git")
                        .trim()
                        .chars()
                        .take(80)
                        .collect()
                });
                serde_json::json!({
                    "project":link.project,"repository":link.repository_id(),
                    "label":if label.is_empty() {"Repositorio"} else {label.as_str()},
                    "commit":link.commit,
                })
            })
            .collect::<Vec<_>>();
        Ok(serde_json::json!({
            "schema":"daimon.topic-projects/v1",
            "entry_binding":[human,entry,entry_session,native],
            "target":key,"repositories":repositories,
        }))
    }

    fn project_checkpoint(
        &self,
        scope: &CheckpointScope,
        workspace: &str,
        checkout: &Path,
        selector: LinkSelector,
    ) -> Result<Option<ProjectCheckpoint>> {
        let inspect = || -> Result<(PathBuf, Option<ProjectCheckpoint>)> {
            let mut conn = self.conn.lock().expect("store mutex poisoned");
            let tx = conn.transaction()?;
            scope.authorize(&tx, &self.instance_id)?;
            let CheckpointScope {
                key, entry, human, ..
            } = *scope;
            let (session, folder) = workspace_on(&tx, key, human, workspace)?;
            let checkpoint = checkpoint_on(&tx, key, entry, human, session, workspace, selector)?;
            tx.commit()?;
            Ok((folder, checkpoint))
        };
        let (folder, selected) = inspect()?;
        anyhow::ensure!(
            crate::files::workspace_marker_matches(&folder, workspace)?,
            "Topic workspace ownership marker unavailable"
        );
        let Some(selected) = selected else {
            return Ok(None);
        };
        verify_checkout(&folder, workspace, checkout, &selected.delta.link)?;
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
        let verification = verify_checkout(&folder, &delta.workspace, checkout, &delta.link);
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
            check_sources(
                &tx,
                key,
                entry,
                human,
                &checkpoint.delta.sources,
                &checkpoint.delta.link,
            )?;
            if checkpoint.delta == delta {
                verification?;
                return Ok(ProjectDeltaOutcome::Retained { checkpoint });
            }
        } else {
            check_sources(&tx, key, entry, human, &delta.sources, &delta.link)?;
        }
        let revision: i64 = tx.query_row(
            "SELECT COALESCE(MAX(revision),0) FROM project_checkpoint_deltas WHERE session_id=?1",
            [session],
            |row| row.get(0),
        )?;
        if delta.expected_revision != revision || retained.is_some() {
            return Ok(ProjectDeltaOutcome::Conflict { revision });
        }
        verification?;
        let checkpoint = ProjectCheckpoint {
            revision: revision
                .checked_add(1)
                .context("Topic checkpoint revision exhausted")?,
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
        let link = ProjectLink {
            project: Uuid::now_v7(),
            repository: None,
            locator: "git:/fixture/story.git".into(),
            commit: "1".repeat(40),
            label: None,
        };
        let answer = format!(
            "The selected story.\nProject link: {}",
            serde_json::to_string(&link).unwrap()
        );
        store
            .record_native_message(
                local,
                "entry-native",
                "entry-turn",
                "answer",
                Some("final_answer"),
                &answer,
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
            assert!(check_sources(&conn, entry, entry, 100, &sources, &link).is_ok());
            assert!(check_sources(&conn, worker, entry, 100, &sources, &link).is_err());
        }
        store
            .set_session_codex_thread(entry, "replacement")
            .unwrap();
        let conn = store.conn.lock().unwrap();
        assert!(check_sources(&conn, entry, entry, 100, &sources, &link).is_err());
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
        let remote = tempfile::tempdir().unwrap();
        git(
            remote.path(),
            &["init", "-q", "--bare", "--object-format=sha1"],
        );
        let locator = remote.path().to_str().unwrap();
        git(&checkout, &["remote", "add", "origin", locator]);
        git(&checkout, &["push", "origin", "HEAD:refs/heads/main"]);
        git(remote.path(), &["symbolic-ref", "HEAD", "refs/heads/main"]);
        let link = ProjectLink {
            project: Uuid::now_v7(),
            repository: None,
            locator: format!("git:{locator}"),
            commit,
            label: Some("Story".into()),
        };

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
        let marker = workspace.path().join(".daimon-topic");
        let citation = format!(
            "A story was committed.\nProject link: {}",
            serde_json::to_string(&link).unwrap()
        );
        let snapshot = serde_json::json!({
            "native": "fixture-native", "revision": "retained-source", "boundary": "fixture-turn",
            "turn_ids": ["fixture-turn"], "entries": [citation],
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
            link,
            sources: vec![CheckpointSource::Observer {
                native: "fixture-native".into(),
                revision: card.revision,
                source_revision: card.source_revision,
            }],
        };
        assert!(
            store
                .apply_project_delta(&scope, delta.clone(), Path::new("story"))
                .is_err()
        );
        std::fs::write(&marker, "other claim").unwrap();
        assert!(
            store
                .apply_project_delta(&scope, delta.clone(), Path::new("story"))
                .is_err()
        );
        std::fs::write(&marker, &claim).unwrap();

        let mut missing = delta.clone();
        missing.link.commit = "0".repeat(40);
        assert!(
            verify_checkout(workspace.path(), &claim, Path::new("story"), &missing.link).is_err()
        );
        let mut unrelated = delta.clone();
        unrelated.link.project = Uuid::now_v7();
        assert!(
            store
                .apply_project_delta(&scope, unrelated, Path::new("story"))
                .is_err()
        );
        let same_commit = workspace.path().join("copy");
        git(workspace.path(), &["clone", locator, "copy"]);
        assert_eq!(git(&same_commit, &["rev-parse", "HEAD"]), delta.link.commit);
        let mut relative = delta.link.clone();
        relative.locator = "git:../origin.git".into();
        git(
            &same_commit,
            &["remote", "set-url", "origin", "../origin.git"],
        );
        assert!(verify_checkout(workspace.path(), &claim, Path::new("copy"), &relative).is_err());
        git(
            &same_commit,
            &["remote", "set-url", "origin", "/fixture/other.git"],
        );
        assert!(
            store
                .apply_project_delta(&scope, delta.clone(), Path::new("copy"))
                .is_err()
        );
        assert!(
            store
                .project_checkpoint(&scope, &claim, Path::new("story"), LinkSelector::default())
                .unwrap()
                .is_none()
        );
        let mut competing = delta.clone();
        competing.operation = Uuid::now_v7();
        let barrier = std::sync::Barrier::new(2);
        let results = std::thread::scope(|threads| {
            let propose = |delta| {
                barrier.wait();
                store
                    .apply_project_delta(&scope, delta, Path::new("story"))
                    .unwrap()
            };
            let first = threads.spawn(move || propose(delta));
            let second = threads.spawn(move || propose(competing));
            (first.join().unwrap(), second.join().unwrap())
        });
        let checkpoint = match results {
            (
                ProjectDeltaOutcome::Accepted { checkpoint },
                ProjectDeltaOutcome::Conflict { revision: 1 },
            )
            | (
                ProjectDeltaOutcome::Conflict { revision: 1 },
                ProjectDeltaOutcome::Accepted { checkpoint },
            ) => checkpoint,
            outcomes => panic!("expected one winner and one conflict: {outcomes:?}"),
        };
        let delta = checkpoint.delta;
        let mut different = delta.clone();
        different.link.locator = "git:different".into();
        assert!(matches!(
            store
                .apply_project_delta(&scope, different, Path::new("story"))
                .unwrap(),
            ProjectDeltaOutcome::Conflict { revision: 1 }
        ));
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
        let moved = workspace.path().join("subdir/moved");
        std::fs::create_dir(moved.parent().unwrap()).unwrap();
        std::fs::rename(checkout, &moved).unwrap();
        assert!(matches!(
            store.apply_project_delta(&scope, delta.clone(), Path::new("subdir/moved")).unwrap(),
            ProjectDeltaOutcome::Retained { checkpoint } if checkpoint.revision == 1
        ));
        assert_eq!(
            store
                .project_checkpoint(
                    &scope,
                    &claim,
                    Path::new("subdir/moved"),
                    LinkSelector::default()
                )
                .unwrap()
                .unwrap()
                .delta,
            delta
        );
        assert_eq!(git(&moved, &["diff", "--cached"]), staged);
        let projected = store.topic_project_projection(100, entry, topic).unwrap();
        assert_eq!(
            projected["repositories"][0]["project"],
            delta.link.project.to_string()
        );
        assert_eq!(projected["repositories"][0]["commit"], delta.link.commit);
        assert!(projected["repositories"][0].get("locator").is_none());
        assert_eq!(projected["repositories"][0]["label"], "Story");
        assert!(store.topic_project_projection(101, entry, topic).is_err());
        assert!(
            store
                .project_checkpoint(
                    &CheckpointScope {
                        human: 101,
                        ..scope
                    },
                    &claim,
                    Path::new("subdir/moved"),
                    LinkSelector::default(),
                )
                .is_err()
        );
        // Retire the cited fixture card while leaving the live worker selection valid.
        store
            .conn
            .lock()
            .unwrap()
            .execute(
                "DELETE FROM interaction_observer_cards WHERE attempt_id=?1",
                [&attempt.id],
            )
            .unwrap();
        assert!(store.controller_execution(resumed, topic, 100).is_ok());
        assert_eq!(
            store.topic_project_projection(100, entry, topic).unwrap()["repositories"],
            serde_json::json!([])
        );
        assert!(
            store
                .project_checkpoint(
                    &scope,
                    &claim,
                    Path::new("subdir/moved"),
                    LinkSelector::default()
                )
                .is_err()
        );
        assert!(
            store
                .apply_project_delta(&scope, delta.clone(), Path::new("subdir/moved"))
                .is_err()
        );
        store.upsert_user(100, UserRole::Admin, false).unwrap();
        assert!(
            store
                .project_checkpoint(
                    &scope,
                    &claim,
                    Path::new("subdir/moved"),
                    LinkSelector::default()
                )
                .is_err()
        );
    }
}
