# Selected Matrix execution adapter

## Portable Conversation publication

The optional `interaction.matrix_publication` configuration adds a typed,
owner-local publication writer to the existing Conversation store. This is the
App portion of [Matrix #496](https://github.com/AlterMundi/daimon-matrix/issues/496),
not a messaging-delivery claim. On10November the existing original three App
receivers adopted the qualified full-audio native publisher and the matching
current web reader. Each actual owner status returns its paired-human general
Conversation descriptor; this does not install Matrix signed publication policy
or discharge an older ambiguous obligation. It needs
no Telegram account, bot token, browser or model turn.

The selected descriptor contains `surface_ref`, a sorted unique `audience`
(at most 256 entries and 32 KiB serialized), and an absolute `signing_key_file`.
The latter is a same-owner, mode-0600 regular file holding an Ed25519 seed;
symlinks and unsafe permissions refuse. Keep actual custody paths and private
bytes out of project records. The `status` operation returns only the public
descriptor and verification key. Installation must use the existing authorized
resource/owner route; this configuration does not grant arbitrary actors access.

Existing owner control commands are:

```text
telecodex --control CONFIG matrix publication status
telecodex --control CONFIG matrix publication commit < REQUEST.json
telecodex --control CONFIG matrix publication inspect PUBLICATION_UUID
telecodex --control CONFIG matrix publication confirm PUBLICATION_UUID REQUEST_SHA256
telecodex --control CONFIG matrix publication retire
telecodex --control CONFIG matrix publication list CURSOR
```

`commit` takes at most 64 KiB on stdin and validates the exact deterministic
publication ID, native binding digest, selected surface/audience and bounded
part. An immediate SQLite transaction commits the immutable content and receipt
body before the backend signs it. Exact duplicate requests recover the same
proof; changed content, binding, owner, audience or signing key refuses. Missing
acknowledgment requires inspecting that identity, never reauthoring speech.
Existing Stop and maintenance admission fences apply to fresh publication.
The request binds `not_after_ms` from the original native operation in both its
native obligation digest and deterministic part UUID. Expired fresh requests
refuse; existing exact proofs remain inspectable after expiry.

The normal authenticated Conversation feed has an independent `publications`
cursor. Its `matrix_visibility` sources use the existing revision-checked part
reader and retain explicit provenance. They are neither human utterances nor
execution authority, receiving-copy evidence or task completion. They do not
trigger automatic speech or companion reactions. Older native readers keep the
old cursor form when this optional configuration is absent.

The staged journal caps each owner's conversation at 4096 parts / 64 MiB. Its
technical copies have a rolling 24-hour retention window after both the native
deadline and the host acknowledgment of durably retained native confirmation.
`confirm` is a trusted model-free host operation with the exact request digest,
invoked only after that native journal commit. It establishes visibility proof
acknowledgment, never receiving delivery, human reading or task completion. A
lost acknowledgment leaves the copy pending and pinned.

Each new commit and the owner `retire` operation removes at most 64 eligible
copies. Deletion and a constant-size per-conversation retired-deadline fence
share one transaction. No per-message tombstone archive is created; a regressed
clock cannot recreate a retired exact request. Monotonic sequences preserve feed
cursors. Native histories and ordinary inbox/response records are unchanged.
Pending/ambiguous copies are never deleted for capacity. If they fill the journal,
publication refuses rather than losing work. No new timer or model turn is used.

**End-to-end receiving remains distinct:** the selected native installation/transport
must supply the real deadline and confirm only after its committed proof. Matrix
owns the signed publication policy and seven-body useful messaging journey. App
owner/reader readiness and retirement tests alone do not establish that connection.

`tests/matrix_publication_http_io.py` drives the actual Matrix native journal
and `ConversationJournalTransport` through the real owner socket and SQLite,
verifies native commit before metadata acknowledgment using another connection,
and exercises the authenticated HTTP feed/part reader and restart recovery.
Home identity and the native harness are synthetic. Its lost-result case recovers through one durably reserved exact proof read,
without another publication. A failed proof read keeps uncertainty pinned across
restart/calls and does not reset the read budget. Both fresh and warm metadata
acknowledgments run outside the native SQLite transaction.
Set `PYTHONPATH` to the selected Matrix candidate SDK; CI pins
`ae2bd0b5c014dda5d4cf4ac63b730468e271a453` for this composition. It verifies no Telegram token,
transmission, inference, fabricated input or native turn. The portable fixture
is public synthetic test material, not operational custody. The seven-body
native installation and useful messaging journey remain separate qualification.

The optional host module `scripts/matrix_execution.py` connects an already
approved Matrix `ExecutionStore` cycle to its authenticated owner-local SDK
client. It is a building block for [Matrix #367](https://github.com/AlterMundi/daimon-matrix/issues/367),
part of [Daimon Interaction](https://github.com/AlterMundi/daimon-matrix/issues/313).
The conversation can retain explicitly configured Matrix requests and canonical
returns. No remote participant or receiving execution is selected by default.

The trusted host constructs one closed task with `make_task`, including the
original input UUID, exact execution scope and explicit being/body destination.
The task hash is part of the existing externally approved instruction. For a
reply, the host instead selects an SDK-verified native parent; the SDK derives
the destination from that parent's authenticated origin. The parent's directed
being/body kind is frozen in the task and preserved on return; broadcast parents
are rejected before mutation. Model output supplies
only text. It cannot override destination, channel, parent, tool or authority.

Construct `broker = MatrixExecutionBroker(instruction, task, authenticated_client)`
and use `broker.controller(approved_store, qualified_runner)` to create the existing
`ReviewController` with an exact instruction/task admission guard. A Scope alone
does not bind the recipient; do not reuse the broker with an unpinned controller.
The broker implements the existing `NativeBroker` interface; the model never
receives this Python object or native credentials. Before mutation, authenticated source observation must report the approved being
and body through `runtime.status`, within the same absolute deadline. Both native
clients must select the same runtime, server origin and socket. The SDK keeps
messaging-only and observation capabilities separate; the host adapter routes
each purpose through its existing capability rather than creating a mixed one. The SDK must support an
absolute `deadline_ns` as well as a per-operation socket timeout. The current qualified source is Matrix
`5e1dba7a1466104495650fc31e52f0f167472776`. Legacy nonqueued transport and
controller compatibility is also checked against `9b2b8ec2c455d3bf316bc00dc9e1bac44e9d5094`;
that older source does not supply funded source queues.

The application relay explicitly identifies `interaction-controller` and
`session_request` or `worker_result`. The signed native event identifies its
actual author. Neither marker impersonates the human or grants receiving model
execution. The selected recipient's existing human execution approval, runner,
provider and budget must independently admit any inference. There is no default
recipient, paid model, arrival hook, inbox polling or automatic reply.

The original input UUID fixes the native send identity independently of session
renewal and destination. Native journals reject changed parameters under that
identity. A correction is a distinct retained human input, not permission to
rewrite or reissue the original. An ambiguous submission remains charged in
`ExecutionStore`; explicit `inspect` observes the same SDK send without replay,
refund or new execution. `accept_verified_reply` correlates an already verified
selected event to the original message ID, digest, author, thread and recipient.
It does not perform signature verification itself or read an inbox.

## Explicit selected-reply inspection

The existing integrator's `matrix_status` optionally accepts `receive_after`
with one acknowledged `request_id`. That explicitly reads one selected-thread
page through the configured host, retains valid canonical replies, and returns
an inspection cursor to the SAME active conversation. Omit `receive_after` for
the previous retained-state-only observation; it is invalid with `message_id`.
No result-triggered native turn, background reader or second I/O session follows.

The owner-only `matrix_operator.py --receive` mode accepts exactly
`{status, source, after, limit}`. `status` is the existing authenticated retained
request snapshot, `source` must equal its frozen claimed source, and the request
must already have an acknowledged submission. Unknown/submitting sends cannot
be inferred into replies or retransmitted by this reader.

The existing `MatrixConversationReceipt.read_replies` observes that exact native
send and reads one authenticated `messaging.inbox` page filtered by its immutable
thread UUID. The receiver must support the additive selected-thread inbox API
(Matrix #436); rejection never falls back to a broad scan. One absolute deadline
covers all SDK calls. Pages contain at most three events and the host output is
bounded to64KiB. Only replies with the exact selected parent, thread and sender
are exposed as canonical callback values. Unrelated speech in that thread
advances the global cursor without becoming a callback or instruction.
Signatures and admission remain verified by the existing Matrix reader; this
adapter is not a separate signature verifier.

The read-only receipt imports normal native replies verbatim with
`reply_kind: speech`. No fabricated worker/execution reference is needed. A
valid existing controller `worker_result` relay keeps its strict original and
execution-reference correlation and its historical callback bytes. Text that
fails that worker-envelope check remains unverified speech, including structured
claims: its embedded text is not extracted and it never becomes an instruction,
a work result, an approval or a source of fuel. The execution broker's strict
worker-result parser is unchanged. Canonical presentation remains
`completed: null`; a signed reply is not task completion or native incorporation.
Legacy callbacks without `reply_kind` retain their bytes and source revisions;
absence is not a newly verified completion claim.

The caller records each callback through the existing authenticated owner return
before retaining `next_cursor`. Re-reading an inspected page is read-only; the
canonical message UUID/digest remains the store's deduplication boundary. A full
page indicates only that the limit was reached, not proof of another result or
completion. Failure retains the prior cursor and uncertainty; never resend work
to repair observation. This installs no poller, hook, model turn, new inbox/store
or native session. Automatic return attachment, receiving native work and real
human acceptance remain separate unfinished integration outcomes.

## Bounded new-message page for the combined heartbeat candidate

The same owner host now supports `matrix_operator.py --inbox` with closed
`{source, channel_id, after, limit}` input. This reads one explicitly selected
existing incoming channel, at most three events, under one absolute deadline.
The current owner connection and its existing messaging/observation capabilities
remain authoritative. Runtime identity is checked before the inbox call. Native
Matrix verifies message signatures and current membership/audience; this adapter
is a bounded reader/projection, not another signature verifier or inbox engine.

The projection preserves immutable message ID/digest, signed author/body,
thread, destination, response context, coordination metadata and raw native text.
Even text containing an Interaction relay stays verbatim peer source; this
reader never extracts embedded instructions or upgrades claims to human speech,
work approval or completion. An unsupported text payload remains explicit with
its native identity. Cursor order, owner/channel, page and64KiB output bounds
are checked before a page is returned. Exact rereads have the same source
identity; the consuming backend must retain accepted items before advancing its
cursor. Failed reads return no successful cursor. This interface sends nothing,
never retries a mutation, and creates no timer, execution or model call.

The same candidate backend supports an optional owner configuration
`interaction.matrix_inbox_channel = "tribe"` alongside the existing Matrix host.
Incoming-only selection needs no per-recipient routing targets. With that
configuration, the integrating `matrix_status` operation accepts
`{"inbox_next":true}` alone. It reads at most three native events using the
retained cursor; the model cannot change the channel, source body or cursor.

One SQLite transaction retains immutable native originals and advances their
cursor. Exact retries deduplicate, conflicting identities roll back, and a
changed entry/native generation refuses a late read. The existing
`conversation_part` reader provides `matrix-inbox:EVENT_UUID` sources with exact
revision and bounded pagination; unsupported payloads stay explicit rather than
becoming invented peer speech. Retention is capped at256events/4MiB per logical
entry across generations. At capacity the whole page/cursor remains unchanged;
no original or historical source is deleted to make room. Human consultation
remains available during heartbeat pause; it starts no model or automatic work.

This source component belongs to the single combined candidate. It is not
selected or invoked by the deployed heartbeat. Existing selected-reply reads
keep their exact thread/correlation behavior. The finite producer can additionally freeze
`matrix_inbox = {source = {being_ref = "...", embodiment_id = "..."}, channel_id = "tribe"}`
in its existing contract. It must exactly match the current owner channel/body;
configuration or restart cannot silently widen that source. Each page spends the
existing persisted check/cadence before I/O. The finish transaction verifies its
same counter, binding, generation, expiry and remaining resources, then retains
sources/cursor and uses the existing bounded batch/attention account. An admitted
read may finish during pause, but cannot commit a late page or start attention.
There is no second scheduler, queue, resource refill or producer.

The optional `session_progress = true` source observes new worker commentary
already visible to this integrating Conversation. It reuses the canonical
presentation audience captured with the native item, exact source revision and
`conversation_part` reader; a later session switch cannot widen that audience.
The initial cursor starts at configuration's existing high-water mark, avoiding
historical narration replay. Each check reads at most four new eligible rows,
with a persisted bounded cursor and ordinary seen-revision deduplication across
pause/restart. Integrator commentary and private/direct worker output are not
new offers. This source shares the same four-offer batch and conserved execution
account with inbox, workflows and reports. Commentary is evidence of an update,
not task completion or permission to resume a paused/blocked goal. Existing
canonical result/question callbacks and workflow milestones remain their owning
paths; this adds no observer-model refresh or parallel task coordinator.

The optional finite contract `purpose = {input_ref = "ACTUAL_ORIGINAL_UUID",
channel = "conversation"}` selects an already accepted human operating request
in this same native entry. Integer Telegram originals retain this receiver's
actual `telegram:BOT_ID` provenance; Telegram is not required. Configuration
looks up the actual retained original and freezes its source hash. Missing,
foreign, unaccepted, changed or retired originals refuse; no replacement text is
accepted. A changed purpose prevents further checks/admission and is explicit
as `purpose_retired`, without erasing already committed history or refilling fuel.

Each nonempty batch carries only its `operating_purpose` reference/revision and
an exact `heartbeat_source` reader using `purpose:human`. That reader returns
the earlier human text in bounded parts, including while admission is paused;
it creates no new input or publication grant. The integrator can use that actual
`input_ref` with ordinary `workflow_declare`, adding separately attributed peer
evidence to the bounded step scope. Existing workflow ownership, idle-only child
admission, conserved account, source/result correlation and scoped pause continue
to apply. A peer message or metadata offer never becomes the human request.
The optional purpose supplies context, not a model judgment that its text
authorizes every proposed task. Existing separately authorized workflows retain
their actual human originals; this adds no second task/authority engine.

The purpose reader also supplies a bounded current `primary_routing` view for
an original already dispatched to an existing owner. A genuinely additional
scoped workflow must name that exact accepted human `parent_instruction`.
Without it, the ordinary duplicate dispatch/creation refusal remains unchanged.
At declaration the backend freezes the primary's source hash, current owner/
native binding generation, epoch and original request coverage, and revalidates
them before future steps and returns. This is not an acceptance-time generation
record. Foreign originals, session-authored or withdrawn parents, mismatching
current owners and creation plans cannot acquire this linkage. Interview
restrictions use the same existing source-protection rule as session dependencies.

The original owner/instruction is neither resent, rewritten, retired nor marked
completed by that additional workflow. Child request IDs remain distinct; their
attributed context and status retain the primary reference. A later withdrawal
or rebind closes new admission while accepted/uncertain child effects remain
history. This supports a real already-routed operating purpose without replacing
it with a fabricated unclaimed human message.

No-news reads are silent. Failed source reads consume checks and produce one
revision-bound availability notice, with a separate recovery notice; unchanged
failures do not repeatedly activate the integrator. Page retention uses a
savepoint so capacity/identity failure cannot commit partial events before the
failure state. Own-body echoes and already canonical correlated Matrix replies
are excluded from new-original offers. Exact native sources use the existing
reader; unsupported payload/status metadata is explicit inline evidence.

### Original handling and correlated native responses

The same integrator's `matrix_response` controller operation reads `pending`
(at most eight descriptors per row cursor) or `status`, retains an explicit
`defer` reason/next condition, or submits a selected `reply`. Deferral is still
unresolved; it creates no timer, worker or new authority. Source revisions remain
the immutable original's revisions, independent of handling state. Pending views
exclude own-body echoes and already canonical correlated returns. Their paging
is a bounded current view, not an immutable remote snapshot.

Reply supplies the exact original UUID/revision and at most8000bytes of this
integrator's own speech. One transaction freezes the response text, native parent,
owner/channel, fresh send UUID and authoring deadline before calling the existing
SDK. A later identical request returns retained state without another send;
changed text refuses. The host re-reads the selected signed parent under the same
absolute deadline and uses native `messaging.reply`, preserving a group parent's
group audience or a direct parent's sender and recipient kind. It does not use
the directed-only worker-relay parser or invent a human original. The native
parent retains its immutable hash, author and thread.

The existing authenticated physical caller selects attention ownership. An owned
execution must still have its exact live generation; authoring expiry cannot
exceed its reserved execution deadline. Pause closes further mutation. Already
in-flight work may have an uncertain effect: the response intent remains
`submitting`/`uncertain`, with no automatic retry. `inspect` calls only native
`messaging.delivery`, including after the authoring deadline; it can retain a
late observed result without admitting a new send. Native event/hash identity is
immutable across later inspections. The API never resets a reservation or an
intent to manufacture another attempt.

`submitted` means a native authored outcome. It remains pending until native
member receiving-copy receipts prove the distinct intended members' copies;
`recipient_copy_proved` does not mean all-body uptake, model incorporation, task
completion or human hearing. A weaker/failed later observation cannot erase the
retained stronger proof. Complete native evidence stays in the SDK journal;
controller status exposes bounded metadata and at most eight member summaries.

Storage reuses one handling column per retained original. At most32response
intents per logical entry are admitted, each at most128KiB including its receipt;
the remaining original rows hold only bounded latest deferral metadata. These
bounds are not reset by restart, pause/resume or source generations. Capacity
leaves originals/intents inspectable rather than deleting history or resending.
There is no new scheduler, reasoner, credential or model call in this adapter.

Batch review alone is not a response or permission to reinterpret peer speech as
human instructions. Selected task/DMK/editorial
follow-through and actual combined receiving/model/spoken acceptance remain
unfinished. The finite producer remains unconfigured in production.

### Native package adoption under an existing start watcher

`scripts/native_package_handoff.py` is a finite receiving operator, not part of
the heartbeat or a new supervisor. Use the existing qualified native maintenance,
stopped-only complete-package installer and stopped-only recovery commands. A
generic watcher calling ordinary `daemon start` must not race this sequence:
that command can discard saved maintenance recovery before installation.

The owner supplies one bounded private `daimon.native-package-handoff/v1` plan:
stable UUID `id`, `ready`, receiving `uid`/`cgroup`, `package`, complete relative
`files` SHA256 map (including `bin/codex`), `codex_home`, and fresh `supervisor`/
`receiver` process identities from this operator's `identity(pid)`. Configuration
is not authorization. Keep `ready=false` until the complete selected stack is
qualified. The explicit `--adopt` invocation takes `--plan` and `--receipt` paths;
an existing receipt refuses rearming, including after uncertainty. A fixed sibling
lock serializes this intent without holding the native lifecycle lock.

Run the coordinator in the target's existing persistent service cgroup, for
example through a dedicated named tmux server launched there. Inspect actual
placement; detachment or a tmux name does not prove it. Do not stop that service
or launch its replacement in a disposable build unit. The operator refuses a
different cgroup, owner, package hash or process generation. Linux pidfds bind
signals and exit observations to the selected processes rather than reused PIDs.

Only the generic start watcher receives SIGSTOP; native execution/admission stays
live. Its already launched start child must finish first (two-second observation,
then deferral), because suspending its Python parent does not stop that child.
The native receiver still decides its natural-idle handoff. A terminal deferral
releases the same watcher. Only confirmed `handoffReady` plus observed old-process
exit permits stopped installation and snapshot-preserving restoration in the
same persistent cgroup. Compare all package files/resources and the installer's
fixed `codex -> bin/codex` compatibility link; CLI equality alone is insufficient.
Pin the complete previous tree and release path independently. Inventory is bounded at64regular files,128total entries and1GiB, covering the actual44-file stock0.167 predecessor without copying it. A known old package can be restored after refused
installation; this is software recovery, never a history restore or input replay.

Uncertain maintenance/exit/restore is retained, never resent or converted into
fresh start. The watcher remains held when releasing it could erase uncertain
recovery. Inspect that receipt and actual native state before further action;
there is no automatic rearm or forced stop. A successfully restored receiver is
checked for code/placement before the exact watcher resumes. No host action,
global Stop, goal mutation, archive or provider/model selection is performed.

For the owner-scoped five-minute pause window, use
`schema=daimon.native-package-handoff/v2` with `lifecycle_deadline_unix` set to
that transaction's restoration-start time, not its final deadline. The existing
owner bridge reserves `10 * targets + 40` seconds for restoring exact unchanged
pauses; do not let native maintenance overlap that reservation. This timestamp
is materialized only when the qualified package and actual observed target set
are ready. It creates no goal hold, consent or automatic rearm. Legacy v1 plans
retain their prior behavior and cannot carry this bounded field; an old helper
rejects v2 instead of silently ignoring its expiry.

The operator maps the deadline once to monotonic time. With less than200seconds
left it defers before sending maintenance. Otherwise the fixed native133second
observation remains intact (138second command cap). After confirmed handoff AND
actual old-process exit, it skips candidate installation if fewer than66seconds
remain, restoring the exact selected predecessor instead. Installation is capped
at15seconds, stopped-only restoration at45seconds, each clipped to the remaining
window. A lost installer ACK inspects the atomic full-package selection once;
never resend install. Expiry or unavailable recovery is explicit uncertainty,
not a guarantee of service readiness or authority to fresh-start/force the host.
The independent owner bridge still restores only its unchanged acknowledged
pauses; later human decisions and unknown effects win. Reuse this one operator,
not a retry coordinator. Tests cover short-window deferral, long-maintenance
restore reserve and a lost installer ACK with real fixture process identities.

`tests/native_package_handoff.py OLD_CLI CANDIDATE_CLI --scratch /selected/data --lifecycle-seconds 220`
qualifies the actual complete-package route with an isolated managed receiver,
live competing start watcher and original loaded thread. It uses only unreachable
loopback inference and preserves unfinished fixtures on failure. The smaller CI
unit suite checks generation/cgroup refusal, terminal deferral and uncertainty
without targeting a real daemon. These are operator proofs, not receiving/model/
audio acceptance of the heartbeat.

## Funded selected-original replies — Matrix #312 / Telecodex #532

A finite approved purpose and a later received original are separate inputs.
Do not embed a future original in the approved purpose: the original's signed
coordination metadata references that approval's hash. The host constructs
`MatrixExecutionBroker(instruction, purpose, authenticated_client,
received_source=verified_event)` only after selecting the exact SDK-verified
original. The purpose must match the approved task hash; the original fixes the
reply parent/destination and its complete event digest. The broker accepts only
`kind: work` metadata naming that exact instruction hash.

Use the existing `broker.controller(store, qualified_runner)` and
`run_due_once(instruction_id, revision, purpose, work_id=selected_work_id)`.
This explicit mode requires the existing funding and queued-source gates; neither
can be disabled. The work row must match the pinned account, instruction,
message ID and full source digest before runner admission. Another eligible
original cannot borrow this broker. Existing core approval, episode authority,
source eligibility, deduplication and provider reservations still own admission;
metadata itself grants none of them. The runner receives only the core's
`selected_original`; it does not receive an arbitrary inbox or new conversation.

A reply retains the same root/account/instruction correlation with `kind: result`.
It is passive and cannot enqueue another work turn. The signed SDK reply and the
existing `conversation_return` callback bring it back to the original canonical
Interaction conversation. I/O remains ingress/egress for that same integrator,
not an additional reasoning session or a private-history aggregation mechanism.

The technical sender's programmatic `coordination=` keyword is for the trusted
host to attach an already selected existing work correlation. CLI/stdin remains
the closed `{status, source}` contract; neither model text nor that keyword can
create an account, human approval, budget, provider or receiver activation.
Without `received_source`, legacy manual single-cycle behavior remains unchanged;
legacy controllers reject a queued work ID rather than silently using it.

## Technical original transport

`MatrixConversationTransport(authenticated_status, selected_author, authenticated_client)`
relays an already retained human original without a model call, synthetic execution
instruction or per-message execution approval. The selected host supplies the
source `{being_ref, embodiment_id}` from owner setup and reads the status through
the authenticated controller. This class is not exposed to a model, does not
read an inbox, and offers no execution controller. It shares the broker's exact
source/client checks, absolute deadline, immutable original and recipient, signed
native send identity, delivery inspection and verified-return correlation.

The outgoing thread is the retained request UUID; the stable send identity uses
the same original-derived namespace as the existing broker. `send()` relays only
the exact original, its attribution and selected lineage. It emits
`execution_ref: null`: this is a technical transport event, not an assertion that
an inference cycle was approved. `make_received_task` can prepare this verified
request, but only the receiver's independently admitted execution path may run a
model or produce its work result. Transport cannot mint fuel or paid approval.
Worker replies still require their actual execution reference.

Reconstructing the transport from the same retained current status retains the
native journal identity. Do not automatically retry an uncertain operation;
inspect the same send. Switching a previously authored original between execution
and technical modes cannot alter its old relay: the journal rejects changed
parameters under the same identity. This is a matching host capability; deploy
receiving parsers that accept the explicit null transport reference. The pinned
receiver preparation already accepts it; third-party consumers may require an
update.

This removes sender-side inference admission from the technical transport. The
normal controller can explicitly inspect and retain signed replies through
`matrix_status` with `receive_after`. Result-triggered native continuation and
the selected receiving native owner remain separate unfinished integration
work; importing or constructing the class installs neither listener nor peer activation.

## Normal-controller technical submission

An optional `[interaction.matrix_transport]` connects `matrix_request` to the
selected host command. Without it, request retention preserves the previous
passive behavior. With it, the normal integrating tool first atomically claims
the retained original, then invokes the configured argv through bounded stdin
and stdout. Commands, source identity and socket/credential references come only
from owner setup, never model text. No second native writer, inbox poller,
execution store or paid admission is introduced.

```toml
[interaction.matrix_transport]
command = ["/usr/bin/python3", "-B", "/path/to/matrix_operator.py", "--native-connection", "/path/to/current/connection.json", "--binding", "/path/to/private/host-binding.json"]
source = {kind = "body", being_ref = "SOURCE_BEING_REF", embodiment_id = "SOURCE_EMBODIMENT_ID"}
timeout_seconds = 45
```

The host command budget includes the qualified SDK startup, not only socket I/O.
An actual MEDUSA read took19.4seconds, with most time in SDK qualification and
imports; a15second host cutoff could reject normal work before its result.
Use a measured startup allowance within the existing1–60second range;45seconds
is the ordinary example. This does not enlarge native inference budgets or
permit retrying an uncertain send. Keep the adapter's bounded RPC deadline and
use status-only inspection after a lost command result. Changing this field
uses the existing same-actor profile/companion maintenance route in
[the fleet guide](interaction-fleet-updates.md#matrix-profile-changes-and-same-scope-web-companions).

Replace placeholders with the explicitly selected existing source and recipients;
this example is not an enrollment or activation. The owner-only binding uses
`schema: telecodex.matrix-host-binding/v1`, the exact `source` object with
`being_ref` and `embodiment_id`, and two purpose references named `messaging` and
`observation`. Each reference has only absolute `socket`, `client_config` and
`client_key` paths to existing owner-local SDK material. The SDK verifies their
capabilities; the host requires matching runtime ID, expected server and socket.
The messaging capability stays messaging-only and permits the selected operation:
`messaging.inbox` for a new-message page, inbox/delivery for selected-reply
inspection, or `messaging.send` for submission. An inbox-only grant can read
without acquiring send authority. Observation separately permits `runtime.status`. The adapter never loads the
runtime outside its daemon or creates credentials. Its two calls share one
absolute deadline. Do not use a combined capability: the SDK rejects mixed
messaging and observation profiles.

### Current receiving SDK context

The optional owner-only `--native-connection` flag reads the current managed
Cluster owner connection at each invocation. It uses that connection's selected
interpreter, closed imports, code digest and code owner, then calls the SAME
maintained `sdk_parameters`/`qualified_startup` verifier before loading the host
adapter. Preserve the exact isolated/no-site/no-bytecode context, including its
disabled-bytecode prefix; do not relax qualification or import installed/global
packages to get past a rejection. The connection's arbitrary Python code string
is never executed. Only the supported managed-owner argv layout is accepted;
other layouts fail explicitly rather than falling back to a cached older SDK.
Without this flag, an operator can still supply an already qualified context.

The parent never reads/repackages stdin before replacing itself with that
receiving process. The exact original, ordinary process group, deadlines,
request journal and conservative uncertain-send behavior remain unchanged.
Bootstrap qualification failures return only their exception class, keeping
private paths and diagnostics out of the controller/model result. A successor
SDK is resolved from the existing connection; this creates no credential,
permission, runtime identity or alternative transport.

Keep the host binding in an existing owner-private directory whose ancestors
satisfy the SDK's protected-file rules. A private leaf under a group-writable
ancestor can still be refused. Use the established protected owner location;
do not loosen validation or change unrelated global configuration permissions.
Both purpose clients must match the same runtime/server/socket, and the online
source observation must still match the selected body before any send.

The existing request row freezes the selected source author as `claimed_source`
and records `submitting` atomically before the command can have an effect.
That source survives a lost ACK, restart or later owner configuration change.
Both the host ACK and an early canonical callback must match the retained source,
request-derived native send ID and request UUID thread. A different source cannot
establish the submission by returning before its ACK. Legacy passive rows without
a technical claim retain their existing verified-callback contract. A valid fixed-source/request/destination submission becomes `submitted`;
that proves the SDK-authenticated authored outcome, not receiving incorporation,
completion or a particular delivery receipt. The original, binding and minimal
native submission are retained; signed receipts remain owned by the SDK journal.
Concurrent or later repeated tool calls never claim an already submitting,
submitted or uncertain original again. A lost response, bounded-process failure
or cancellation remains `submission_uncertain`; a crash can leave `submitting`
with unknown outcome. Restart does not resend either state. Inspect the stable
native send identity and its actual journal before further recovery. Child
termination affects only that command's own process group and does not establish
that an SDK effect was cancelled. An early verified canonical reply cannot be
erased by a later submission ACK or failed host observation.

This wires the normal controller's outbound technical send. The existing
SDK-verified owner callback retains canonical returns; automatic return attachment
and actual receiving native steering remain unfinished. No configured host or
participant is enabled by default, and technical arrivals never admit inference.

## Retained conversation requests and returns

Add `matrix_targets` under the existing `[interaction]` profile only for explicitly
selected recipients. Each entry has a distinct `name` and a `destination` tagged
`kind = "being"` with `being_ref`, or `kind = "body"` with both `being_ref` and
`embodiment_id`. These are signed identity references, not labels resolved through
an archived pair lane. An empty list preserves ordinary local-only operation.

The integrator's `matrix_request` operation accepts one retained `input_ref`, a
configured `selector`, and a `new`, `amends` or `context` relation. It cannot supply
replacement text. Selection atomically freezes the original, recipient, entry
generation, admission epoch and up to four explicitly selected same-entry,
same-recipient parent originals. Parent text and authorship remain separate from
the current human text or committed machine transcript. The explicit relation
(`new`, `amends` or `context`) and its exact selected request IDs also travel into
the receiving task, protected by the approved task hash. A relation cannot name
parents outside that package or add a recipient selector. Older relays without
a relation remain unclassified; absence does not mean an amendment or grant
execution. The receiving native owner still owns actual steering and admission.
Deploy a matching receiving host: the previous closed parser rejects the new
relation field, even though the signed Matrix transport itself accepts the text.
Serialized selected content is bounded to 15360 UTF-8 bytes, reserving 1024 bytes
for the SDK relay's fixed metadata, relation and bounded execution reference. Oversized JSON-escaped context
is refused before consuming the original. A Matrix selection excludes local
routing, creation and implicit native-question answers for that same original.

`matrix_status` reads one selected request or canonical event. The authenticated
owner can use `telecodex --control CONFIG matrix status UUID`. The trusted host
passes that exact status to `make_conversation_task`; it verifies the immutable
binding and excludes private human return coordinates from the outbound relay.
A model cannot paraphrase a relayed original into apparent human speech.
`make_received_task` prepares a selected SDK-verified original for independent
receiving approval; it does not read an inbox or approve execution.

After SDK signature and reply-parent verification, the host derives a callback
with `broker.conversation_return` and records it through
`telecodex --control CONFIG matrix return JSON`. This owner-local callback is a
trusted host boundary, not a model tool or independent signature validator.
Exact event retries are idempotent; changed bytes under the same event fail.
Late replies remain historical after native renewal or admission changes, with
`current: false`. Corrections retain their parent request and make the prior
result noncurrent; a received reply alone never proves task completion.

The browser requests the optional third `matrix` cursor from `/api/interaction`.
Canonical sources use `matrix:<event UUID>` and `kind: matrix_result`, preserving
the selected label and authenticated source author. Text and speech share the
existing source/revision checks. A contextual reply sends a new human original
to the integrator; the integrator explicitly selects its relation and recipient.
Two-cursor clients retain their local-only behavior. Device-client adoption and
production receiving execution remain separate qualification requirements.

## Retained return correlation

`MatrixConversationReceipt(authenticated_status, authenticated_client)` rebuilds
read-only correlation from an acknowledged technical request. The status must
retain `claimed_source` and the closed native `submission`, with phase `submitted`
or `reply_received`. It validates the immutable original binding, frozen author,
recipient and request-derived send/thread IDs. It can inspect that same SDK
submission and correlate an already SDK-verified selected reply through the
existing `conversation_return` callback. The inspected outcome must exactly match
the acknowledged message ID/hash and route; a different native result cannot
replace the recorded submission.

A historical `current: false` request remains readable. Reconstruction neither
changes its phase nor recreates pending admission: the object has no sender or
execution controller, and its `submit` method always refuses effects. The
canonical callback leaves current-generation/Stop checks to the existing owner
store. This is a trusted host API, not independent signature verification or OS
isolation; pass only authenticated owner status and SDK-verified events.

An uncertain send without a known ACK is insufficient to reconstruct this
receipt. Delivery inspection can show that some native send exists under an ID,
but is not proof that its full original wire content matched this retained human
request. Preserve that uncertainty and inspect the original SDK evidence rather
than fabricate a submission, reset the phase, resend or select another body.
Legacy manually approved relays retain their existing broker correlation path.

This component supplies restart/late-return correlation. Automatic selected-event
intake still needs the SDK's selected-thread read path and an explicitly selected
host attachment; constructing the receipt does not read an inbox, install a
listener or activate a receiving model.

## Qualification and remaining integration

Run the zero-inference suite using the pinned SDK checkout and its test helpers:

```sh
PYTHONPATH=<matrix>/src:<matrix> python3 -B tests/matrix_execution.py -v
```

The suite uses synthetic signed identities, actual native journals and loopback
HTTP/receipts, plus the existing synthetic external-approval fixture and real
SQLite execution store. Its dataclass client seam calls `GroupMessaging`. A
separate test uses the real AF_UNIX/HMAC client and synthetic daemon to reject a
mismatched being before send. These tests do not qualify a complete installed
receiving runtime, paid accounting or live cross-body execution. CI pins the SDK
source.

`tests/matrix_conversation_http_io.py` also exercises the actual native controller,
authenticated owner CLI and HTTP server around signed SDK fixtures, including
canonical returns, correction context and local-plan exclusion. Run it with the
same SDK source, existing dashboard dependencies and a qualified text binary;
reuse an unchanged binary. Add `--funded` for the funded selected-original journey.
That variant passes through the actual controller, signed SDK request/reply,
SQLite funding gate, owner callback and canonical HTTP return. It checks one
call/full worst-case charge reservation, selected-source-only access, a passive
result, one canonical return and preserved uncertainty across restart. The worker
is a controlled model-free stand-in, not an actual provider/native worker. Earlier
actual pinned-native first-use qualification is separate evidence; this fixture
does not establish real provider spending, receiving human use or automatic
integrator incorporation. CI runs both modes and two affected old-SDK legacy
journeys. Python-only changes to the four known Matrix host/test paths select the dedicated
`matrix-host` compiled canonical consumer job and the existing SDK/legacy suite,
without repeating unrelated native, voice or lifecycle journeys. Documentation
may accompany that profile; Rust, dependency, unknown-file and full-text-job
changes retain their full qualification. The actual workflow scope program is
tested, and a change to the dedicated job exercises it. The profile adds no
receiving deployment or model activation.

Production deployment, qualified receiver execution and the selected live
cross-body correction/renewal trial remain open in #367. One inference/token admission does not establish a global
monetary ceiling. No existing local routing, selected runtime or paused goal is
changed by importing this module.

### Existing signed messaging enrollment as the host owner proof

A receiving host can use `telecodex.matrix-host-binding/v2` with `source`, the
existing messaging-only client reference, and `enrollment` containing absolute
`application`/`binding` references, the signed public `identity`, and its pinned
Ed25519 `public_key`. Keep the host binding and enrollment documents in their
existing owner-only directories. The SDK's protected reader requires that private
parent as well as private, single-link files; public adapter code stays separate.

The host verifies the detached enrollment signature and exact application hash,
its messaging descriptor, being/origin, and the configured native runtime ID,
label and expected server. Each actual native call still authenticates and checks
its current messaging authority, reader selection and destination. Tampered
metadata or a different native client refuses before an effect. This permits the
already-enrolled messaging role to read/reply without depending on an unrelated
legacy `runtime.status` capability's expiry. It issues no role, renews no key or
validity, reads no private ledger and synthesizes no runtime status. The v1 host
binding remains compatible with its separate observation capability.

Use the same finite owner-selected heartbeat/resource controls. Enrollment alone
is neither model-execution permission nor proof of receipt, action or response.

The v2 owner binding may additionally select `intake_after`, a nonnegative native
inbox frontier at most2^53-1, observed through the existing authenticated SDK.
Set this only for a new intake before producer activation, under the existing
paused generation, to avoid spending model allocation on pre-pilot history.
The private owner selection filters the intake view; no native original is
removed, acknowledged, marked read or described as processed. Existing retained
parent verification and direct/manual native history access remain unchanged.

A zero consumer cursor fetches after that configured native frontier. An empty
view keeps the consumer cursor at zero; the page meaning discloses the selected
frontier. Only a genuine new native event advances it to that event's sequence.
A nonzero consumer cursor below the selected frontier refuses: this cannot rebase
an existing reader or hide its pending originals. Keep the selected window frozen
for the operation; it is not a model-supplied request argument or a reset control.

## Heartbeat user menu

The heart opens a viewport-clamped menu next to its actual button on desktop
and mobile. The normal menu presents a brief useful state and supported controls;
it omits internal generations, source-check timestamps, implementation caveats
and unsupported feature placeholders. Messages and scheduled reviews are shown
only when supported. Pausing/enabling keeps the existing generation-fenced owner
commands; status reads never change settings or start work. Only fresh explicit
operational evidence animates the heart. Pending work is described as waiting,
not as proof of readiness or a disabled heartbeat. Operator diagnostics remain
available through the existing owner status API.

## Communication card language

Ordinary Matrix inbox, response and visibility cards use brief product states
(Received, Sent, Delivered, Delivery not confirmed, Message copy or Communication)
from existing metadata. Detailed verification caveats, publication identities
and receipts remain in the existing collapsed Matrix details. Source text,
attribution, revisions, reply binding, cursor and publication journals are
unchanged. Payload-to-speech formatting and suppression of authorization-control
payloads remain with the Matrix producer's existing compact-text projection;
this presentation change adds no parser, router, publication or provider call.
