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

The selected Meta account requires a separate real-provider qualification.
The local account reports browser login, while the headless model catalog
has no visible models and the first MSP model turn reports a credential
failure. Resolve the selected subscription without substituting API billing.
Gateway topic binding, effective tools, steering and interruption remain
open. See the [capability inventory](../acp/gateway-coverage.md).
