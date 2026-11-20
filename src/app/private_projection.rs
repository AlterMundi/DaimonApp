//! A fixed owner command for one offered Reports purpose, not a general shell.
//! Private custody remains on the host; the actor supplies only exact revisions.
use super::*;
use crate::interaction::OwnerActionPurpose;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

// One configured projection per receiver. Do not create waiting host processes
// when a caller submits concurrent actions or readbacks.
static ACTION: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);

pub(super) fn runtime_hint(config: &crate::interaction::PrivateProjectionConfig) -> String {
    format!(
        "\n\nOnly when this accepted Reports return offers task {}, this receiver selects interaction_controller/private_projection as the host route for its already authorized private refresh, including an older task note that names refresh.py. Reconcile the retained human purpose first. Use these configured input files, preserving concurrent editorial fields: {}. After completed reconciliation, call private_projection run with the exact batch/task revisions and input digests. Do not expose publisher credentials or call its CLI from the isolated actor. If status shows an unresolved invocation, inspect that exact invocation; inspection never publishes. Status/inspection/ACK do not establish hearing, a new publication, or completion of the whole human task. With no matching offered Reports task, this hint authorizes no action.",
        config.task_id,
        serde_json::json!({"snapshot":config.snapshot,"reconciliation":config.reconciliation})
    )
}

pub(super) fn repair_runtime_hint(config: &crate::interaction::PrivateProjectionConfig) -> String {
    format!(
        "\n\nOnly when this accepted Reports return offers task {}, use interaction_controller/alerts_repair for the separately configured, already authorized Alerts owner repair. Reconcile the exact incident and completed report first using {}. Run with the offered return/task revisions and exact input digests. The host command selects the supported repair, never the model. Preserve current pauses and unknown effects. On an unresolved invocation inspect it once through its original adapter; do not rerun it or equate acknowledgment with resolution. No matching task means no repair authority.",
        config.task_id,
        serde_json::json!({"snapshot":config.snapshot,"reconciliation":config.reconciliation})
    )
}

/// A service repair is not an artifact publication or an alert acknowledgment.
fn validate_repair_receipt(value: &Value, snapshot: &[u8], inspect: bool) -> Result<Value> {
    let source: Value = serde_json::from_slice(snapshot)?;
    let incident = &source["incident"];
    let safe_id = |v: &Value| {
        v.as_str().is_some_and(|s| {
            !s.is_empty()
                && s.len() <= 256
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.:".contains(&b))
        })
    };
    anyhow::ensure!(
        source["schema"] == "daimon-alerts-repair-input/v1"
            && safe_id(&incident["id"])
            && safe_id(&incident["resource_id"])
            && incident["revision"].as_u64().is_some(),
        "Exact repair incident input required"
    );
    anyhow::ensure!(
        value["schema"] == "daimon-alerts-owner-repair/v1"
            && value["source_sha256"] == digest(snapshot)
            && value["incident_id"] == incident["id"]
            && value["incident_revision"] == incident["revision"]
            && value["resource_id"] == incident["resource_id"],
        "Repair receipt does not identify original incident"
    );
    let state = if inspect {
        "existing_resolution_verified"
    } else {
        "resolved_verified"
    };
    anyhow::ensure!(
        value["state"] == state
            && value["resolution_state"] == "resolved"
            && value["resolution_revision"]
                .as_u64()
                .is_some_and(|r| r > incident["revision"].as_u64().unwrap())
            && safe_id(&value["operation_id"]),
        "Same incident resolution at a higher revision required"
    );
    Ok(
        json!({"phase":"observed","state":value["state"],"source_sha256":value["source_sha256"],
        "incident_id":value["incident_id"],"incident_revision":value["incident_revision"],
        "resource_id":value["resource_id"],"resolution_state":"resolved",
        "resolution_revision":value["resolution_revision"],"operation_id":value["operation_id"],
        "verification_only":inspect,"original_invocation_execution":if inspect {"not_established"} else {"observed"}}),
    )
}

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Status {},
    Inspect {
        invocation: String,
    },
    Run {
        return_id: String,
        batch_revision: String,
        task_revision: String,
        snapshot_sha256: String,
        reconciliation_sha256: String,
    },
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn validate_reconciliation(
    config: &crate::interaction::PrivateProjectionConfig,
    receipt: &[u8],
    return_id: &str,
) -> Result<()> {
    let receipt: Value = serde_json::from_slice(receipt)?;
    anyhow::ensure!(
        receipt
            .pointer(&config.reconciliation_return_pointer)
            .and_then(Value::as_str)
            == Some(return_id)
            && receipt.pointer(&config.reconciliation_partial_pointer) == Some(&Value::Bool(false)),
        "Completed reconciliation does not identify this Reports return"
    );
    Ok(())
}

