# Account-bound 3D workshop

The 3D workshop in a standalone Conversation opens a small, reversible mesh
editor. A person can prepare an exact source revision and an instruction, save
that exchange in their current account, and import a proposed revision later.
Another browser signed into the same account can retrieve that source/proposal
pair, compare A/B, and explicitly resume from the proposal. An explicit native handoff can send that saved request to a chosen existing
conversation. This source implementation does not interpret the instruction
itself or activate any model until the person explicitly sends a request.

The daimon integration is designed for numerical geometry tools and explicit
parameters. Browser clicks are not the editing protocol. These are mesh
operations; a parametric CAD constraint/history system is not implemented.

## Authority and persistence

`GET /api/interaction/atelier` lists at most32 request headers, account capacity,
and an opaque local-browser namespace selector. `POST` to that exact path accepts
only `{action:"save-request", request:raw}` or
`{action:"save-reply", requestId:id, reply:raw}`. Actor authority comes exclusively
from the existing App authorizer, grants and `interaction_only` scope. Writes
use the existing exact Origin/CSRF contract, before body buffering and again
after I/O. Monitor credentials cannot use these routes.

`GET /api/interaction/atelier/requests/{id}` returns the retained receipt and
exact UTF-8 request/optional reply. `?format=request|reply` downloads those exact
bytes, with a content SHA-256 ETag. All account responses are private/no-store.
The imported protocol's IDs and hashes bind geometry, source, instruction,
project, parent and return. They do not prove signed daimon authorship.

An immutable request is unique within its authenticated account. An exact retry
returns the same receipt; different bytes under the same ID refuse. One immutable
reply is permitted. Confirmed reads/retries remain possible if a later validator
is unavailable. Unknown save outcomes are recovered by exact GET, without another
submission. Independent immutable inserts need no shared active-selection CAS;
SQLite transactions serialize insertion, quotas and generation increments.
There is no server-side active model/head pointer to replace.

The new feature namespace is `state_dir/atelier-workshop/exchanges.sqlite3`.
It opens no existing identity, session, voice or native-input databases. It uses
the existing private-directory/file-lock conventions, owner-only files, a
bounded SQLite rollback journal, atomic quota accounting and no implicit reset,
deletion or background cleanup. Corruption/unsafe paths refuse. Existing ordinary
state backup policy applies; this feature adds no scheduler or migration.

The trusted parent holds the existing App credentials. It fences requests and
returns by current actor/credential/epoch, and exposes only the narrow same-origin
bridge to the editor. No credential or human reference is sent into the frame.
The editor requires a parent handshake before opening its browser database. Its
local drafts and moments use a server-derived per-account namespace. This
prevents accidental account mixing in the UI; same-origin IndexedDB is not an
OS security boundary against someone controlling the browser profile. Local
history is not fully account-synchronized: only explicitly saved exchanges sync.

## Resource and asset bounds

The account accepts8MiB per request/reply,32requests and64MiB logical exchange
storage per account; the whole feature allows64accounts and128MiB logical data.
SQLite has a192MiB page limit, plus at most one bounded rollback journal of
approximately that size while writing. These are storage limits, not a process
RAM guarantee. The global file lock serializes transactions. Validation permits
one fixed Node subprocess per process, with a192MiB V8 heap and12second timeout;
OS process overhead is additional. No imported code is executed. Node is already
required by the existing avatar-workshop validator; unavailable validation
refuses new material while retained exact readback works.

The parent module and account-bound editor are generic MIT source selected from
DaimonAtelier. `dashboard/web/atelier-workshop/PROVENANCE.json` records source
commit, transformation, build and exact file hashes; `scripts/verify_atelier_workshop.py`
checks the committed bundle. The source project's
`node app/scripts/export-daimonapp.mjs <destination>` rebuilds the receiving
bundle and copies only the generic editor/protocol/license selection. Private
example locators, model media, user projects, operator records and account state
are excluded. The two protocol modules and fixed Node validation entry remain
server-only; static routing exposes only `index.html` and `host.js`.

The editor carries its existing fonts and third-party license notices and uses
a response-specific script-hash CSP. Other App CSPs are unchanged. There are no
external script/font/model requests. Native/provider execution, live deployment,
fabrication, public galleries and physical-device acceptance are separate stages.

## Qualification

