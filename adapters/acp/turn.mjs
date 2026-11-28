import { spawn } from 'node:child_process';
import { addAbortListener, once } from 'node:events';

import { acpFrames } from './frames.mjs';

const MAX_TEXT = 16 * 1024;
const DEADLINE_MS = 120_000;

export function validateSessionId(value) {
  if (typeof value !== 'string' || value.length === 0 || Buffer.byteLength(value) > 256
      || /[\s\p{Cc}]/u.test(value)) throw new Error('Invalid native ACP session ID');
  return value;
}

export async function runAcpTurn({
  binary, args, cwd, env, text, beforeSubmit, signal, openSession,
  unavailable, openFailure, allowLargeCommandList = false, selectPermission, instructions, images = [],
  onInputAccepted,
}) {
  if (typeof text !== 'string' || (!text.trim() && !images.length) || Buffer.byteLength(text) > MAX_TEXT) {
    throw new TypeError('Invalid ACP foreground input');
  }
  if (instructions !== undefined && (typeof instructions !== 'string'
      || !instructions.trim() || Buffer.byteLength(instructions) > 8 * 1024)) {
    throw new TypeError('Invalid ACP receiving guidance');
  }
  const deadline = AbortSignal.timeout(DEADLINE_MS);
  const stop = signal ? AbortSignal.any([signal, deadline]) : deadline;
  let child;
  let closed;
  let cancellation;
  let cancellationDeadline;
  let nativeSessionId;
  let exposed = false;
  let reason = unavailable;
  try {
    stop.throwIfAborted();
    child = spawn(binary, args, {
      cwd, env,
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
    const replies = acpFrames(child.stdout, { allowLargeCommandList });
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
        if (done) throw new Error('ACP closed before its response');
        if (typeof value.method === 'string') {
          if ('id' in value) {
            if (value.method === 'session/request_permission' && selectPermission) {
              const optionId = exposed && value.params?.sessionId === nativeSessionId
                ? selectPermission(value.params) : undefined;
              await send({ id: value.id, result: { outcome: optionId
                ? { outcome: 'selected', optionId } : { outcome: 'cancelled' } } });
            } else {
              await send({
                id: value.id, error: { code: -32601, message: 'Client operation unavailable' },
              });
            }
          } else if (value.method === 'session/update') {
            await onUpdate?.(value.params);
          }
          continue;
        }
        if (value.id !== id || !('result' in value) || 'error' in value) {
          throw new Error('ACP response unconfirmed');
        }
        return value.result;
      }
    }

    const initialized = await request('initialize', { protocolVersion: 1, clientCapabilities: {} });
    if (initialized?.protocolVersion !== 1) throw new Error('ACP v1 required');
    reason = openFailure;
    if (images.length && initialized.agentCapabilities?.promptCapabilities?.image !== true) {
      return { phase: 'not_submitted', reason: 'acp_image_input_unavailable' };
    }
    nativeSessionId = validateSessionId(await openSession(request, initialized));

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

    let inputAccepted = false;
    let answer = '';
    let answerBytes = 0;
    const terminal = await request('session/prompt', {
      sessionId: nativeSessionId,
      prompt: [
        ...(instructions ? [{ type: 'text', text: instructions }] : []),
        ...(text ? [{ type: 'text', text }] : []),
        ...images,
      ],
    }, async ({ sessionId, update } = {}) => {
      if (sessionId !== nativeSessionId) throw new Error('ACP update came from another session');
      if (update?.sessionUpdate !== 'agent_message_chunk' || update.content?.type !== 'text') return;
      const chunk = update.content.text;
      if (typeof chunk !== 'string') throw new Error('Invalid response text');
      answerBytes += Buffer.byteLength(chunk);
      if (answerBytes > MAX_TEXT) throw new Error('ACP response exceeds bound');
      if (!inputAccepted && chunk.trim() && onInputAccepted) {
        await onInputAccepted(nativeSessionId);
        inputAccepted = true;
      }
      answer += chunk;
    });
    const visible = answer.trim();
    const rawToolCall = visible.startsWith('<tool_call>')
      && visible.includes('<function=')
      && !visible.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, '').trim();
    if (terminal?.stopReason !== 'end_turn' || !visible || rawToolCall) {
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
