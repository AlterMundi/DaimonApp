import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { frames, writeFrame } from '../worker-pipes.mjs';
import { callController, controllerBridge, controllerCallKey } from './controller-bridge.mjs';
import { sharedMemory } from './shared-memory.mjs';

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


async function isolatedGooseProfile(root) {
  const config = join(root, 'config', 'goose');
  await mkdir(config, { recursive: true });
  const extensions = Object.fromEntries(['developer', 'extensionmanager', 'summon', 'tom', 'todo', 'summarize']
    .map(name => [name, { name, type: 'platform', enabled: false }]));
  await writeFile(join(config, 'config.yaml'), JSON.stringify({ extensions }), { mode: 0o600 });
  const key = join(root, 'provider-fixture');
  await writeFile(key, 'fixture-only\n', { mode: 0o600 });
  return key;
}

async function runWorker(t, profile, text, beforeDecision, agy, controller) {
  const child = spawn(process.execPath, [worker, '--profile', profile], {
    env: {}, stdio: ['pipe', 'pipe', 'ignore'],
  });
  const finished = once(child, 'close');
  t.after(() => { child.kill('SIGKILL'); });
  const messages = frames(child.stdout);
  const same = { schema: agy ? 'daimon-gateway.antigravity-turn/v2' : 'daimon-gateway.goose-turn/v1',
    inputId, sessionId: '00000000-0000-4000-8000-000000000002' };
  await writeFrame(child.stdin, { ...same, type: 'start', text, body, ...agy, ...(controller ? { controller: true } : {}) });
  const first = (await messages.next()).value;
  if (beforeDecision === null) {
    assert.deepEqual(first, { ...same, type: 'outcome', outcome: first.outcome });
    child.stdin.end();
    assert.deepEqual(await finished, [0, null]);
    return { outcome: first.outcome };
  }
  assert.equal(first.type, 'prepare_submission', JSON.stringify(first));
  assert.notEqual(first.nativeSessionId, same.sessionId);
  const { nativeSessionId, ...correlation } = first;
  assert.ok(nativeSessionId);
  assert.deepEqual(correlation, { ...same, type: 'prepare_submission',
    ...(agy ? { workspace: agy.workspace, inputAcceptance: true, workAcceptance: true, targetedInterrupt: true } : {}) });
  const committed = beforeDecision(nativeSessionId);
  await writeFrame(child.stdin, {
    ...same, type: 'submission_decision', committed,
    ...(agy && committed ? { observeAcceptance: true, requireWork: true } : {}),
  });
  if (agy && committed) {
    assert.deepEqual((await messages.next()).value, { ...same, type: 'input_accepted', nativeSessionId });
  }
  let settled = (await messages.next()).value;
  while (controller && settled?.type === 'controller_call') {
    const { callId, operation, arguments: args } = settled;
    assert.deepEqual(settled, { ...same, type: 'controller_call', nativeSessionId, callId, operation, arguments: args });
    await writeFrame(child.stdin, { ...same, type: 'controller_reply', callId,
      success: true, text: controller(operation, args) });
    settled = (await messages.next()).value;
  }
  assert.deepEqual(settled, { ...same, type: 'outcome', outcome: settled.outcome });
  child.stdin.end();
  assert.deepEqual(await finished, [0, null]);
  return { nativeSessionId, outcome: settled.outcome };
}

