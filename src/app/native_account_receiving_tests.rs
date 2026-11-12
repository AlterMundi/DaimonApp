//! Explicit opt-in actual Core + App client + existing Matrix owner journey.
use super::*;
use crate::codex::{CodexEvent, CodexEventOutcome, CodexRunner, NativeToolOutput};
use crate::config::SearchMode;
use crate::interaction::{MatrixDestination, MatrixTransportConfig};
use crate::models::{SessionKey, SessionRecord, TurnRequest};
use std::os::unix::fs::PermissionsExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[tokio::test]
#[ignore = "requires an explicitly selected built Core binary and Matrix test checkout"]
async fn actual_core_usage_reaches_existing_app_owner_and_signed_journal() {
    actual_core_owner_journey(false).await;
}

#[tokio::test]
#[ignore = "requires the owner-enabled Core/standalone executor and Matrix test checkout"]
async fn actual_core_process_owner_dispatches_tool_and_retains_signed_usage() {
    actual_core_owner_journey(true).await;
}

async fn actual_core_owner_journey(process_owner: bool) {
    let core = std::env::var("TELECODEX_TEST_CORE_BIN").expect("select built Core binary");
    let python = std::env::var("TELECODEX_TEST_PYTHON").expect("select Matrix test Python");
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("core-home");
    std::fs::create_dir(&home).unwrap();
    let workspace = root.path().join("owned-work");
    std::fs::create_dir(&workspace).unwrap();
    let outside = root.path().join("unselected-private");
    std::fs::write(&outside, "synthetic-outside-private").unwrap();
    let artifact = workspace.join("useful-result.txt");
    if process_owner {
        std::fs::write(
            workspace.join("AGENTS.md"),
            "Owned startup fixture instructions.",
        )
        .unwrap();
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let provider_port = listener.local_addr().unwrap().port();
    let credential = home.join("fake-provider-credential");
    std::fs::write(&credential, "synthetic-private-provider").unwrap();
    let script = format!(
        "import os\nassert 'codex-owned-exec-' in os.environ['HOME']\nassert os.environ['HOME']!=os.environ['CODEX_HOME']\ntry:\n os.listdir(os.environ['CODEX_HOME'])\nexcept OSError:\n pass\nelse:\n raise AssertionError('executor control readable')\nassert 'BOUNDED_FIXTURE_AMBIENT' not in os.environ\nfor denied in [{}, {}, '/usr/bin/true', '/bin/true']:\n try:\n  open(denied).read()\n except OSError:\n  pass\n else:\n  raise AssertionError('unselected private root readable')\nwith open({}, 'x') as result:\n result.write('one owned useful action')\nprint('owned-tool-accepted')\n",
        json!(credential.to_string_lossy()),
        json!(outside.to_string_lossy()),
        json!(artifact.to_string_lossy())
    );
    use base64::Engine as _;
    let encoded = base64::engine::general_purpose::STANDARD.encode(script.as_bytes());
    let tool_arguments = json!({"cmd":format!("/usr/bin/python3 -c 'import base64; exec(base64.b64decode(\"{encoded}\"))'"),"yield_time_ms":1000,"max_output_tokens":500}).to_string();
    let attempts = if process_owner { 2 } else { 1 };
    let provider = tokio::spawn(async move {
        for index in 0..attempts {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = Vec::new();
            let mut block = [0; 8192];
            loop {
                let n = stream.read(&mut block).await.unwrap();
                assert!(n > 0);
                request.extend_from_slice(&block[..n]);
                assert!(request.len() <= 1024 * 1024);
                if let Some(end) = request.windows(4).position(|v| v == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..end]).to_lowercase();
                    assert!(headers.starts_with("post /responses "));
                    let length: usize = headers
                        .lines()
                        .find_map(|line| line.strip_prefix("content-length:"))
                        .unwrap()
                        .trim()
                        .parse()
                        .unwrap();
                    if request.len() >= end + 4 + length {
                        let body: Value =
                            serde_json::from_slice(&request[end + 4..end + 4 + length]).unwrap();
                        assert_eq!(body["max_output_tokens"], 200);
                        if process_owner {
                            assert!(
                                body.to_string()
                                    .contains("Owned startup fixture instructions.")
                            );
                            assert!(!body.to_string().contains("synthetic-private-provider"));
                            assert!(!body.to_string().contains("synthetic-outside-private"));
                            assert!(
                                body["tools"].to_string().contains("exec_command"),
                                "selected tool missing from actual native request"
                            );
                            if index == 1 {
                                assert!(
                                    body["input"].to_string().contains("owned-tool-accepted"),
                                    "actual registry/handler did not return the owned tool result: {:?}",
                                    body["input"].as_array().map(|items| items
                                        .iter()
                                        .filter(|item| item["type"] == "function_call_output")
                                        .collect::<Vec<_>>())
                                );
                            }
                        } else {
                            assert!(
                                body["tools"]
                                    .as_array()
                                    .is_none_or(|tools| tools.is_empty()),
                                "host ceiling must reach actual Core before provider submission"
                            );
                        }
                        break;
                    }
                }
            }
            let response_id = format!("exact-response-{index}");
            let item = if process_owner && index == 0 {
                json!({"type":"function_call","id":"exact-tool-item","call_id":"exact-owned-tool","name":"exec_command","arguments":tool_arguments})
            } else {
                json!({"type":"message","role":"assistant","id":"exact-answer","content":[{"type":"output_text","text":"Signed original handled"}]})
            };
            let events = [
                json!({"type":"response.created","response":{"id":response_id}}),
                json!({"type":"response.output_item.done","item":item}),
                json!({"type":"response.completed","response":{"id":response_id,"usage":{"input_tokens":2,"output_tokens":1,"total_tokens":3}}}),
            ];
            let body: String = events
                .iter()
                .map(|event| format!("data: {event}\n\n"))
                .collect();
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).await.unwrap();
        }
    });
    let sandbox = if process_owner {
        "workspace-write"
    } else {
        "read-only"
    };
    let permission_profile = if process_owner {
        format!(
            "[permissions.funded.filesystem]\n\"/usr\" = \"read\"\n\"/bin\" = \"read\"\n\"/lib\" = \"read\"\n\"/lib64\" = \"read\"\n\"/etc\" = \"read\"\n\"/usr/bin/true\" = \"deny\"\n{} = \"read\"\n{} = \"write\"\n",
            json!(
                std::path::Path::new(&core)
                    .with_file_name("codex-exec-server")
                    .to_string_lossy()
            ),
            json!(workspace.to_string_lossy())
        )
    } else {
        String::new()
    };
    std::fs::write(
        home.join("config.toml"),
        format!(
            r#"
model = "bounded-fake"
model_provider = "test"
approval_policy = "never"
sandbox_mode = "{sandbox}"
{permission_profile}
[model_providers.test]
name = "Synthetic local receiving fixture"
base_url = "http://127.0.0.1:{provider_port}"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
"#
        ),
    )
    .unwrap();
    let port_guard = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = port_guard.local_addr().unwrap().port();
    drop(port_guard);
    let mut server = Command::new(&core)
        .args([
            "--listen",
            &format!("ws://127.0.0.1:{port}"),
            "--disable-plugin-startup-tasks-for-tests",
        ])
        .env("CODEX_HOME", &home)
        .env("BOUNDED_FIXTURE_AMBIENT", "synthetic-ambient-only")
        .env("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")
        .env_remove("OPENAI_API_KEY")
        .env_remove("CODEX_API_KEY")
        .env_remove("CODEX_ACCESS_TOKEN")
        .stdout(std::process::Stdio::null())
        .stderr(std::fs::File::create(root.path().join("core.stderr")).unwrap())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let ready = Instant::now() + Duration::from_secs(15);
    loop {
        if tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .is_ok()
        {
            break;
        }
        assert!(
            Instant::now() < ready,
            "actual Core did not become ready: {:?}",
            server.try_wait()
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let proxy = root.path().join("proxy");
    std::fs::write(
        &proxy,
        format!(
            r#"#!/usr/bin/env python3
import os,socket,sys,threading
assert sys.argv[1:]==['app-server','proxy']
s=socket.create_connection(('127.0.0.1',{port}),timeout=30)
def upload():
 while True:
  data=os.read(0,8192)
  if not data: return
  s.sendall(data)
threading.Thread(target=upload,daemon=True).start()
while True:
 data=s.recv(8192)
 if not data: break
 os.write(1,data)
"#
        ),
    )
    .unwrap();
    std::fs::set_permissions(&proxy, std::fs::Permissions::from_mode(0o700)).unwrap();
    let report = root.path().join("report.json");
    let config = MatrixTransportConfig {
        command: vec![
            python,
            "-B".into(),
            format!(
                "{}/tests/native_account_owner_fixture.py",
                env!("CARGO_MANIFEST_DIR")
            ),
            report.to_string_lossy().into(),
        ],
        source: MatrixDestination::Body {
            being_ref: format!("dm:being:v1:{}", "A".repeat(43)),
            embodiment_id: "embodiment:synthetic".into(),
        },
        timeout_seconds: 5,
        native_funding_binding: Some("synthetic-test-selection".into()),
        native_host_restrictions: Some(
            serde_json::from_value(json!({
                "processLimits":if process_owner {json!({"memoryBytes":536870912,"cpuPercent":50,"tasks":128})}else{Value::Null},
                "permissions":if process_owner {"funded"}else{":read-only"},"tools":if process_owner {json!([{"name":"exec_command","namespace":"functions"}])}else{json!([])},"environment":{"PATH":"/usr/bin:/bin"},
                "codeModeLimits":{"maxHeapSizeBytes":33554432,"maxYieldTimeMs":1000}
            }))
            .unwrap(),
        ),
    };
    let key = SessionKey {
        chat_id: 1,
        thread_id: 2,
    };
    let session = SessionRecord {
        id: 1,
        key,
        session_title: None,
        codex_thread_id: None,
        force_fresh_thread: false,
        updated_at: "2026-11-11T00:00:00Z".into(),
        cwd: if process_owner {
            workspace.clone()
        } else {
            root.path().to_path_buf()
        },
        model: Some("bounded-fake".into()),
        reasoning_effort: None,
        service_tier: None,
        collaboration_mode: None,
        session_prompt: None,
        sandbox_mode: sandbox.into(),
        approval_policy: "never".into(),
        search_mode: SearchMode::Disabled,
        add_dirs: vec![],
        busy: false,
    };
    let request = TurnRequest {
        session_key: key,
        from_user_id: 1,
        prompt: String::new(),
        runtime_instructions: None,
        attachments: vec![],
        review_mode: None,
        override_search_mode: None,
    };
    let state = Arc::new(tokio::sync::Mutex::new((None::<String>, None::<Session>)));
    let receiving = state.clone();
    let runner = CodexRunner::new(proxy)
        .with_shared_app_server(true)
        .with_idle_only(true)
        .with_tool_output(NativeToolOutput {
            name: "heartbeat_attention".into(),
            namespace: None,
            output: "One signed synthetic original; no real peer or account".into(),
            retain: true,
        });
    let (_send, receive) = tokio::sync::mpsc::unbounded_channel();
    let result=tokio::time::timeout(Duration::from_secs(30),runner.run_turn(&session,&request,CancellationToken::new(),receive,move |event| {
        let state=receiving.clone();let config=config.clone();
        async move {
            let mut state=state.lock().await;
            match event {
                CodexEvent::ThreadStarted(thread)=>{state.0=Some(thread);Ok(CodexEventOutcome::None)}
                CodexEvent::NativeTurnSubmitting=>{
                    let start=json!({"thread_id":state.0,"parent_allowance":{"maxProviderAttempts":2,"maxRequestBytes":1024*1024,"deadlineUnixMs":Utc::now().timestamp_millis()+7000}});
                    let owner=Session::start(&config,&start).await?;
                    let descriptor=owner.descriptor.clone();let host_restrictions=owner.host_restrictions.clone();state.1=Some(owner);
                    Ok(CodexEventOutcome::FundedInferenceAllowance {allowance:descriptor.allowance,cycle_id:descriptor.provider_reservation_cycle_id,max_output_tokens:descriptor.max_output_tokens,host_restrictions})
                }
                CodexEvent::NativeProviderAttemptReservation(attempt)=>Ok(CodexEventOutcome::ProviderAttemptReserved(state.1.as_mut().unwrap().reserve(attempt).await?)),
                CodexEvent::NativeProviderAttemptUsage(usage)=>Ok(CodexEventOutcome::ProviderUsageRecorded(state.1.as_mut().unwrap().record_usage(usage).await?)),
                CodexEvent::NativeTurnStarted(turn)=>{state.1.as_mut().unwrap().bind(&turn).await?;Ok(CodexEventOutcome::None)}
                _=>Ok(CodexEventOutcome::None),
            }
        }
    })).await.unwrap().unwrap_or_else(|error|panic!("actual composed receiving failed: {error:#}; phase: {:?}; owner report: {:?}; Core: {:?}",state.try_lock().ok().map(|s| (s.0.is_some(), s.1.is_some(), s.1.as_ref().is_some_and(|owner| owner.bound.is_some()))),std::fs::read_to_string(&report),std::fs::read_to_string(root.path().join("core.stderr"))));
    assert_eq!(result.assistant_text, "Signed original handled");
    if process_owner {
        assert_eq!(
            std::fs::read_to_string(&artifact).unwrap(),
            "one owned useful action"
        );
    }
    let mut state = state.lock().await;
    let owner = state.1.as_mut().unwrap();
    let reply = owner
        .exchange(
            json!({"operation":"reconcile","cycleId":owner.descriptor.provider_reservation_cycle_id,
        "nativeTurnId":owner.bound,"outcome":"completed","effectsReconciled":true}),
        )
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&reply).unwrap()["reconciled"],
        "completed"
    );
    owner.child.wait().await.unwrap();
    let receipt: Value = serde_json::from_slice(&std::fs::read(&report).unwrap()).unwrap();
    assert_eq!(receipt["cycle"]["state"], "completed");
    assert_eq!(receipt["observations"].as_array().unwrap().len(), attempts);
    assert_eq!(receipt["observations"][0]["tokenUsage"]["totalTokens"], 3);
    assert_eq!(receipt["funding"]["spent"], 8 * attempts);
    assert_eq!(receipt["funding"]["reserved"], 0);
    assert_eq!(receipt["funding"]["calls"], attempts);
    provider.await.unwrap();
    server.kill().await.unwrap();
    server.wait().await.unwrap();
}
