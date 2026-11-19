use super::*;
use tokio::net::{TcpListener, TcpStream};

type Socket = WebSocketStream<TcpStream>;
const LOGIN_ID: &str = "test-device-login";

async fn request(socket: &mut Socket, method: &str) -> Value {
    let value: Value =
        serde_json::from_str(socket.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
    assert_eq!(value["method"], method);
    value
}

async fn send(socket: &mut Socket, value: Value) {
    socket
        .send(WsMessage::Text(value.to_string().into()))
        .await
        .unwrap();
}

async fn response(socket: &mut Socket, request: &Value, result: Value) {
    send(socket, json!({"id":request["id"],"result":result})).await;
}

async fn accept(listener: &TcpListener) -> Socket {
    let (stream, _) = listener.accept().await.unwrap();
    let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
    let init = request(&mut socket, "initialize").await;
    response(&mut socket, &init, json!({})).await;
    request(&mut socket, "initialized").await;
    socket
}

async fn fixture() -> (tempfile::TempDir, CodexRunner, TcpListener) {
    let root = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    // This executable rejects every external CLI command, including login/status.
    let binary =
        super::super::tests::proxy_fixture(root.path(), listener.local_addr().unwrap().port());
    (
        root,
        CodexRunner::new(binary).with_shared_app_server(true),
        listener,
    )
}

fn current_account() -> Value {
    json!({"account":{"type":"chatgpt","email":"selected@example.test","planType":"pro"},"requiresOpenaiAuth":true})
}

async fn begin(socket: &mut Socket, early_update: bool) {
    let start = request(socket, "account/login/start").await;
    assert_eq!(start["params"], json!({"type":"chatgptDeviceCode"}));
    if early_update {
        update(socket, Value::String("chatgpt".into())).await;
    }
    response(
        socket,
        &start,
        json!({"type":"chatgptDeviceCode","loginId":LOGIN_ID,
        "verificationUrl":"https://auth.openai.com/codex/device","userCode":"ABCD-EFGH"}),
    )
    .await;
}

async fn update(socket: &mut Socket, mode: Value) {
    send(
        socket,
        json!({"method":"account/updated","params":{"authMode":mode,"planType":"pro"}}),
    )
    .await;
}

async fn complete(socket: &mut Socket, id: &str, success: bool) {
    send(socket, json!({"method":"account/login/completed","params":{
        "loginId":id,"success":success,"error":if success {Value::Null}else {json!("PRIVATE_PROVIDER_DETAIL")}}})).await;
}

#[tokio::test]
async fn shared_status_observes_native_server_without_refresh_or_cli() {
    let (_root, runner, listener) = fixture().await;
    let server = tokio::spawn(async move {
        let mut socket = accept(&listener).await;
        let read = request(&mut socket, "account/read").await;
        assert_eq!(read["params"], json!({"refreshToken":false}));
        response(&mut socket, &read, current_account()).await;
    });
    let status = runner.account_status().await.unwrap();
    assert!(status.authenticated);
    assert!(status.detail.contains("selected@example.test"));
    server.await.unwrap();
}

#[tokio::test]
async fn shared_logout_requires_native_readback() {
    for still_signed_in in [false, true] {
        let (_root, runner, listener) = fixture().await;
        let server = tokio::spawn(async move {
            let mut socket = accept(&listener).await;
            let logout = request(&mut socket, "account/logout").await;
            response(&mut socket, &logout, json!({})).await;
            let read = request(&mut socket, "account/read").await;
            assert_eq!(read["params"], json!({"refreshToken":false}));
            let result = if still_signed_in {
                current_account()
            } else {
                json!({"account":null,"requiresOpenaiAuth":true})
            };
            response(&mut socket, &read, result).await;
        });
        assert_eq!(runner.logout().await.is_err(), still_signed_in);
        server.await.unwrap();
    }
}

#[tokio::test]
async fn shared_login_verifies_same_server_in_both_notification_orders() {
    for update_first in [false, true] {
        let (_root, runner, listener) = fixture().await;
        let server = tokio::spawn(async move {
            let mut socket = accept(&listener).await;
            begin(&mut socket, update_first).await;
            complete(&mut socket, LOGIN_ID, true).await;
            if !update_first {
                update(&mut socket, json!("chatgpt")).await;
            }
            let read = request(&mut socket, "account/read").await;
            assert_eq!(read["params"], json!({"refreshToken":false}));
            response(&mut socket, &read, current_account()).await;
        });
        let mut session = runner.start_device_auth().await.unwrap();
        let prompt = session.read_prompt().await.unwrap();
        assert_eq!(prompt.user_code, "ABCD-EFGH");
        let result = session.wait(CancellationToken::new()).await.unwrap();
        assert!(result.contains("selected@example.test"));
        server.await.unwrap();
    }
}

#[tokio::test]
async fn shared_login_cancels_only_its_native_login_id() {
    let (_root, runner, listener) = fixture().await;
    let server = tokio::spawn(async move {
        let mut socket = accept(&listener).await;
        begin(&mut socket, false).await;
        let cancel = request(&mut socket, "account/login/cancel").await;
        assert_eq!(cancel["params"], json!({"loginId":LOGIN_ID}));
        response(&mut socket, &cancel, json!({"status":"cancelled"})).await;
    });
    let session = runner.start_device_auth().await.unwrap();
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(
        session
            .wait(cancel)
            .await
            .unwrap_err()
            .to_string()
            .contains("cancelled")
    );
    server.await.unwrap();
}

#[tokio::test]
async fn another_login_completion_cannot_confirm_our_failed_login() {
    let (_root, runner, listener) = fixture().await;
    let server = tokio::spawn(async move {
        let mut socket = accept(&listener).await;
        begin(&mut socket, true).await;
        complete(&mut socket, "unrelated-login", true).await;
        complete(&mut socket, LOGIN_ID, false).await;
    });
    let session = runner.start_device_auth().await.unwrap();
    let error = session
        .wait(CancellationToken::new())
        .await
        .unwrap_err()
        .to_string();
    assert!(error.contains("sign-in failed"));
    assert!(!error.contains("PRIVATE_PROVIDER_DETAIL"));
    server.await.unwrap();
}

#[tokio::test]
async fn completed_login_with_no_current_account_is_not_success() {
    let (_root, runner, listener) = fixture().await;
    let server = tokio::spawn(async move {
        let mut socket = accept(&listener).await;
        begin(&mut socket, true).await;
        complete(&mut socket, LOGIN_ID, true).await;
        let read = request(&mut socket, "account/read").await;
        response(
            &mut socket,
            &read,
            json!({"account":null,"requiresOpenaiAuth":true}),
        )
        .await;
    });
    let session = runner.start_device_auth().await.unwrap();
    assert!(session.wait(CancellationToken::new()).await.is_err());
    server.await.unwrap();
}

#[tokio::test]
async fn completion_without_account_update_remains_unconfirmed() {
    let (_root, runner, listener) = fixture().await;
    let server = tokio::spawn(async move {
        let mut socket = accept(&listener).await;
        begin(&mut socket, false).await;
        complete(&mut socket, LOGIN_ID, true).await;
        // Await the real terminal outcome, not a sleep used as a receipt. If
        // completion was not yet observed at expiry, only its exact cancel is
        // allowed; neither readback nor logout may substitute for the update.
        let next = socket.next().await;
        if let Some(Ok(WsMessage::Text(text))) = next {
            let cancel: Value = serde_json::from_str(&text).unwrap();
            assert_eq!(cancel["method"], "account/login/cancel");
            assert_eq!(cancel["params"], json!({"loginId":LOGIN_ID}));
            response(&mut socket, &cancel, json!({"status":"notFound"})).await;
        }
    });
    let mut session = runner.start_device_auth().await.unwrap();
    if let DeviceAuthTransport::Shared(state) = &mut session.transport {
        state.deadline = Instant::now() + Duration::from_millis(150);
    }
    assert!(
        session
            .wait(CancellationToken::new())
            .await
            .unwrap_err()
            .to_string()
            .contains("not confirmed in time")
    );
    server.await.unwrap();
}

#[tokio::test]
async fn non_shared_receiver_keeps_its_cli_login_and_logout() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("codex");
    fs::write(
        &path,
        r#"#!/usr/bin/env python3
import sys
if sys.argv[1:] == ['login','--device-auth']:
 print('https://auth.openai.com/codex/device\nEnter this one-time code\nABCD-EFGH',flush=True)
elif sys.argv[1:] == ['logout']:
 print('Successfully logged out')
else:
 sys.exit(7)
"#,
    )
    .unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let runner = CodexRunner::new(path).with_shared_app_server(false);
    let mut session = runner.start_device_auth().await.unwrap();
    assert_eq!(session.read_prompt().await.unwrap().user_code, "ABCD-EFGH");
    session.wait(CancellationToken::new()).await.unwrap();
    assert!(runner.logout().await.unwrap().contains("logged out"));
}

#[test]
fn absent_or_malformed_native_account_does_not_become_logged_in() {
    let signed_out = account_status(&json!({"account":null,"requiresOpenaiAuth":true})).unwrap();
    assert!(!signed_out.authenticated);
    assert!(account_status(&json!({"requiresOpenaiAuth":true})).is_err());
    assert!(
        account_status(&json!({"account":{"type":"unknown"},"requiresOpenaiAuth":true})).is_err()
    );
}
