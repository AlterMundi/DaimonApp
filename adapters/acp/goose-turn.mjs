// One explicit foreground turn over Goose ACP v1.
import { spawn } from 'node:child_process';
import { addAbortListener, once } from 'node:events';

const MAX_FRAME = 512 * 1024;
const MAX_TEXT = 16 * 1024;
const DEADLINE_MS = 120_000;
const PREFIX = '_goose/unstable/';

async function* frames(stream) {
  let pending = Buffer.alloc(0);
  const decoder = new TextDecoder('utf8', { fatal: true });
  for await (const bytes of stream) {
    let start = 0;
    while (start < bytes.length) {
      const end = bytes.indexOf(10, start);
      const part = bytes.subarray(start, end < 0 ? bytes.length : end);
      if (pending.length + part.length > MAX_FRAME) throw new Error('ACP frame exceeds bound');
      pending = Buffer.concat([pending, part]);
      if (end < 0) break;
      const message = JSON.parse(decoder.decode(pending));
      pending = Buffer.alloc(0);
      start = end + 1;
      if (message?.jsonrpc !== '2.0') throw new Error('Invalid ACP message');
      yield message;
    }
  }
  if (pending.length) throw new Error('Unterminated ACP frame');
}

function validateSessionId(value) {
  if (typeof value !== 'string' || value.length === 0 || Buffer.byteLength(value) > 256
      || /[\s\p{Cc}]/u.test(value)) throw new Error('Invalid native ACP session ID');
  return value;
}

function isSelectedCatalog(catalog, expected) {
  if (!Array.isArray(catalog?.tools)) return false;
  const names = catalog.tools.map(tool => tool?.name);
  if (names.length !== expected.length || names.some(name => typeof name !== 'string')) return false;
  return [...names].sort().every((name, index) => name === expected[index]);
}

/** The owner supplies the isolated process profile and the journal callback. */
export async function runGooseTurn({
  binary, cwd, env, mcpServers, toolNames, text, beforeSubmit, signal,
}) {
  if (typeof text !== 'string' || !text.trim() || Buffer.byteLength(text) > MAX_TEXT
      || !Array.isArray(toolNames) || !toolNames.length
      || toolNames.some(name => typeof name !== 'string' || !name)
      || new Set(toolNames).size !== toolNames.length) {
    throw new TypeError('Invalid Goose foreground input');
  }
  const expected = [...toolNames].sort();
  const deadline = AbortSignal.timeout(DEADLINE_MS);
  const stop = signal ? AbortSignal.any([signal, deadline]) : deadline;
  let child;
  let closed;
  let cancellation;
  let cancellationDeadline;
  let nativeSessionId;
  let exposed = false;
  let reason = 'goose_unavailable';
  try {
    stop.throwIfAborted();
    child = spawn(binary, [], {
      cwd, env: {
        ...env, GOOSE_DISABLE_SESSION_NAMING: 'true',
        GOOSE_DISABLE_SKILLS: 'true', GOOSE_SLASH_COMMANDS_ENABLED: 'false',
      },
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    child.on('error', () => {});
    child.stdin.on('error', () => {});
    closed = new Promise(resolve => child.once('close', resolve));
    cancellation = addAbortListener(stop, () => {
      if (!exposed) {
        child.kill('SIGKILL');
        return;
      }
      child.stdin.write(JSON.stringify({
        jsonrpc: '2.0', method: 'session/cancel', params: { sessionId: nativeSessionId },
      }) + '\n');
      cancellationDeadline = setTimeout(() => child.kill('SIGKILL'), 500);
    });
    const replies = frames(child.stdout);
    let nextId = 0;
    async function send(message) {
      stop.throwIfAborted();
      if (!child.stdin.write(JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n')) {
        await once(child.stdin, 'drain', { signal: stop });
      }
    }
    async function request(method, params, onUpdate) {
      const id = ++nextId;
      await send({ id, method, params });
      for (;;) {
        stop.throwIfAborted();
        const { value, done } = await replies.next();
        stop.throwIfAborted();
        if (done) throw new Error('Goose ACP closed before its response');
        if (typeof value.method === 'string') {
          if ('id' in value) {
            await send({
              id: value.id, error: { code: -32601, message: 'Client operation unavailable' },
            });
          } else if (value.method === 'session/update') {
            onUpdate?.(value.params);
          }
          continue;
        }
        if (value.id !== id || !('result' in value) || 'error' in value) {
          throw new Error('Goose ACP response unconfirmed');
        }
        return value.result;
      }
    }

    const initialized = await request('initialize', { protocolVersion: 1, clientCapabilities: {} });
    if (initialized?.protocolVersion !== 1) throw new Error('Goose ACP v1 required');

    reason = 'goose_catalog_unverified';
    if (initialized.agentCapabilities?._meta?.goose?.nativeSkills?.enabled !== false) {
      throw new Error('The ACP process did not verify that native skills are disabled');
    }
    const configured = await request(PREFIX + 'config/extensions/list', {});
    if (!Array.isArray(configured?.extensions)) throw new Error('Goose extensions unavailable');
    // The owner-selected profile disables bundled extensions. Preflight reads
    // it back without modifying persistent configuration.
    if (configured.extensions.some(entry => entry?.enabled !== false)) {
      throw new Error('Unexpected configured Goose extension');
    }
    const started = await request('session/new', { cwd, mcpServers });
    nativeSessionId = validateSessionId(started?.sessionId);
    const selected = await request(PREFIX + 'tools/list', { sessionId: nativeSessionId });
    if (!isSelectedCatalog(selected, expected)) throw new Error('Goose tool catalog mismatch');

    reason = 'gateway_submission_not_recorded';
    stop.throwIfAborted();
    let abortDecision;
    const aborted = new Promise(resolve => {
      abortDecision = addAbortListener(stop, () => resolve(false));
    });
    try {
      if (await Promise.race([beforeSubmit(nativeSessionId), aborted]) !== true) {
        return { phase: 'not_submitted', reason };
      }
    } finally {
      abortDecision[Symbol.dispose]();
    }
    exposed = true;
    reason = 'native_result_unconfirmed';

    let answer = '';
    let answerBytes = 0;
    const terminal = await request('session/prompt', {
      sessionId: nativeSessionId, prompt: [{ type: 'text', text }],
    }, ({ sessionId, update } = {}) => {
      if (sessionId !== nativeSessionId) throw new Error('ACP update came from another session');
      if (update?.sessionUpdate !== 'agent_message_chunk' || update.content?.type !== 'text') return;
      const chunk = update.content.text;
      if (typeof chunk !== 'string') throw new Error('Invalid response text');
      answerBytes += Buffer.byteLength(chunk);
      if (answerBytes > MAX_TEXT) throw new Error('Goose response exceeds bound');
      answer += chunk;
    });
    if (terminal?.stopReason !== 'end_turn' || !answer.trim()) {
      return { phase: 'uncertain', reason, sessionId: nativeSessionId };
    }
    return { phase: 'completed', sessionId: nativeSessionId, text: answer };
  } catch {
    return exposed
      ? { phase: 'uncertain', reason, sessionId: nativeSessionId }
      : { phase: 'not_submitted', reason };
  } finally {
    cancellation?.[Symbol.dispose]();
    clearTimeout(cancellationDeadline);
    if (child) {
      child.stdin.end();
      child.stdout.resume();
      const kill = setTimeout(() => {
        child.kill('SIGKILL');
        child.stdout.destroy();
        child.stdin.destroy();
      }, 750);
      try {
        await closed;
      } finally {
        clearTimeout(kill);
      }
    }
  }
}
