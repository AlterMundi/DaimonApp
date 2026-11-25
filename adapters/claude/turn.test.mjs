import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';

import { runClaudeTurn } from './turn.mjs';

const expectedBody = { beingRef: 'fixture-being', embodimentId: 'fixture-body', incarnationId: 'fixture-live', manifestHash: 'fixture-manifest' };
const status = {
  schema: 'dm.runtime.status/v1', integrity: 'ok', being_ref: expectedBody.beingRef,
  manifest_hash: expectedBody.manifestHash,
  local_origin: { embodiment_id: expectedBody.embodimentId, incarnation_id: expectedBody.incarnationId },
};
const connected = [{ name: 'matrix', source: 'sdk', status: 'connected', tools: [{ name: 'daimon_status' }] }];
const input = { id: 'f7a01e1c-e56e-4244-af02-dbf554097205',
  sessionId: '2aebcc8d-c0c8-494b-b751-91459dd88a94', text: 'Return the synthetic body status.' };

function options(overrides) {
  return {
    broker: { server: {}, readStatus: async () => status },
    expectedBody, toolNames: ['daimon_status'], input,
    profile: { binary: 'fixture', cwd: 'fixture', cliVersion: 'fixture-version', env: { CLAUDE_CONFIG_DIR: 'fixture' } },
    beforeSubmit() {},
    ...overrides,
  };
}

test('submission is recorded before input and loss leaves the same request uncertain', async () => {
  for (const hasResult of [true, false]) {
    const events = [];
    const outcome = await runClaudeTurn(options({
      beforeSubmit: (id, sessionId) => { events.push(['record', id, sessionId]); return true; },
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            events.push(['input', request.message.content]);
          }
          yield { type: 'system', session_id: input.sessionId };
          if (hasResult) {
            yield { type: 'result', subtype: 'success', is_error: false,
              session_id: input.sessionId, result: 'Synthetic body status.' };
          }
        },
        close() {},
      }),
    }));
    assert.deepEqual(events, [['record', input.id, input.sessionId], ['input', input.text]]);
    assert.equal(outcome.phase, hasResult ? 'completed' : 'uncertain');
    assert.equal(outcome.sessionId, input.sessionId);
  }
});

test('wrong receiving incarnation refuses before spawning Claude', async () => {
  const result = await runClaudeTurn(options({
    expectedBody: { ...expectedBody, incarnationId: 'replacement' },
    query: () => assert.fail('Unexpected query for mismatched identity'),
  }));
  assert.deepEqual(result, { phase: 'not_submitted', reason: 'matrix_identity_mismatch' });
});

test('unavailable Matrix refuses before spawning Claude', async () => {
  const result = await runClaudeTurn(options({
    broker: { readStatus: async () => { throw new Error('Fixture disconnected'); } },
    query: () => assert.fail('Unexpected query with Matrix unavailable'),
  }));
  assert.deepEqual(result, { phase: 'not_submitted', reason: 'matrix_identity_unverified' });
});

const sdkPath = process.env.CLAUDE_TEST_SDK_PATH;
const cliVersion = process.env.CLAUDE_TEST_CLI_VERSION ?? '2.1.323';
const claudePath = process.env.CLAUDE_TEST_BINARY;
test('pinned Agent SDK observes the effective MCP catalog without releasing a prompt',
  { skip: !sdkPath || !claudePath, timeout: 25_000 }, async () => {
    const { query, tool, createSdkMcpServer } = await import(pathToFileURL(sdkPath));
    const root = await mkdtemp(join(tmpdir(), 'gateway-claude-preflight-'));
    try {
      for (const [name, extra, liveOnSecondRead, reason] of [
        ['exact', false, true, 'gateway_submission_not_recorded'],
        ['extra', true, true, 'claude_catalog_mismatch'],
        ['changed', false, false, 'matrix_identity_changed'],
      ]) {
        const directory = join(root, name);
        await mkdir(directory, { mode: 0o700 });
        let readCount = 0;
        let committed = 0;
        let launched = 0;
        const fixtureTool = tool('daimon_status', 'Synthetic status', {}, () => {
          launched += 1;
          assert.fail('No prompt must reach the model');
        });
        const server = createSdkMcpServer({
          name: 'fixture-matrix',
          tools: extra ? [fixtureTool, tool('unexpected_tool', 'Unexpected', {}, () => assert.fail())] : [fixtureTool],
        });
        const outcome = await runClaudeTurn(options({
          query,
          broker: { server, readStatus: async () => {
            readCount += 1;
            return liveOnSecondRead || readCount === 1 ? status : null;
          }},
          profile: { binary: claudePath, cwd: directory, cliVersion, env: {
            HOME: directory, PATH: '/usr/bin:/bin', CLAUDE_CONFIG_DIR: directory,
            DISABLE_AUTOUPDATER: '1', DISABLE_TELEMETRY: '1',
          }},
          beforeSubmit() {
            committed += 1;
            return false; // Do not release a provider input during preflight.
          },
          signal: AbortSignal.timeout(7_000),
        }));
        assert.deepEqual(outcome, { phase: 'not_submitted', reason }, name);
        assert.equal(committed, name === 'exact' ? 1 : 0, name);
        assert.equal(launched, 0);
      }
    } finally {
      await rm(root, { recursive: true });
    }
  });
