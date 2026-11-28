import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rmdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { museCommandId, runMuseTurn } from './turn.mjs';

const binary = process.env.MUSE_TEST_BINARY;

test('Muse MSP returns a durable exact session and submits only journaled originals', {
  skip: !binary, timeout: 45_000,
}, async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'muse-msp-native-'));
  try {
    const intended = [];
    const beforeSubmit = async original => { intended.push(original); return true; };
    const options = { binary, cwd, provider: 'echo', env: process.env, beforeSubmit };
    const firstCommand = museCommandId();
    const first = await runMuseTurn({ ...options, commandId: firstCommand, text: 'MSP ECHO ONE' });
    assert.equal(first.phase, 'completed', first.reason);
    assert.ok(first.text.includes('MSP ECHO ONE'));
    assert.equal(first.commandId, firstCommand);

    const secondCommand = museCommandId();
    const second = await runMuseTurn({ ...options, nativeSessionId: first.sessionId,
      commandId: secondCommand, text: 'MSP ECHO TWO' });
    assert.equal(second.phase, 'completed', second.reason);
    assert.equal(second.sessionId, first.sessionId);
    assert.notEqual(second.nativeTurn, first.nativeTurn);
    assert.ok(second.text.includes('MSP ECHO TWO'));
    assert.deepEqual(intended, [
      { sessionId: first.sessionId, commandId: firstCommand },
      { sessionId: first.sessionId, commandId: secondCommand },
    ]);

    const denied = await runMuseTurn({ ...options, nativeSessionId: first.sessionId,
      commandId: museCommandId(), text: 'Keep this unsent', beforeSubmit: async () => false });
    assert.deepEqual(denied, { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' });

    const missing = await runMuseTurn({ ...options, nativeSessionId: randomUUID(),
      commandId: museCommandId(), text: 'Do not replace this missing session' });
    assert.deepEqual(missing, { phase: 'not_submitted', reason: 'muse_native_session_unconfirmed' });
    assert.equal(intended.length, 2);
  } finally {
    await rmdir(cwd);
  }
});
