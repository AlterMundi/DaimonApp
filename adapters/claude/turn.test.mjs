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

test('native input acceptance uses the exact root UUID before the final result', async () => {
  const status = { type: 'system', subtype: 'status', session_id: input.sessionId };
  let receipts = 0;
  const outcome = await runClaudeTurn(options({
    beforeSubmit: () => true,
    onInputAccepted() { receipts++; },
    query: ({ prompt }) => ({
      async initializationResult() { return { claude_code_version: 'fixture-version' }; },
      async mcpServerStatus() { return connected; },
      async *[Symbol.asyncIterator]() {
        for await (const _request of prompt) {}
        yield { ...status, user_message_uuids: [input.sessionId] };
        yield { ...status, type: 'assistant', parent_tool_use_id: 'nested', user_message_uuids: [input.id] };
        assert.equal(receipts, 0);
        yield { ...status, user_message_uuids: [input.id] };
        assert.equal(receipts, 1);
        yield { ...status, type: 'assistant', user_message_uuids: [input.id] };
        assert.equal(receipts, 1);
        yield { type: 'result', subtype: 'success', is_error: false, session_id: input.sessionId, result: 'Done.' };
      },
      close() {},
    }),
  }));
  assert.equal(outcome.phase, 'completed');
  assert.equal(receipts, 1);
});

test('cumulative usage requires a complete native attribution and a valid model map', async () => {
  const resultId = '911842d8-c25a-4b7e-bd86-7d0d817e279b';
  const counts = { inputTokens: 12, outputTokens: 4, cacheReadInputTokens: 8, cacheCreationInputTokens: 2 };
  const modelUsage = { answer: counts, evaluator: counts };
  for (const [ids, usage, matching] of [
    [[input.id], modelUsage, true],
    [[input.sessionId], modelUsage, false],
    [[input.id, input.sessionId], modelUsage, false],
    [[input.id, input.id], modelUsage, false],
    [input.id, modelUsage, false],
    [[input.id], [counts], false],
  ]) {
    const outcome = await runClaudeTurn(options({
      beforeSubmit: () => true,
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const _request of prompt) {}
          yield { type: 'result', subtype: 'success', is_error: false,
            session_id: input.sessionId, result: 'Done.', uuid: resultId,
            user_message_uuids: ids, modelUsage: usage,
          };
        },
        close() {},
      }),
    }));
    assert.equal(outcome.phase, 'completed');
    assert.deepEqual(outcome.sessionUsage, matching
      ? { resultId, inputTokens: 24, outputTokens: 8, cacheReadInputTokens: 16, cacheCreationInputTokens: 4 }
      : undefined);
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

test('portable pause and resume cannot replace a Claude goal condition', async () => {
  for (const text of ['/goal pause', '/goal resume', '/goal  resume ', '/goal Pause', '/goal  RESUME ']) {
    const outcome = await runClaudeTurn(options({
      input: { ...input, text, nativeGoalCommand: true },
      beforeSubmit: () => assert.fail('A goal control must not commit native input'),
      query: () => assert.fail('A goal control must not start the native writer'),
    }));
    assert.deepEqual(outcome, { phase: 'not_submitted', reason: 'claude_goal_control_unavailable' });
  }
});

test('fresh history quotes preserve the distinct current original at submission', async () => {
  const historySeed = { turn: 7, human: 'Review the layout.', assistant: 'I can update the layout next.' };
  const text = 'Yes, do that.';
  const outcome = await runClaudeTurn(options({
    input: { ...input, text, historySeed },
    beforeSubmit: () => true,
    query: ({ prompt, options: nativeOptions }) => ({
      async initializationResult() {
        assert.match(nativeOptions.systemPrompt.append, /historical quotations only/);
        assert.ok(!nativeOptions.systemPrompt.append.includes(historySeed.assistant));
        return { claude_code_version: 'fixture-version' };
      },
      async mcpServerStatus() { return connected; },
      async *[Symbol.asyncIterator]() {
        for await (const request of prompt) {
          assert.equal(request.uuid, input.id);
          assert.deepEqual(request.message.content, [
            { type: 'text', text: 'Gateway historical context (JSON):\n' + JSON.stringify(historySeed) },
            { type: 'text', text },
          ]);
        }
        yield { type: 'result', subtype: 'success', is_error: false,
          session_id: input.sessionId, result: 'I will update the layout.' };
      },
      close() {},
    }),
  }));
  assert.equal(outcome.phase, 'completed');
});

