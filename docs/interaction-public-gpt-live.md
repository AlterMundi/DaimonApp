# Optional public GPT-Live comparison

This default-off comparison uses public GPT-Live WebRTC with managed Responses
delegation. It is distinct from Realtime and OpenAI · Codex voice. It does not
replace the integrating Codex session or inherit its identity, memory, credentials,
tools or active work automatically. The [roadmap](interaction-roadmap.md) retains
those requirements.

## Configuration and selection

Use the existing authenticated dashboard and owner configuration. Never export
Codex login tokens as project keys or put credentials in the browser, URLs,
source, issues or logs. Explicit public project access and a selected backend
model are required. Private files use the existing owner-only reader; identity
and backend instructions are bounded to8KiB each. Invalid configuration refuses
startup. An unavailable key refuses activation before microphone permission or a
provider POST; it does not discover credentials.

See the commented `openai_live` settings in `dashboard/config.example.toml`.
Session/backend/delegation options pass through bounded owner configuration rather
than reducing provider features to the old manual-turn adapter. Browser overrides
are not accepted. WebRTC negotiates audio format. Total serialized configuration
is bounded to32KiB.

After explicitly configuring and qualifying this mode, select **Under the hood →
Avatar → OpenAI · GPT-Live comparison**. Activation is a human action. Existing
current-provider defaults and native Codex remain unchanged. Choice and owner are
frozen per visit; there is no mid-capture switch or silent fallback. Disable only
through scoped voice-idle maintenance, preserving journals and recovery readers.

## Capture, recovery and bounds

Server admission acquires the existing cross-mode voice lease before microphone
permission. One monotonic admission covers negotiation/capture: at most600seconds
and19,200,000input PCM bytes. Configuration may reduce this to300–600seconds;
reconnect cannot enlarge an existing admission. Local recording starts before the
WebRTC offer. Listening requires a connected peer and matching `session.started`.

Originals reuse the browser20MiB/128-record budget and receiving original store.
Engine tags isolate recovery in the historical `codex_voice` store; its name does
not select Codex. One-second fragments permit interrupted-prefix recovery; an
unsaved tail may be missing. Server receipts must match visit, binding, ordinal,
SHA-256, bytes and provenance before local retirement. **Retry saving** retains
the same original: it never reruns ASR, submits speech, dispatches work or creates
another session. Save/Discard affect local originals, not server work. Rollback
must keep a reader that ignores foreign-engine records and preserves originals.

The journal is limited to512records/32MiB,256KiB per receipt, two unsettled
creations total and one per human. Admission reserves2MiB of trusted source
capacity inside that aggregate bound. Meaningful provider events are capped at
8192/2MiB per visit and32KiB each; raw media frames are not copied. Source pages
contain at most64events/64KiB with exact revision continuation. Interrupted writes
count toward capacity. Refuse admission before billing at capacity; never evict
uncertain work/originals. No automatic retirement or per-frame log is installed.

## Review retained conversation

After reload, the comparison can restore the latest owner-bound voice transcript
without activating the microphone or connecting to OpenAI. **Earlier voice
conversation** pages one retained visit at a time through the existing journal;
its source reader follows exact byte/revision cursors, at most128pages/2MiB per
visit. Names and spacing remain the provider's automatic transcript, not a
verified human original, utterance boundary or evidence of hearing/task completion.
The interface groups fragments for display only, retains its existing64-card/
128KiB window, and does not feed this viewer history back into a model.

Failed reads retain the same visit cursor and deduplicate already shown source
IDs. **Retry voice history** resumes that read; ordinary presence refresh does
not loop failed reads or rescan a successfully restored binding. New/changed
owners invalidate pending reads before presentation. Prior histories never
replace live captions. Source/original review grants no new tools, input replay,
backend completion or new voice-call creation.

## Closing and uncertainty

One durable intent precedes one creation POST. Exact retries only read retained
outcomes. Lost responses, process loss and failed receipt commits do not authorize
another billed call. The sideband attaches to the exact opaque ID with the same
project access and receives future events only. Its trusted reader is installed
before the SDP answer reaches the browser.

Stopping capture starts a bounded30second drain of known managed Responses and
needed client continuations. One durable `session.close` is sent only when those
are complete. Unconfigured function/client work is never fabricated or executed. Trusted
`session.closed`, usage and backend completion remain separate. Missing
finalization stays unconfirmed. Disconnect cleanup detaches control, releases the
media lease and retains outcomes; it never sends close as a cancellation shortcut.
Do not delete records, change UUIDs or replay commands to clear uncertainty.
Owner-led reconciliation of interrupted public calls remains unfinished and
blocks another billed visit.

## Optional current-conversation context

