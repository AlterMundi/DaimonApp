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
    let core = std::env::var("TELECODEX_TEST_CORE_BIN").expect("select built Core binary");
    let python = std::env::var("TELECODEX_TEST_PYTHON").expect("select Matrix test Python");
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("core-home");
    std::fs::create_dir(&home).unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let provider_port = listener.local_addr().unwrap().port();
    let provider = tokio::spawn(async move {
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
                    assert!(
                        body["tools"]
                            .as_array()
                            .is_none_or(|tools| tools.is_empty()),
                        "host tool ceiling must reach actual Core before provider submission"
                    );
                    break;
                }
            }
        }
        let events = [
            json!({"type":"response.created","response":{"id":"exact-response"}}),
            json!({"type":"response.output_item.done","item":{"type":"message","role":"assistant","id":"exact-answer","content":[{"type":"output_text","text":"Signed original handled"}]}}),
            json!({"type":"response.completed","response":{"id":"exact-response","usage":{"input_tokens":2,"output_tokens":1,"total_tokens":3}}}),
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
    });
    std::fs::write(
        home.join("config.toml"),
        format!(
            r#"
model = "bounded-fake"
model_provider = "test"
approval_policy = "never"
sandbox_mode = "read-only"
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
        .env("CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG", "1")
        .env_remove("OPENAI_API_KEY")
        .env_remove("CODEX_API_KEY")
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
                "permissions":":read-only","tools":[],"environment":{"PATH":"/usr/bin:/bin"},
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
        cwd: root.path().to_path_buf(),
        model: Some("bounded-fake".into()),
        reasoning_effort: None,
        service_tier: None,
        collaboration_mode: None,
        session_prompt: None,
        sandbox_mode: "read-only".into(),
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
    })).await.unwrap().unwrap_or_else(|error|panic!("actual composed receiving failed: {error:#}; owner report: {:?}; Core: {:?}",std::fs::read_to_string(&report),std::fs::read_to_string(root.path().join("core.stderr"))));
    assert_eq!(result.assistant_text, "Signed original handled");
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
    assert_eq!(receipt["observations"].as_array().unwrap().len(), 1);
    assert_eq!(receipt["observations"][0]["tokenUsage"]["totalTokens"], 3);
    assert_eq!(receipt["funding"]["spent"], 8);
    assert_eq!(receipt["funding"]["reserved"], 0);
    assert_eq!(receipt["funding"]["calls"], 1);
    provider.await.unwrap();
    server.kill().await.unwrap();
    server.wait().await.unwrap();
}