/// Traverse held directory FDs, refusing symlinks in every component.
#[cfg(unix)]
fn bounded_file(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    use std::io::Read;
    use std::os::fd::{AsRawFd, FromRawFd};
    use std::os::unix::ffi::OsStrExt;
    use std::path::Component;
    anyhow::ensure!(path.is_absolute(), "Projection input must be absolute");
    let mut directory = fs::File::open("/")?;
    let components: Vec<_> = path.components().skip(1).collect();
    anyhow::ensure!(!components.is_empty(), "Projection file required");
    for (index, component) in components.iter().enumerate() {
        let Component::Normal(name) = component else {
            bail!("Canonical projection path required")
        };
        let name = std::ffi::CString::new(name.as_bytes())?;
        let last = index + 1 == components.len();
        let flags = libc::O_RDONLY
            | libc::O_NOFOLLOW
            | libc::O_CLOEXEC
            | if last {
                libc::O_NONBLOCK
            } else {
                libc::O_DIRECTORY
            };
        let fd = unsafe { libc::openat(directory.as_raw_fd(), name.as_ptr(), flags) };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // Each owned FD is closed before advancing; renamed ancestors cannot retarget it.
        directory = unsafe { fs::File::from_raw_fd(fd) };
    }
    anyhow::ensure!(
        directory.metadata()?.is_file() && directory.metadata()?.len() <= maximum,
        "Bounded regular projection input required"
    );
    let mut bytes = Vec::new();
    directory.take(maximum + 1).read_to_end(&mut bytes)?;
    anyhow::ensure!(
        bytes.len() as u64 <= maximum,
        "Projection input grew beyond bound"
    );
    Ok(bytes)
}

