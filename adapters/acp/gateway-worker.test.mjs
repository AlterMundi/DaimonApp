import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { frames, writeFrame } from '../worker-pipes.mjs';

const binary = process.env.GOOSE_TEST_ACP_BINARY;
const worker = fileURLToPath(new URL('./gateway-worker.mjs', import.meta.url));

test('Goose worker reaches the owner decision with its selected status MCP on the real binary', {
  skip: !binary,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'goose-gateway-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const config = join(root, 'config', 'goose');
  await mkdir(config, { recursive: true });
  const extensions = Object.fromEntries(['developer', 'extensionmanager', 'summon', 'tom', 'todo', 'summarize']
    .map(name => [name, { name, type: 'platform', enabled: false }]));
  await writeFile(join(config, 'config.yaml'), JSON.stringify({ extensions }), { mode: 0o600 });
  const key = join(root, 'provider-fixture');
  await writeFile(key, 'fixture-only\n', { mode: 0o600 });
  const status = join(root, 'status.py');
  const body = { beingRef: 'fixture-being', embodimentId: 'fixture-body',
    incarnationId: 'fixture-incarnation', manifestHash: 'a'.repeat(64) };
  await writeFile(status, `
import json
import sys
assert sys.argv[1:] == ["--body-status"]
assert json.load(sys.stdin)["source"] == {"being_ref": "fixture-being", "embodiment_id": "fixture-body"}
print(json.dumps({"schema": "dm.runtime.status/v1", "integrity": "ok",
  "being_ref": "fixture-being", "manifest_hash": "a" * 64,
  "local_origin": {"embodiment_id": "fixture-body", "incarnation_id": "fixture-incarnation"}}))
`, { mode: 0o600 });
  const profile = join(root, 'profile.json');
  await writeFile(profile, JSON.stringify({
    binary, cwd: root, stateRoot: root, provider: 'openai', model: 'gpt-4o-mini',
    providerKeyFile: key, matrixStatusCommand: ['/usr/bin/python3', status], body,
  }), { mode: 0o600 });
  const child = spawn(process.execPath, [worker, '--profile', profile], {
    env: {}, stdio: ['pipe', 'pipe', 'ignore'],
  });
  const finished = once(child, 'close');
  t.after(() => { child.kill('SIGKILL'); });
  const messages = frames(child.stdout);
  const same = { schema: 'daimon-gateway.goose-turn/v1',
    inputId: '00000000-0000-4000-8000-000000000001', sessionId: '00000000-0000-4000-8000-000000000002' };
  await writeFrame(child.stdin, { ...same, type: 'start', text: 'Synthetic fixture only', body });
  const first = (await messages.next()).value;
  assert.equal(first.type, 'prepare_submission', JSON.stringify(first));
  assert.notEqual(first.nativeSessionId, same.sessionId);
  const { nativeSessionId, ...correlation } = first;
  assert.ok(nativeSessionId);
  assert.deepEqual(correlation, { ...same, type: 'prepare_submission' });
  await writeFrame(child.stdin, { ...same, type: 'submission_decision', committed: false });
  assert.deepEqual((await messages.next()).value, {
    ...same, type: 'outcome', outcome: { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' },
  });
  child.stdin.end();
  assert.deepEqual(await finished, [0, null]);
});
