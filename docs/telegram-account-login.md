# Telegram account login with a shared Codex server

When `codex.shared_app_server=true`, explicit Telegram login and logout use the
same native App Server that runs conversations. An external `codex login status`
only observes stored credentials; it cannot confirm that the running server
adopted them. Ordinary input preflight retains its existing lightweight check.

`/login` reads the current server account. If already signed in, it reports that
account. To deliberately switch, use `/logout`, then `/login`, and complete the
official device-code sign-in using the intended account. This changes the shared
server's account for its conversations; it does not copy permissions or projects
from external connected services.

The shared path starts `account/login/start` with `chatgptDeviceCode`. It retains
the native login ID, accepts only that login's completion, observes
`account/updated`, and confirms a current ChatGPT account with
`account/read(refreshToken=false)` before reporting success. Cancellation uses
only the retained `account/login/cancel` ID. Logout uses `account/logout` and
checks that the same server reports no account. These operations close only
their proxy connection; they do not restart the server or modify native threads,
goals, history, provider selection or retained inputs.

If a response is lost, the result is unconfirmed. Check the current account
before trying another sign-in. Do not automatically repeat an auth write, switch
to another account, copy tokens, replay a failed turn or reset a conversation.
Non-shared receivers retain their CLI authentication path.

Protocol compatibility is checked against the installed native schema. Synthetic
WebSocket tests cover both notification orders, failed/mismatched completions,
missing account updates, cancellation and logout readback. These tests establish
the bridge behavior; a human-selected live account switch and subsequent useful
conversation remain separate receiving acceptance. An account read alone does
not prove provider access or migration of account-specific tools.
