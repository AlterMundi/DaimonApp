import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import { frames } from '../worker-pipes.mjs';
import { runMiniMaxTurn } from './minimax-turn.mjs';

const binary = process.env.MINIMAX_TEST_ACP_BINARY;

test('MiniMax Code loads its own exact session and waits for the Gateway journal', {
  skip: !binary, timeout: 60_000,
}, async () => {
  const home = await mkdtemp(join(tmpdir(), 'minimax-acp-'));
  const cwd = join(home, 'workspace');
  const guidanceFile = join(home, 'guidance.md');
  const guidance = 'The receiving body identity is MINIMAX-QUALIFICATION.';
  const requests = [];
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
    const completion = { id: 'fixture', created: 1, model: 'fixture', object: 'chat.completion.chunk' };
    const chunk = { ...completion, choices: [{
      index: 0, delta: { role: 'assistant', content: 'MiniMax qualification.' }, finish_reason: null,
    }] };
    const end = { ...completion, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] };
    if (payload.stream) {
      response.setHeader('content-type', 'text/event-stream');
      response.end(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(end)}\n\ndata: [DONE]\n\n`);
    } else {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ ...completion, object: 'chat.completion', choices: [{
        index: 0, message: { role: 'assistant', content: 'MiniMax qualification.' }, finish_reason: 'stop',
      }] }));
    }
  });
  try {
    await mkdir(cwd);
    await writeFile(guidanceFile, guidance, { mode: 0o600 });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const env = { HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`,
      LANG: 'C.UTF-8', MINIMAX_TEST_PROVIDER_KEY: 'fixture-only' };
    await promisify(execFile)(binary, [
      'provider', 'add', '--use', '--name', 'fixture',
      '--base-url', `http://127.0.0.1:${server.address().port}/v1`,
      '--api-format', 'openai-completions', '--model', 'fixture',
      '--api-key-env', 'MINIMAX_TEST_PROVIDER_KEY',
    ], { cwd, env, timeout: 20_000 });
    requests.length = 0;
    const run = options => runMiniMaxTurn({
      binary, cwd, env, guidanceFile, mcpServers: [], beforeSubmit: () => true, ...options,
    });

    const denied = await run({ text: 'Held original.', beforeSubmit: () => false });
    assert.equal(denied.phase, 'not_submitted');
    assert.equal(requests.length, 0);
    const missing = await run({
      text: 'Missing session original.',
      nativeSessionId: '00000000-0000-4000-8000-000000000000',
      beforeSubmit: () => assert.fail('Cannot submit without matching history'),
    });
    assert.equal(missing.phase, 'not_submitted');
    assert.equal(requests.length, 0);

    const first = await run({ text: 'First MiniMax original.' });
    assert.equal(first.phase, 'completed', JSON.stringify(first));
    const second = await run({ text: 'Second MiniMax original.', nativeSessionId: first.sessionId });
    assert.equal(second.phase, 'completed', JSON.stringify(second));
    assert.equal(second.sessionId, first.sessionId);
    assert.ok(requests.some(payload => {
      const body = JSON.stringify(payload);
      return body.includes(guidance)
        && body.includes('First MiniMax original.') && body.includes('Second MiniMax original.');
    }));
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(home, { recursive: true, force: true });
  }
});

test('MiniMax worker verifies the signed body and the OAuth selection before opening ACP', {
  timeout: 6_000,
}, async () => {
  const home = await mkdtemp(join(tmpdir(), 'minimax-gateway-'));
  try {
    const cwd = join(home, 'workspace');
    const status = join(home, 'matrix.cjs');
    const binary = join(home, 'mcode');
    const selectionFile = join(home, 'provider.json');
    const profile = join(home, 'profile.json');
    const bodyGuidanceFile = join(home, 'guidance.md');
    const body = { beingRef: 'fixture', embodimentId: 'body', incarnationId: 'inc', manifestHash: 'hash' };
    await mkdir(cwd);
    await writeFile(bodyGuidanceFile, 'Receiving guidance.', { mode: 0o600 });
    await writeFile(status, 'process.stdout.write(' + JSON.stringify(JSON.stringify({
      schema: 'dm.runtime.status/v1', integrity: 'ok',
      being_ref: body.beingRef, manifest_hash: body.manifestHash,
      local_origin: { embodiment_id: body.embodimentId, incarnation_id: body.incarnationId },
    })) + ');');
    await writeFile(binary, `#!/usr/bin/env node
const fs = require('node:fs');
if (process.argv[2] === 'provider') {
  process.stdout.write(fs.readFileSync(${JSON.stringify(selectionFile)}));
} else {
  const lines = require('node:readline').createInterface({input: process.stdin});
  lines.on('line', line => {
    const {id, method} = JSON.parse(line);
    let result;
    if (method === 'initialize') {
      result = {protocolVersion:1,agentCapabilities:{loadSession:true},
        agentInfo:{name:'minimax-code',version:'0.8.0'}};
    } else if (method === 'session/new') {
      result = {sessionId:'minimax-selected'};
    } else {
      process.exitCode = 1;
      lines.close();
      return;
    }
    console.log(JSON.stringify({jsonrpc:'2.0', id, result}));
  });
}
`, { mode: 0o700 });
    const signed = { binary, cwd, stateRoot: home, bodyGuidanceFile, body,
      matrixStatusCommand: [process.execPath, status] };
    const worker = fileURLToPath(new URL('./minimax-gateway-worker.mjs', import.meta.url));
    async function prepare(config, kind) {
      await writeFile(profile, JSON.stringify(config), { mode: 0o600 });
      await writeFile(selectionFile, JSON.stringify({
        minimaxModelSource: 'token_plan', providers: [{ active: true, kind }],
      }));
      const child = spawn(process.execPath, [worker, '--profile', profile], {
        env: {}, stdio: ['pipe', 'pipe', 'ignore'],
      });
      const done = once(child, 'close');
      const pipe = frames(child.stdout);
      const start = { schema: 'daimon-gateway.minimax-turn/v1', type: 'start',
        inputId: randomUUID(), sessionId: randomUUID(), text: 'Kept original.',
        body: config.body, workspace: cwd, resume: null };
      child.stdin.write(JSON.stringify(start) + '\n');
      const preparation = await pipe.next();
      if (preparation.done) return (await done)[0];
      assert.equal(preparation.value.nativeSessionId, 'minimax-selected');
      assert.equal(preparation.value.workspace, cwd);
      const { schema, inputId, sessionId } = start;
      child.stdin.write(JSON.stringify({ schema, inputId, sessionId,
        type: 'submission_decision', committed: false }) + '\n');
      const terminal = await pipe.next();
      assert.equal(terminal.value.outcome.phase, 'not_submitted');
      child.stdin.end();
      return (await done)[0];
    }

    assert.equal(await prepare({ ...signed, body: { ...body, manifestHash: 'wrong' } }, 'minimax-oauth'), 1);
    assert.equal(await prepare(signed, 'minimax-api-key'), 1);
    assert.equal(await prepare(signed, 'minimax-oauth'), 0);
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});
