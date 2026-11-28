import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdtemp, rmdir } from 'node:fs/promises';
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
