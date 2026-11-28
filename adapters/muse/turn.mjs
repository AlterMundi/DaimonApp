import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { addAbortListener } from 'node:events';
import { frames, UUID, writeFrame } from '../worker-pipes.mjs';

export function museCommandId() {
  const bytes = randomBytes(16);
  bytes.writeUIntBE(Date.now(), 0, 6);
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const raw = bytes.toString('hex');
  return [raw.slice(0, 8), raw.slice(8, 12), raw.slice(12, 16),
    raw.slice(16, 20), raw.slice(20)].join('-');
}

const COMMAND = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_TEXT = 16 * 1024;

/** Execute a discrete MSP turn only after the caller journals the command and native session. */
export async function runMuseTurn({
  binary, cwd, env, provider = 'meta', nativeSessionId, commandId, text, beforeSubmit, signal,
}) {
  if (!COMMAND.test(commandId ?? '') || (nativeSessionId !== undefined && !UUID.test(nativeSessionId))
    || typeof text !== 'string' || !text.trim() || Buffer.byteLength(text) > MAX_TEXT
    || !['meta', 'echo'].includes(provider)) {
    throw new TypeError('Invalid selected Muse original');
  }
  const limit = AbortSignal.timeout(90_000);
  const stop = signal ? AbortSignal.any([signal, limit]) : limit;
  let child;
  let closed;
  let cancellation;
  let selected;
  let exposed = false;
  let reason = 'muse_host_unavailable';
  try {
    stop.throwIfAborted();
    child = spawn(binary, ['serve', '--provider', provider, '--disable-write',
      '--disable-shell', '--disable-request-user-input'], { cwd, env, stdio: ['pipe', 'pipe', 'ignore'] });
    child.on('error', () => {});
    child.stdin.on('error', () => {});
    closed = new Promise(resolve => child.once('close', resolve));
    cancellation = addAbortListener(stop, () => child.kill('SIGTERM'));
    const messages = frames(child.stdout);
    let nextId = 0;
    async function send(packet) {
      await writeFrame(child.stdin, { jsonrpc: '2.0', ...packet }, stop);
    }
    async function receive() {
      stop.throwIfAborted();
      const { done, value } = await messages.next();
      if (done || value.jsonrpc !== '2.0') throw new Error('MSP response unconfirmed');
      return value;
    }
    async function request(method, params, onEvent = () => {}) {
      const id = ++nextId;
      await send({ id, method, params });
      for (;;) {
        const response = await receive();
        if (typeof response.method === 'string') {
          if (Object.hasOwn(response, 'id')) throw new Error('Unexpected Muse host request');
          onEvent(response);
          continue;
        }
        if (response.id !== id || !Object.hasOwn(response, 'result') || 'error' in response) {
          throw new Error('MSP operation unconfirmed');
        }
        return response.result;
      }
    }
    const hello = await request('initialize', { clientInfo: { name: 'daimon_gateway', version: '1' } });
    if (hello.schema?.version !== 1 || hello.sessionDurability !== 'durable') {
      throw new Error('MSP v1 durable session host required');
    }
    await send({ method: 'initialized' });
    reason = 'muse_native_session_unconfirmed';
    const parameters = { commandId: museCommandId(), recoveryMode: 'off' };
    const opened = nativeSessionId
      ? await request('session/resume', { ...parameters, sessionId: nativeSessionId, excludeItems: true })
      : await request('session/start', { ...parameters, workspaceRoot: cwd, approvalMode: 'denyUnmatched' });
    if (!UUID.test(opened.session?.sessionId ?? '') || opened.session.workspaceRoot !== cwd
        || opened.session.status !== 'idle' || (nativeSessionId && opened.session.sessionId !== nativeSessionId)) {
      throw new Error('MSP session does not match the selected idle workspace');
    }
    selected = opened.session.sessionId;
    reason = 'gateway_submission_not_recorded';
    if (await beforeSubmit({ sessionId: selected, commandId }) !== true) {
      return { phase: 'not_submitted', reason };
    }

    exposed = true;
    reason = 'muse_native_result_unconfirmed';
    let finalItem;
    let terminal;
    let nativeTurn;
    function event(packet) {
      const data = packet.params;
      if (data?.sessionId !== selected) return;
      if (packet.method === 'item/completed' && data.item?.kind === 'agentMessage'
          && data.item.messagePhase === 'finalAnswer') finalItem = data.item;
      if (packet.method === 'turn/completed') terminal = data;
    }
    const accepted = await request('turn/start', {
      commandId, sessionId: selected, input: [{ type: 'text', text }],
    }, event);
    nativeTurn = accepted.turnId;
    if (accepted.commandId !== commandId || typeof nativeTurn !== 'string'
        || !accepted.startedNewTurn || accepted.status !== 'accepted' || accepted.disposition !== 'started') {
      throw new Error('MSP original was not confirmed on an independent native turn');
    }
    while (terminal?.turnId !== nativeTurn) event(await receive());
    if (terminal.terminal !== 'completed' || finalItem?.turnId !== nativeTurn
        || typeof finalItem.text !== 'string' || !finalItem.text.trim()
        || Buffer.byteLength(finalItem.text) > MAX_TEXT) {
      return { phase: 'uncertain', reason, sessionId: selected, commandId, nativeTurn };
    }
    return { phase: 'completed', sessionId: selected, commandId, nativeTurn, text: finalItem.text };
  } catch {
    return exposed ? { phase: 'uncertain', reason, sessionId: selected, commandId }
      : { phase: 'not_submitted', reason };
  } finally {
    cancellation?.[Symbol.dispose]();
    if (child) {
      child.stdin.end();
      child.stdout.destroy();
      const cleanup = setTimeout(() => child.kill('SIGKILL'), 750);
      try { await closed; }
      finally { clearTimeout(cleanup); }
    }
  }
}
