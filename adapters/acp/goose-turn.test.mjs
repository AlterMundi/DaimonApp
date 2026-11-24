import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { test } from 'node:test';

import { runGooseTurn } from './goose-turn.mjs';

const toolName = 'matrix__daimon_status';

async function temp(t) {
  const dir = await mkdtemp(join(tmpdir(), 'goose-turn-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

test('exact catalog and journal acknowledgement are required before provider input', async t => {
  const cwd = await temp(t);
  const binary = join(cwd, 'goose-fixture');
  const marker = join(cwd, 'provider');
  await writeFile(binary, `#!/usr/bin/node
const { createInterface } = require('node:readline');
const { appendFileSync } = require('node:fs');
const input = createInterface({ input: process.stdin });
function send(message) {
  console.log(JSON.stringify({ jsonrpc: '2.0', ...message }));
}
const sessionId = 'native-session-42';
input.on('line', line => {
  const { id, method, params } = JSON.parse(line);
  if (method === 'session/prompt') {
    if (params.sessionId !== sessionId) process.exit(2);
    appendFileSync(process.env.MARKER, 'provider\\n');
    if (process.env.OUTCOME === 'lost') process.exit(1);
    send({ method: 'session/update', params: {
      sessionId, update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Reply for 42' } },
    }});
  }
  const result = ({
    initialize: { protocolVersion: 1, agentCapabilities: { _meta: { goose: {
      nativeSkills: { enabled: process.env.GOOSE_DISABLE_SKILLS !== 'true' || process.env.OUTCOME === 'skills-on' },
    } } } },
    '_goose/unstable/config/extensions/list': { extensions: [{ enabled: false }] },
    'session/new': { sessionId },
    '_goose/unstable/tools/list': { tools: process.env.TOOLS.split(' ').map(name => ({ name })) },
    'session/prompt': { stopReason: 'end_turn' },
  })[method];
  send({ id, result });
});
`);
  await chmod(binary, 0o700);
  const run = (tools, beforeSubmit, outcome) => runGooseTurn({
    binary, cwd, env: { MARKER: marker, TOOLS: tools, OUTCOME: outcome ?? '' },
    mcpServers: [], toolNames: [toolName], text: 'Original 42', beforeSubmit,
  });
  const skills = await run(toolName, () => assert.fail('skill loader reached journal'), 'skills-on');
  assert.deepEqual(skills, { phase: 'not_submitted', reason: 'goose_catalog_unverified' });
  const wrong = await run(toolName + ' unexpected_tool', () => assert.fail('catalog drift reached journal'));
  assert.deepEqual(wrong, { phase: 'not_submitted', reason: 'goose_catalog_unverified' });
  const veto = await run(toolName, session => {
    assert.equal(session, 'native-session-42');
    return false;
  });
  assert.deepEqual(veto, { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' });
  await assert.rejects(readFile(marker), { code: 'ENOENT' });
  const accepted = await run(toolName, session => session === 'native-session-42');
  assert.deepEqual(accepted, { phase: 'completed', sessionId: 'native-session-42', text: 'Reply for 42' });
  const lost = await run(toolName, () => true, 'lost');
  assert.deepEqual(lost, { phase: 'uncertain', reason: 'native_result_unconfirmed', sessionId: 'native-session-42' });
  assert.equal(await readFile(marker, 'utf8'), 'provider\nprovider\n');
});

test('stock Goose cannot authorize a provider prompt', {
  skip: !process.env.GOOSE_TEST_STOCK_ACP_BINARY,
}, async t => {
  const cwd = await temp(t);
  assert.deepEqual(await runGooseTurn({
    binary: process.env.GOOSE_TEST_STOCK_ACP_BINARY, cwd,
    env: { PATH: '/usr/bin:/bin', HOME: cwd },
    mcpServers: [], toolNames: [toolName], text: 'Synthetic refusal fixture',
    beforeSubmit: () => assert.fail('unverified provider catalog reached journal'),
  }), { phase: 'not_submitted', reason: 'goose_catalog_unverified' });
});

test('pinned real Goose uses only the local provider after the journal acknowledges', {
  skip: !process.env.GOOSE_TEST_ACP_BINARY,
}, async t => {
  const cwd = await temp(t);
  const config = join(cwd, 'config');
  await mkdir(join(config, 'goose'), { recursive: true });
  const extensions = Object.fromEntries(['developer', 'extensionmanager', 'summon', 'tom', 'todo', 'summarize']
    .map(name => [name, { name, type: 'platform', enabled: false }]));
  await writeFile(join(config, 'goose', 'config.yaml'), JSON.stringify({ extensions }));
  const fixture = join(cwd, 'mcp.py');
  await writeFile(fixture, `
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        result = {
            "protocolVersion": request["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fixture", "version": "1"},
        }
    elif request["method"] == "tools/list":
        result = {"tools": [{
            "name": "daimon_status", "description": "Read synthetic status",
            "inputSchema": {"type": "object", "properties": {}},
        }]}
    else:
        print(json.dumps(dict(jsonrpc="2.0", id=request["id"], error=dict(code=-32601, message="Unsupported"))), flush=True)
        continue
    print(json.dumps(dict(jsonrpc="2.0", id=request["id"], result=result)), flush=True)
`);
  const requests = [];
  const original = 'native-goose-probe-42';
  const interrupted = 'native-goose-interrupt-43';
  const stop = new AbortController();
  const server = createServer(async (request, response) => {
    if (request.method !== 'POST') {
      response.writeHead(404).end();
      return;
    }
    let raw = '';
    for await (const bytes of request) raw += bytes;
    const body = JSON.parse(raw);
    requests.push({ url: request.url, body });
    if (JSON.stringify(body.messages).includes(interrupted)) {
      stop.abort();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const model = 'gpt-4o-mini';
    const event = (delta, finish_reason) => ({
      id: 'fixture-42', model, created: 1766229303, object: 'chat.completion.chunk',
      choices: [{ index: 0, delta, finish_reason }],
    });
    for (const part of [
      event({ role: 'assistant', content: 'Synthetic reply for 42' }, null), event({}, 'stop'),
      { ...event({}, null), choices: [], usage: { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28 } },
    ]) response.write('data: ' + JSON.stringify(part) + '\n\n');
    response.end('data: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  const binary = process.env.GOOSE_TEST_ACP_BINARY;
  const env = {
    PATH: '/usr/bin:/bin', HOME: cwd, XDG_CONFIG_HOME: config, XDG_DATA_HOME: join(cwd, 'data'),
    XDG_CACHE_HOME: join(cwd, 'cache'), GOOSE_PROVIDER: 'openai', GOOSE_MODEL: 'gpt-4o-mini',
    OPENAI_API_KEY: 'fixture-only', OPENAI_HOST: 'http://127.0.0.1:' + server.address().port,
  };
  let admitted;
  const result = await runGooseTurn({
    binary, cwd, env, toolNames: [toolName], text: original,
    mcpServers: [{ name: 'matrix', command: '/usr/bin/python3', args: [fixture], env: [] }],
    beforeSubmit(session) {
      assert.equal(requests.length, 0);
      admitted = session;
      return true;
    },
  });
  assert.ok(admitted, JSON.stringify(result));
  assert.deepEqual(result, { phase: 'completed', sessionId: admitted, text: 'Synthetic reply for 42' });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/v1/chat/completions');
  assert.ok(JSON.stringify(requests[0].body.messages).includes(original));

  let interruptedSession;
  const cancelled = await runGooseTurn({
    binary, cwd, env, toolNames: [toolName], text: interrupted, signal: stop.signal,
    mcpServers: [{ name: 'matrix', command: '/usr/bin/python3', args: [fixture], env: [] }],
    beforeSubmit(session) {
      assert.equal(requests.length, 1);
      interruptedSession = session;
      return true;
    },
  });
  assert.notEqual(interruptedSession, admitted);
  assert.deepEqual(cancelled, {
    phase: 'uncertain', sessionId: interruptedSession, reason: 'native_result_unconfirmed',
  });
  assert.equal(requests.length, 2);
});
