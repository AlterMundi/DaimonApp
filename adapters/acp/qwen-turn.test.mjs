import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { access, mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { runQwenTurn } from './qwen-turn.mjs';

const binary = process.env.QWEN_TEST_ACP_BINARY;
const answer = 'QWEN-ACP-PORTABILITY-OK';
const guidance = 'Apply the receiving body guidance. The next block is the current original.';
const settings = fileURLToPath(new URL('./qwen-pilot-settings.json', import.meta.url));

test('Qwen preserves native context across processes and honors the journal', {
  skip: !binary, timeout: 60_000,
}, async () => {
  const home = await mkdtemp(join(tmpdir(), 'qwen-acp-'));
  const cwd = join(home, 'workspace');
  const requests = [];
  const interrupt = new AbortController();
  const server = createServer(async (request, response) => {
    const buffers = [];
    for await (const bytes of request) buffers.push(bytes);
    if (request.method === 'GET') {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ object: 'list', data: [{ id: 'fixture', object: 'model' }] }));
      return;
    }
    const payload = JSON.parse(Buffer.concat(buffers).toString());
    requests.push(payload);
    assert.equal(payload.model, 'fixture');
    if (JSON.stringify(payload.messages).includes('Interrupt this ACP turn')) {
      interrupt.abort();
      return;
    }
    const completion = {
      id: 'fixture', created: 1, model: 'fixture', object: 'chat.completion.chunk',
    };
    const chunk = { ...completion, choices: [{
      index: 0, delta: { role: 'assistant', content: answer }, finish_reason: null,
    }] };
    const end = { ...completion, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] };
    response.setHeader('content-type', 'text/event-stream');
    response.end(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(end)}\n\ndata: [DONE]\n\n`);
  });
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const baseUrl = `http://127.0.0.1:${server.address().port}/v1`;
    await mkdir(cwd);
    const env = {
      HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`,
      LANG: 'C.UTF-8', OPENAI_API_KEY: 'fixture-only', OPENAI_BASE_URL: baseUrl,
      OPENAI_MODEL: 'fixture',
      QWEN_CODE_SYSTEM_SETTINGS_PATH: settings, QWEN_CODE_SYSTEM_DEFAULTS_PATH: settings,
    };
    async function step(text, expected, authorize = true) {
      let submissions = 0;
      const result = await runQwenTurn({
        binary, cwd, env, mcpServers: [], nativeSessionId: expected, freshSessionId: randomUUID(),
        model: 'fixture', text, instructions: guidance,
        beforeSubmit(id) {
          submissions++;
          if (expected) assert.equal(id, expected);
          return authorize;
        },
      });
      return { result, submissions };
    }
    const denied = await step('Original held by Gateway.', undefined, false);
    assert.equal(denied.result.phase, 'not_submitted');
    assert.equal(denied.submissions, 1);
    assert.equal(requests.length, 0);
    const first = await step('First ACP portability turn.');
    assert.equal(first.result.phase, 'completed', JSON.stringify(first.result));
    assert.equal(first.result.text, answer);
    await assert.rejects(access(join(home, '.qwen', 'settings.json')), { code: 'ENOENT' });
    const missing = await step('A missing binding must not reset the topic.',
      '00000000-0000-4000-8000-000000000000');
    assert.equal(missing.result.phase, 'not_submitted');
    assert.equal(missing.submissions, 0);
    const second = await step('Second ACP portability turn.', first.result.sessionId);
    assert.equal(second.result.phase, 'completed', JSON.stringify(second.result));
    assert.equal(second.result.sessionId, first.result.sessionId);
    assert.equal(requests.length, 2);
    assert.ok(JSON.stringify(requests[1].messages.at(-1).content).includes(guidance));
    assert.match(JSON.stringify(requests[1].messages), /First ACP portability turn/);
    assert.match(JSON.stringify(requests[1].messages), /Second ACP portability turn/);
    const cancelled = await runQwenTurn({
      binary, cwd, env, mcpServers: [], nativeSessionId: first.result.sessionId, model: 'fixture',
      text: 'Interrupt this ACP turn.', signal: interrupt.signal, beforeSubmit: () => true,
    });
    assert.deepEqual(cancelled, {
      phase: 'uncertain', reason: 'native_result_unconfirmed', sessionId: first.result.sessionId,
    });
    assert.equal(requests.length, 3);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(home, { recursive: true, force: true });
  }
});

test('Qwen refuses malformed and conflicting load responses before submission', async () => {
  const home = await mkdtemp(join(tmpdir(), 'qwen-acp-load-'));
  const stub = join(home, 'qwen');
  try {
    await writeFile(stub, `#!/usr/bin/env node
const { createInterface } = require('node:readline');
function send(message) {
  console.log(JSON.stringify({ jsonrpc: '2.0', ...message }));
}
createInterface({ input: process.stdin }).on('line', line => {
  const { id, method } = JSON.parse(line);
  if (method === 'initialize') {
    send({ id, result: {
      protocolVersion: 1, agentInfo: { name: 'qwen-code' },
      agentCapabilities: { loadSession: true },
    } });
  } else if (method === 'session/load') {
    const mode = process.env.LOAD_FIXTURE;
    if (mode === 'foreign-update') {
      send({ method: 'session/update', params: { sessionId: 'other', update: {
        sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Foreign history' },
      } } });
    }
    const result = mode === 'invalid' ? null : mode === 'foreign-id' ? { sessionId: 'other' } : {};
    send({ id, result });
  } else if (method === 'session/new' || method === 'session/prompt') {
    require('node:fs').writeFileSync('unexpected-foreground-operation', method);
    process.exit(2);
  }
});
`, { mode: 0o700 });
    for (const mode of ['invalid', 'foreign-id', 'foreign-update']) {
      let authorized = false;
      const result = await runQwenTurn({
        binary: stub, cwd: home, nativeSessionId: 'selected', mcpServers: [], text: 'Test original',
        env: { PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, LOAD_FIXTURE: mode },
        beforeSubmit() { authorized = true; return true; },
      });
      assert.deepEqual(result, { phase: 'not_submitted', reason: 'qwen_session_unconfirmed' });
      assert.equal(authorized, false);
    }
    await assert.rejects(access(join(home, 'unexpected-foreground-operation')), { code: 'ENOENT' });
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});


test('Qwen checks the workspace provider and signed body before starting the CLI', {
  timeout: 5_000,
}, async () => {
  const home = await mkdtemp(join(tmpdir(), 'qwen-gateway-route-'));
  try {
    const cwd = join(home, 'workspace');
    const config = join(cwd, '.qwen');
    const binary = join(home, 'qwen');
    const marker = join(home, 'cli-started');
    const providerKeyFile = join(home, 'key');
    const profile = join(home, 'profile.json');
    const bodyGuidanceFile = join(home, 'guidance');
    const status = join(home, 'status.json');
    const observer = join(home, 'body-status.cjs');
    const body = { beingRef: 'fixture', embodimentId: 'body', incarnationId: 'inc', manifestHash: 'hash' };
    await mkdir(config, { recursive: true });
    await writeFile(binary, `#!/usr/bin/env node
require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'started');
`, { mode: 0o700 });
    await writeFile(providerKeyFile, 'synthetic', { mode: 0o600 });
    await writeFile(bodyGuidanceFile, guidance, { mode: 0o600 });
    await writeFile(observer, "process.stdout.write(require('node:fs').readFileSync(process.argv[2]));");
    const observation = {
      schema: 'dm.runtime.status/v1', integrity: 'ok', being_ref: body.beingRef,
      manifest_hash: body.manifestHash,
      local_origin: { embodiment_id: body.embodimentId, incarnation_id: body.incarnationId },
    };
    await writeFile(status, JSON.stringify(observation));
    await writeFile(profile, JSON.stringify({ binary, cwd, stateRoot: home, model: 'fixture',
      body, providerKeyFile, bodyGuidanceFile,
      matrixStatusCommand: [process.execPath, observer, status] }), { mode: 0o600 });
    const worker = fileURLToPath(new URL('./qwen-gateway-worker.mjs', import.meta.url));
    async function run() {
      const child = spawn(process.execPath, [worker, '--profile', profile], {
        env: {}, stdio: ['pipe', 'ignore', 'ignore'],
      });
      const exit = once(child, 'close');
      child.stdin.end(JSON.stringify({ schema: 'daimon-gateway.qwen-turn/v1', type: 'start',
        inputId: randomUUID(), sessionId: randomUUID(), text: 'synthetic',
        body, workspace: cwd, resume: null }) + '\n');
      await exit;
    }
    const override = join(config, 'settings.json');
    await writeFile(override, JSON.stringify({ modelProviders: { openai: [{
      id: 'fixture', baseUrl: 'http://127.0.0.1:1/v1',
    }] } }));
    await run();
    await assert.rejects(access(marker), { code: 'ENOENT' });
    await rm(override);
    await writeFile(status, JSON.stringify({ ...observation, manifest_hash: 'different' }));
    await run();
    await assert.rejects(access(marker), { code: 'ENOENT' });
    await writeFile(status, JSON.stringify(observation));
    await run();
    await access(marker);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});
