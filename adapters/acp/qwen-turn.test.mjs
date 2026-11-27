import assert from 'node:assert/strict';
import { access, mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';

import { runQwenTurn } from './qwen-turn.mjs';

const binary = process.env.QWEN_TEST_ACP_BINARY;
const answer = 'QWEN-ACP-PORTABILITY-OK';

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
    await mkdir(join(home, '.qwen'), { mode: 0o700 });
    await writeFile(join(home, '.qwen', 'settings.json'), JSON.stringify({
      security: { auth: { selectedType: 'openai' } },
      general: { enableAutoUpdate: false },
      telemetry: { enabled: false },
      ui: { enableFollowupSuggestions: false },
      memory: {
        enableManagedAutoMemory: false, enableManagedAutoDream: false, enableAutoSkill: false,
        enableTeamMemorySync: false, enableStructuredRecall: false,
      },
      modelProviders: { openai: [{
        id: 'fixture', baseUrl, envKey: 'OPENAI_API_KEY', generationConfig: { maxRetries: 0 },
      }] },
    }));
    const env = {
      HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`,
      LANG: 'C.UTF-8', OPENAI_API_KEY: 'fixture-only', OPENAI_BASE_URL: baseUrl,
      OPENAI_MODEL: 'fixture',
    };
    async function step(text, expected, authorize = true) {
      let submissions = 0;
      const result = await runQwenTurn({
        binary, cwd, env, mcpServers: [], nativeSessionId: expected, text,
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
    const missing = await step('A missing binding must not reset the topic.',
      '00000000-0000-4000-8000-000000000000');
    assert.equal(missing.result.phase, 'not_submitted');
    assert.equal(missing.submissions, 0);
    const second = await step('Second ACP portability turn.', first.result.sessionId);
    assert.equal(second.result.phase, 'completed', JSON.stringify(second.result));
    assert.equal(second.result.sessionId, first.result.sessionId);
    assert.equal(requests.length, 2);
    assert.match(JSON.stringify(requests[1].messages), /First ACP portability turn/);
    assert.match(JSON.stringify(requests[1].messages), /Second ACP portability turn/);
    const cancelled = await runQwenTurn({
      binary, cwd, env, mcpServers: [], nativeSessionId: first.result.sessionId,
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
