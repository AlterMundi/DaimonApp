# Daimon Interaction: qualification and next roadmap

Status: qualification is in progress against the reviewed [v0.2 executable plan](interaction-v02.md). Selected native journeys and the standalone UI have receiving evidence; full product acceptance remains open. This protocol does not authorize new capture, publication or background attention. Owner: [Daimon Interaction](https://github.com/AlterMundi/daimon-matrix/issues/313).
Design: [integrating conversation](interaction.md).

## Media transfer deadline —7November2026

Ordinary recorded-audio and selected-PNG POSTs now allow a finite120seconds,
matching attached-file transfers, instead of aborting at20seconds even while
bytes may still be uploading. Read/JSON deadlines, image/audio byte caps,
hashes, frozen targets, CSRF/authentication and recovery ownership are unchanged.
No automatic image resend is added; audio keeps its existing receipt-first,
limited same-original recovery. The image selector still coalesces concurrent
text/voice requests into one upload and preserves drafts/images on failure.

Shipped state-machine tests hold both uploads beyond25seconds and complete them
once with the same original. The image journey also expires the120second bound,
preserves its draft and selected bytes, and retries only after another explicit
send. Existing audio recovery, target and unknown-acknowledgment cases pass.
These are synthetic zero-provider checks, not human network acceptance.

Actual receiving logs show client disconnections before body reception completed
in both reported failure windows. They do not identify the exact browser request
or establish whether its20second timer, network, proxy or another client action
caused each disconnect. The hard client deadline is a verified limitation; its
removal at20seconds is not proof of the incidents' root cause. Physical-network
upload acceptance and the full roadmap remain open.

## Retained real voice native handoff —7November2026

A read-only inspection of the already retained human public-Live/native visit
verifies the following bounded chain through the current consuming owner reader.
That historical visit used the then-selected clip interpretation path; it does
not qualify the subsequently selected live-window/continuous-ASR input path:

- Two accepted native work roots retain three exact acoustic originals. Their
  original IDs, audio/text hashes, formulation, chronological capture order and
  dialogue/intent references match the separate native admission records. Both
  roots used the existing integrating native execution; no new being/thread/work
  was created by this verification. Raw capture receipts alone still do not admit
  work: the distinct retained work admissions supply this evidence.
- One canonical native progress part matches the exact retained append content,
  revision and cursor and has its trusted provider acknowledgement. This proves
  context transport, not task completion, semantic incorporation or human hearing.
- The retained voice journal is closed with capture ended. Its last filesystem
  write precedes the native final observation; this is a local retained-state
  ordering, not a provider invoice or audio-duration-derived clock. That final
  still reads completely through the current owner-bound canonical presentation
  API with the original native binding. The separate existing DMK curation/readback
  matches the genuine voice original. This supports native work surviving the
  voice connection, without claiming that the late final was spoken in that visit.

The verifier used raw read-only presentation/status operations and an SQLite
read-only connection. It did not invoke status/list convenience paths with media
retirement, repeat ASR, open a provider/voice connection, append context, replay
originals/work, curate again or modify the real visit journal. Its bytes were
checked unchanged. Private IDs, language, memory content and bounded evidence
stay in the owning operator checkpoint; no human episode is published here.

Still unqualified: a fresh voice connection actually returning that late final,
lookup/pagination from inside the live conversation, useful speech after repeated
physical replacement, semantic listening/latency/noise/interruption, real account/
phone/background/hearing and the remaining full roadmap. The next real trial is
already requested; do not synthesize a human input, re-run a terminal paid trial
or infer acceptance from this read-only chain. Existing unknown provider outcomes
retain their own journals and billing uncertainty.

## Native waveform timing observations —1November2026

One distinct three-phrase Spanish Chromium/CPU/Gemini session on **ec883adf**
records scheduled waveform onset instead of treating the first PCM event as
useful sound. Synthetic injected media passes through the shipped capture worklet,
resampler, native voice route/history and browser playback. Output is muted;
actor/original owner is synthetic. No Sol/worker/native task, production input,
physical microphone or receiving deployment occurs.

| Synthetic question | Native output caption | Last input signal → first scheduled nonquiet window | Detected end → same window |
| --- | --- | --- | --- |
| Seven times nine | Sesenta y tres. | 1.34s | 0.87s |
| Twelve plus seventeen | Veintinueve. | 1.41s | 0.91s |
| Half of ninety | Cuarenta y cinco. | 1.29s | 0.83s |

The three-case median is1.34seconds. Input end is the last synthetic16kHz sample
with absolute PCM amplitude at least128. Output onset is the first complete10ms
window with RMS at least0.001 and peak at least0.003, mapped from captured
AudioContext scheduling/currentTime to performance.now. Tiny two-byte events and
quiet buffers do not qualify. Independently back-projecting observed buffer-end
callbacks agrees within18ms in these cases; this is not a hardware clock bound.
These thresholds establish nonquiet digital signal, not intelligibility, physical
hearing or the first useful word. Correct output captions do not independently
prove that the audio said those words. Three cases are not a general latency
distribution, a controlled526 speedup or a comparison against the modular baseline.

The original trial remains **failed**: its verifier expected three originals,
but natural pauses yielded five, all confirmed with matching retained hashes and
released by the browser. Three separated response records already contain the
necessary waveform observations; a corrected verifier derives the table without
replaying any provider/native input. The synthetic owner also omitted the ordinary
original-list API, causing refresh HTTP500s. That fixture limitation and excluded
normal bootstrap/shared login prevent full-application acceptance claims; it is
not a receiving product diagnosis. No page errors were recorded.

The single provider connection, browser context and server closed; ephemeral
synthetic media/TLS/database state was removed. Selected records remain below2MiB. The declared8MiB temporary-state size check
was not reached before the failed assertion; all that state was nevertheless
removed. No raw generated PCM archive or automatic retry.
Existing phone/avatar/hearing/echo/noise/interruption acceptance and the full
stages2/3/necessary4 goal remain open. Use retained data, never rerun the terminal
trial to repair its verifier.

## Selected incomplete-text report: retained-source verification —1November2026

The exact human-selected historical reply remains complete in the receiving
revision-scoped API:327characters, compared with its240character preview. One
task-relevant long voice original also retains all1149characters, compared with
its1000character list preview. This establishes retained text availability, not
word-for-word acoustic transcription accuracy. Private texts, IDs and screenshots
remain in the receiving operator's bounded selected-source evidence, not here.

A model-free readonly Chromium Conversation fixture uses those exact retained
responses at315and390px. Visible text automatically loads to completion; Copy
captures the exact complete reply/original privately without OS clipboard writes.
Visual inspection includes both terminal passages. Zero API writes/native
submissions/model calls/page errors; owned contexts/browser close. Ordinary
app.js/shared-login bootstrap, device cache and actual phone behavior are excluded.
This verifies the selected cases on the tested renderer, not every historical
message or a new phone acceptance claim.

An independent coordination rollout changed the receiving selector during this
review. Earlier content checks and a later served-asset check are retained as
different observations. The final check pins immutable14bb2bd6 source files:
**UI8248d1a370a0**, identical Conversation JS bytes at both viewports, local and
public HTTPS, and matching public shell build. That rollout is not this
operation's deployment or qualification of coordination features. The native
voice/worker qualifications below retain their own70857ee7source snapshots.
A model-free stub pathname correction is retained; no model/input replay,
retention change or replacement text was used. No new product regression was
reproduced in these selected cases on the served renderer.

## Rendered Conversation, real worker and interruption —1November2026

A further distinct qualification joins the shipped Conversation/avatar modal,
IndexedDB original retention, capture worklet and browser output in real
Chromium390x720 with actual CPU endpointing, Gemini3.8 speech, selected
Sol6.1/openai/medium integration and one actual Sol worker. Input is a task-owned
synthetic48000Hz MediaStream, resampled by the shipped worklet to16000Hz. The
actor is synthetic; normal app.js/shared-login bootstrap and optional integrations
are excluded. This is a rendered Conversation integration, not phone acceptance.

The new work request enumerates the first60primes and returns only their sum
in speech. While the actual worker runs, a casual eclipse explanation stays in
the foreground. A third injected phrase interrupts that explanation and changes
the question to six-times-eight. The foreground produces48, then presents the
canonical7699work result after Sol incorporates the complete independently
verified60-prime report. One continued return subscription, one actual worker
instruction/result. Two native integrator physical turns/one user message and
one actual worker turn are terminal/archived/notLoaded. Four automatic originals
retain independent browser/native/prepared hash and text correlations; only the
firsttwo are delegated. The casual/correction originals stay foreground-only.
Browser originals release after matching confirmation; completed transient native
capture files retire under the existing durable-transcript contract. No new
media archive or changed retention is required for verification.

The test-input injection request precedes the browser AudioBufferSource.stop
call by96.8ms. This is one stop-call observation, **not rendered acoustic silence,
physical hearing or word alignment**. The interrupted eclipse utterance retains
93728browser-reported bytes out of448320generated. The correction and final sum
respectively retain107522and276482generated/browser-reported bytes, closed and
uninterrupted. All output buffers end or stop, capture track and audio contexts
close, the owned browser/server stop, and the page reports zero errors. Visual
inspection confirms the final result fits the390x720avatar modal.

The existing controller again rejects an earlier foreground-only source selected
for routing before Sol inspects/selects the accepted formulation root: two
attempts, one admitted task, no task replay or cancellation from the interruption.
Retained inspection confirms the correct input_ref and explicit routing guidance
already existed in the actual native packet; do not diagnose a missing field or
weaken admission based on that model selection error.

The first browser preparation used the engine active getter, which also includes
starting, and tried to inject PCM before capture existed. Its socket closed
before initial metadata/provider opening: zero originals, both empty native
threads archived/notLoaded. The corrected verifier waits for the actual state
active=true/starting=false. This continues a known-unadmitted preparation; no
model work was replayed. A later retained verifier initially looked for a WAV
that the existing completed-transcript cleanup had correctly retired. Its
correction compares the independently recorded hashes/text and expected cleanup,
without reconstructing media or repeating the completed journey.

This advances the joined digital experience. Physical microphone/hearing,
echo/noise/music, phone interruption, actual shared-login/bootstrap in this
journey, useful intelligible-sound latency distributions and the complete
stages2/3/necessary4 with retained Android/Beacon/iOS/base remain open. Existing
accepted login/client qualifications remain separate; production519/UI/APK did
not change for this trial.

## Actual worker and conversational concurrency —1November2026

One distinct mounted journey on qualified source70857ee7 uses real CPU
endpointing, Gemini3.8 speech, the selected Sol6.1/openai/medium integrator and
one **actual Sol worker**, with synthetic actor/audio/task data. It starts one
worker request to enumerate the first100primes and calculate their sum, then
asks seven-times-eight conversationally while that worker runs. No simulated
worker answer, production input, hardware capture or previous request replay.

Four automatically retained originals preserve prepared text/audio/hash
correlations. The first two reach the actual worker in one attributed
formulation; the two casual originals stay foreground-only. Actual native reads
show two completed integrator physical turns with one human input, and one
completed worker turn. Both test threads are archived/notLoaded. The actual
worker's100prime list and24133sum match an independent arithmetic check; its
complete report is preserved in the sole canonical worker result. Sol returns
only the requested spoken sum, through the same continued foreground watch.

The closed generated casual utterance, “Cincuenta y seis,” precedes actual worker
completion by7848.68ms. Worker execution lasts17101.17ms. Its completion precedes
the canonical result offer by7013.21ms; the foreground generates the correct
Spanish24133response. Those are one journey's event intervals, not first
intelligible/physically heard sound latency or provider-cause attribution.
Generated PCM totals92162bytes for the casual answer and263042for the sum;
there is no browser/player acknowledgment or hearing observation in this trial.

There are **two dispatch attempts, one admitted instruction and one worker
result**. Sol first selects an earlier foreground-only source ID, which is
ineligible as the routing root. The existing controller rejects it; Sol reads
retained inputs/target inputs and selects the accepted formulation root. No
worker task is replayed or duplicated. Keep that observation separate from
successful actual worker incorporation and conversational concurrency.

Retained exact native/worker reads and bounded verification distinguish this
from the earlier synthetic-worker evidence. One provider connection, two
preselected native test threads and bounded isolated fixture data; no receiving
change or new APK. Full phone/avatar hearing, useful latency, echo/noise/music
recovery, interruption/correction in one real journey and complete roadmap
acceptance remain open. Do not rerun completed models to repair observations.

## Native timing observation —1November2026

Read-only derivation from the retained canonical-question journey measures
523/489ms from detected phrase-end event to original confirmation and
2027/1797ms to the next generated audio event. The question offer reaches its
first audio event in451ms; the canonical result offer does so in432ms. The
synthetic worker return emission precedes its canonical integrator offer by
8986ms, with integrator commentary at6020ms. These are one journey's observation
intervals, not isolated provider causes or a distribution. Its first audio event
contains just two PCM bytes and raw output was not retained: nonzero/intelligible
or physically heard audio timing cannot be recovered. The admission-wording
overstatement is separately retained and corrected below. No native source or
unmarked commentary is promoted to a canonical return merely to improve timing.

The native client was absent from the existing Browser voice timing hooks.
It now supplies original lifecycle and separate output-event marks to that same
bounded page-local inspector. Tests cover first marks, missing values, eight
original/sixteen source-output limits, Clear/binding reset and no implicit
phrase-response pairing. The shipped native engine's hook tests retain exact
scope, recovery, interruption and cleanup; legacy Conversation/timing tests pass.

A real390×720 Chromium/full-shell/native/modal/IndexedDB check observes those
marks through the actual Conversation hookup and inspector, with a retired
queued question and a fresh completed result. Clear removes them. The exact
original and frozen scope/release remain intact; zero POSTs or page errors,
track/context/browser closed. A missing interpretation event stays not observed.
Capture/socket/owner metadata and muted output are synthetic, with no CPU,
provider/Sol/worker or physical hearing/latency claim. Bounded evidence is retained
under4MiB. The pending phone trial and full roadmap remain open.

## Admission acknowledgment evidence limit —1November2026

Read-only inspection of the successful canonical-question journey found a
separate wording defect: first generated audio said the request had already
been transmitted to Beta3.038s before the recorded synthetic worker acceptance.
The preceding receipt proved integrator admission only. The completed native
response/result observations remain valid; they do not erase this premature
speech claim. Generated-event ordering is not physical heard timing or evidence
of the provider's internal cause. No completed original or model work was replayed.

The existing bridge admission now explicitly names the integrating conversation
as recipient and says worker delivery is not established by that receipt. This
metadata and the native speech instruction apply to both initial work and short
answer/correction admissions. Separate canonical returns remain authoritative
for stronger claims.15bridge,24dialogue and20mounted voice checks pass, covering
both admission forms and unchanged continued returns.

One distinct bounded actual Gemini/real-bridge qualification with a synthetic
owner spoke: “He enviado la solicitud para preparar las opciones de título para
tu receta.” It recorded one synthetic integrator admission and zero worker
delivery. This is one observed wording, not universal model compliance. Exact
source hashes, synthetic original, receipt and output text are retained under
4MiB. The stream, bridge and feeder close; no Sol, native worker, production
input, browser, hardware, playback or general latency acceptance is implied.

## Canonical question, scoped answer and full-avatar follow-up —1November2026

PR512 is merged and receiving-adopted at source2f7bbdf4b482,
UIf26ddac2f03e, after CI41340001753 SUCCESS. The existing return watch offers
full canonical pending questions/choices. The same voice socket supplies exact
capture-version availability before question audio; the client freezes it at the
first local acoustic marker. Later revisions cannot widen that phrase, and
absence of a marker keeps the earlier arm-time fallback. Answers still require
retained originals and actual Sol/native controls.

An actual mounted Gemini3.8/CPU/Sol6.1 qualification at b8bfa572 asked the full
brief/detailed question, retained two exact originals, delivered one exact native
response to the synthetic worker and voiced its returned result through the same
continued subscription. Four native ACKs share one completed physical turn with
two native user messages. The synthetic peer did not emit serverRequest/resolved:
its retained question row became unknown when the fixture stopped. This does
not prove a resolved-question receipt or independent worker-model uptake.
Separate existing actual-native roundtrip/multi resolution tests pass. Completed
provider work was not replayed to qualify the final availability-metadata delta.
20mounted voice/15foreground/24dialogue checks and client scope regressions pass.

A separate actual Chromium390×720 check uses the **shipped full shell**,
Conversation, native client, voice modal and IndexedDB owner. Synthetic socket,
capture and canonical-question metadata reproduce the race against ordinary
For you refresh. The first acoustic marker captures the offered version; a
later version does not change the retained3244byte WAV's scope. The complete
question, interim answer and returned-result captions are visible. Queued old
question audio is retired at interruption and never acknowledged as played;
a fresh result schedules/ends9600PCM bytes after the matching phrase ACK.
The original leaves local recovery only after its exact completion hash, without
Send or any POST. Returning to Conversation marks interrupted generated text
and stops the capture track. No page errors were observed; the result caption
fits the viewport. Screenshot and bounded terminal evidence are retained.

This browser check uses muted output, synthetic capture/socket/owner metadata
and no CPU/provider/Sol/worker call. It complements the separate actual-provider/
native journey and existing active-playback waveform checks; it is not one full
physical journey or hearing/latency proof. Context/browser close at exit;
retained evidence is bounded to4MiB with no ongoing job. Phone acceptance,
echo/noise, real worker-model uptake and useful latency remain open, as do the
same full stages2/3/necessary4 and retained Android/Beacon/iOS/base obligations.

## Retained native speech/Sol page qualification follow-up —1November2026

The deployed PR504 backend and its native-provider paged-return check are recorded
in the maintained receiving operation. A further actual mounted Gemini/CPU/Sol
journey split one synthetic clip into three sentence originals. Inspection of the
already-completed Sol turn verifies that all three exact source texts, hashes,
order and prepared-transcript/audio-hash correlations reached Sol in one
attributed foreground formulation. It is not proof of a returned long report.

The fixture called `answer_worker` after a durable queued instruction appeared,
before the simulated worker registered its native turn. The resulting
`KeyError: native-topic-7` stopped the fixture before it emitted the worker result.
Queued instruction retention is not native worker acceptance. The shared fixture
helper now waits for that started-peer observation before answering. Existing
canonical-routing journeys pass with the unchanged qualified native binary.

The real synthetic Sol turn was read terminal/completed and archived. Its
queued/submitting worker instruction remains uncertain and retained; it was not
replayed, requeued or marked returned. No new model work was used to repair the
verifier or inspect the retained source context. Whole actual-Sol paged return,
physical device/hearing and useful-latency acceptance remain open. Do not rerun
that terminal journey; use its retained state for any further observation.

A subsequent **new** synthetic request qualified the changed PR506 policy through
the mounted app, actual manual Gemini/CPU activity and actual Sol6.1/openai/medium.
It retained three exact sentence originals in one source-bound formulation,
dispatched once to an isolated simulated worker, and stored its complete
1851character report unchanged. Actual Sol read that same report at offsets0and1600
under one exact return revision, then returned the requested conclusion as a
short canonical answer. The foreground generated that conclusion with196322PCM
bytes in a closed, uninterrupted utterance. There were two native ACKs (original
input and internal return continuation) in **one physical completed turn** and
one native user message, not two separate physical turns. The completed isolated
Sol thread was read terminal/idle and archived.

The initial observer for this new request timed out because it required a
foreground page query. That query was correctly unnecessary: Sol had already
read both worker pages and the canonical first page contained the entire requested
conclusion. Retained verification proved the full report hash, both actual Sol
source reads, canonical text/revision and final generated utterance without any
new model/provider/native submission. Keep the raw observer timeout and corrected
outcome evidence distinct; do not rerun successful work to repair the verifier.

Qualify the requested source-preserving outcome rather than requiring pagination
at a particular layer. A foreground reads further offered pages when a requested
detail is absent; it can answer directly when the integrator already supplied the
complete requested detail. The earlier direct-provider/simulated-owner page test
covers the first case; this actual-Sol journey covers the second. It does not
establish actual-Sol foreground pagination, an independent worker model, browser
rendering, physical microphone/playback/hearing, real echo/noise or general
useful-latency acceptance. The earlier unrelated uncertain worker submission
remains retained and was never replayed.

## Browser capture and native-provider follow-up —1November2026

A bounded owned Chromium qualification now exercises the shipped microphone
AudioWorklet/resampler, native conversation client, actual CPU endpoint detector,
mounted backend and selected Gemini3.8 dialogue together. Its fake mono input
runs at48000Hz; the shipped worklet delivers16000Hz PCM. Two automatically
closed sentence originals match their retained WAV hashes and are released only
after confirmation, without Send. One real provider connection answers the
synthetic eight-times-nine question correctly in Spanish. All11real Web Audio
buffers end; the closed, uninterrupted utterance records147360generated and
acknowledged played bytes. The observed detected-phrase-end to browser playing
interval is753ms in this single synthetic trial, not a final-speech-to-heard or
general latency measurement.

The local owner remains simulated: there are zero Sol calls or worker
admissions. This is a qualification page using the shipped clients, not the full
avatar/conversation shell or human shared login. Output is muted; Web Audio
scheduling, source completion and byte acknowledgment do not establish physical
hearing, waveform fidelity, microphone behavior, echo/noise handling or phone
acceptance. Both audio contexts, the capture track, CPU worker, isolated server
and owned browser profile finish/close; bounded evidence is retained locally.
The earlier model-free browser run separately verifies the same capture/endpoint
and original-confirmation path with simulated provider audio.

An earlier actual-provider fixture failed when its owner returned a raw leading
transcript space instead of the real owner's normalized outer whitespace. A
model-free bridge reproduction confirmed that mismatch. The shared test owner
now follows the existing native normalization contract; a mounted regression
keeps the prepared interpretation byte-exact while checking the normalized
retained text. This is a fixture correction, not a deployed backend repair.
Earlier failed fixture attempts and their diagnostic corrections remain retained;
none of their original/model work was replayed to repair the observer.

## Product outcome

One habitual text/voice conversation lets a person discuss ideas and advance
several complex, persistent work contexts. Sessions can progress concurrently;
the person can correct work, answer questions and receive useful progress without
manually managing queues or interpreting transport metadata. A simple button is
enough to participate. Read-only inspection remains available beneath the simple
surface. Fluency means useful coordination, not imitation of a serial human chat.

The immutable `daimon-interaction-v0.1.0` tags mark the first functional baseline,
not daily-use acceptance. Keep that milestone while improving the experience.

## Native foreground qualification

The1November native foreground is specified in
[interaction-voice-foreground.md](interaction-voice-foreground.md). PR496,
sourceba9ed22/mergeeb119c06, passed complete CI41303898080 and
Android/decoder41303898081. Receiving UIc99f1b340f67 has21verified local/public
assets and matched native/backend/worker/completed-reader support. Existing
collectors, goal definitions, native daemon, unknown inputs and ordinary speech
paths were preserved. Deployment is not full milestone or human acceptance.

One bounded mounted journey used actual Gemini3.8 native input/output and an
actual Sol6.1/openai/medium integrating root, with synthetic actor/worker/audio.
Two exact originals and completed interpretations were retained. Sol admitted
and dispatched the work, native speech continued while the worker was pending,
interruption was observed, and the returned recommendation was generated as
speech through the foreground. One nonblocking generator delivered acknowledgment
and result on the same call. Both actual native turns completed and their
task-owned root was archived. Do not replay those originals, models or qualifiers.

54focused transport/bridge/acoustic/mounted tests,12CPU activity tests and33legacy
live-transcription tests pass. Generated-audio intervals were11.036s after the
first endpoint,1.094s for the following conversational response and638ms after
the canonical offer. These are not rendered-browser, physical hearing, general
latency or barge-in-to-silence acceptance. The first response remains materially
slower. The human was notified of the actual UI and asked one browser/avatar
pause/automatic-response/interruption trial. Keep that pilot stable during the
trial; long utterances, useful questions/corrections, heard context, echo/noise,
device behavior and the full roadmap remain open.

Retained failures explain the current regressions: native ownership normalizes
outer whitespace while prepared interpretations keep it; canonical returns can
use source-linked integrating commentary with an empty final answer; metadata
can change without a new row cursor; the model did not rearm a completed
one-shot watch. The watch now streams distinct canonical sources using documented
`willContinue`, at most160responses, without repeating admission. Stale sources
are skipped and the bounded session window is revalidated on invalidations.
The cursor reproduction is independent evidence, not a claim that it caused
every missed return. The timeout observer was also corrected to read
`assistant_utterance`, the route's actual text event, rather than raw output
transcription events.

A generator trial stopped before offering its worker result because its second
phrase had no endpoint. Offline replay of the exact synthetic PCM hashes with
warm VAD/history boundaries reproduced one legacy endpoint versus two with the
native acoustic fallback, the latter after1632ms quiet. The second clip alone
did not reproduce it. Native mode explicitly selects1600ms measured acoustic
silence when semantic scoring does not close a phrase; ordinary ASR remains
unchanged. The successful whole-provider case used semantic endpoints, so do
not describe it as provider acceptance of that particular fallback case.

A WebSocket context ending does not prove resource closure. Forced ASGI
cancellation exposed skipped cleanup; provider closure now precedes separately
shielded bounded cleanup, with actual close receipts in the mounted regression.
Cancelling a provider proposal/watch does not cancel native work. An unoffered
canonical reference can return to a later watch; an attempted response is not
replayed. Reuse the bound `Native.read` method for metadata-only native reads
instead of executing its source with incomplete module globals.

The Android background-decoder fixture backgrounds its actual task, observes
`STOPPED`, and rechecks `CREATED` before later replies. Run41297782951 established
a transition timeout, not its underlying cause. Current emulator CI passed the
updated lifecycle/decoding/focus assertions; physical device acceptance is separate.
Observe actual CI conclusions: `gh pr merge --auto` can merge immediately when
branch checks do not defer it, so that flag alone is not a wait for qualification.

## Browser observation discipline

Use synchronous `waitForFunction` predicates for local browser readiness. For
asynchronous IndexedDB/hash/network snapshots, perform bounded `page.evaluate`
polling and validate the exact returned snapshot. An installed Playwright polling
implementation can treat a Promise as truthy before its eventual false result;
an async predicate then returns early instead of waiting. Read the installed
implementation and reproduce that boundary on an empty local page before blaming
the app. Preserve the original failed observation; complete missing reads from
retained state without repeating provider/native work.

Inspect the receiving executable's actual hash and owning adoption receipt before
starting a new real-provider fixture. A stale fixture pin is not a reason to
replace the live binary. Known-unadmitted preparation can continue once after
reconciling the qualified artifact; retain its failed preimage and prohibit replay
when any original/provider/native admission is uncertain.

Synthetic native peers must not publish completion merely because a
`turn/start` packet arrived. The late-artifact qualifier now waits for the
matching retained `native_collections.first_turn` in the running local turn,
then emits its synthetic answer/completion. Delaying the fake ACK/start by250ms
reproduced the old verifier failure; the same compiled CI executable passes when
the qualifier waits for that actual start. Keep the artifact cooldown/retention
checks intact. This is fixture synchronization, not a new product repair or
permission to replay native work.

## Complete visible message text

Visible canonical answers remain eligible for the bounded text reader when a
later correction is pending or the source belongs to an earlier native binding.
Those labels still describe provenance/currentness; reading historical text does
not authorize automatic speech, replying to a worker, replay or task completion.
The existing source/revision reader continues to enforce actual read access.

App and observed Telegram originals use the same two-reader visibility queue.
A1000-character preview is expanded through the existing read-only original-text
parts, including voice transcripts. Keep the exact input identity/generation,
Unicode offsets, original prefix and finite12-part/16000-character automatic
budget; longer text retains an explicit continuation. Metadata refresh preserves
already-read text. Failures expose a reading retry without resending, answering
or overwriting the saved original. Copy still reads the full original separately.

## What existing evidence establishes

Evidence types are distinct: synthetic automation, real native/provider execution,
and observed human use. Reuse retained evidence when the relevant code and conditions
are unchanged. Re-run the affected scenario when a change invalidates it; do not
repeat all model work after every cosmetic edit.

| Capability / owning work | Existing evidence | Still needed |
| --- | --- | --- |
| Text ingress, durable originals, steering, returns and recovery (#109–#113) | Automated process qualification; selected real native journeys | Broader combined journeys and normal daily use |
| Observer, semantic route/clarification/new context, explicit local addressing (#114–#116) | Source-linked implementation, synthetic routing comparisons, bounded receiving checks | Held-out human intent, summary fidelity across changing work, adapter-specific dependency returns |
| Many retained contexts / execution budget (#117) | Synthetic 20-context scenario; real two-worker overlap | Mixed sustained use; 20 retained contexts must not be described as 20 paid concurrent workers |
| Voice (#118, Integrators #4) | Real ASR/TTS and native journey; human confirmed hearing the routed reply on 2026-10-19 | Everyday audio timing, background/reconnect and bilingual usability |
| Monitor (#170) | Retained graph and browser qualification | Comprehension and unobstructed small-screen use |
| Selected visual references (Integrators #5) | Bounded selected-reference implementation/qualification | Combined user journey; not continuous video perception |
| Observer interviews (#119) | Explicit selected interview / source-isolation slice | User evaluation of useful interviews; no automatic publisher acceptance |
| Web repair (#196) | Direct-topic isolation, canonical returns, correction and receiving checks | Regression across surface switching and historical requests |
| Native mobile/badge, cross-body routing, continuous audiovisual interaction | Future work or limited research prototypes | Not delivered as part of this baseline |

The human voice round trip confirms one successful real journey. It does not
establish statistical routing accuracy, faithful summaries for every session,
or complete coverage of the interactions between implemented features.

## Current implementation and evidence

The independent conversation UI increments in #243–#246 are merged and deployed.
The retained UI release `d65ff7a` had matching served companion script and stylesheet
bytes. Its unchanged layout evidence remains applicable; #221 tracks the later
Beacon revision-3 source and actual receiving selection. Populated browser checks cover complete visible
reply expansion, collapsed inspection, narrow layout, finite glyph changes,
reduced motion and Beacon controls. A receiving check reads actual private state
with a temporary scoped QA device; only access bootstrap is adapted, and the
device is revoked afterward. It is not human shared-login acceptance.

Rejected Source hum revision 2 used a 65 Hz anchor, weighted natural partials,
slow breath and an 18 Hz amplitude texture. Offline Web Audio measurements cover
spectrum, bounded transitions and exact mute/voice-priority silence. Receiving
state and browser activation are observed separately from physical hearing.

Retained real native journeys cover parallel work and corrections, question
answers, semantic observer repair, unhinted routing, artifact return and logical
continuity. Their source revisions and outcomes differ: a recovered goal artifact
return must not erase the original failed campaign boundary, and earlier native
evidence does not establish that every scenario passed on the final release.
Reuse matching evidence, qualify affected changes and retain unresolved cases.
The native writer and listener were preserved during these web-only deployments.

The subsequent #249/#250 listener adoption preserved three active native
collectors and their goals/accounting. A real two-worker finishing journey on
that exact executable exercised direct input during the same active routed
execution: no extra router admission, later correction reflected in the actual
file, independent other-worker completion, one destination answer and a retained
canonical integrating return. The authorized file was downloaded and matched its
hash. Missing verifier observations were completed against retained API data,
without repeating model work. The representative delivery request and canonical
result ID must not be confused with full membership and delivery identity.

The Codex#7 foreground client passed full CI and rendered a synthetic notice in
an actual TUI, with unchanged native turns and daemon. New normal local launches
select that client. Subsequent real-native qualification cleared one explicitly
selected paused scratch goal without worker speech and retired an actual routed
worker task through the integrator. The native receipt and withdrawal provenance,
correlated integrating results, destination publication receipts and real owner
journal were inspected. The actual TUI rendered both retained notices without
another worker turn or action replay. Telegram HTTP receipts in this campaign
are synthetic; they are not human Telegram perception.

The final busy-collector case resumed a paused goal while ordinary direct work
was active. The native receipt reported `steered` in the same physical turn; the
ordered clause changed the actual JSON file, the goal completed, and the actual
already-ready TUI displayed the control notice. The canonical integrating answer
and authorized file bytes were verified separately. A missing source-topic reply
was a real #215 publisher defect: a direct-origin publication was suppressed after
its primary return selected the integrator despite enabled secondary projection.
#253 fixes that condition. Its process regression fails on the prior executable
and passes on the qualified candidate. The candidate delivered the original two
proven-unsent fixture progress/final publications once, preserving their IDs and
file bytes without repeating native/control/model work.

A subsequent actual-provider V08 case held retained copying and source multipart
upload while the same worker accepted ordinary direct and routed continuations.
An idle fixture restart recovered the byte job without native replay; downloads
matched exact bytes/hash, the direct-only file stayed outside the integrating
audience, and a deliberately lost upload acknowledgment stayed uncertain across
restart without resending it. These are exercised conditions, not universal fault
or routing-accuracy claims.

Initial CLI startup observations were inconclusive. An instrumented read-only
reattachment later issued its first owner query at 14.591 seconds, received its
response in 0.0008 seconds and displayed the notice at 15.302 seconds. The already-ready
live control case subsequently passed. Startup, owner transport and rendering
must remain distinct; no universal cold-start timing guarantee is asserted.

## Receiving checkpoint — 2026-10-21

| Component | Selected qualified source | Evidence |
| --- | --- | --- |
| Independent web | `d65ff7a` | Served assets/private reads, populated narrow/keyboard layouts, full readable answers and collapsed inspection; automated access bootstrap adapted |
| Listener | PR #253, tested commit `fcaf7623`, SHA-256 `ff0aed983258dececdc0466ce5d00557fc1d477320fbeb24446da0310ddd56b1` | Full qualification run 39629205705 and retained real-native busy result recovery |
| Marker observer | PR #254, head `65f5bfa` | Forty-eight local tests, qualified run 39631734758 and receiving Telegram marker acknowledgment |
| Next-launch local CLI | Codex#7, tested commit `f309a1d` | Full native CI, actual retained goal/task notices and an actual live busy-goal notice |

The writer-preserving listener/observer adoption kept the native daemon, current
collector, goal definition/accounting and application configurations unchanged.
A missing catalog name was reconciled from its actual retained bot-authored
Telegram rename observation; it was not manufactured human speech. The observer
received acknowledgment for the goal marker while preserving the canonical name
and unknown Telegram lifecycle. Its finite connected inventory retains unknown
native state and recency rather than guessing. Existing running CLI clients keep
their loaded code; no other body's adoption is implied.

Implementation slices #203/#108/#210/#214/#215/#216/#241 are delivered. Stage #208
and #61/#213/#221 remain open for human comprehension, visual and physical sonic
acceptance. Automated/native evidence for Q01-Q21, V01-V08 and S01-S05 is retained
by method and source; human H observations are not filled in by code review,
synthetic accounts or favorable digital measurements. This is not full product
acceptance. Use the short human journeys below; do not replay completed technical
work for a subjective review.

## Current experience acceptance

On 2026-10-26 the human accepted the independent app and integrating channel as a
solid, reasonably reliable and versatile functional base. The immutable tag is
`interaction-functional-baseline-2026-10-26`. Compact controls and the click-free
revision-6 Beacon have specific human acceptance. Preserve those results while
qualifying the remaining #213/#221 refinements and the complete v0.2 campaign;
this does not claim universal aesthetic, background-phone or multi-user acceptance.
Shared Matrix authentication remains the existing access path, without a Telegram
launch requirement. The product direction includes a future native/badge client.

For each changed UI journey, inspect the actual served revision on desktop and
phone: chat/composer first; the initially closed header inspector opens into a
readable scrolling overlay and closes without losing the underlying draft,
recording or selected image. Exercise long histories, live questions, intermediate
results, perceptible expression/rest changes and reduced motion. Interaction uses
the explicitly selected authored appearance; Sessions keeps its existing consumer.
The header shows the selected daimon and authenticated human on two lines, with no
second name under the inspector. A fixture screenshot is not phone acceptance.

For remaining sound checks, distinguish browser suspension, quiet/passive
evidence, unavailable observation and synthesis failure. Preserve the accepted
40.4 Hz sine composition and smooth continuous carriers. Measure changes to
mix/transitions device-free, including 18% reply ducking, recording arbitration
and mute; physical listening remains a separate observation. Reuse the existing
click-free phone acceptance instead of treating it as unheard again.

## Execution method

Complete the integrated v0.2 implementation first, then run this campaign with
real native sessions. Development fixtures can run throughout implementation;
they are not a substitute for the post-implementation real-session campaign.
Track each requirement, implementation PR, receiving revision and case result in
[v0.2 milestone 8](https://github.com/AlterMundi/telecodex/milestone/8),
coordinating issue #208 and Daimon Interaction Project 14. Preserve private
originals/receipts locally; publish concise nonprivate evidence and failures.


1. Use existing deterministic/process fixtures for ordering, fault injection,
   duplicate delivery, budgets and permissions. No model or physical recording
   is needed for those invariants.
2. Use a small number of real native workers for incorporation, semantic context
   and result correctness. Prefer inexpensive configured models; increase model
   capability only when task semantics require it. Verify task effects, not just
   a worker's completion declaration.
3. Use a short phone session with the human for actual intent, visual comprehension
   and hearing. Automate setup, measurements, assertions and cleanup. Ask the human
   only for judgments or physical behavior that cannot be established automatically.
4. Follow with ordinary use over several days, recording defects without requiring
   the human to follow a script all day. This establishes ecological usability;
   it does not replace fault-injection checks.

Each executed row records source revision, relevant configuration/model, case ID,
retained original/result identities, expected outcome, observed outcome, evidence
class and unresolved defect. A small campaign report links existing journals and
receipts instead of duplicating state. `Not run`, `failed`, and `uncertain` remain
distinct. Resume missing observations; never replay uncertain work to improve a report.

For Q10/Q11, retain a definitely-unsent worker instruction, recover it from the
same client with its original identity, and lose that recovery response. A saved
status check must prevent another native submission. Verify refusal for an
uncertain/accepted instruction, unrelated original, retired entry and read-only
grant; historical evidence remains intact.

For Q17, inspect each key control’s bounds with populated voice status and the player visible; document-level overflow alone can miss clipping inside a scroll container. Growing transcripts and replies must preserve live following, while updates must not move a reader browsing earlier history. Explicit text/voice submission returns to the live conversation. Exercise a long multipart spoken reply and a visible Update from card: Follow advances inside the actual audio segment, resumes without jumping to the beginning, suspends while hidden/paused/inspecting and while the person holds a scrolling gesture. Releasing the finger returns to spoken progress without changing the Follow checkbox; wheel/keyboard scrolling waits briefly for the gesture to settle. Only an explicit checkbox change disables Follow. Check Voice off, unknown duration, Unicode offsets, source replacement and reduced motion. Position inside a segment is approximate; do not claim word-level synchronization.

Use isolated test credentials/workers where needed. Preserve the human's browser session and existing device grants. Use synthetic destructive scenarios. A global Stop requires
a fresh explicit human request for that operation, including during testing.
Hardware capture and shared-device tests need their actual authorization/window.

## Acceptance scenarios

`A` means deterministic/process automation, `N` real native/provider execution,
and `H` human judgment. These are evidence needs, not separate mandatory test suites.
Combine rows in a few reusable journeys wherever practical.

| ID | Action | Expected user-visible result / evidence | Method |
| --- | --- | --- | --- |
| Q01 | Discuss a possibility without requesting work; then explicitly request action | Useful local discussion; dispatch only when warranted. Inspect actual admissions | A, N, H |
| Q02 | Use a deliberate leading selector, reply to a result, then override reply focus; quote a selector as content | Selected destination follows explicit intent; quoted/incidental tags do not launch work | A, H |
| Q03 | Offer overlapping topics with different relevant histories; add an ambiguous message and a genuinely new subject | Route from source-linked context; ask when necessary; do not manufacture a session to escape ambiguity. Compare with the human's intended acceptable outcome | A, N, H |
| Q04 | Let two meaningful tasks overlap and finish in reverse order while continuing discussion | Both keep progressing; intermediate communication and final results remain attributed and legible; neither result disappears behind the other | A, N, H |
| Q05 | Correct a running task; also delay preparation of an older voice input until newer text is accepted | Appropriate steer/interrupt reaches work in time; later-captured correction prevails in actual output. Inspect native acknowledgment and task effect separately | A, N |
| Q06 | Change context after an observer card was generated; include a retracted fact/open question | Refresh uses the relevant delta/source cut; correction survives consolidation; a recorded structured answer is distinguishable from an unanswered question and from native incorporation; stale or unavailable context is visible rather than invented | A, N, H |
| Q07 | Trigger a worker question while other work is active; answer in ordinary text/voice conversation; let another agent-issued task become obsolete | Short action-first request with a clear reason/reply method; actual answer reaches the correct live request without duplicate entry. Withdraw obsolete tasks with a reason, distinct from human completion. Canonical durable tasks also appear in For you, with complete action text and text/voice reply context; reading never resolves them. Later direct-only tasks stay out of the integrating scope. No buried question, fabricated expired-channel answer or stale control revival | A, N, H |
| Q08 | Explicitly address another local topic from a session | Authored dependency and correlated return stay visible; no quoted dispatch, recursive activation or silent unsupported adapter path | A, N |
| Q09 | Stop playback during speech; separately issue a task-specific cancellation/interrupt | Audio stops promptly without silently cancelling work. Execution cancellation has its own matched evidence; uncertain external effects are not called rolled back | A, N, H |
| Q10 | Reload, lose connectivity, suspend/background the phone, then reconnect | Retained inputs/results recover once; no automatic replay of uncertain dispatch or surprise replay of old audio; fresh useful progress is distinguishable from history | A, N, H |
| Q11 | Fail ASR, routing, a worker and TTS at their respective boundaries | Retained state explains the problem, text remains usable, known-unsent and uncertain work differ; no invented transcript/result or retry side effect | A, selected N |
| Q12 | Deliver a final answer covering several old requests; deliver the same native event twice | One canonical presentation per requesting conversation, correction-aware revision/history; no copy per historical request and no visible metadata tail | A |
| Q13 | Use routed work and ordinary direct input in the same session while quota is active; inspect CLI, session Telegram topic and integrator | The topic also projects attributed integrator inputs, progress and answers once, without creating another input or task. The integrator still receives its correlated return. Direct input remains ordinary, with no router admission/quota charge; no internal JSON or metadata tail leaks | A, N, H |
| Q14 | Reach the configured execution budget with many retained contexts | Inputs remain visible and recoverable; direct work is responsive; bounded actual execution and waiting are truthful. Record context count separately from running workers | A, selected N |
| Q15 | Speak mixed Spanish/English; queue several speech chunks/results; start speaking during output | Understandable transcription, natural spacing, no overlapping playback, clear capture state and cancelable queued speech. Judge actual sound, not just the `ended` event | A, N, H |
| Q16 | Complete transcription, fail transcription, render speech, then exercise expiry/size limits | Durable text is retained; successful source audio is removed; failed/uncertain audio is bounded and identifiable. TTS pruning matches its documented cache policy, without pretending immediate playback deletion | A |
| Q17 | Use a narrow screen, large text and keyboard; open read-only diagnostics during parallel work | Main text/voice interaction remains readable and reachable, including a short viewport with the software keyboard. The header inspector starts closed, opens into a readable scrolling overlay, and closes without losing drafts, recording or attachments. Its close control remains reachable. Read-only routing evidence is accessible; live questions remain in the main conversation. Truthful compact activity is understandable. No overlap or inaccessible clarification | A browser, H |
| Q18 | Use a simple/advanced presentation and an independently read-only monitor credential | Read-only inspection stays accessible; presentation does not grant destructive authority. Exercise the selected simple/advanced configuration and allowed/denied goal, question, approval and artifact operations. Existing credentials retain their audience and grants; profiles cannot be deferred as planned for this milestone | A, H |
| Q19 | Select one or several immutable images; reorder/remove, fail one decode/upload, record voice and then change the visible selection | One original preserves all image identities, order, optional points and frozen voice references; no partial silent submission. Indexed readback uses the same audience. Retry/reconnect cannot reorder or replace the original; uncertainty prompts clarification, with no claim to see a changed scene | A, selected N/H |
| Q20 | Interview completed and busy source sessions through an explicitly selected observer finding | Exact fork only where supported; derived/pinned context otherwise labeled. Interview does not mutate source work; publication is a separate selected act | A, N, H |
| Q21 | Request an artifact from routed work; revisit after session renewal/compaction | Correct continuity and truthful access to retained output. Required authorized artifact registration and browser access from actual output turns, immutable hash/bytes and audience; independent destination references, multifile partial failures, expiry/revocation and supported logical renewal. Hold byte storage while sending the next input to that SAME worker; primary text and successor admission must progress. Restart during retained copying without replaying native work; late files must appear on an already-visible reply without replaying its narration. No arbitrary path access, audience expansion or false delivery claim | A, N |

## Integrated v0.2 extensions

Record a compact coverage matrix: existing/new integrator, existing/new worker,
busy/idle, standalone/Telegram, authorized/read-only. Reuse paired journeys;
there is no requirement to repeat all cases for every Cartesian combination.
Persisted tool registration must not restrict acceptance to fresh test threads.

| ID | Additional action | Required observation / evidence |
| --- | --- | --- |
| V01 | Two existing sessions overlap; switch one to direct Telegram input; answer its live question; receive an artifact and reconnect | Real native task effects, retained attribution, independent primary return and deduplicated destination publications; ordinary direct ingress stays outside the router. Q04/Q07/Q10/Q13/Q21 |
| V02 | Confirm an assistant goal proposal; explicitly change another goal; cancel/stale/repeat a confirmation; say “yes, then ask X” | Exactly scoped human control transaction, single-use confirmation and exact human follow-up admitted once after the native control precondition succeeds, through a joint native admission or an acknowledged correlated child. No inferred interrupt/accounting reset. Include old integrator/worker paths and allowed/denied device grants |
| V03 | Inject native model/external goal mutation between read and set/clear; fail between replacement clear/set | A stale operation cannot mutate the replacement goal. Native preconditions or honest refusal; partial/unknown outcome retained. Wrapper precheck alone is not a pass |
| V04 | Withdraw an obsolete task while its issuer runs; change binding; answer a stale question; attempt an approval with a read-only credential | Scoped attributable withdrawal distinct from human completion, no fabricated live responder or approval; relevant ordinary answers accepted without repeated entry. Q07/Q18 |
| V05 | Switch return surfaces and lose Telegram acknowledgment after an accepted send | Shared canonical event/destination identity prevents ordinary/projected duplication; ambiguous delivery remains uncertain without resend or task replay; primary return independent. Q12/Q13 |
| V06 | Cancel during interreply/interchunk silence, start capture, hide/disable/change source, fail one TTS, then reconnect | Generation-owned waiting cancels even with no active audio element; next reply remains usable, question priority visible, late progress does not displace final, no historical autoplay. Q09/Q10/Q11/Q15 |
| V07 | Inspect companion with parallel activity; select two unrelated per-being vocabularies and client defaults; reuse pack labels with changed bytes; inject missing/invalid/stale hint; test reduced motion, hidden screen and narrow keyboard layout | Exact receiver-selected catalog digest and actual response/turn bind cosmetic hints; whole composition fits or uses its description. One finite local sequence, no duplicate/old-source replay; readable operational states independent of artistic meaning and no animation inference loop. Q17/Q18 |
| V08 | Download artifact; hold file copying while continuing the same session; restart a retained byte job; fail one of several files; expire/revoke grant; renew logical session; lose Telegram delivery acknowledgment | Actual retained bytes/hash/audience and original output provenance, useful partial/unavailable state, no old-current-binding requirement after supported renewal and no duplicate execution. Hold an actual source-file upload while the same session receives direct and routed input: text must progress, direct output/files must not leak into the integrating audience, late captions identify the original answer, and lost upload ACKs remain uncertain after restart. Q21 |

| V09 | Use the same shared-login app and Telegram entry; keep an unsent draft/recording while denying only the Telegram observation, then restore it | Read-only originals and traces use the actual interaction grant. Optional-read 403 preserves conversation and input/media state across live updates; real session expiry follows reconnect. No input replay or administrative permission expansion |

For V02, include a file produced by the confirmed goal: verify its actual bytes,
ordered follow-up and first useful native turn, then download it through the
integrating audience. A goal metadata acknowledgment alone does not establish
file return. Retained output must recover across service restart without replay.

For V02, review a proposal in the main conversation surface, preserve an existing
composer draft, then confirm or decline through an actual submitted human message.
Review alone must not execute or create an original. Inspect retained partial and
unknown outcomes after expiry; read-only clients may inspect but cannot mutate.
Check narrow/keyboard-height layouts with a live decision and the composer.

For V02/V03, include an idle worker and a busy existing collector. Verify the
current invocation context and selected human follow-up on the first useful
model step after control admission, not only in the client payload. Distinguish queued/claimed control
from a native write attempt. A newer explicit goal command must retire an older
queued activation before it can reactivate work. Exercise a goal reply followed
by a routed correction in that collector: its final item has one canonical
return, not a native copy plus a routed delivery. A later direct input still
selects its own surface. Native admission remains distinct from incorporation,
completion, Telegram delivery and physical hearing.

The final campaign report must distinguish synthetic fault injection, real native
execution, browser observations, receiving adoption and human judgments. Required
Q01–Q21/V01–V08 capability cases cannot pass as “planned”, unavailable or not run.
Mark each method separately when its human observation remains pending. Existing
valid evidence may satisfy unchanged deterministic cases; native combined journeys
must exercise the finished integrated version. Do not infer subjective child
appeal, physical hearing or days of daily use from browser automation.

## Human journeys

Proposed sessions are short and adjustable, not reserved appointments:

- Text: overlapping familiar contexts, one ambiguity, one local discussion and a
  deliberate correction. The human states intended destinations before seeing
  outcomes where possible, without turning the implementation's guesses into labels.
- Voice: continue the same work, introduce a second task, answer a question and
  interrupt playback. Include mixed language and natural pauses; judge both
  intelligibility and whether the conversation is easy to follow.
- Continuity: reconnect on the phone, inspect the collapsed monitor, switch to an
  ordinary direct topic and return. Explore one selected reference or interview
  only if useful, rather than manufacturing irrelevant tasks.

The system should explain enough that the person can describe what is happening
without reading raw JSON. Children using a simple interface and accessible
read-only inspection are a design target, not a claim of tested child usability.

## Measurements and acceptance

ASR cache accounting must inspect retained private jobs without creating them or
syncing each historical directory. Qualify a populated history: the new intent
still crosses its file/directory durability barrier before provider execution;
uncertain reservations, byte limits, ownership and symlink rejection stay intact.
Removing these history-dependent writes is not proof of streaming transcription
or a measured end-to-end improvement on a human phone.

Measure the journey by original input: end of speech/commit, transcript ready,
routing decision, native acceptance, first useful progress, final result and
playback start/end. Separate queue, preparation, inference and execution time;
report distributions and case counts, not one impressive total or batch latency.
Record model calls/tokens and attributed service costs where observable; missing
billing stays unknown.

Routing measures include wrong destination, necessary/unnecessary clarification,
unnecessary new context and appropriate local conversation. Keep ambiguous
acceptable sets; do not punish a useful clarification just to increase accuracy.
Use held-out human intent distinct from synthetic cases and real corrections.
Inspect observer factual fidelity, retained corrections, open questions, source
coverage and freshness. A fluent card or a worker coverage declaration is not proof.

For the campaign's exercised cases, require no silent input loss, duplicate task
effects, wrong audience, involuntary direct-topic interception or false delivery
claims. Required corrections must affect the resulting work. Every unresolved
failure blocks acceptance of its capability, not unrelated exploration. Finite
success is evidence for exercised conditions, not a claim of universal zero failure.

Set latency/cost targets after the baseline is measured; do not invent production
SLOs from synthetic tests. Human acceptance additionally requires a comprehensible
screen and comfortable turn-taking. Record actual judgments and examples.

Retain transcripts, event timings and selected evidence under their existing
audiences. Do not build a raw-audio archive or publish private conversations as a
research corpus. An explicitly selected diagnostic sample needs its own purpose
and retention; routine audio follows the existing deletion/cache policy.

## Goals, directed controls and visible session lifecycle

Human requirements added 2026-10-19; receiving qualification remains required.
A habitual integrating conversation should also make session lifecycle understandable in Telegram,
without requiring the dashboard or CLI.
The [harness control study and delivery plan](integrator-controls.md) records the
installed capability inventory, supported external controls, recovery choices
and exact distinction between human-directed commands and delegated autonomy.

- Distinguish an active native goal (suggested marker: target) from actual
  execution without an active goal (suggested marker: lightning). An active goal
  can be waiting; its marker must not claim current execution. Idle sessions
  need no ordinary activity marker. Paused/blocked goals and human questions
  remain inspectable and must not be mistaken for completed work.
- Offer a compact inventory such as active goals, executing sessions without
  goals, and currently passive sessions with conversational activity in the
  last configurable X days. Seven days is an initial proposal. Count actual
  attributed exchanges, not status reads, metadata polling or title updates.
  Expose observation freshness and unknown lifecycle state. A topic and a
  renewed native thread are not automatically two user-visible conversations.
- Preserve human titles, topic icons, stable selectors and native bindings.
  Status decoration must not become canonical identity or a rename loop. Reuse
  the existing activity observer/catalog; this calls for no second Telegram
  consumer, model wakeups or new background attention.

- Accept explicit human-directed goal controls through the integrator, with
  a resolved target and native outcome. For example, a human's instruction to
  resume one session's goal or clear it before proceeding with a replacement
  should not require manually visiting that topic to type a slash command.
  Keep control intent separate from text forwarded to the worker; validate
  the current goal/binding and retain the actual acknowledgment. Quoted slash
  commands or a model's proposal are not themselves human control requests.
- Clear is not interrupt, and changing a goal does not itself undo completed
  effects or cancel running work. An ambiguous target or replacement requires
  clarification. Do not clear a goal merely to make an unrelated next message
  fit. Concurrent human changes must invalidate a stale control selection.

For the catalog/activity implementation, exercise the existing observer with
`--topic-markers` and inspect its finite `--inventory --activity-days 7` output.
Include an idle active goal, working without an active goal, paused/blocked
metadata, stale/disconnected observations, a renewed binding and a human rename.
The marker must preserve the complete canonical title and icon; retiring the
observer or using `--restore-topic-markers` restores only acknowledged owned
decoration. Inject a lost title-edit acknowledgment and restart: its uncertain
attempt must remain inspectable without replay. Metadata and tool-only activity
must not inflate the recent-conversation count. These source fixtures complement,
and do not replace, the actual receiving Telegram observations.

Current native `update_goal` permits complete, blocked, and explicitly requested
pause, but not resume or limit changes. The checked native runtime can also mark
goals blocked on turn errors or execution unavailability. Improving agent-owned
lifecycle control requires a supported harness capability and an explicit
delegation model. Sending the same agent-originated decision through another
session or a user-origin API must not manufacture human authorship. Today's
integrator-directed human controls and future delegated autonomy are separate
capabilities to evaluate.

Extend Q13/Q14/Q18 to exercise: active-goal/idle vs executing/no-goal display,
completion and blocking, recent-idle count ageing, observer disconnect, explicit
human resume/clear, ambiguous targets, stale goal changes and exactly one control
effect. Reads and projections must never activate or clear a goal. Preserve
budget, explicit pause and Stop semantics. Unknown resume/control outcomes are
inspected, never automatically replayed.

## Development sequence and creative horizon

1. **Usable surface and broad qualification.** Implement the human's simple
   text/voice view, collapsed read-only diagnostics, clear compact activity and
   cancelable spacing between speech segments. Project integrator activity into
   the corresponding session's Telegram topic as well as CLI, preserving the
   correlated integrator return and direct-topic independence. Run affected browser/audio checks,
   then the integrated campaign. User-profile configuration is a separate
   presentation/access requirement; CSS hiding cannot implement permissions.
2. **Attention and semantic reliability.** Improve observer fidelity and intent
   evaluation from observed failures. Compare classifier/embedding candidates on
   held-out intent before adopting them. Coordinate timely questions, grouped
   progress and results without making the human manage every worker. Priorities
   for interruptions and summaries should be inspectable and adjustable.
3. **Continuity of useful work.** Close artifact-return and session-renewal gaps,
   improve reconnection/background use and verify long mixed sessions. Preserve
   source evidence and ordinary direct interaction. Explicit session dependencies
   must work through the actual supported native adapter.
4. **Replaceable realtime frontends and mobile button.** Compare native realtime
   services against the working modular ASR/text/TTS baseline over the same
   controller. Preserve interruptible speech separately from work cancellation.
   Develop a minimal native mobile client and then qualify real Bluetooth button,
   headset and OS background behavior. Android/iOS parity and an arbitrary headset
   power-button binding are not assumed.
5. **Situated perception and selected observer consumers.** Extend selected frames
   toward useful live visual context only where the task benefits. Add explicitly
   enabled interview/editorial consumers with source provenance and separate
   publication. Do not convert every observed event into a new task or retain
   continuous raw media by default.
6. **Multiple bodies after local polish.** Complete canonical Matrix correlation,
   receiving adoption and device consumption under #163 and Matrix #367/#373.
   Distinct identities, audiences and observed delivery remain explicit. This is
   deferred scope, not a prerequisite for a usable single-body product.

Steps 1–3 are the immediate product path. Later tracks can share the stable
controller; they do not require throwaway intermediate architectures. Their order
depends on observed value, rather than promising a date for every imagined feature.

The broader Field/Nexus direction is a situated doorway into ongoing thought:
move between a simple conversation and inspectable relationships among projects,
experiences, evidence and perspectives. Encounters can become exploration,
research, interviews, decisions or creative work without turning all conversation
into tasks. A child can use the button and later explore what happens beneath it.
Voluntary co-presence and richer spatial interfaces remain a creative horizon,
not capabilities delivered by this routing milestone. Shared context does not
imply a universal memory pool or automatic disclosure of personal sessions.

## Research grounding

The collective research on integrating conversations (2026-10-15) and native
WebRTC (2026-10-18) motivates the architecture; it does not establish product
acceptance. The following primary references explain specific design lessons:

- [JarvisBench](https://github.com/cchen1436/JarvisBench): coordination includes
  allocating scarce human attention, asking useful questions and returning
  judgments to execution. Evaluate both directions, not only destination labels.
  Its distinct intervention/replay tracks should not be presented as proof of
  20 simultaneous production tasks or a drop-in runtime.
- [Qwen Live Harness, inspected revision](https://github.com/QwenLM/Qwen-Live-Harness/tree/b2d17b8706b226ff7792683ecd8f050f18f9752e):
  separate conversational interaction from asynchronous execution and speech
  scheduling. Its display reports are not our durable observer; the desktop
  implementation is not an already-integrated Linux/mobile client.
- [Magentic-UI](https://www.microsoft.com/en-us/research/publication/magentic-ui-report/):
  shared, inspectable work and collaboration suggest keeping the workspace
  available beneath the chat, rather than forcing all understanding into speech.

Use the configured collective corpus for the complete evidence ledger and
provider-access findings. New model releases warrant targeted research when a
decision depends on them; they are not a reason to postpone qualifying this MVP.

## Beacon-derived sonic language supplement — #221

These are additional acceptance cases for the human-requested opt-in sonic layer,
not evidence that it exists. Keep automated event/signal verification separate
from perceptual and subjective listening. Do not start the real-session campaign
until the integrated product is ready; offline deterministic development checks
remain appropriate. Playback requires deliberate client audio activation.

| ID | Journey | Required evidence |
| --- | --- | --- |
| S01 | Verify the Beacon 40.4 series: idle F1, active +F2, tools/subagents +F3, active goal +F4, pending +F7, blockage/error +F11 | Actual Beacon F-index convention and additive simultaneous components; real tool/subagent, goal, pending and error evidence; no extra arbitrary harmonics or unknown-state pitch |
| S02 | Advance, block, await a live answer, lose freshness, disconnect and reconnect | The mapping follows the actual selected state and current membership. Unknown/stale is not silently rendered as idle, waiting or blockage; no invented emotional state or historical-event replay |
| S03 | Overlap session voices, including repeated intervals and changing membership | Deterministic bounded aggregate signal with inspectable contributing sessions; omissions/unknowns explicit, transitions finite and levels controlled. The chord and monitor refer to the same selected set |
| S04 | Start a speech reply, answer a question, adjust volume/mute, stop during a transition and reconnect | Declared ducking/priority policy matches owned playback; mute/stop silence actual owned audio nodes, cancel scheduled transitions and do not cancel tasks. No new inference or microphone capture |
| S05 | Activate the opt-in browser renderer; hide/suspend/resume; separately listen to the compositions | Actual browser activation/suspension and audio-output evidence; no unsolicited autoplay or false active-audio claim. Human observations address comfort, distinguishability and learned chord interpretation only after the full journey is prepared |

No S case passes merely because a sound name, score, mock event, planned renderer
or favorable code review exists. Unimplemented synthesis and subjective claims
remain explicitly unproven. Default silence and read-only visual inspection stay
available. Existing Q/V requirements and direct-topic independence still apply.

## Continuous-voice extension — milestone9

The maintained [full roadmap and v0.3 execution plan](interaction-roadmap.md)
extends this protocol; existing evidence remains valid for unchanged behavior.
Qualification must cover partial captions during capture, one committed original
on Send, discard without dispatch, revision/correction order, reconnect without
uncertain replay, useful incremental output, speech interruption independent of
job cancellation, and coherent concurrent question/progress/final returns.
Measure first partial, ASR finalization, final intended speech to first intelligible
sound, segment gaps and interruption-to-silence separately. Exercise Spanish with
English names/commands, long pauses and self-corrections. Keep deterministic
transport/state fixtures separate from actual provider and physical-phone hearing
evidence. Reuse the accepted base and do not recreate its obsolete generic
human-testing request.
