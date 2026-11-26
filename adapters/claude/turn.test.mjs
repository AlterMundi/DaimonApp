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
  const success = {
    type: 'result', subtype: 'success', is_error: false,
    session_id: input.sessionId, result: 'Synthetic body status.',
  };
  const budgetExhausted = { ...success, subtype: 'error_max_budget_usd', is_error: true };
  for (const result of [
    success, undefined, { ...success, session_id: undefined }, { ...success, is_error: undefined },
    budgetExhausted, { ...budgetExhausted, session_id: undefined },
  ]) {
    const events = [];
    const resume = result === success;
    const outcome = await runClaudeTurn(options({
      input: { ...input, resume },
      beforeSubmit: (id, sessionId) => { events.push(['record', id, sessionId]); return true; },
      query: ({ prompt, options: nativeOptions }) => ({
        async initializationResult() {
          assert.equal(nativeOptions.resume, resume ? input.sessionId : undefined);
          assert.equal(nativeOptions.sessionId, resume ? undefined : input.sessionId);
          return { claude_code_version: 'fixture-version' };
        },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            events.push(['input', request.message.content]);
          }
          yield { type: 'system', session_id: input.sessionId };
          if (result) yield result;
        },
        close() {},
      }),
    }));
    assert.deepEqual(events, [['record', input.id, input.sessionId], ['input', input.text]]);
    assert.equal(outcome.phase, result === success ? 'completed' : 'uncertain');
    assert.equal(outcome.sessionId, input.sessionId);
    if (result === budgetExhausted) assert.equal(outcome.reason, 'claude_budget_exhausted');
    else assert.notEqual(outcome.reason, 'claude_budget_exhausted');
  }
});

test('only an explicitly selected human goal uses the native command mode', async () => {
  for (const [nativeGoalCommand, supported] of [[false, true], [true, true], [true, false]]) {
    const observed = [];
    const text = '/goal';
    const outcome = await runClaudeTurn(options({
      input: { ...input, text, nativeGoalCommand },
      beforeSubmit: () => { observed.push('committed'); return true; },
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async supportedCommands() { return supported ? [{ name: 'goal' }] : []; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            observed.push('submitted');
            assert.equal(request.message.content, text);
            assert.equal(request.client_composed, nativeGoalCommand ? undefined : true);
            assert.deepEqual(request.origin, nativeGoalCommand ? { kind: 'human' } : undefined);
          }
          yield { type: 'result', subtype: 'success', is_error: false,
            session_id: input.sessionId, result: 'No goal set.' };
        },
        close() {},
      }),
    }));
    assert.deepEqual(observed, supported ? ['committed', 'submitted'] : []);
    assert.equal(outcome.phase, supported ? 'completed' : 'not_submitted');
    if (!supported) assert.equal(outcome.reason, 'claude_goal_command_unavailable');
  }
});

test('subscription refusal is retained without mistaking it for an unobserved result', async () => {
  const resetsAt = 1795719000;
  for (const [workObserved, terminalObserved] of [[false, true], [true, true], [false, false]]) {
    const outcome = await runClaudeTurn(options({
      beforeSubmit: () => true,
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            const session_id = request.session_id;
            if (workObserved) yield { type: 'assistant', session_id, message: { content: [{ type: 'tool_use' }] } };
            yield { type: 'rate_limit_event', session_id,
              rate_limit_info: { status: 'rejected', rateLimitType: 'five_hour', resetsAt } };
            yield { type: 'assistant', session_id, parent_tool_use_id: null, error: 'rate_limit',
              message: { model: '<synthetic>', content: [{ type: 'text', text: 'Untrusted raw provider content' }] } };
            if (terminalObserved) yield { type: 'result', session_id, subtype: 'error_during_execution', is_error: true };
          }
        },
        close() {},
      }),
    }));
    assert.deepEqual(outcome, {
      phase: 'subscription_limited', sessionId: input.sessionId, workObserved, terminalObserved,
      limit: { window: 'five_hour', resets_at: resetsAt },
    });
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

test('shared DMK guidance distinguishes recall from the selected native writer', async () => {
  const writer = '/fixture tools/dmk';
  for (const sharedDmkWriter of [undefined, writer]) {
    let append;
    const profile = { ...options().profile, sharedDmk: {}, sharedDmkWriter };
    await runClaudeTurn(options({
      profile,
      query({ options: nativeOptions }) {
        append = nativeOptions.systemPrompt.append;
        throw new Error('Stop after inspecting the prompt');
      },
    }));
    assert.match(append, /The DMK MCP connector provides contextual recall and reads/);
    assert.equal(append.includes(JSON.stringify(writer)), sharedDmkWriter === writer);
  }
});

test('committed private work can outlive startup while bounded work still expires', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  for (const profile of [
    { fullAccess: true },
    { fullAccess: true, maxBudgetUsd: 0.10 },
    { fullAccess: false },
  ]) {
    const bounded = !profile.fullAccess || profile.maxBudgetUsd !== undefined;
    const outcome = await runClaudeTurn(options({
      profile: { ...options().profile, ...profile },
      beforeSubmit: () => true,
      query: ({ prompt, options: nativeOptions }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            t.mock.timers.tick(121_000);
            assert.equal(nativeOptions.abortController.signal.aborted, bounded);
            if (bounded) return;
            yield { type: 'result', subtype: 'success', is_error: false,
              session_id: request.session_id, result: 'Long private result.' };
          }
        },
        close() {},
      }),
    }));
    assert.equal(outcome.phase, bounded ? 'uncertain' : 'completed');
  }
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
        ['missing resume', false, true, 'claude_resume_session_missing'],
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
          input: { ...input, resume: name === 'missing resume' },
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