test('subscription refusal is retained without mistaking it for an unobserved result', async () => {
  const resetsAt = 1795719000;
  for (const [workObserved, terminalObserved] of [[false, true], [true, true], [false, false]]) {
    let receipts = 0;
    const outcome = await runClaudeTurn(options({
      beforeSubmit: () => true,
      onInputAccepted(work) {
        if (!work) return false;
        receipts++;
      },
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          for await (const request of prompt) {
            const session_id = request.session_id;
            yield { type: 'system', subtype: 'status', session_id, user_message_uuids: [request.uuid] };
            if (workObserved) yield { type: 'assistant', session_id, user_message_uuids: [request.uuid],
              message: { content: [{ type: 'tool_use' }] } };
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
    assert.equal(receipts, workObserved ? 1 : 0);
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

test('Claude sends steer on the existing input stream and correlates the native result by UUID', async () => {
  const steer = { id: 'c230ad35-1c37-4b03-b60f-44d2f0fc58bf', text: 'Adjust the current work.' };
  for (const consumedInRoot of [true, false, null]) {
    const receipts = [];
    let ready = false;
    const steering = {
      messages: (async function* () { yield steer; })(),
      admit: async () => ready,
      ready: async () => { ready = true; },
      close() {},
      result: async (ids, text) => { receipts.push([ids, text]); },
    };
    const result = {
      type: 'result', subtype: 'success', is_error: false, session_id: input.sessionId,
    };
    const outcome = await runClaudeTurn(options({
      beforeSubmit: () => true,
      steering,
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async *[Symbol.asyncIterator]() {
          assert.equal((await prompt.next()).value.uuid, input.id);
          yield { type: 'assistant', session_id: input.sessionId, user_message_uuid: input.id };
          const { value: next } = await prompt.next();
          assert.deepEqual(next, {
            type: 'user', uuid: steer.id, session_id: input.sessionId, parent_tool_use_id: null,
            origin: { kind: 'human' }, client_composed: true, priority: 'next',
            message: { role: 'user', content: steer.text },
          });
          yield { ...result, result: 'Unrelated reply.',
            user_message_uuid: '66df791f-a4aa-4c7c-82c7-6878f545beb8' };
          yield {
            ...result, result: 'Root reply.',
            user_message_uuids: consumedInRoot ? [input.id, steer.id] : [input.id],
          };
          if (consumedInRoot === false) yield {
            ...result, result: 'Separate reply.', user_message_uuid: steer.id,
          };
        },
        close() {},
      }),
    }));
    assert.deepEqual(outcome, {
      phase: 'completed', sessionId: input.sessionId, text: 'Root reply.', steerSubmitted: [steer.id],
    });
    assert.deepEqual(receipts, consumedInRoot === null
      ? [] : [[[steer.id], consumedInRoot ? null : 'Separate reply.']]);
  }
});

test('a completed root keeps the exact native cancellation of its queued steer', async () => {
  const steer = { id: 'c230ad35-1c37-4b03-b60f-44d2f0fc58bf', text: 'Queued correction.' };
  const accepted = { still_queued: [], cancelled: [steer.id] };
  for (const [receipt, delay, text = 'Root completed.'] of [
    [accepted, 0],
    [accepted, 25],
    [accepted, 25, ''],
    [{ still_queued: [], cancelled: [input.id] }, 0],
    [{ still_queued: [steer.id], cancelled: [] }, 0],
    [undefined, Infinity],
  ]) {
    const interrupt = new AbortController();
    const outcome = await runClaudeTurn(options({
      beforeSubmit: () => true,
      interruptSignal: interrupt.signal,
      steering: {
        messages: (async function* () { yield steer; })(),
        admit: async () => true,
        ready: async () => {},
        close() {},
        result: () => assert.fail('The steer has no result'),
      },
      query: ({ prompt }) => ({
        async initializationResult() { return { claude_code_version: 'fixture-version' }; },
        async mcpServerStatus() { return connected; },
        async interrupt(options) {
          assert.deepEqual(options, { cancelQueued: true });
          if (delay === Infinity) return new Promise(() => {});
          if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
          return receipt;
        },
        async *[Symbol.asyncIterator]() {
          assert.equal((await prompt.next()).value.uuid, input.id);
          yield { type: 'system', subtype: 'init', session_id: input.sessionId,
            capabilities: ['interrupt_receipt_v1', 'interrupt_cancel_queued_v1'] };
          yield { type: 'assistant', session_id: input.sessionId, user_message_uuids: [input.id] };
          assert.equal((await prompt.next()).value.uuid, steer.id);
          interrupt.abort();
          await Promise.resolve();
          yield { type: 'result', subtype: 'success', is_error: false, session_id: input.sessionId,
            user_message_uuids: [input.id], result: text };
        },
        close() {},
      }),
    }));
    assert.equal(outcome.phase, text ? 'completed' : 'interrupted');
    assert.equal(outcome.text, text || undefined);
    assert.deepEqual(outcome.steerSubmitted, [steer.id]);
    assert.deepEqual(outcome.cancelled, receipt?.cancelled.includes(steer.id) ? [steer.id] : undefined);
  }
});

test('a steer refused before being yielded is never claimed as submitted', async () => {
  const outcome = await runClaudeTurn(options({
    beforeSubmit: () => true,
    steering: {
      messages: (async function* () {
        yield { id: 'c230ad35-1c37-4b03-b60f-44d2f0fc58bf', text: 'Not admitted.' };
      })(),
      admit: async () => false,
      ready: async () => {},
      close() {},
      result: () => assert.fail('Unsubmitted input cannot get a receipt'),
    },
    query: ({ prompt }) => ({
      async initializationResult() { return { claude_code_version: 'fixture-version' }; },
      async mcpServerStatus() { return connected; },
      async *[Symbol.asyncIterator]() {
        assert.equal((await prompt.next()).value.uuid, input.id);
        yield { type: 'assistant', session_id: input.sessionId, user_message_uuid: input.id };
        assert.equal((await prompt.next()).done, true);
        yield { type: 'result', subtype: 'success', is_error: false,
          session_id: input.sessionId, user_message_uuid: input.id, result: 'Root reply.' };
      },
      close() {},
    }),
  }));
  assert.deepEqual(outcome.steerSubmitted, []);
  assert.equal(outcome.phase, 'completed');
});
