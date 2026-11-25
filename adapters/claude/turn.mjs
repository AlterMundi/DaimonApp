// The foreground Claude adapter consumes one already selected Gateway input.
// The caller owns the Matrix broker and the canonical request journal.
import { bodyMatches } from './matrix-broker.mjs';

const SERVER = 'matrix';
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const MAX_INPUT_BYTES = 16 * 1024;
const MAX_RESULT_BYTES = 64 * 1024;

function catalogMatches(status, expectedTools) {
  if (!Array.isArray(status) || status.length !== 1) return false;
  const server = status[0];
  if (server.name !== SERVER || server.source !== 'sdk' || server.status !== 'connected') {
    return false;
  }
  if (!Array.isArray(server.tools) || server.tools.length !== expectedTools.length) {
    return false;
  }
  const names = server.tools.map(({ name }) => name).sort();
  return [...expectedTools].sort().every((name, index) => name === names[index]);
}

/**
 * broker.server must be an SDK MCP instance bound to the same authorized
 * Matrix client used by broker.readStatus. Gateway supplies expectedBody from
 * its selected signed admission, and persists the submission boundary using
 * beforeSubmit. No transcript or SDK status establishes Matrix authority.
 *
 * This is deliberately a discrete turn. Steering, reconnect and goals must
 * be advertised separately when their native behavior has been qualified.
 */
export async function runClaudeTurn({
  query, broker, expectedBody, toolNames, input, profile, beforeSubmit, signal,
}) {
  if (typeof input?.text !== 'string' || input.text.length === 0
      || Buffer.byteLength(input.text) > MAX_INPUT_BYTES
      || !UUID.test(input.id) || !UUID.test(input.sessionId)
      || !Array.isArray(toolNames) || toolNames.length === 0
      || new Set(toolNames).size !== toolNames.length
      || !toolNames.every(name => /^[a-z][a-z0-9_]{0,63}$/.test(name))
      || !expectedBody?.beingRef || !expectedBody.embodimentId || !expectedBody.incarnationId
      || !expectedBody.manifestHash
      || !profile?.binary || !profile.cwd || !profile.cliVersion || !profile.env?.CLAUDE_CONFIG_DIR) {
    throw new TypeError('Invalid Claude turn selection');
  }

  let release;
  const ready = new Promise(resolve => { release = resolve; });
  const deadline = AbortSignal.timeout(120_000);
  const stop = signal ? AbortSignal.any([signal, deadline]) : deadline;
  const abortController = new AbortController();
  function cancel() { abortController.abort(); }
  stop.addEventListener('abort', cancel, { once: true });
  if (stop.aborted) cancel();
  let dispatched = false;
  let native;
  let reason = 'matrix_identity_unverified';

  async function* prompt() {
    if (!await ready || abortController.signal.aborted) return;
    if (await beforeSubmit(input.id, input.sessionId) !== true) return;
    dispatched = true;
    if (abortController.signal.aborted) return;
    yield {
      type: 'user', uuid: input.id, session_id: input.sessionId, parent_tool_use_id: null,
      message: { role: 'user', content: input.text },
    };
  }

  try {
    if (abortController.signal.aborted) {
      return { phase: 'not_submitted', reason: 'cancelled' };
    }
    if (!bodyMatches(await broker.readStatus(), expectedBody)) {
      return { phase: 'not_submitted', reason: 'matrix_identity_mismatch' };
    }
    reason = 'claude_catalog_unverified';
    const allowedTools = toolNames.map(name => `mcp__${SERVER}__${name}`);
    native = query({
      prompt: prompt(),
      options: {
        abortController, cwd: profile.cwd, pathToClaudeCodeExecutable: profile.binary,
        env: profile.env, model: profile.model, sessionId: input.sessionId,
        maxTurns: profile.maxTurns, maxBudgetUsd: profile.maxBudgetUsd,
        settingSources: [], strictMcpConfig: true, tools: [], allowedTools,
        mcpServers: { [SERVER]: broker.server }, permissionMode: 'dontAsk',
        permissionPrompts: 'none', persistSession: profile.persistSession === true,
      },
    });
    const initialized = await native.initializationResult();
    if (initialized.claude_code_version !== profile.cliVersion) {
      return { phase: 'not_submitted', reason: 'claude_version_mismatch' };
    }
    if (!catalogMatches(await native.mcpServerStatus(), toolNames)) {
      return { phase: 'not_submitted', reason: 'claude_catalog_mismatch' };
    }
    reason = 'matrix_identity_unverified';
    if (!bodyMatches(await broker.readStatus(), expectedBody)) {
      return { phase: 'not_submitted', reason: 'matrix_identity_changed' };
    }
    reason = 'gateway_submission_not_recorded';
    if (abortController.signal.aborted) return { phase: 'not_submitted', reason: 'cancelled' };
    release(true);
    for await (const event of native) {
      if (typeof event.session_id === 'string' && event.session_id) {
        if (input.sessionId !== event.session_id) {
          return dispatched
            ? { phase: 'uncertain', reason: 'claude_session_changed', sessionId: input.sessionId }
            : { phase: 'not_submitted', reason: 'claude_session_changed' };
        }
      }
      if (event.type !== 'result' || !dispatched) continue;
      if (event.subtype === 'success' && event.is_error === false
          && event.session_id === input.sessionId
          && typeof event.result === 'string' && event.result.trim()
          && Buffer.byteLength(event.result) <= MAX_RESULT_BYTES) {
        return { phase: 'completed', sessionId: input.sessionId, text: event.result };
      }
      return { phase: 'uncertain', reason: 'claude_result_unqualified', sessionId: input.sessionId };
    }
  } catch {
    // Provider errors can include secrets and private input. Outcome only.
  } finally {
    release(false);
    abortController.abort();
    native?.close();
    stop.removeEventListener('abort', cancel);
  }
  return dispatched
    ? { phase: 'uncertain', reason: 'claude_result_unobserved', sessionId: input.sessionId }
    : { phase: 'not_submitted', reason: stop.aborted ? 'cancelled' : reason };
}
