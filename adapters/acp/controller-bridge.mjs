import { randomBytes } from 'node:crypto';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { createConnection, createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { closed, frames, writeFrame } from '../worker-pipes.mjs';

export const CONTROLLER = 'interaction_controller';
const LIMIT = 15600;

export function controllerError(text) {
  return { isError: true, content: [{ type: 'text', text }] };
}

export function controllerArguments(value) {
  return closed(value, ['operation', 'arguments'])
    && typeof value.operation === 'string' && /^[a-z_]{1,64}$/.test(value.operation)
    && value.arguments && typeof value.arguments === 'object' && !Array.isArray(value.arguments)
    && Buffer.byteLength(JSON.stringify(value.arguments)) <= LIMIT;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(key =>
      JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
  }
  return JSON.stringify(value);
}

export function controllerCallKey(value) {
  const args = { ...value };
  delete args.toolSummary;
  return controllerArguments(args) ? canonicalJson(args) : undefined;
}

// The ACP stdio MCP process is separate from the worker that owns the
// Gateway pipe. This private, per-turn socket carries only tool calls.
export async function controllerBridge(correlation, output, stop) {
  const directory = await mkdtemp(join(tmpdir(), 'daimon-acp-'));
  const access = { path: join(directory, 'controller.sock'), nonce: randomBytes(32).toString('hex') };
  const sockets = new Set();
  const pending = new Map();
  let active;
  let nextCall = 0;
  const uncertain = () => controllerError('Controller result unconfirmed. Inspect retained state.');

  const server = createServer(socket => {
    socket.on('error', () => {});
    if (sockets.size >= 8 || stop.signal.aborted) {
      socket.destroy();
      return;
    }
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
    void (async () => {
      const unread = setTimeout(() => socket.destroy(), 2000);
      try {
        const { value: request } = await frames(socket).next();
        clearTimeout(unread);
        if (!active || stop.signal.aborted || !closed(request, ['nonce', 'call'])
            || request.nonce !== access.nonce || !controllerArguments(request.call)) {
          socket.destroy();
          return;
        }
        const turn = active;
        if (!turn.claim(controllerCallKey(request.call))) {
          socket.destroy();
          return;
        }
        const callId = ++nextCall;
        const result = new Promise(resolve => pending.set(callId, resolve));
        await writeFrame(output, { ...correlation, ...request.call, type: 'controller_call',
          nativeSessionId: turn.nativeSessionId, callId }, stop.signal);
        socket.end(JSON.stringify(await result) + '\n');
      } catch {
        socket.destroy();
      } finally {
        clearTimeout(unread);
      }
    })();
  });
  async function close() {
    active = undefined;
    for (const socket of sockets) socket.destroy();
    for (const resolve of pending.values()) resolve(uncertain());
    pending.clear();
    server.close();
    await rm(directory, { recursive: true, force: true });
  }
  try {
    server.listen(access.path);
    await once(server, 'listening', { signal: stop.signal });
  } catch (error) {
    await close();
    throw error;
  }
  return {
    access, close,
    async serve(input, nativeSessionId, claim) {
      active = { nativeSessionId, claim };
      try {
        for await (const reply of input) {
          if (!closed(reply, ['schema', 'type', 'inputId', 'sessionId', 'callId', 'success', 'text'])
              || reply.type !== 'controller_reply' || reply.schema !== correlation.schema
              || reply.inputId !== correlation.inputId || reply.sessionId !== correlation.sessionId
              || !pending.has(reply.callId) || typeof reply.success !== 'boolean'
              || typeof reply.text !== 'string') break;
          const resolve = pending.get(reply.callId);
          pending.delete(reply.callId);
          resolve({ isError: !reply.success, content: [{ type: 'text', text: reply.text }] });
        }
      } finally {
        active = undefined;
        stop.abort();
      }
    },
  };
}

export async function callController(access, call, signal) {
  if (!controllerArguments(call)) return controllerError('Invalid controller call.');
  const socket = createConnection(access.path);
  const stop = () => socket.destroy();
  socket.on('error', stop);
  signal.addEventListener('abort', stop, { once: true });
  try {
    await once(socket, 'connect', { signal });
    await writeFrame(socket, { nonce: access.nonce, call }, signal);
    const { value } = await frames(socket).next();
    return value ?? controllerError('Controller result unconfirmed. Inspect retained state.');
  } catch {
    return controllerError('Controller result unconfirmed. Inspect retained state.');
  } finally {
    socket.destroy();
    signal.removeEventListener('abort', stop);
  }
}
