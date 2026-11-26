# Antigravity foreground route

Gateway accepts an explicit `matrix antigravity run JSON` owner command when
`interaction.antigravity_foreground` is selected. It uses the same original
selection, Matrix body verification, journal, capacity and response path as
Claude and Goose. `matrix antigravity status EVENT_ID` reads the retained
attempt. An original already admitted by any foreground engine keeps that
engine and outcome, including across restarts.

A configured worker must speak `daimon-gateway.antigravity-turn/v1` over the
existing JSON lines worker protocol. Its start frame carries Gateway's selected
session UUID. Before submitting the original to Antigravity, the worker must
verify the effective tool catalog and receiving body and return that exact
UUID as `nativeSessionId` in `prepare_submission`. Gateway requires the explicit
ID and commits it together with provider exposure before releasing the worker.
An absent or different native ID prevents submission. Loss after the commit
retains uncertainty.

## Worker profile

The worker supports the Antigravity SDK 0.1.24 local OpenAI-compatible backend.
Use a dedicated Python environment with `google-antigravity==0.1.24` and
`mcp==2.3.0`. Supply the selected interpreter and
`gateway-worker.py --profile /absolute/profile.json` as the Gateway worker
command. Select an approved local model and an owner-managed loopback
completion endpoint with no credentials. The profile is an owner-only regular
file. It takes these fields:

- `node` and `matrixStatusCommand` select the maintained observation broker
  dependencies. The command uses the existing Matrix host's `--body-status`
  contract.
- `body` contains `beingRef`, `embodimentId`, `incarnationId` and
  `manifestHash`. The Gateway start frame and the broker must confirm it.
- `providerPort` and `model` select `127.0.0.1:<port>/v1/chat/completions`.
- `stateRoot` is a dedicated owner-only native history directory. The worker
  uses 128 MiB and 2048 entries as admission thresholds. One bounded turn
  may finish above its threshold, and subsequent requests are refused. The operator
  can retain the directory and deliberately select a new one without
  changing Gateway's journal or resubmitting existing originals.
- Optional `selectedMemory` follows the same owner-only one-record binding
  as the Goose broker. Its `inputId` must match the exact original before
  the no-argument tool is exposed.

Antigravity's direct MCP registration exposes extra resource tools. The
worker uses the maintained observation broker through two scoped host
callbacks and enables no built-ins or subagents. It checks the exact effective
provider catalog through a one-use loopback endpoint. The SDK's readiness
challenge is answered in a disposable native session without contacting the
selected model endpoint. The final session uses the journal-selected UUID.
The local SDK receives the exact original to materialize its native session.
The gate holds that request while the worker verifies the native ID, Matrix
binding and reachability of the selected loopback listener. A refused or timed-out
connection before Gateway's submission decision is a known unsent turn.
The connection check sends no HTTP request or original text. The selected
provider receives the input only after Gateway's decision. Each subsequent
provider request must carry the exact original and the same tool catalog. One follow-up
is permitted after one approved observation. Failure after commit is
uncertain and never triggers resubmission.

Run the joined qualification in a disposable loopback namespace:

```sh
timeout 130 unshare -Urn sh -c 'ip link set lo up &&
  exec /usr/bin/python3 -B tests/antigravity_foreground_io.py "$1" "$2"' \
  sh /absolute/gateway-executable /absolute/sdk-venv/bin/python
```

The test runs the real SDK and Gateway with synthetic Matrix authority and a
synthetic provider. Leave the production route unset until the signed body,
selected model, DMK authorization and sender readback have been qualified.
For the signed interop fixture, set `PYTHONPATH` to the pinned Matrix
checkout's `src` and repository root. Run as the normal test user so the
fixture's Unix peer credentials and private file permissions match:

```sh
python3 -B tests/foreground_signed_io.py antigravity \
  /absolute/gateway-executable /absolute/sdk-venv/bin/python /absolute/dmk/scripts
```

This second test runs an authenticated Matrix socket and a real DMK reader
against disposable signing material and a disposable DMK pool. The provider
is still a loopback responder with no account or real inference. It verifies
the sender's signed readback, the original thread and the receipt hash.

`matrix antigravity interrupt EVENT_ID` stops the selected current worker.
Set `FOREGROUND_TEST_SIGNED_INTERRUPT=before` in the signed fixture to test
the boundary before provider exposure, or `=1` to test a stop after
the provider has received the request. The latter retains an uncertain
original across restart. The Gateway never resubmits that original.

The maintained evidence and limits are in
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497).
