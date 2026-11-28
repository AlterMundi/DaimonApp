import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdtemp, rm, rmdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { fileURLToPath } from 'node:url';

import { frames, writeFrame } from '../worker-pipes.mjs';
import { runAntigravityTurn } from './antigravity-turn.mjs';

const binary = process.env.AGY_TEST_AUTHENTICATED_BINARY;

test('agy reopens the exact sandboxed session using the selected account', {
  skip: !binary, timeout: 90_000,
}, async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agy-native-reopen-'));
  const marker = `DAIMON-${randomBytes(5).toString('hex')}`;
  const options = { binary, cwd, env: process.env, model: 'gemini-4-neon', effort: 'medium',
    signal: AbortSignal.timeout(85_000) };
  const admissions = [];
  const beforeSubmit = async id => { admissions.push(id); return true; };
  try {
    const first = await runAntigravityTurn({ ...options, beforeSubmit,
      text: `For this synthetic test remember the marker ${marker}. Reply only ACK. Do not use tools.` });
    assert.equal(first.phase, 'completed', first.reason);
    assert.equal(first.text.trim(), 'ACK');
    const resumed = await runAntigravityTurn({ ...options, nativeSessionId: first.sessionId, beforeSubmit,
      text: 'Reply with just the marker I supplied in this conversation. Do not use tools.' });
    assert.equal(resumed.phase, 'completed', resumed.reason);
    assert.equal(resumed.sessionId, first.sessionId);
    assert.equal(resumed.text.trim(), marker);
    assert.deepEqual(admissions, [first.sessionId, first.sessionId]);

    const withheld = await runAntigravityTurn({ ...options, nativeSessionId: first.sessionId,
      text: 'Synthetic original withheld by the journal.', beforeSubmit: async () => false });
    assert.equal(withheld.phase, 'not_submitted');
    assert.equal(withheld.reason, 'gateway_submission_not_recorded');
    const missing = await runAntigravityTurn({ ...options, nativeSessionId: randomUUID(), beforeSubmit,
      text: 'Synthetic original addressed to a missing session.' });
    assert.equal(missing.phase, 'not_submitted');
    assert.deepEqual(admissions, [first.sessionId, first.sessionId]);
  } finally {
    await rmdir(cwd);
  }
});


