import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { frames, writeFrame } from '../worker-pipes.mjs';

const binary = process.env.GOOSE_TEST_ACP_BINARY;
const worker = fileURLToPath(new URL('./gateway-worker.mjs', import.meta.url));
const exec = promisify(execFile);
const body = { beingRef: 'fixture-being', embodimentId: 'fixture-body',
  incarnationId: 'fixture-incarnation', manifestHash: 'a'.repeat(64) };
const inputId = '00000000-0000-4000-8000-000000000001';

async function fixtureObservation(root) {
  const status = join(root, 'status.py');
  await writeFile(status, `
import json
import sys
assert sys.argv[1:] == ["--body-status"]
assert json.load(sys.stdin)["source"] == {"being_ref": "fixture-being", "embodiment_id": "fixture-body"}
print(json.dumps({"schema": "dm.runtime.status/v1", "integrity": "ok",
  "being_ref": "fixture-being", "manifest_hash": "a" * 64,
  "local_origin": {"embodiment_id": "fixture-body", "incarnation_id": "fixture-incarnation"}}))
`, { mode: 0o600 });
  return ['/usr/bin/python3', status];
}


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
  const matrixStatusCommand = await fixtureObservation(root);
  const marker = join(root, 'early-memory-read');
  const reader = join(root, 'dmk-fixture.py');
  await writeFile(reader, `
from pathlib import Path
import sys
Path(sys.argv[1]).touch()
raise SystemExit(2)
`, { mode: 0o600 });
  const profile = join(root, 'profile.json');
  await writeFile(profile, JSON.stringify({
    binary, cwd: root, stateRoot: root, provider: 'openai', model: 'gpt-4o-mini',
    providerKeyFile: key, matrixStatusCommand, body,
    selectedMemory: {
      command: ['/usr/bin/python3', reader, marker], inputId, pool: 'main',
      recordUid: '00000000-0000-4000-8000-000000000003', revision: 1, bodyRef: 'fixture:goose',
    },
  }), { mode: 0o600 });
  const child = spawn(process.execPath, [worker, '--profile', profile], {
    env: {}, stdio: ['pipe', 'pipe', 'ignore'],
  });
  const finished = once(child, 'close');
  t.after(() => { child.kill('SIGKILL'); });
  const messages = frames(child.stdout);
  const same = { schema: 'daimon-gateway.goose-turn/v1',
    inputId, sessionId: '00000000-0000-4000-8000-000000000002' };
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
  await assert.rejects(readFile(marker), { code: 'ENOENT' });
});

test('Goose MCP exposes only the selected native DMK record revision', {
  skip: !process.env.DMK_TEST_SCRIPTS,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'goose-dmk-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const database = join(root, 'library.db');
  const reader = process.env.DMK_TEST_SCRIPTS;
  const python = process.env.DMK_TEST_PYTHON ?? '/usr/bin/python3';
  const text = 'The synthetic fixture used a blue marker.';
  const { stdout } = await exec(python, ['-B', '-c', `
import json, sys
sys.path.insert(0, sys.argv[1])
import memoryctl as memory
memory.init_db()
selected = memory.add_text("library", "Portability fixture", sys.argv[2])
memory.add_text("library", "Unselected control", "This decoy must stay private.")
print(json.dumps(memory._read_chapter(selected)))
`, reader, text], { cwd: root, env: {
    PATH: '/usr/bin:/bin', HOME: root, HMK_AGENT_MEMORY_BASE: root, HMK_DB_PATH: database,
  }, maxBuffer: 16000, timeout: 10000 });
  const selected = JSON.parse(stdout);
  const requestBinding = join(root, 'recall.json');
  const bodyRef = 'fixture:goose';
  await writeFile(requestBinding, JSON.stringify({
    schema: 'hmk.deep-recall.binding/v1', being_ref: body.beingRef, body_ref: bodyRef,
    pools: [{ name: 'main', database }],
  }), { mode: 0o600 });
  const matrixStatusCommand = await fixtureObservation(root);
  const command = [python, join(reader, 'dmk_mcp.py'), '--binding', requestBinding];
  const before = await readFile(database);
  async function exercise(revision, check) {
    const selectedMemory = {
      command, inputId, pool: 'main', recordUid: selected.record_uid, revision, bodyRef,
    };
    const child = spawn(process.execPath, [worker, '--matrix-mcp'], {
      stdio: ['pipe', 'pipe', 'ignore'],
      env: { DAIMON_OBSERVATION: JSON.stringify({ body, matrixStatusCommand, selectedMemory }) },
    });
    const finished = once(child, 'close');
    const messages = frames(child.stdout);
    let id = 0;
    async function call(method, params) {
      await writeFrame(child.stdin, { jsonrpc: '2.0', id: ++id, method, params });
      const reply = (await messages.next()).value;
      assert.equal(reply.id, id);
      return reply;
    }
    try {
      const tools = (await call('tools/list', {})).result.tools;
      assert.deepEqual(tools.map(tool => tool.name), ['daimon_status', 'dmk_read_selected']);
      assert.equal((await call('tools/call', {
        name: 'dmk_read_selected', arguments: { recordUid: 'another-record' },
      })).error.code, -32601);
      const reply = await call('tools/call', { name: 'dmk_read_selected', arguments: {} });
      await check(reply.result);
    } finally {
      child.stdin.end();
      assert.deepEqual(await finished, [0, null]);
    }
  }
  await exercise(selected.revision, outcome => {
    assert.deepEqual(JSON.parse(outcome.content[0].text), {
      pool: 'main', record_uid: selected.record_uid, revision: selected.revision, text,
    });
  });
  await exercise(selected.revision + 1, outcome => {
    assert.equal(outcome.isError, true);
    assert.ok(!JSON.stringify(outcome).includes(text));
  });
  assert.deepEqual(await readFile(database), before);
});
