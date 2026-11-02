# Conversational avatar services and Instant — 2 November 2026

Author: CompAII. Scope: a fluent spoken foreground above an existing persistent
integrator, with asynchronous sourced requests and spoken returns. This is a
primary-source documentation comparison, not a provider benchmark, account-credit
verification or migration. No new model inference or personal recording was sent
for this investigation. Selected research remains under 64 KiB; retain this dated
brief and its source links, without accumulating provider-page mirrors or media.

## Decision supported by the evidence

Keep the integrator and its work sessions independent of the speech provider.
The first alternative worth comparing with the working Gemini baseline is
**GPT-Live with client delegation**: its documented boundary accepts an existing
agent/service while the voice continues conversing. This is an architectural
fit, not evidence that it sounds better or is more reliable on our phones.
[OpenAI Live overview](https://developers.openai.com/api/docs/guides/live),
[delegation contract](https://developers.openai.com/api/docs/guides/live-delegation).

The earlier collective investigations of 15/18/26 October already covered layered
integration, native WebRTC and the speech frontier. The current receiving reader
returned the integrating-conversation map and the26October speech report at
coherent generation43. They remain historical evidence; this brief adds current
service lifecycle and selection checks. In particular, the earlier successful
native-login WebRTC experiment was not a general API-credit entitlement.

## Candidate map

| Provider / route | Documented capability | Fit and unresolved requirement |
| --- | --- | --- |
| OpenAI GPT-Live1 | Full-duplex voice; an independently chosen backend; client delegation can connect our own harness. WebRTC is recommended. | Best documented match to the foreground/integrator separation. Keep our source admission, task state and return validation. Access and phone comparison unverified. |
| OpenAI Realtime (`gpt-realtime-2.1` example) | Native speech-to-speech, interruption handling, tools and automatic turn detection over WebRTC/WebSocket. | A separate candidate when we want explicit session/tool ownership. GPT-Live and Realtime have different handshakes and events; they are not interchangeable aliases. |
| Google Gemini3.8Live | Continuous native audio and asynchronous function calling; blocking/scheduling behavior depends on model and API. | Current implemented baseline. Preserve the exact nonblocking contract and tool-return lifecycle; a faster model does not fix a delayed or cancelled bridge. |
| Alibaba Qwen3.8OmniFlashRealtime | Full-duplex text/audio/video, custom functions, semantic VAD; WebSocket/WebRTC/AOQ. Spanish output is listed. | Strong second challenger for noisy turn taking. Requires the selected regional workspace/key. Verify delayed external returns and cancellation, not only a spoken demo. |
| xAI GrokVoice3.0 | Bidirectional audio/text, configurable voice/turn detection and function/MCP tools; versioned name or moving alias. | Plausible independent speech provider. OpenAI-compatible events do not prove equivalent async-tool or interruption semantics. |
| Amazon Nova2Sonic | Active Bedrock speech-to-speech model for real-time conversations. | Worth testing where Bedrock access exists; bidirectional transport and tool-return handling need a separate adapter qualification. |
| ElevenLabs ElevenAgents | Managed interactive voice WebSocket; client tools and noninterrupting contextual updates. | Useful managed comparison, distinct from its standalone TTS endpoints. Validate that our asynchronous Sol return can enter without starting duplicate work. |
| Mistral Voice Agents / Voxtral3 | Managed STT→LLM→TTS pipeline, tools, interruption support and LiveKit-based transport. | Contemporary alternative to maintaining the whole chain ourselves. It remains a staged pipeline, so first-audio and slow-tool behavior need measurement. |
| Deepgram Voice Agent | Managed/BYO thinking endpoint, including OpenAI-compatible custom services and multiple LLM providers. | Can use Anthropic, Google, Groq or NVIDIA models as text brains without assuming those models are native speech services. Current Deepgram-hosted experimental LLMs have separate access/data constraints. |
| MiniMax Speech2.8 | WebSocket incremental text-to-speech. | A speech component for a composed stack, not proof of a whole duplex conversational agent. Same distinction applies to choosing standalone STT/TTS products from the broader26October survey. |
| NVIDIA PersonaPlex7Bv1 | Downloadable full-duplex speech model with voice/role conditioning. | Research/local-control comparison; the official card describes English and GPU deployment. It does not establish a ready Spanish phone replacement. |
| Hume EVI | Native/externally assisted expressive conversation and custom language-model routes. | Exclude from a new production choice: Hume explicitly ends TTS/EVI API access on13November2026. Older feature guides do not override that notice. |

Primary capability sources, retrieved2November2026:

- [OpenAI Realtime](https://developers.openai.com/api/docs/guides/realtime) and [audio workflow distinctions](https://developers.openai.com/api/docs/guides/audio).
- [Gemini3.8 migration/tool semantics](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/migrate-from-gemini-2-5-to-gemini-3-8-live) and [async tools](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/asynchronous-function-calling). The AI Studio capability URL redirected to an unavailable reader destination; the Cloud source is a separate API deployment, not proof of account entitlement.
- [Qwen realtime](https://help.aliyun.com/en/model-studio/realtime) and [voice/language list](https://help.aliyun.com/en/model-studio/omni-voice-list).
- [Grok speech-to-speech](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech).
- [Nova2Sonic official card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-sonic.html).
- [ElevenAgents protocol](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket) and [context updates](https://elevenlabs.io/docs/eleven-agents/libraries/web-sockets).
- [Mistral voice-agent architecture](https://docs.mistral.ai/studio/audio/voice-agents/overview).
- [Deepgram LLM/provider contract](https://developers.deepgram.com/docs/voice-agent-llm-models).
- [MiniMax streaming TTS](https://platform.minimax.io/docs/api-reference/speech-t2a-websocket).
- [PersonaPlex official model card](https://huggingface.co/nvidia/personaplex-7b-v1).
- [Hume shutdown notice](https://dev.hume.ai/voice/docs/speech-to-speech-evi/overview).

The table is a bounded selection map, not a claim that every provider/model in
the market has been audited. No native equivalent was established here for every
text provider in our wider catalog. Absence from these results is not proof that
one does not exist. Cartesia, Soniox, Inworld and local CPU STT/TTS remain in the
prior component survey; their component quality is a different comparison from
an integrated speech agent.

## What Instant can do

OpenAI's `chat-latest` points to ChatGPT's current Instant model. Its card lists
text input/output, image input, streaming, function calling, structured outputs
and Responses tools including search, retrieval, code execution and MCP. It lists
**no native audio**. The alias changes over time; freeze the observed version in
an evaluation. [Official model card](https://developers.openai.com/api/docs/models/chat-latest).

Our proposed use is a conversational text layer for clarifying and refining
requests, extracting constraints/corrections, discussing images and explaining
verified returns. It could also sit between a streaming recognizer and synthesizer.
That adds a staged speech pipeline; it does not acquire duplex audio simply by
being called Instant. Keep Sol responsible for persistent planning/routing until
a measured comparison justifies a change. These are design hypotheses, not newly
installed behavior or evidence that Instant outperforms the live model.

## Cost, credits and actual access

GPT-Live1 lists **$0.05 per connected session-minute**, billed by the second,
with backend/model/tool costs separate. That is **$3 per connected hour** before
backend work. GrokVoice3.0 lists **$0.08/minute plus text-input charges**. Different
billing bases make STT-only or generated-audio rates incomparable without a common
workload. [OpenAI rate card](https://developers.openai.com/api/docs/models/gpt-live-1),
[Grok rate card](https://docs.x.ai/developers/pricing).

ChatGPT plan usage and API credits are separate routes. Official documentation
permits eligible paid Pro/Business owners to link an owned API organization and
claim a subscription benefit; it requires matching account email/ownership and
has expiry rules. To confirm accreditation, inspect the **correct organization's
Billing grant/balance, grant date and expiry**, rather than infer it from a Codex
login. No grant or balance was verified in this investigation.
[Credit eligibility/claim guide](https://developers.openai.com/api/docs/guides/chatgpt-api-credits).

Supported Sign in with ChatGPT integrations can consume an eligible plan under
an explicit app grant and cap; sign-in alone does not create an additional
allowance or expose memories. Do not assume that this grants GPT-Live/API access.
[Official plan-sharing explanation](https://learn.chatgpt.com/docs/sign-in-with-chatgpt).

Current Gemini use is evidenced by the existing application. Other providers'
public API availability, an existing text-provider credential, access to a
specific speech model and a usable balance are four different observations.
New accounts, billing changes and paid calls were not performed for this brief.

## Smallest discriminating comparison

After resolving actual provider access, compare Gemini and GPT-Live first; add
Qwen or Grok if their account/transport route is ready. Reuse synthetic Spanish
fixtures, not uncertain human originals. Bound each provider session to three
minutes, one active trial and one explicit close; keep aggregate timings/errors
and only the selected short outputs needed for listening. Clean disposable media
through its existing bounded cache. No background benchmark or account creation.

Test a pause inside a sentence, road noise without words, an interruption with
a corrected number, and a delayed simulated Sol return while conversation
continues. Check that a new answer reaches the integrator once, an interruption
stops speech without cancelling unrelated work, and the eventual source-bound
return is spoken completely. Measure end-of-phrase→first meaningful sound,
missing audio/clicks, false interruptions, duplicate admissions and total billed
session/backend usage. Captions appearing quickly are not evidence of heard speech.

For Instant, use a separate text-only comparison of faithful formulation and
correction handling against the existing voice role; then measure an actual
streaming speech chain if its text behavior merits it. Provider demos and
documented features select experiments; phone acceptance chooses the product.
