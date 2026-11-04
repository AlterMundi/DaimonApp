# GPT-Live workflow and practice comparison — 4 November 2026

Human-selected direction: adapt DaimonApp to the best evidenced conversational
workflow, rather than forcing GPT-Live through the existing Qwen/Gemini adapter.
This is a bounded design investigation, not a provider audition, entitlement
check or production adoption. The current diagnostic limits remain unchanged.
The [roadmap](interaction-roadmap.md#current-refinement-toward-an-approachable-avatar--4-november-2026)
owns implementation and family-pilot acceptance; this note records the rationale.

## Starting architecture

Use GPT-Live client delegation with our persistent integrating agent as the
backend. Keep identity and conversation style in a short voice prompt; keep
tools, detailed workflows, durable memory, permissions and task execution in
the backend. Client delegation is selected for ownership of our existing
agent/state, not because it is universally better than Responses delegation.
The official design supports both. The backend model remains independently
selectable; GPT-Live does not require the integrator to become an OpenAI model.
[Official overview](https://developers.openai.com/api/docs/guides/live).

Prefer the documented WebRTC media/data-channel architecture for the browser,
with server-owned credentials and a sideband for backend event handling and
steering where needed. Compare it with a primary WebSocket only for a concrete
requirement. Do not retain our server-PCM transport merely because it exists.
Retain durable input/result ownership and recoverability as product requirements,
while redesigning their transport-specific implementation where necessary.

## Decisions from inspected sources

| Evidence | What changes in our design | What still needs qualification |
| --- | --- | --- |
| Official migration guide: continuous audio, no Realtime manual commits/response triggers; Live lacks the same spoken-response completion event | Build a Live lifecycle adapter instead of subclassing the Qwen turn loop. Drive speaking state from actual playback, not a guessed final transcript/response event. | Browser playback, interruption and bounded recording boundaries under continuous input. |
| Official client delegation: notification carries an ID/offset, not task text; transcripts can be fragments or mistaken | Assemble the request from source-linked transcript ranges and application context. Carry corrections and pending work with their IDs; never dispatch a fragment merely because it arrived. | Exact-source admission when a delegation overlaps unfinished or corrected speech; late returns and superseded requests. |
| Official migration/return guidance: backend tasks can outlive voice; spoken and quiet updates are distinct | Preserve ongoing work across disconnects; send useful verified results for speech and quiet state separately. Do not narrate every tool step. | Reconnect checkpoint/delta hydration and human hearing, separately from receipt of an appended update. |
| OpenAI Live Console, pinned source below | Inspect separate browser/server startup, generation guards, backend event ownership, bounded delegations/tool rounds and terminal cleanup. Use it as a comparison fixture, not a second production app. | Its README explicitly leaves end-to-end compatibility verification open; no deployment acceptance transfers to us. |
| Travizm's protocol notes, pinned source below | Useful developer-reported traps: wrong event families, delegation without task text, injection ACK versus audibility, interruption versus work cancellation. Check each against current official schemas. | The author's October wire observations are not our current account test or a universal protocol guarantee. |
| InteractionBench, submitted2November | Evaluate timing, task correctness and grounded continuity together. Fast speech alone does not establish useful interaction. | Published system comparisons include client/network effects; no ranking transfers directly to our Spanish/device setting. |

Official primary references, retrieved4November2026:

- [Migration](https://developers.openai.com/api/docs/guides/live-migration):
  workflow/prompt separation and the continuous audio versus Realtime lifecycle.
- [Delegation and tools](https://developers.openai.com/api/docs/guides/live-delegation):
  transcript/offset assembly, delegation IDs, quiet/spoken updates and late work.
- [Session management](https://developers.openai.com/api/docs/guides/live-conversations):
  context and connection lifecycle; do not assume a replacement inherits state.
- [Voice evaluation Cookbook](https://developers.openai.com/cookbook/examples/audio/voice_agent_evaluation):
  use as the evaluation-design reference, not evidence that we ran its benchmark.

Inspected implementations and research:

- [OpenAI Live Console](https://github.com/openai/openai-live-console/tree/5f64ecb3009d8274da9953c825d469ea6b6b67c3),
  especially `server/session.ts`, `client/session.ts` and README. Read selected
  startup/control sections; no whole-repository audit or execution. Publication
  date not established by this read; revision retrieved4November.
- [Travizm protocol notes](https://github.com/Travizm/dsh-openai-live/blob/6f78ffc2355d24dcf6ed4fac2a77959d2a674d53/docs/protocol.md),
  author-reported wire observations dated7/15October, retrieved4November. Treat
  its account/billing assertions separately from protocol observations; they
  are not a source of permission or proof of our access.
- [He et al., InteractionBench](https://arxiv.org/abs/2611.02430),
  submitted2November2026. Abstract inspected; the full harness and experiments
  were not reproduced. It is an evaluation lead, not an implementation choice.

## Reuse, replace and measure

Reuse shared login, exact human-source/correction history, persistent tasks,
permission checks, canonical results/questions, viewers and the integrating
role. Replace provider-specific assumptions: manual audio commits, response-end
events, synchronous tools, a prompt containing every backend tool procedure,
and reconnection that starts with unrelated recent excerpts.

The first integrated comparison must cover a natural greeting, an unfinished
sentence, correction during a delayed request, an interruptible spoken return,
one useful artifact, a pending question, a provider renewal, and reconnect to
the acknowledged checkpoint. Record first useful audible response, interruption
to quiet, output queue age, result correctness, missed/duplicate actions,
continuity and total voice/backend cost. Use the existing Qwen journey as a
comparison, not a template that dictates Live's protocol. Do not create a new
worker hierarchy or provider-owned memory store to imitate a demo.

## Prior work, acquisition gaps and retention

The retained15/18October integrating-conversation research already considered
Qwen Live Harness, JarvisBench, lab task/social dialogue, native Codex WebRTC and
client delegation. Its existing map and original source retain their historical
dates, audience and unresolved experiments. This note adds current migration
decisions; it does not publish that private corpus or treat its map as fresh
independent validation.

Selected X lead: OpenAIDevs post2098099372999446590. Direct public retrieval
returned403; no post/thread body was inspected. Existing subscription search
configuration permits long automatic retries and has no verified source-linked
retrieval; no paid fallback or speculative model call was started. Do not quote
or claim lessons from the inaccessible post.

Selected YouTube lead: OpenAI, “Discoverability widgets with GPT-Live,”
[video QUOwyLwoykU](https://www.youtube.com/watch?v=QUOwyLwoykU), search metadata
dated8July2026. One bounded no-media subtitle discovery request was blocked by
a sign-in/bot challenge. No captions or video content were inspected; metadata
alone does not establish widget behavior. Relevant talks/demos remain an
acquisition gap before claiming a complete community/video review.

Keep this brief, selected pinned links and acquisition outcomes. Do not retain
full platform mirrors, download media, export cookies, install search watchers
or accumulate per-query logs. Revisit a missing source through an already
authorized working reader when it can resolve a concrete implementation choice.
No inference, provider switch, limit change or new recording occurred here.
