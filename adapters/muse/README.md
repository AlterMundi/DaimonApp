# Muse MSP foreground candidate

This client uses the installed `muse serve` session protocol. It opens a
durable session in the selected workspace or resumes the exact retained
session. Gateway's caller must retain the UUIDv7 command ID and native
session before allowing the client to send an original. The worker verifies
the matching acknowledgement and terminal event before returning a reply.
A lost or unconfirmed result retains the command ID and native session
for reconciliation. The client sends each command once.

The local qualification uses Muse Code's echo provider with tools disabled.
It verifies a fresh process resumes the same native session, and that a
denied original and a missing session cause no provider submission.

```sh
MUSE_TEST_BINARY=/absolute/muse node --test adapters/muse/turn.test.mjs
```

The ITACA pilot follows the official `muse-canary` channel and retains
`muse-stable` for comparison. The same selected subscription credential
reports an active subscription locally. Stable 1.4.25 and Canary 1.4.26
returned an empty visible model catalog. Canary reproduced this with fresh
configuration and data directories using the existing credential, and a
single explicit model probe was refused by the provider. One earlier
completed interactive turn had no model identifier in the native export.
Keep authentication and history while testing config isolation. Qualify a
real MSP turn against the selected subscription before wiring the topic.
Gateway topic binding, effective tools, steering and interruption remain
open. See the [capability inventory](../acp/gateway-coverage.md).
