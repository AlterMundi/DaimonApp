//! Authentication must belong to the same native server that runs conversations.
//! The CLI path remains available for receivers without a shared server.
use super::*;

const AUTH_RPC_TIMEOUT: Duration = Duration::from_secs(10);
const DEVICE_LOGIN_TIMEOUT: Duration = Duration::from_secs(15 * 60);

pub struct CodexDeviceAuthSession {
    transport: DeviceAuthTransport,
}

enum DeviceAuthTransport {
    Cli(Box<CliDeviceAuthSession>),
    Shared(Box<SharedDeviceLogin>),
}

impl CodexDeviceAuthSession {
    pub(super) fn cli(session: CliDeviceAuthSession) -> Self {
        Self {
            transport: DeviceAuthTransport::Cli(Box::new(session)),
        }
    }

    pub async fn read_prompt(&mut self) -> Result<CodexDeviceAuthPrompt> {
        match &mut self.transport {
            DeviceAuthTransport::Cli(session) => session.read_prompt().await,
            DeviceAuthTransport::Shared(session) => Ok(session.prompt.clone()),
        }
    }

    pub async fn wait(self, cancel: CancellationToken) -> Result<String> {
        match self.transport {
            DeviceAuthTransport::Cli(session) => session.wait(cancel).await,
            DeviceAuthTransport::Shared(session) => session.wait(cancel).await,
        }
    }
}

async fn rpc(process: &mut AppServerProcess, method: &str, params: Value) -> Result<Value> {
    // A timeout is an unknown outcome, never permission to repeat an auth write.
    tokio::time::timeout(AUTH_RPC_TIMEOUT, async {
        let id = process.send_request(method, params).await?;
        process.await_response(id).await
    })
    .await
    .context("Codex account operation could not be confirmed. Check sign-in before trying again.")?
}

fn account_status(value: &Value) -> Result<CodexAuthStatus> {
    let requires_auth = value["requiresOpenaiAuth"]
        .as_bool()
        .context("Codex account status could not be confirmed.")?;
    let account = value
        .get("account")
        .context("Codex account status is missing.")?;
    let detail = match account.get("type").and_then(Value::as_str) {
        Some("chatgpt") => {
            let email = account["email"].as_str().unwrap_or("ChatGPT account");
            let plan = account["planType"].as_str().unwrap_or("unknown");
            format!("Logged in with ChatGPT: {email}\nPlan: {plan}")
        }
        Some("apiKey") => "Using API key authentication.".into(),
        Some("amazonBedrock") => "Using Amazon Bedrock authentication.".into(),
        None if account.is_null() => {
            return Ok(CodexAuthStatus {
                authenticated: !requires_auth,
                detail: if requires_auth {
                    "Not logged in"
                } else {
                    "The configured provider does not require OpenAI sign-in."
                }
                .into(),
            });
        }
        _ => bail!("Codex account status could not be confirmed."),
    };
    Ok(CodexAuthStatus {
        authenticated: true,
        detail,
    })
}

async fn read_account(process: &mut AppServerProcess) -> Result<Value> {
    rpc(process, "account/read", json!({"refreshToken": false})).await
}

pub(super) async fn shared_status(binary: &Path) -> Result<CodexAuthStatus> {
    let mut process = AppServerProcess::spawn(binary, true).await?;
    let result = async {
        process.initialize().await?;
        account_status(&read_account(&mut process).await?)
    }
    .await;
    let _ = process.shutdown().await;
    result
}

pub(super) async fn shared_logout(binary: &Path) -> Result<String> {
    let mut process = AppServerProcess::spawn(binary, true).await?;
    let result = async {
        process.initialize().await?;
        rpc(&mut process, "account/logout", Value::Null).await?;
        let account = read_account(&mut process).await?;
        anyhow::ensure!(
            account.get("account").is_some_and(Value::is_null),
            "Codex sign-out could not be confirmed. Check the current account before trying again."
        );
        Ok("Codex is signed out.".into())
    }
    .await;
    let _ = process.shutdown().await;
    result
}