test('agy foreground worker journals, uses its selected tool and resumes the same native session', {
  skip: !process.env.AGY_TEST_AUTHENTICATED_BINARY, timeout: 90_000,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'agy-gateway-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const profile = join(root, 'profile.json');
  const orientation = join(root, 'embodiment.md');
  await writeFile(orientation, 'You are embodied as AUDIT-GREEN. Use that exact name when asked.', { mode: 0o600 });
  const skills = join(root, 'skills');
  const fixtureSkill = join(skills, 'fixture-marker');
  await mkdir(fixtureSkill, { recursive: true });
  await writeFile(join(fixtureSkill, 'SKILL.md'),
    '---\nname: fixture-marker\ndescription: Returns the fixture marker.\n---\nThe marker is MARBLE-ORBIT.\n');
  await writeFile(profile, JSON.stringify({
    adapter: 'agy', binary: process.env.AGY_TEST_AUTHENTICATED_BINARY, cwd: root,
    home: process.env.HOME, model: 'gemini-4-neon', effort: 'medium',
    matrixStatusCommand: await fixtureObservation(root), body, bodyGuidanceFile: orientation,
    sharedSkillsDirectory: skills,
  }), { mode: 0o600 });
  const start = { workspace: root, resumeNativeSessionId: null };
  const withheld = await runWorker(t, profile, 'Keep this fixture unsent.', () => false, start);
  assert.deepEqual(withheld.outcome, { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' });
  const first = await runWorker(t, profile,
    'Call the MCP tool shared_skill with name fixture-marker. Reply only with the marker from that skill. Remember the phrase jade-pocket.',
    () => true, start);
  assert.equal(first.outcome.phase, 'completed', first.outcome.reason);
  assert.equal(first.outcome.text.trim(), 'MARBLE-ORBIT');
  const resumed = await runWorker(t, profile,
    'Reply with your receiving body name and the phrase I directly asked you to remember. Omit the marker returned by the skill.',
    id => { assert.equal(id, first.nativeSessionId); return true; },
    { ...start, resumeNativeSessionId: first.nativeSessionId });
  assert.equal(resumed.outcome.phase, 'completed', resumed.outcome.reason);
  assert.deepEqual(resumed.outcome.text.trim().split(/\s+/), ['AUDIT-GREEN', 'jade-pocket']);
});

test('the ACP controller socket requires turn activation, native tool selection and its own nonce', { timeout: 5000 }, async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const stop = new AbortController();
  const signal = AbortSignal.timeout(2000);
  const correlation = { schema: 'fixture', inputId, sessionId: 'attempt' };
  const call = { operation: 'capabilities', arguments: {} };
  const bridge = await controllerBridge(correlation, output, stop);
  const wire = frames(output);
  try {
    assert.equal((await callController(bridge.access, call, signal)).isError, true);
    const grants = new Set();
    const serving = bridge.serve(frames(input), 'native', key => grants.delete(key));
    assert.equal((await callController(bridge.access, call, signal)).isError, true);
    grants.add(controllerCallKey(call));
    assert.equal((await callController({ ...bridge.access, nonce: 'wrong' }, call, signal)).isError, true);
    assert.equal((await callController(bridge.access, { ...call, operation: 'session_request' }, signal)).isError, true);
    assert.equal(grants.size, 1);
    const result = callController(bridge.access, call, signal);
    assert.deepEqual((await wire.next()).value, {
      ...correlation, ...call, type: 'controller_call', nativeSessionId: 'native', callId: 1,
    });
    assert.equal(grants.size, 0);
    await writeFrame(input, { ...correlation, type: 'controller_reply', callId: 1,
      success: true, text: 'confirmed' });
    assert.deepEqual(await result, { isError: false, content: [{ type: 'text', text: 'confirmed' }] });
    assert.equal((await callController(bridge.access, call, signal)).isError, true);
    grants.add(controllerCallKey(call));
    const pending = callController(bridge.access, call, signal);
    assert.equal((await wire.next()).value?.callId, 2);
    bridge.interrupt();
    assert.deepEqual(await pending, {
      isError: true, content: [{ type: 'text', text: 'Controller result unconfirmed. Inspect retained state.' }],
    });
    await writeFrame(input, { ...correlation, type: 'controller_reply', callId: 2,
      success: true, text: 'late confirmation' });
    assert.equal(stop.signal.aborted, false);
    grants.add(controllerCallKey(call));
    assert.equal((await callController(bridge.access, call, signal)).isError, true);
    assert.equal(grants.size, 1);
    input.end();
    await serving;
    assert.equal(stop.signal.aborted, true);
  } finally {
    input.destroy();
    output.destroy();
    await bridge.close();
  }
});

test('agy calls the scoped Gateway controller before completing the same turn', {
  skip: !process.env.AGY_TEST_AUTHENTICATED_BINARY, timeout: 45_000,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'agy-controller-worker-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const profile = join(root, 'profile.json');
  await writeFile(profile, JSON.stringify({
    adapter: 'agy', binary: process.env.AGY_TEST_AUTHENTICATED_BINARY, cwd: root,
    home: process.env.HOME, model: 'gemini-4-neon', effort: 'medium',
    matrixStatusCommand: await fixtureObservation(root), body,
  }), { mode: 0o600 });
  const operations = [];
  const { outcome } = await runWorker(t, profile,
    'Call interaction_controller with operation capabilities and arguments {}. Reply only with its marker.',
    () => true, { workspace: root, resumeNativeSessionId: null }, (operation, args) => {
      operations.push([operation, args]);
      return JSON.stringify({ marker: 'COPPER-VALLEY' });
    });
  assert.deepEqual(operations, [['capabilities', {}]]);
  assert.equal(outcome.phase, 'completed');
  assert.equal(outcome.text.trim(), 'COPPER-VALLEY');
});

test('agy accepts an owner-retained image and leaves a changed image unsent', {
  skip: !process.env.AGY_TEST_AUTHENTICATED_BINARY, timeout: 45_000,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'agy-image-worker-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const profile = join(root, 'profile.json');
  await writeFile(profile, JSON.stringify({
    adapter: 'agy', binary: process.env.AGY_TEST_AUTHENTICATED_BINARY, cwd: root,
    home: process.env.HOME, model: 'gemini-4-neon', effort: 'medium',
    matrixStatusCommand: await fixtureObservation(root), body,
  }), { mode: 0o600 });
  const redPng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAAQ0lEQVR4nO3OMQ0AIBAAsRfBjH9RiMEFx9CkAjpn7a9MPhASEhKqB0JCQkL1QEhISKgeCAkJCdUDISEhoXogJCT02AUpiX6I5IlWSAAAAABJRU5ErkJggg==', 'base64');
  const path = join(root, createHash('sha256').update(redPng).digest('hex'));
  await writeFile(path, redPng, { mode: 0o600 });
  const start = { workspace: root, resumeNativeSessionId: null,
    attachments: [{ path, mime: 'image/png' }] };
  const accepted = await runWorker(t, profile,
    'What primary color is the attached square? Reply only with the color.', () => true, start);
  assert.equal(accepted.outcome.phase, 'completed', accepted.outcome.reason);
  assert.match(accepted.outcome.text.trim(), /^red[.!]?$/i);

  await writeFile(path, Buffer.alloc(redPng.length));
  const changed = await runWorker(t, profile, 'Do not submit changed bytes.', null, start);
  assert.deepEqual(changed.outcome,
    { phase: 'not_submitted', reason: 'antigravity_attachment_unavailable' });
});

test('Goose worker reaches the owner decision with its selected status MCP on the real binary', {
  skip: !binary,
}, async t => {
  const root = await mkdtemp(join(tmpdir(), 'goose-gateway-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const key = await isolatedGooseProfile(root);
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
  const { outcome } = await runWorker(t, profile, 'Synthetic fixture only', () => false);
  assert.deepEqual(outcome, { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' });
  const endpoint = createServer(() => assert.fail('Provider received HTTP during admission'));
  endpoint.listen(0, '127.0.0.1');
  await once(endpoint, 'listening');
  const providerPort = endpoint.address().port;
  await new Promise((resolve, reject) => endpoint.close(error => error ? reject(error) : resolve()));
  const offline = { ...JSON.parse(await readFile(profile, 'utf8')), providerPort };
  await writeFile(profile, JSON.stringify(offline));
  const refused = await runWorker(t, profile, 'Synthetic fixture with no listener', null);
  assert.deepEqual(refused.outcome, { phase: 'not_submitted', reason: 'goose_provider_unavailable' });
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
  const scopedMemory = { command: command.slice(0, -2), bindingFile: requestBinding, bodyRef };
  const readRequest = { action: 'read', pool: 'main', record_uid: selected.record_uid,
    expected_revision: selected.revision };
  const memory = await sharedMemory({ body, sharedMemory: scopedMemory },
    readRequest, AbortSignal.timeout(8000));
  assert.equal(memory.pools[0].result.raw, text);
  const search = await sharedMemory({ body, sharedMemory: scopedMemory },
    { action: 'search', query: 'Portability fixture' }, AbortSignal.timeout(8000));
  assert.equal(search.pools[0].result.items[0].record_uid, selected.record_uid);
  await assert.rejects(sharedMemory({ body, sharedMemory: scopedMemory },
    { ...readRequest, action: 'delete' }, AbortSignal.timeout(8000)));
  if (process.env.AGY_TEST_AUTHENTICATED_BINARY) {
    await t.test('agy reads DMK through the owner-selected memory binding', async t => {
      const profile = join(root, 'agy-dmk.json');
      await writeFile(profile, JSON.stringify({
        adapter: 'agy', binary: process.env.AGY_TEST_AUTHENTICATED_BINARY, cwd: root,
        home: process.env.HOME, model: 'gemini-4-neon', effort: 'medium',
        matrixStatusCommand, body, sharedMemory: scopedMemory,
      }), { mode: 0o600 });
      const { outcome } = await runWorker(t, profile,
        'Call dmk_recall to search for the exact title Portability fixture, then call dmk_recall again with action read, its returned record_uid and pool. Reply with just the color in the original record.',
        () => true, { workspace: root, resumeNativeSessionId: null });
      assert.equal(outcome.phase, 'completed', outcome.reason);
      assert.equal(outcome.text.trim().toLowerCase(), 'blue');
    });
  }
  if (binary) {
    await t.test('real worker uses the DMK record and offers only the approved tools', async t => {
      const key = await isolatedGooseProfile(root);
      const requests = [];
      const tool = 'matrix__dmk_read_selected';
      const answer = 'The approved marker was blue.';
      const prompt = 'Use the approved memory to tell me the marker color.';
      let committed = false;
      const server = createServer(async (request, response) => {
        if (request.method !== 'POST') {
          response.writeHead(404).end();
          return;
        }
        let raw = '';
        for await (const part of request) raw += part;
        const data = JSON.parse(raw);
        const toolNames = data.tools?.map(value => value.function.name).sort();
        const messages = data.messages;
        const hasSource = messages.some(message => message.role === 'tool'
          && JSON.stringify(message).includes(text));
        requests.push({ committed, path: request.url, toolNames, hasSource });
        if (!committed || request.url !== '/v1/chat/completions' || requests.length > 2
            || JSON.stringify(messages).includes('This decoy must stay private.')) {
          response.writeHead(400).end();
          return;
        }
        function chunk(delta, finish_reason) {
          return { id: 'fixture-memory-401', model: 'gpt-4o-mini',
            created: 1766229303, object: 'chat.completion.chunk',
            choices: [{ index: 0, delta, finish_reason }],
          };
        }
        const content = hasSource
          ? [chunk({ role: 'assistant', content: answer }, null), chunk({}, 'stop')]
          : [chunk({ role: 'assistant', tool_calls: [{ index: 0, id: 'call_memory_401',
            type: 'function', function: { name: tool, arguments: '{}' } }] }, null), chunk({}, 'tool_calls')];
        const usage = { prompt_tokens: 8, completion_tokens: 7, total_tokens: 15 };
        response.writeHead(200, { 'Content-Type': 'text/event-stream' });
        for (const item of [...content, { ...chunk({}, null), choices: [], usage }]) {
          response.write('data: ' + JSON.stringify(item) + '\n\n');
        }
        response.end('data: [DONE]\n\n');
      });
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
      t.after(() => { server.closeAllConnections(); server.close(); });
      const wrapper = join(root, 'goose-loopback');
      await symlink(binary, wrapper + '.native');
      await writeFile(wrapper, `#!/bin/sh
export OPENAI_HOST=http://127.0.0.1:${server.address().port}
exec "$0.native" "$@"
`, { mode: 0o700 });
      const profile = join(root, 'profile.json');
      const selectedMemory = {
        command, inputId, pool: 'main', recordUid: selected.record_uid, revision: selected.revision, bodyRef,
      };
      await writeFile(profile, JSON.stringify({ binary: wrapper, cwd: root, stateRoot: root,
        provider: 'openai', model: 'gpt-4o-mini', providerKeyFile: key, matrixStatusCommand, body, selectedMemory,
      }), { mode: 0o600 });
      const result = await runWorker(t, profile, prompt, () => {
        assert.equal(requests.length, 0);
        committed = true;
        return true;
      });
      assert.deepEqual(result.outcome, { phase: 'completed', sessionId: result.nativeSessionId, text: answer });
      assert.deepEqual(requests, [false, true].map(hasSource => ({
        committed: true, path: '/v1/chat/completions', toolNames: ['matrix__daimon_status', tool], hasSource,
      })));
    });
  }
  assert.deepEqual(await readFile(database), before);
});