Run `python -B scripts/verify_atelier_workshop.py`,
`python -B tests/dashboard_atelier_workshop.py` and
`python -B tests/dashboard_atelier_workshop_api.py` using the locked dashboard
dependencies. The existing `tests/dashboard_io.py` CI entry loads both suites on Python3.11;
asset verification also runs in the storage suite. The API suite mounts
the real App middleware and shared Home authorizer with only the identity lookup
replaced by a synthetic identity response; it uses real Node/SQLite transactions.

`tests/dashboard_atelier_workshop_browser.py` starts a disposable loopback TLS
App and uses `PLAYWRIGHT_MODULE`/`CHROMIUM_EXECUTABLE` for an installed browser.
`ATELIER_CHECKS_DIR` optionally retains the report/screenshots. It exercises real
synthetic App bearer sessions, CSRF, large exchange bodies, lost acknowledgment,
fresh-profile hydration, account switching, revocation and the shipped CSP.
Certificate bypass is restricted to that temporary browser context. No real
human login, native input or inference is part of the fixture.

No deployment is included. A later receiving rollout must use the then-current
qualified full App package and existing maintainer route; rollback selects its
preceding package while preserving the new private exchange database. Do not
promote this source branch merely because isolated qualification passes.


## Explicit native handoff

The receiving drawer separates Save from Send. `GET atelier/destinations` projects
current owned session destinations as opaque choice keys and labels, with no
preselected destination or native/actor reference exposed to the frame. It uses
`Provider.session_workspace` and the existing workspace entitlement. The first
`{action:"dispatch", requestId, choice}` freezes the actual current destination,
conversation binding, one deterministic native input UUID, original text and
three original-file references. A bounded16KiB accounting reservation covers the
one immutable dispatch record per saved request. Original attachments use the
existing private original-file store and its existing256MiB capacity.

The native text explicitly identifies its application-composed envelope and the
human's verbatim instruction. Leading hashtag/control text inside that instruction
cannot override the selected session. The files contain the exact .clayrequest,
a bounded MIT numerical Node tool and an application-context guide. Their bytes
and identities are frozen before native I/O; no private example or account data
is embedded in the tool. The guide is format context, not fabricated human speech.

An atomic claim precedes one call to `conversation_input_submit`. Concurrent or
repeated Send calls inspect that same original. `GET requests/{id}/native` reads
its retained status without submitting. An unknown acknowledgment keeps its ID,
source and destination. A separate explicit `retry-dispatch` invokes the existing
native writer with exactly that frozen UUID/body; its journal owns deduplication
and retirement. It creates no replacement original or automatic retry. Prepared
but unattempted file work can be retried without a native submission.

Returned candidates come only from the exact original's existing trace, with
actual instruction coverage, current result revision and authorized canonical
artifact association. At most eight result sources and ten returned .clayreply
candidates are inspected per foreground check. Older files can be validated by
an explicit source/revision reference using the existing direct trace reader.
`{action:"collect", requestId, artifactId, source, revision}` revalidates that
association and the existing artifact entitlement, opens the existing immutable
artifact descriptor, checks size/SHA and validates the editable child protocol.
It atomically retains the reply and its input/source/revision/artifact origin.
No model-authored path provides file authority. Receive still preserves open work;
only the existing explicit A/B Resume adopts the proposal.

Workspace and artifact entitlements remain separate. This route does not enroll
or extend a credential. Existing synchronous authorization is rechecked around
slow I/O, and the existing `retain_io` path completes an owned write on client
cancellation. Source, native acceptance, worker coverage and actual human/model
use remain different observations. No background collector, provider switch,
new native client, printer operation or service deployment is added.

Qualification: `tests/dashboard_atelier_native_store.py` adds four storage/lifecycle tests: SQLite
claim/quota/atomic-origin and cancellation of the mounted owned write to the existing dashboard CI entry. The existing
`conversation_files_http_io.py` entry also runs `dashboard_atelier_native_io.py`
with its selected real native binary: actual App bearer/CSRF, owner socket and
SQLite, original-file delivery, chosen session, lost ACK, identical retry,
entitlements, canonical numerical return and restart. The numerical peer is
synthetic and uses no inference. `dashboard_atelier_native_browser.py BINARY`
with the existing Playwright/browser environment exercises the actual receiving
parent/editor through that same real native writer on disposable loopback TLS.
This source qualification is distinct from review, compatible deployment and an
actual model/human-device collaboration.
