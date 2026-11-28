import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdtemp, rm, rmdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

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

test('agy reports a declined native tool without converting uncertainty into a reply', async t => {
  const cwd = await mkdtemp(join(tmpdir(), 'agy-declined-tool-'));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const server = join(cwd, 'agent.cjs');
  const sessionId = randomUUID();
  await writeFile(server, String.raw`#!${process.execPath}
const assert = require('node:assert/strict');
const readline = require('node:readline');
const sessionId = ${JSON.stringify(sessionId)};
const send = message => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n');
let original;
readline.createInterface({ input: process.stdin }).on('line', line => {
  const { id, method, result } = JSON.parse(line);
  if (method === 'initialize') {
    send({ id, result: { protocolVersion: 1, agentInfo: { name: 'Antigravity ACP Server' } } });
  } else if (method === 'session/new') {
    send({ id, result: { sessionId, configOptions: [
      { id: 'model', category: 'model', currentValue: 'gemini-4-neon' },
      { id: 'thought', category: 'thought_level', currentValue: 'medium' },
    ] } });
  } else if (method === 'session/prompt') {
    original = id;
    send({ id: 100, method: 'session/request_permission', params: {
      sessionId, toolCall: { name: 'run_command' },
      options: [{ optionId: 'allow', kind: 'allow_once' }, { optionId: 'reject', kind: 'reject_once' }],
    } });
  } else if (id === 100) {
    assert.deepEqual(result, { outcome: { outcome: 'selected', optionId: 'reject' } });
    send({ id: original, error: { code: -32603, message: 'Fixture closed after a refused tool' } });
  }
});
`, { mode: 0o700 });

  const receipts = [];
  const outcome = await runAntigravityTurn({
    binary: server, cwd, env: process.env, model: 'gemini-4-neon', effort: 'medium',
    text: 'A synthetic prompt with a tool request.',
    beforeSubmit: async id => { receipts.push(['submitted', id]); return true; },
    onInputAccepted: async id => { receipts.push(['accepted', id]); },
    signal: AbortSignal.timeout(5000),
  });
  assert.deepEqual(receipts, [['submitted', sessionId], ['accepted', sessionId]]);
  assert.deepEqual(outcome, { phase: 'uncertain', reason: 'native_tool_declined_without_reply', sessionId });
});