The owner may explicitly select `conversation_context=true`. Managed Responses
then receives one application function, `compaii_conversation_read`, backed only
by existing authorized presentation-page and exact source/revision readers. The
browser supplies no tool calls, authority, source text or provider commands.
Pages retain their exact cursors and bounded previews; part reads retain offsets
and revisions. Ownership and paired-actor access are checked before and after
the read. Returned text is source data, not new instructions or execution proof.
This covers the current conversation, not DMK, arbitrary private sessions, native
task execution or full being memory. Those roadmap requirements remain open.

Only trusted completed function items select a read; argument deltas cannot.
At most16calls are retained per visit, each with at most4KiB arguments and8KiB
output, inside the existing256KiB receipt/32MiB aggregate journal bounds. A
result intent precedes its single `response.item.create` write. Once all known
results for that response are sent, a durable intent precedes one `response.create`.
Socket sends are not acknowledgments. A lost write/commit is never retried; restart
retains the unresolved intent and blocks close. Unknown tools remain unresolved.
The documented continuation has no separate item success acknowledgment: trusted
new Responses lifecycle and matching completion settle backend work. An old
response completion cannot close over a new running response. No native input,
work delegation, ASR retry, media replay or extra provider session is created.

Source and mounted tests cover read authorization, two pending results, resumed
completion, restart/lost-write refusal and storage bounds. Actual owner page/part
reads establish access wiring; useful model recall and physical speech need their
own receiving qualification. Keep this feature off on unconfigured receivers;
ordinary common software delivery does not enable providers or copy credentials.

## Optional provider-stored continuation

The owner may select `resume_mode="stored_fork"` together with explicit
`session_options={store=true}`. The default is `fresh`; neither remote storage nor
continuation is enabled implicitly. This choice requires project storage to be
enabled and permitted by its data policy. OpenAI documents30day availability of
stored recordings; Zero Data Retention disables this feature. Actual account
eligibility, recording readiness and useful behavior must be tested separately.
See [OpenAI's stored-session workflow](https://developers.openai.com/api/docs/guides/live-conversations#prepare-a-session-for-forking).

The first explicitly activated visit creates a stored source. On a later
activation, the server selects the unique terminal source in that owner's
continuation chain. Parent references determine this chain; wall-clock movement
cannot select an earlier ancestor. Before microphone permission or a billed POST,
the source must be trusted-closed, storage-requested, configured identically and
free of known pending/failed/incomplete Responses or needed client results.
Changed identity, voice, backend/tool policy, ambiguous source chains or missing
storage require review rather than silently starting an unrelated conversation.
Each activation retains the existing600second/PCM admission bound.

The [documented WebRTC fork](https://developers.openai.com/api/docs/guides/live-conversations#start-a-webrtc-fork)
uses the source's exact opaque ID and only a new SDP offer. Provider inheritance
carries the original model, voice, instructions and conversation; no previous
startup envelope, serialized prompt or transcript is nested into the new request.
The application retains a flat predecessor reference and configuration/request
digests. Controls and sideband attach to the new child ID. A response reusing the
parent ID is unconfirmed, not a successful replacement.

One durable intent owns each fork. Lost responses and process loss preserve
uncertainty and prevent a second fork/fresh fallback; exact retries only read the
retained outcome. Existing published fresh-call receipts keep their digest
contract. A closed event, synthetic context construction or successful fork ACK
is not proof that the next voice remembers a correction, preserves task semantics
or speaks useful results. Within a call, GPT-Live's provider-owned compaction
remains distinct from application task records and cross-call continuation.
Unexpected disconnects without trusted closure and unavailable/expired stored
recordings still require reconciliation; saved-text/semantic-checkpoint fallback
and late-work routing remain unfinished. No timeout or diagnostic context bound
is enlarged by this option.

## Qualification boundary

Mounted authorization/upload/cancellation tests and Chromium synthetic desktop/
mobile journeys cover wiring and original recovery. They make no public provider
request, use no human microphone and prove no hearing quality. Public access,
useful tasks, full identity/memory/work/tool integration, artifacts/questions
and sustainable renewal remain open. Retained transcript presentation is
implemented separately from provider reconnection and memory hydration. Follow the
[practice comparison](interaction-gpt-live-practices.md) before enabling a
person-facing trial; this is not full-stack adoption.

## Receiving sideband media observation

Actual project WebRTC qualification observed raw `session.input_audio.append` and
`session.output_audio.delta` frames on the attached sideband without event IDs.
They belong to media transport and are discarded before source-ID validation;
they are never journaled or forwarded as conversation text. Transcript, backend
and close events retain strict source identities. A synthetic spoken backend
question returned its backend-only fact, completed Responses and trusted close
with24seconds usage; this is digital qualification, not physical hearing or full
being/memory/native-tool acceptance.