test('agy reports only a matching native cancellation receipt as interrupted', { timeout: 10_000 }, async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'agy-native-interrupt-'));
  const fixture = join(cwd, 'agy.mjs');
  const sessionId = randomUUID();
  try {
    await writeFile(fixture, `#!${process.execPath}
import assert from 'node:assert/strict';
import { createInterface } from 'node:readline';
import { createConnection } from 'node:net';
const send = value => console.log(JSON.stringify({ jsonrpc: '2.0', ...value }));
const sessionId = ${JSON.stringify(sessionId)};
let promptId;
let controller;
let pendingTool;
const call = { operation: 'capabilities', arguments: {} };
for await (const line of createInterface({ input: process.stdin })) {
  const { id, method, params, result } = JSON.parse(line);
  if (id === 'permission' && !method) {
    assert.equal(result.outcome.outcome, 'selected');
    pendingTool = new Promise((resolve, reject) => {
      const socket = createConnection(controller.path);
      socket.on('error', reject);
      socket.on('connect', () => socket.write(JSON.stringify({ nonce: controller.nonce, call }) + '\\n'));
      socket.setEncoding('utf8');
      let reply = '';
      socket.on('data', chunk => { reply += chunk; });
      socket.on('end', () => resolve(JSON.parse(reply)));
    });
    continue;
  }
  switch (method) {
    case 'initialize':
      send({ id, result: { protocolVersion: 1, agentInfo: { name: 'Antigravity ACP Server' } } });
      break;
    case 'session/new':
      controller = JSON.parse(params.mcpServers[0]?.env[0].value ?? '{}').controller;
      send({ id, result: { sessionId, configOptions: [
        { category: 'model', id: 'model', currentValue: 'gemini-4-neon' },
        { category: 'thought_level', id: 'thought_level', currentValue: 'medium' },
      ] } });
      break;
    case 'session/prompt':
      assert.equal(promptId, undefined);
      assert.equal(params.sessionId, sessionId);
      promptId = id;
      send({ method: 'session/update', params: { sessionId, update: {
        sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Started' },
      } } });
      if (controller) send({ id: 'permission', method: 'session/request_permission', params: {
        sessionId, toolCall: { name: 'mcp_matrix_interaction_controller', rawInput: call },
        options: [{ kind: 'allow_once', optionId: 'allow' }],
      } });
      break;
    case 'session/cancel':
      assert.equal(id, undefined);
      assert.equal(params.sessionId, sessionId);
      assert.ok(promptId);
      if (controller) {
        const tool = await pendingTool;
        assert.equal(tool?.isError, true);
        assert.match(tool.content[0].text, /unconfirmed/);
      }
      if (process.env.FIXTURE_RECEIPT === 'none') process.exit(0);
      send({ id: promptId + Number(process.env.FIXTURE_RECEIPT === 'wrong-id'),
        result: { stopReason: 'cancelled' } });
      break;
    default:
      assert.fail('Unexpected ACP frame');
  }
}
`, { mode: 0o700 });
    for (const receipt of ['confirmed', 'wrong-id', 'none', 'hard-stop', 'withheld', 'before-prompt']) {
      const interrupt = new AbortController();
      const hardStop = new AbortController();
      let accepted = 0;
      const result = await runAntigravityTurn({
        binary: fixture, cwd, env: { FIXTURE_RECEIPT: receipt },
        model: 'gemini-4-neon', effort: 'medium', text: 'Synthetic original',
        signal: hardStop.signal, interruptSignal: interrupt.signal,
        beforeSubmit: async id => {
          assert.equal(id, sessionId);
          if (receipt === 'withheld' || receipt === 'before-prompt') interrupt.abort();
          return receipt !== 'withheld';
        },
        onInputAccepted: async id => {
          assert.equal(id, sessionId);
          accepted++;
          if (receipt === 'hard-stop') hardStop.abort();
          else interrupt.abort();
        },
      });
      assert.equal(accepted, ['withheld', 'before-prompt'].includes(receipt) ? 0 : 1, receipt);
      assert.deepEqual(result, receipt === 'confirmed' ? { phase: 'interrupted', sessionId }
        : receipt === 'withheld' ? { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' }
        : receipt === 'before-prompt' ? { phase: 'not_submitted', reason: 'native_interrupt_before_prompt' }
          : { phase: 'uncertain', reason: 'native_result_unconfirmed', sessionId }, receipt);
    }

    const body = { beingRef: 'fixture-being', embodimentId: 'fixture-body',
      incarnationId: 'fixture-incarnation', manifestHash: 'a'.repeat(64) };
    const status = join(cwd, 'status.mjs');
    await writeFile(status, `
console.log(JSON.stringify({
  schema: 'dm.runtime.status/v1', integrity: 'ok', being_ref: ${JSON.stringify(body.beingRef)},
  manifest_hash: ${JSON.stringify(body.manifestHash)},
  local_origin: { embodiment_id: ${JSON.stringify(body.embodimentId)},
    incarnation_id: ${JSON.stringify(body.incarnationId)} },
}));
`, { mode: 0o600 });
    const profile = join(cwd, 'profile.json');
    await writeFile(profile, JSON.stringify({
      adapter: 'agy', binary: fixture, home: cwd, cwd, model: 'gemini-4-neon', effort: 'medium',
      matrixStatusCommand: [process.execPath, status], body,
    }), { mode: 0o600 });

    for (const controller of [false, true]) {
      const worker = fileURLToPath(new URL('./gateway-worker.mjs', import.meta.url));
      const child = spawn(process.execPath, [worker, '--profile', profile], { stdio: ['pipe', 'pipe', 'ignore'] });
      const closed = once(child, 'close');
      try {
        const scope = { schema: 'daimon-gateway.antigravity-turn/v2', inputId: randomUUID(), sessionId: randomUUID() };
        const replies = frames(child.stdout);
        await writeFrame(child.stdin, { ...scope, type: 'start', text: 'Synthetic original',
          body, workspace: cwd, resumeNativeSessionId: null, ...(controller ? { controller } : {}) });
        const prepared = (await replies.next()).value;
        assert.equal(prepared?.type, 'prepare_submission');
        assert.equal(prepared.nativeSessionId, sessionId);
        assert.equal(prepared.targetedInterrupt, true);
        await writeFrame(child.stdin, { ...scope, type: 'submission_decision', committed: true,
          observeAcceptance: true, targetedInterrupt: true });
        assert.deepEqual((await replies.next()).value, { ...scope, type: 'input_accepted', nativeSessionId: sessionId });
        if (controller) {
          const pending = (await replies.next()).value;
          assert.equal(pending?.type, 'controller_call');
          assert.equal(pending.operation, 'capabilities');
        }
        await writeFrame(child.stdin, { ...scope, type: 'interrupt' });
        assert.deepEqual((await replies.next()).value, {
          ...scope, type: 'outcome', outcome: { phase: 'interrupted', sessionId },
        });
        child.stdin.end();
        assert.deepEqual(await closed, [0, null]);
      } finally {
        child.kill('SIGKILL');
      }
    }
  } finally {
    await rm(cwd, { recursive: true, force: true });
  }
});
