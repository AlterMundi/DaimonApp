//! One configured host child owns a financial capability for this native turn.
//! No account choice, signing key or balance is accepted from model traffic.
use super::*;
use crate::codex::{NativeInferenceAllowance, NativeProviderAttemptReservation};
use serde::Deserialize;
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::time::Instant;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Descriptor {
    pub thread_id: String,
    pub provider_reservation_cycle_id: String,
    pub allowance: NativeInferenceAllowance,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Ready {
    ready: Descriptor,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Reserved {
    cycle_id: String,
    attempt_id: String,
    authorized: bool,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Bound {
    cycle_id: String,
    bound: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Reconciled {
    cycle_id: String,
    reconciled: String,
}

pub(super) struct Session {
    // Never reap the leader before killing this exact owned group: its PID
    // cannot be reused while the unreaped child still owns it.
    group: Option<super::matrix::OwnedMatrixCommand>,
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    pub descriptor: Descriptor,
    deadline: Instant,
    io_timeout: Duration,
    closed: bool,
    bound: Option<String>,
}
impl Drop for Session {
    fn drop(&mut self) {
        drop(self.group.take());
        let _ = self.child.start_kill();
    }
}
async fn read(stdout: &mut BufReader<ChildStdout>) -> Result<Vec<u8>> {
    let mut raw = Vec::new();
    loop {
        let bytes = stdout.fill_buf().await?;
        anyhow::ensure!(
            !bytes.is_empty(),
            "Native account owner closed; inspect retained cycle"
        );
        let end = bytes.iter().position(|byte| *byte == b'\n');
        let count = end.map_or(bytes.len(), |end| end + 1);
        anyhow::ensure!(
            raw.len() + count <= 65536,
            "Native account reply exceeds bound"
        );
        raw.extend_from_slice(&bytes[..count]);
        stdout.consume(count);
        if end.is_some() {
            return Ok(raw);
        }
    }
}
async fn write(stdin: &mut ChildStdin, value: &Value) -> Result<()> {
    let mut raw = serde_json::to_vec(value)?;
    raw.push(b'\n');
    anyhow::ensure!(raw.len() <= 65536, "Native account command exceeds bound");
    stdin.write_all(&raw).await?;
    stdin.flush().await?;
    Ok(())
}
impl Session {
    pub async fn start(
        config: &crate::interaction::MatrixTransportConfig,
        start: &Value,
    ) -> Result<Self> {
        use std::os::unix::process::CommandExt;
        use std::process::Stdio;
        let funding = config
            .native_funding_binding
            .as_ref()
            .context("Native account binding absent")?;
        let parent: NativeInferenceAllowance =
            serde_json::from_value(start["parent_allowance"].clone())?;
        parent.validate()?;
        let thread = start["thread_id"]
            .as_str()
            .context("Native account thread absent")?;
        let wall = Utc::now().timestamp_millis();
        let mono = Instant::now();
        let remaining = parent
            .deadline_unix_ms
            .checked_sub(wall)
            .filter(|ms| *ms > 0)
            .context("Native account parent expired")?;
        let deadline = mono + Duration::from_millis(remaining as u64);
        let io_timeout = Duration::from_secs(config.timeout_seconds);
        let mut command = Command::new(&config.command[0]);
        command
            .args(&config.command[1..])
            .arg("--native-owner")
            .arg("--funding-binding")
            .arg(funding);
        command.env(
            "DAIMON_MATRIX_HOST_DEADLINE_MS",
            (wall + config.timeout_seconds as i64 * 1000).to_string(),
        );
        command.as_std_mut().process_group(0);
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        let mut child = command.spawn().context("Native account host unavailable")?;
        let group = super::matrix::OwnedMatrixCommand(
            child.id().context("Native account host PID absent")?,
        );
        let mut stdin = child.stdin.take().context("Native account input absent")?;
        let mut stdout = BufReader::new(
            child
                .stdout
                .take()
                .context("Native account output absent")?,
        );
        let ready = tokio::time::timeout_at(std::cmp::min(deadline, mono + io_timeout), async {
            write(&mut stdin, start).await?;
            Ok::<Ready, anyhow::Error>(serde_json::from_slice(&read(&mut stdout).await?)?)
        })
        .await
        .context("Native account startup expired; no automatic retry")??
        .ready;
        ready.allowance.validate()?;
        anyhow::ensure!(
            ready.thread_id == thread
                && Uuid::parse_str(&ready.provider_reservation_cycle_id)
                    .is_ok_and(|id| id.to_string() == ready.provider_reservation_cycle_id)
                && ready.allowance.max_provider_attempts <= parent.max_provider_attempts
                && ready.allowance.max_request_bytes <= parent.max_request_bytes
                && ready.allowance.deadline_unix_ms <= parent.deadline_unix_ms,
            "Native account descriptor differs from inherited reservation"
        );
        let selected = ready
            .allowance
            .deadline_unix_ms
            .checked_sub(wall)
            .filter(|ms| *ms > 0)
            .context("Native account selection expired")?;
        let deadline = std::cmp::min(deadline, mono + Duration::from_millis(selected as u64));
        Ok(Self {
            group: Some(group),
            child,
            stdin,
            stdout,
            descriptor: ready,
            deadline,
            io_timeout,
            closed: false,
            bound: None,
        })
    }
    async fn exchange(&mut self, frame: Value) -> Result<Vec<u8>> {
        anyhow::ensure!(
            !self.closed,
            "Native account exchange is uncertain; never replay"
        );
        // A dropped/cancelled future keeps this fence set. Late output cannot
        // become the acknowledgment of another operation.
        self.closed = true;
        let limit = std::cmp::min(self.deadline, Instant::now() + self.io_timeout);
        let result = tokio::time::timeout_at(limit, async {
            write(&mut self.stdin, &frame).await?;
            read(&mut self.stdout).await
        })
        .await
        .context("Native account reply expired; inspect original cycle")??;
        self.closed = false;
        Ok(result)
    }
    pub async fn reserve(&mut self, request: NativeProviderAttemptReservation) -> Result<bool> {
        let cycle = self.descriptor.provider_reservation_cycle_id.clone();
        anyhow::ensure!(
            request.thread_id == self.descriptor.thread_id && request.cycle_id == cycle,
            "Native account request owner changed"
        );
        let attempt = request.attempt_id.clone();
        let frame = json!({"operation":"reserve","params":{"threadId":request.thread_id,
            "cycleId":request.cycle_id,"attemptId":request.attempt_id,"ordinal":request.ordinal,
            "maxRequestBytes":request.max_request_bytes,"deadlineUnixMs":request.deadline_unix_ms}});
        let result = self.exchange(frame).await;
        let validated = result.and_then(|value| {
            let reply: Reserved = serde_json::from_slice(&value)?;
            anyhow::ensure!(
                reply.cycle_id == cycle && reply.attempt_id == attempt,
                "Native account reply correlation changed"
            );
            Ok(reply.authorized)
        });
        if !matches!(validated, Ok(true)) {
            self.closed = true;
        }
        validated
    }
    pub async fn not_started(&mut self) -> Result<()> {
        anyhow::ensure!(self.bound.is_none(), "Native turn already bound");
        let cycle = self.descriptor.provider_reservation_cycle_id.clone();
        let reply = self
            .exchange(json!({"operation":"reconcile","cycleId":cycle,
            "nativeTurnId":Value::Null,"outcome":"not_started","effectsReconciled":true}))
            .await?;
        // This is terminal even if its reply is malformed: never retry it.
        self.closed = true;
        let reply: Reconciled = serde_json::from_slice(&reply)?;
        anyhow::ensure!(
            reply.cycle_id == cycle && reply.reconciled == "not_started",
            "Native non-submission reconciliation changed"
        );
        Ok(())
    }
    pub async fn bind_or_cancel(&mut self, physical: &str, cancel: &CancellationToken) -> bool {
        let bound = tokio::select! {
            biased;
            _ = cancel.cancelled() => false,
            result = self.bind(physical) => result.is_ok(),
        };
        if !bound {
            self.closed = true;
            // Return to the native loop so its existing exact-turn interrupt
            // can run. This requests cancellation; it never proves a stop.
            cancel.cancel();
        }
        bound
    }
    pub async fn bind(&mut self, physical: &str) -> Result<()> {
        if let Some(bound) = &self.bound {
            anyhow::ensure!(
                bound == physical && !self.closed,
                "Native account physical owner changed"
            );
            return Ok(());
        }
        let cycle = self.descriptor.provider_reservation_cycle_id.clone();
        let result = self
            .exchange(json!({"operation":"bind","cycleId":cycle,"nativeTurnId":physical}))
            .await?;
        let result: Bound = match serde_json::from_slice(&result) {
            Ok(result) => result,
            Err(error) => {
                self.closed = true;
                return Err(error.into());
            }
        };
        if result.bound != physical || result.cycle_id != cycle {
            self.closed = true;
            bail!("Native account binding reply changed");
        }
        self.bound = Some(physical.into());
        Ok(())
    }
}

pub(super) fn configured(
    shared: &AppShared,
) -> Result<
    Option<(
        &crate::interaction::MatrixTransportConfig,
        crate::store::HeartbeatInboxSource,
    )>,
> {
    let Some(profile) = shared.config.interaction.as_ref() else {
        return Ok(None);
    };
    let Some(transport) = profile
        .matrix_transport
        .as_ref()
        .filter(|t| t.native_funding_binding.is_some())
    else {
        return Ok(None);
    };
    let crate::interaction::MatrixDestination::Body {
        being_ref,
        embodiment_id,
    } = &transport.source
    else {
        bail!("Financial owner requires current body source");
    };
    let channel = profile
        .matrix_inbox_channel
        .as_ref()
        .context("Financial owner requires selected native inbox")?;
    Ok(Some((
        transport,
        crate::store::HeartbeatInboxSource {
            source: crate::store::MatrixAuthor {
                being_ref: being_ref.clone(),
                embodiment_id: embodiment_id.clone(),
            },
            channel_id: channel.clone(),
        },
    )))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::interaction::{MatrixDestination, MatrixTransportConfig};
    fn fixture(mode: &str, path: &Path) -> (MatrixTransportConfig, Value) {
        let code = r#"import sys,json,time
mode,path=sys.argv[1:3]
start=json.loads(sys.stdin.readline())
allowance=start['parent_allowance'].copy()
if mode=='larger': allowance['maxProviderAttempts']+=1
cycle='58963816-596f-4ec0-8122-9769b34887e7'
print(json.dumps({'ready':{'threadId':start['thread_id'],'providerReservationCycleId':cycle,'allowance':allowance}}),flush=True)
for line in sys.stdin:
 f=json.loads(line)
 with open(path,'a') as log: log.write(f['operation']+'\n')
 if mode=='lost': time.sleep(3)
 if f['operation']=='reconcile':
  print(json.dumps({'reconciled':('wrong' if mode=='bad-reconcile' else 'not_started'),'cycleId':cycle}),flush=True)
 elif f['operation']=='bind':
  print(json.dumps({'bound':('wrong' if mode=='bad-bind' else f['nativeTurnId']),'cycleId':cycle}),flush=True)
 else:
  p=f['params']; reply={'cycleId':cycle,'attemptId':p['attemptId'],'authorized':True}
  if mode=='wrong': reply['attemptId']='2f699de7-c1ba-4cc0-af09-e2b53aeec2ae'
  if mode=='duplicate':
   print('{"cycleId":"'+cycle+'","cycleId":"'+cycle+'","attemptId":"'+p['attemptId']+'","authorized":true}',flush=True)
  elif mode=='oversize': print('x'*65537,flush=True)
  else: print(json.dumps(reply),flush=True)
"#;
        let config = MatrixTransportConfig {
            command: vec![
                "python3".into(),
                "-B".into(),
                "-c".into(),
                code.into(),
                mode.into(),
                path.to_string_lossy().into(),
            ],
            source: MatrixDestination::Body {
                being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
                embodiment_id: "embodiment:source".into(),
            },
            timeout_seconds: 1,
            native_funding_binding: Some("/private/selected-funding.json".into()),
        };
        let start = json!({"thread_id":"observed-native","parent_allowance":{
            "maxProviderAttempts":2,"maxRequestBytes":512,"deadlineUnixMs":Utc::now().timestamp_millis()+5000}});
        (config, start)
    }
    fn request(owner: &Session) -> NativeProviderAttemptReservation {
        NativeProviderAttemptReservation {
            thread_id: owner.descriptor.thread_id.clone(),
            cycle_id: owner.descriptor.provider_reservation_cycle_id.clone(),
            attempt_id: Uuid::now_v7().to_string(),
            ordinal: 1,
            max_request_bytes: owner.descriptor.allowance.max_request_bytes,
            deadline_unix_ms: owner.descriptor.allowance.deadline_unix_ms,
        }
    }
    #[tokio::test]
    async fn owner_pipe_correlates_exact_attempt_and_binds_only_once() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("writes");
        let (config, start) = fixture("ok", &path);
        let mut owner = Session::start(&config, &start).await.unwrap();
        let physical = Uuid::now_v7().to_string();
        owner.bind(&physical).await.unwrap();
        owner.bind(&physical).await.unwrap();
        assert!(owner.reserve(request(&owner)).await.unwrap());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "bind\nreserve\n");
    }
    #[tokio::test]
    async fn owner_not_started_is_exact_and_never_repeated() {
        for mode in ["ok", "bad-reconcile"] {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("writes");
            let (config, start) = fixture(mode, &path);
            let mut owner = Session::start(&config, &start).await.unwrap();
            assert_eq!(owner.not_started().await.is_ok(), mode == "ok");
            assert!(owner.not_started().await.is_err());
            assert_eq!(std::fs::read_to_string(&path).unwrap(), "reconcile\n");
        }
    }
    #[tokio::test]
    async fn owner_bind_cancellation_and_failure_yield_to_native_interrupt() {
        for mode in ["lost", "bad-bind"] {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("writes");
            let (mut config, start) = fixture(mode, &path);
            config.timeout_seconds = 60;
            let mut owner = Session::start(&config, &start).await.unwrap();
            let cancel = CancellationToken::new();
            let control = cancel.clone();
            let observed = path.clone();
            let cancelling = tokio::spawn(async move {
                if mode == "lost" {
                    let deadline = Instant::now() + Duration::from_secs(1);
                    while !observed.exists() && Instant::now() < deadline {
                        tokio::time::sleep(Duration::from_millis(5)).await;
                    }
                    assert!(observed.exists());
                    control.cancel();
                }
            });
            assert!(
                !tokio::time::timeout(
                    Duration::from_secs(2),
                    owner.bind_or_cancel(&Uuid::now_v7().to_string(), &cancel)
                )
                .await
                .unwrap()
            );
            cancelling.await.unwrap();
            assert!(cancel.is_cancelled());
            assert!(owner.reserve(request(&owner)).await.is_err());
            assert_eq!(std::fs::read_to_string(&path).unwrap(), "bind\n");
        }
    }
    #[tokio::test]
    async fn owner_pipe_refuses_larger_inherited_allowance_before_requests() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("writes");
        let (config, start) = fixture("larger", &path);
        assert!(Session::start(&config, &start).await.is_err());
        assert!(!path.exists());
    }
    #[tokio::test]
    async fn owner_pipe_bad_reply_permanently_fences_without_another_write() {
        for mode in ["wrong", "duplicate", "oversize"] {
            let temp = tempfile::tempdir().unwrap();
            let path = temp.path().join("writes");
            let (config, start) = fixture(mode, &path);
            let mut owner = Session::start(&config, &start).await.unwrap();
            assert!(owner.reserve(request(&owner)).await.is_err());
            assert!(owner.reserve(request(&owner)).await.is_err());
            assert_eq!(std::fs::read_to_string(&path).unwrap(), "reserve\n");
        }
    }
    #[tokio::test]
    async fn owner_pipe_dropped_wait_retains_fence_and_kills_only_its_child() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("writes");
        let (config, start) = fixture("lost", &path);
        let mut owner = Session::start(&config, &start).await.unwrap();
        let pid = owner.child.id().unwrap();
        let packet = request(&owner);
        assert!(
            tokio::time::timeout(Duration::from_millis(150), owner.reserve(packet))
                .await
                .is_err()
        );
        assert!(owner.reserve(request(&owner)).await.is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "reserve\n");
        drop(owner);
        let deadline = Instant::now() + Duration::from_secs(2);
        while unsafe { libc::kill(pid as i32, 0) } == 0 && Instant::now() < deadline {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert_ne!(unsafe { libc::kill(pid as i32, 0) }, 0);
    }
}
