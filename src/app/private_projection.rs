//! A fixed owner command for one offered Reports purpose, not a general shell.
//! Private custody remains on the host; the actor supplies only exact revisions.
use super::*;
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Status {},
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
async fn execute(
    config: &crate::interaction::PrivateProjectionConfig,
    snapshot: &[u8],
    seconds: u64,
    closed: &CancellationToken,
) -> Result<Value> {
    use std::os::fd::{AsRawFd, FromRawFd};
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut command = tokio::process::Command::new(&config.command[0]);
    command
        .args(&config.command[1..])
        .current_dir(&config.working_directory);
    command
        .env_clear()
        .env("PATH", "/usr/local/bin:/usr/bin:/bin")
        .env("LANG", "C.UTF-8");
    // The fixed host adapter needs its existing owner binding, never provider secrets.
    for name in ["HOME"] {
        if let Some(value) = std::env::var_os(name) {
            command.env(name, value);
        }
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
            value["source_sha256"] == digest(snapshot)
                && matches!(
                    value["state"].as_str(),
                    Some("unchanged" | "published_verified")
                ),
            "Projection receipt does not identify pinned input"
        );
        // Copy selected receipt fields only, never arbitrary command output.
        Ok(
            json!({"phase":"observed","state":value["state"],"source_sha256":value["source_sha256"],"artifact_ref":value["artifact_ref"],"version_ref":value["version_ref"]}),
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

pub(super) async fn tool(
    app: &App,
    key: SessionKey,
    human: i64,
    request: &crate::codex::DynamicToolRequest,
    args: Value,
    closed: &CancellationToken,
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
            .private_projection_status(human, key, &request.thread_id);
    }
    let config = cfg
        .private_projection
        .context("Private projection action is not configured")?;
    config.validate()?;
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
            )
            .await
        };
        // Unknown/cancelled effects remain held; another return cannot replay them.
        let outcome = result.unwrap_or_else(
            |_| json!({"phase":"unconfirmed","inspection_required":true,"automatic_retry":false}),
        );
        app.shared.store.private_projection_finish(
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
            execute(&wrong, b"{}", 2, &CancellationToken::new())
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
        let task = execute(&config, b"{}", 2, &closed);
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
                execute(&cfg, b"{}", 1, &CancellationToken::new())
                    .await
                    .is_err()
            );
        }
    }
}