#[cfg(target_os = "linux")]
async fn execute_mode(
    config: &crate::interaction::PrivateProjectionConfig,
    snapshot: &[u8],
    seconds: u64,
    closed: &CancellationToken,
    inspect: bool,
    purpose: OwnerActionPurpose,
) -> Result<Value> {
    use std::os::fd::{AsRawFd, FromRawFd};
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut command = tokio::process::Command::new(&config.command[0]);
    command
        .args(&config.command[1..])
        .current_dir(&config.working_directory);
    if inspect {
        command.arg("--inspect-stdin");
    }
    command
        .env_clear()
        .env("PATH", "/usr/local/bin:/usr/bin:/bin")
        .env("LANG", "C.UTF-8");
    // The fixed host adapter needs its existing owner binding, never provider secrets.
    if let Some(value) = std::env::var_os("HOME") {
        command.env("HOME", value);
    }
    command.as_std_mut().process_group(0);
    // This trusted fixed helper and its ordinary children remain outside the
    // actor sandbox. Give each inherited process explicit non-expanding caps;
    // do not claim these are the actor's aggregate cgroup limits.
    unsafe {
        command.as_std_mut().pre_exec(|| {
            for (resource, maximum) in [
                (libc::RLIMIT_AS, 1024 * 1024 * 1024),
                (libc::RLIMIT_CPU, 20),
                (libc::RLIMIT_NOFILE, 256),
            ] {
                let mut limit = std::mem::zeroed::<libc::rlimit>();
                if libc::getrlimit(resource, &mut limit) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                limit.rlim_cur = limit.rlim_cur.min(maximum);
                limit.rlim_max = limit.rlim_max.min(maximum);
                if libc::setrlimit(resource, &limit) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    let mut child = command
        .spawn()
        .context("Private projection command unavailable")?;
    let pid = child.id().context("Projection process missing")?;
    let group = super::matrix::OwnedMatrixCommand(pid);
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) } as i32;
    if fd < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let pidfd = unsafe { std::os::fd::OwnedFd::from_raw_fd(fd) };
    let mut input = child.stdin.take().context("Projection stdin missing")?;
    let mut output = child
        .stdout
        .take()
        .context("Projection stdout missing")?
        .take(8193);
    let work = async {
        let write = async {
            input.write_all(snapshot).await?;
            input.shutdown().await?;
            drop(input);
            Ok::<_, std::io::Error>(())
        };
        let read = async {
            let mut bytes = Vec::new();
            output.read_to_end(&mut bytes).await?;
            Ok::<_, std::io::Error>(bytes)
        };
        let (_, bytes) = tokio::try_join!(write, read)?;
        anyhow::ensure!(bytes.len() <= 8192, "Projection output exceeds bound");
        // Observe exit without reaping the leader: its PID cannot be reused before
        // the owned group is cleaned up, including descendants with closed stdout.
        loop {
            let mut watched = libc::pollfd {
                fd: pidfd.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            let result = unsafe { libc::poll(&mut watched, 1, 0) };
            if result < 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            if result > 0 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        let value: Value = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            value["source_sha256"] == digest(snapshot),
            "Projection receipt does not identify pinned input"
        );
        if purpose == OwnerActionPurpose::AlertsRepair {
            return validate_repair_receipt(&value, snapshot, inspect);
        }
        if inspect {
            anyhow::ensure!(
                value["state"] == "existing_projection_verified"
                    && value["immutable_files_match"] == true
                    && value["owner_broker_all_files_match"] == true
                    && value["artifact_ref"]
                        .as_str()
                        .is_some_and(|s| !s.is_empty())
                    && value["version_ref"].as_str().is_some_and(|s| !s.is_empty()),
                "Existing projection not verified; preserve unresolved invocation"
            );
        } else {
            anyhow::ensure!(
                matches!(
                    value["state"].as_str(),
                    Some("unchanged" | "published_verified")
                ),
                "Projection outcome not verified"
            );
        }
        Ok(
            json!({"phase":"observed","state":value["state"],"source_sha256":value["source_sha256"],"artifact_ref":value["artifact_ref"],"version_ref":value["version_ref"],"verification_only":inspect,"original_invocation_execution":if inspect {"not_established"} else {"observed"},"checkpoint_matches":value["checkpoint_matches"]}),
        )
    };
    let result = tokio::select! {
        _ = closed.cancelled() => Err(anyhow!("Projection cancelled; inspect retained intent")),
        result = tokio::time::timeout(Duration::from_secs(seconds), work) => match result { Ok(value) => value, Err(_) => Err(anyhow!("Projection deadline expired; no automatic retry")) },
    };
    drop(group);
    let status = child.wait().await?;
    anyhow::ensure!(status.success(), "Projection outcome unconfirmed");
    result
}

#[cfg(target_os = "linux")]
async fn execute(
    config: &crate::interaction::PrivateProjectionConfig,
    snapshot: &[u8],
    seconds: u64,
    closed: &CancellationToken,
    purpose: OwnerActionPurpose,
) -> Result<Value> {
    execute_mode(config, snapshot, seconds, closed, false, purpose).await
}

pub(super) async fn tool(
    app: &App,
    key: SessionKey,
    human: i64,
    request: &crate::codex::DynamicToolRequest,
    args: Value,
    closed: &CancellationToken,
    purpose: OwnerActionPurpose,
) -> Result<Value> {
    let args: Request = serde_json::from_value(args)?;
    let cfg = super::routing::profile(&app.shared)?;
    anyhow::ensure!(
        cfg.human_id == human && cfg.entry() == key && !closed.is_cancelled(),
        "Projection requires the current owner entry"
    );
    if matches!(args, Request::Status { .. }) {
        return app
            .shared
            .store
            .private_projection_status(purpose, human, key, &request.thread_id);
    }
    let Ok(_permit) = ACTION.try_acquire() else {
        return Ok(json!({"busy":true,"queued":false}));
    };
    let config = match purpose {
        OwnerActionPurpose::Projection => cfg.private_projection,
        OwnerActionPurpose::AlertsRepair => cfg.alerts_repair,
    }
    .context("Fixed owner action is not configured")?;
    config.validate()?;
    if let Request::Inspect { ref invocation } = args {
        let record =
            app.shared
                .store
                .private_projection_status(purpose, human, key, &request.thread_id)?;
        anyhow::ensure!(
            record["current"]["invocation"] == invocation.as_str(),
            "Projection invocation changed"
        );
        if record["current"]["phase"] == "observed" {
            return Ok(record);
        }
        let (current, raw) = app.shared.store.private_projection_input(
            purpose,
            human,
            key,
            &request.thread_id,
            invocation,
        )?;
        anyhow::ensure!(
            current["descriptor"] == digest(&serde_json::to_vec(&config)?),
            "Projection adapter selection changed; inspect through original owning selection"
        );
        let outcome = execute_mode(
            &config,
            raw.as_bytes(),
            config.timeout_seconds,
            closed,
            true,
            purpose,
        )
        .await
        .unwrap_or_else(
            |_| json!({"phase":"unconfirmed","inspection_required":true,"automatic_retry":false}),
        );
        app.shared.store.private_projection_finish(
            purpose,
            human,
            key,
            &request.thread_id,
            invocation,
            outcome,
        )?;
        return app
            .shared
            .store
            .private_projection_status(purpose, human, key, &request.thread_id);
    }
    #[cfg(not(target_os = "linux"))]
    bail!("Private projection action requires the configured Linux owner");
    #[cfg(target_os = "linux")]
    if let Request::Run {
        return_id,
        batch_revision,
        task_revision,
        snapshot_sha256,
        reconciliation_sha256,
    } = args
    {
        let snapshot = bounded_file(&config.snapshot, 2 * 1024 * 1024)?;
        let receipt = bounded_file(&config.reconciliation, 256 * 1024)?;
        anyhow::ensure!(
            digest(&snapshot) == snapshot_sha256 && digest(&receipt) == reconciliation_sha256,
            "Projection input revision changed"
        );
        validate_reconciliation(&config, &receipt, &return_id)?;
        let descriptor = digest(&serde_json::to_vec(&config)?);
        let claim = app.shared.store.private_projection_claim(
            purpose,
            human,
            key,
            &request.thread_id,
            &request.turn_id,
            &return_id,
            &batch_revision,
            &config.task_id,
            &task_revision,
            &descriptor,
            &snapshot_sha256,
            &reconciliation_sha256,
            std::str::from_utf8(&snapshot)?,
        )?;
        if claim["claimed"] != true {
            return Ok(claim);
        }
        let invocation = claim["current"]["invocation"]
            .as_str()
            .context("Missing projection invocation")?;
        let deadline = claim["current"]["deadline_unix_ms"]
            .as_i64()
            .context("Missing projection deadline")?;
        let remaining = deadline.saturating_sub(Utc::now().timestamp_millis()) / 1000;
        let result = if remaining <= 0 {
            Err(anyhow!("Projection allocation expired"))
        } else {
            execute(
                &config,
                &snapshot,
                config.timeout_seconds.min(remaining as u64),
                closed,
                purpose,
            )
            .await
        };
        // Unknown/cancelled effects remain held; another return cannot replay them.
        let outcome = result.unwrap_or_else(
            |_| json!({"phase":"unconfirmed","inspection_required":true,"automatic_retry":false}),
        );
        app.shared.store.private_projection_finish(
            purpose,
            human,
            key,
            &request.thread_id,
            invocation,
            outcome.clone(),
        )?;
        return Ok(json!({"invocation":invocation,"outcome":outcome}));
    }
    unreachable!()
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    fn config(directory: &Path, program: &str) -> crate::interaction::PrivateProjectionConfig {
        crate::interaction::PrivateProjectionConfig {
            task_id: "intake".into(),
            command: vec!["/usr/bin/python3".into(), "-c".into(), program.into()],
            working_directory: directory.into(),
            snapshot: directory.join("source.json"),
            reconciliation: directory.join("cursor.json"),
            reconciliation_return_pointer: "/latest_check/heartbeat_return".into(),
            reconciliation_partial_pointer: "/latest_check/partial".into(),
            timeout_seconds: 2,
        }
    }

    #[test]
    fn private_projection_refuses_actor_selected_paths_and_symlink_inputs() {
        assert!(
            serde_json::from_value::<Request>(json!({"action":"status","command":["/bin/true"]}))
                .is_err()
        );
        let directory = tempfile::tempdir().unwrap();
        let source = directory.path().join("source.json");
        fs::write(&source, b"payload").unwrap();
        assert_eq!(bounded_file(&source, 7).unwrap(), b"payload");
        assert!(bounded_file(&source, 6).is_err());
        std::os::unix::fs::symlink(&source, directory.path().join("alias.json")).unwrap();
        assert!(bounded_file(&directory.path().join("alias.json"), 100).is_err());
        std::os::unix::fs::symlink(directory.path(), directory.path().join("parent")).unwrap();
        assert!(bounded_file(&directory.path().join("parent/source.json"), 100).is_err());
    }

    #[test]
    fn private_projection_requires_completed_exact_reconciliation() {
        let directory = tempfile::tempdir().unwrap();
        let config = config(directory.path(), "pass");
        let receipt = json!({"latest_check":{"heartbeat_return":"selected","partial":false}});
        assert!(
            validate_reconciliation(&config, &serde_json::to_vec(&receipt).unwrap(), "selected")
                .is_ok()
        );
        assert!(
            validate_reconciliation(&config, &serde_json::to_vec(&receipt).unwrap(), "different")
                .is_err()
        );
        for partial in [Value::Null, Value::Bool(true), json!("false")] {
            let mut changed = receipt.clone();
            changed["latest_check"]["partial"] = partial;
            assert!(
                validate_reconciliation(
                    &config,
                    &serde_json::to_vec(&changed).unwrap(),
                    "selected"
                )
                .is_err()
            );
        }
    }

    #[test]
    fn alerts_repair_requires_same_incident_higher_resolution_and_inspection_proof() {
        let snapshot = serde_json::to_vec(&json!({"schema":"daimon-alerts-repair-input/v1",
            "incident":{"id":"matrix-reader-1","resource_id":"matrix","revision":6}}))
        .unwrap();
        let receipt = json!({"schema":"daimon-alerts-owner-repair/v1","source_sha256":digest(&snapshot),
            "state":"resolved_verified","incident_id":"matrix-reader-1","incident_revision":6,
            "resource_id":"matrix","resolution_state":"resolved","resolution_revision":7,
            "operation_id":"repair-1","private_details":"must not escape"});
        let result = validate_repair_receipt(&receipt, &snapshot, false).unwrap();
        assert!(result.get("private_details").is_none());
        assert!(validate_repair_receipt(&receipt, &snapshot, true).is_err());
        for (key, wrong) in [
            ("incident_id", json!("other")),
            ("incident_revision", json!(5)),
            ("resource_id", json!("another")),
            ("resolution_state", json!("acknowledged")),
            ("resolution_revision", json!(6)),
            ("operation_id", json!("/private/path")),
            ("source_sha256", json!("wrong")),
        ] {
            let mut changed = receipt.clone();
            changed[key] = wrong;
            assert!(
                validate_repair_receipt(&changed, &snapshot, false).is_err(),
                "{key}"
            );
        }
        let mut inspected = receipt;
        inspected["state"] = json!("existing_resolution_verified");
        assert_eq!(
            validate_repair_receipt(&inspected, &snapshot, true).unwrap()["original_invocation_execution"],
            "not_established"
        );
        assert!(
            validate_repair_receipt(&json!({"state":"published_verified"}), &snapshot, false)
                .is_err()
        );
    }

    #[tokio::test]
    async fn alerts_repair_uses_existing_fixed_process_and_sanitized_receipt() {
        let directory = tempfile::tempdir().unwrap();
        let snapshot = serde_json::to_vec(&json!({"schema":"daimon-alerts-repair-input/v1",
            "incident":{"id":"reader-1","resource_id":"matrix","revision":1}}))
        .unwrap();
        let cfg = config(
            directory.path(),
            "import sys,json,hashlib; data=sys.stdin.buffer.read(); incident=json.loads(data)['incident']; print(json.dumps({'schema':'daimon-alerts-owner-repair/v1','state':'resolved_verified','source_sha256':hashlib.sha256(data).hexdigest(),'incident_id':incident['id'],'incident_revision':incident['revision'],'resource_id':incident['resource_id'],'resolution_state':'resolved','resolution_revision':2,'operation_id':'repair-1','extra':'private'}))",
        );
        let result = execute(
            &cfg,
            &snapshot,
            2,
            &CancellationToken::new(),
            OwnerActionPurpose::AlertsRepair,
        )
        .await
        .unwrap();
        assert_eq!(result["incident_id"], "reader-1");
        assert!(result.get("extra").is_none());
        assert!(
            execute(
                &cfg,
                &snapshot,
                2,
                &CancellationToken::new(),
                OwnerActionPurpose::Projection
            )
            .await
            .is_err()
        );
    }

    #[tokio::test]
    async fn private_projection_pins_stdin_sanitizes_environment_and_bounds_receipt() {
        let directory = tempfile::tempdir().unwrap();
        let selected = config(
            directory.path(),
            "import sys,json,hashlib,os,resource; data=sys.stdin.buffer.read(); assert 'RUSTC' not in os.environ; assert resource.getrlimit(resource.RLIMIT_AS)[1]<=1073741824; assert resource.getrlimit(resource.RLIMIT_CPU)[1]<=20; assert resource.getrlimit(resource.RLIMIT_NOFILE)[1]<=256; print(json.dumps({'state':'unchanged','source_sha256':hashlib.sha256(data).hexdigest(),'version_ref':'existing','not_a_receipt_field':'must not escape'}))",
        );
        let result = execute(
            &selected,
            b"{\"pinned\":true}",
            2,
            &CancellationToken::new(),
            OwnerActionPurpose::Projection,
        )
        .await
        .unwrap();
        assert_eq!(result["source_sha256"], digest(b"{\"pinned\":true}"));
        assert_eq!(result["version_ref"], "existing");
        assert!(result.get("not_a_receipt_field").is_none());
        let wrong = config(
            directory.path(),
            "import json; print(json.dumps({'state':'published_verified','source_sha256':'wrong'}))",
        );
        assert!(
            execute(
                &wrong,
                b"{}",
                2,
                &CancellationToken::new(),
                OwnerActionPurpose::Projection
            )
            .await
            .is_err()
        );
    }

    #[tokio::test]
    async fn private_projection_inspection_accepts_only_pinned_served_proof() {
        let directory = tempfile::tempdir().unwrap();
        let good = config(
            directory.path(),
            "import sys,json,hashlib; assert sys.argv[-1]=='--inspect-stdin'; data=sys.stdin.buffer.read(); print(json.dumps({'state':'existing_projection_verified','source_sha256':hashlib.sha256(data).hexdigest(),'artifact_ref':'own','version_ref':'version','immutable_files_match':True,'owner_broker_all_files_match':True,'checkpoint_matches':False}))",
        );
        let result = execute_mode(
            &good,
            b"{}",
            2,
            &CancellationToken::new(),
            true,
            OwnerActionPurpose::Projection,
        )
        .await
        .unwrap();
        assert_eq!(result["verification_only"], true);
        assert_eq!(result["original_invocation_execution"], "not_established");
        assert_eq!(result["checkpoint_matches"], false);
        let false_proof = config(
            directory.path(),
            "import sys,json,hashlib; data=sys.stdin.buffer.read(); print(json.dumps({'state':'existing_projection_verified','source_sha256':hashlib.sha256(data).hexdigest(),'artifact_ref':'own','version_ref':'version','immutable_files_match':True,'owner_broker_all_files_match':False}))",
        );
        assert!(
            execute_mode(
                &false_proof,
                b"{}",
                2,
                &CancellationToken::new(),
                true,
                OwnerActionPurpose::Projection
            )
            .await
            .is_err()
        );
    }

    #[tokio::test]
    async fn private_projection_cancellation_kills_owned_descendants_without_reaping_race() {
        let directory = tempfile::tempdir().unwrap();
        let config = config(
            directory.path(),
            "import subprocess,pathlib,time; p=subprocess.Popen(['sleep','30']); pathlib.Path('child.pid').write_text(str(p.pid)); time.sleep(30)",
        );
        let closed = CancellationToken::new();
        let task = execute(&config, b"{}", 2, &closed, OwnerActionPurpose::Projection);
        let observe = async {
            let until = tokio::time::Instant::now() + Duration::from_secs(1);
            while !directory.path().join("child.pid").exists() {
                assert!(tokio::time::Instant::now() < until);
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            closed.cancel();
        };
        let (result, _) = tokio::join!(task, observe);
        assert!(result.is_err());
        let pid = fs::read_to_string(directory.path().join("child.pid")).unwrap();
        for _ in 0..100 {
            let status = fs::read_to_string(format!("/proc/{pid}/stat"));
            if match &status {
                Err(_) => true,
                Ok(s) => s.split(") ").nth(1).unwrap().starts_with('Z'),
            } {
                return;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        panic!("Owned projection descendant remained running");
    }

    #[tokio::test]
    async fn private_projection_output_overflow_and_deadline_do_not_leave_running_work() {
        let directory = tempfile::tempdir().unwrap();
        for program in ["print('x'*9000)", "import time; time.sleep(30)"] {
            let cfg = config(directory.path(), program);
            assert!(
                execute(
                    &cfg,
                    b"{}",
                    1,
                    &CancellationToken::new(),
                    OwnerActionPurpose::Projection
                )
                .await
                .is_err()
            );
        }
    }
}