struct SharedDeviceLogin {
    process: AppServerProcess,
    login_id: String,
    prompt: CodexDeviceAuthPrompt,
    deadline: Instant,
}

pub(super) async fn shared_device_login(binary: &Path) -> Result<CodexDeviceAuthSession> {
    let mut process = AppServerProcess::spawn(binary, true).await?;
    let prepared = async {
        process.initialize().await?;
        let value = rpc(
            &mut process,
            "account/login/start",
            json!({"type":"chatgptDeviceCode"}),
        )
        .await?;
        anyhow::ensure!(
            value["type"] == "chatgptDeviceCode",
            "Codex did not return a device sign-in."
        );
        let login_id = value["loginId"]
            .as_str()
            .filter(|s| !s.is_empty() && s.len() <= 256)
            .context("Codex sign-in reference is missing; check sign-in before trying again.")?
            .to_string();
        let verification_uri = value["verificationUrl"]
            .as_str()
            .filter(|s| {
                s.len() <= 2048 && reqwest::Url::parse(s).is_ok_and(|url| url.scheme() == "https")
            })
            .context("Codex sign-in link could not be confirmed.")?
            .to_string();
        let user_code = value["userCode"]
            .as_str()
            .filter(|s| !s.is_empty() && s.len() <= 256)
            .context("Codex sign-in code is missing.")?
            .to_string();
        Ok::<_, anyhow::Error>((
            login_id,
            CodexDeviceAuthPrompt {
                verification_uri,
                user_code,
            },
        ))
    }
    .await;
    match prepared {
        Ok((login_id, prompt)) => Ok(CodexDeviceAuthSession {
            transport: DeviceAuthTransport::Shared(Box::new(SharedDeviceLogin {
                process,
                login_id,
                prompt,
                deadline: Instant::now() + DEVICE_LOGIN_TIMEOUT,
            })),
        }),
        Err(error) => {
            let _ = process.shutdown().await;
            Err(error)
        }
    }
}

impl SharedDeviceLogin {
    async fn wait(mut self, cancel: CancellationToken) -> Result<String> {
        let result = self.wait_inner(cancel).await;
        // This closes only our proxy. The shared server and its threads stay up.
        let _ = self.process.shutdown().await;
        result
    }

    async fn cancel(&mut self) {
        // Exact native login ID; no logout or new sign-in on an uncertain cancel.
        let _ = rpc(
            &mut self.process,
            "account/login/cancel",
            json!({"loginId": self.login_id}),
        )
        .await;
    }

    async fn wait_inner(&mut self, cancel: CancellationToken) -> Result<String> {
        let mut completed = false;
        let mut updated = false;
        let mut deadline = self.deadline;
        loop {
            let message = tokio::select! {
                biased;
                _ = cancel.cancelled() => {
                    if !completed { self.cancel().await; }
                    bail!("codex login cancelled");
                }
                _ = sleep_until(deadline) => {
                    if !completed { self.cancel().await; }
                    bail!("Codex sign-in was not confirmed in time. Check the current account before trying again.");
                }
                message = self.process.next_message() => message?
                    .context("Codex sign-in connection closed. Check the current account before trying again.")?,
            };
            match message {
                RpcMessage::Notification { method, params }
                    if method == "account/login/completed"
                        && params["loginId"].as_str() == Some(self.login_id.as_str()) =>
                {
                    anyhow::ensure!(
                        params["success"] == true,
                        "Codex sign-in failed. Please sign in again."
                    );
                    completed = true;
                    deadline = std::cmp::min(deadline, Instant::now() + AUTH_RPC_TIMEOUT);
                }
                RpcMessage::Notification { method, params } if method == "account/updated" => {
                    updated = params["authMode"] == "chatgpt";
                }
                _ => {}
            }
            if completed && updated {
                let value = read_account(&mut self.process).await?;
                anyhow::ensure!(
                    value["account"]["type"] == "chatgpt",
                    "The active Codex account does not match the completed sign-in. Check the current account before trying again."
                );
                return Ok(account_status(&value)?.detail);
            }
        }
    }
}

#[cfg(all(test, unix))]
mod tests;
