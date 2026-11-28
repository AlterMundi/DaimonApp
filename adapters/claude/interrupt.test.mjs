import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const { CLAUDE_TEST_SDK_PATH, CLAUDE_TEST_NATIVE_BINARY } = process.env;

for (const earlierEvaluation of [null, false, true]) {
  const condition = earlierEvaluation === null ? null : 'Confirm the synthetic goal after reopening this session.';
  const label = earlierEvaluation === null ? 'cancels a queued correction and resumes the same native session'
    : earlierEvaluation ? 'restores its objective after an evaluated turn'
      : 'restores an interrupted goal before any provider work';
  test('installed Claude ' + label, {
    skip: !CLAUDE_TEST_SDK_PATH || !CLAUDE_TEST_NATIVE_BINARY,
    timeout: 30_000,
  }, async () => {
    const { query } = await import(CLAUDE_TEST_SDK_PATH);
    const directory = await mkdtemp(join(tmpdir(), 'claude-interrupt-'));
    const session = randomUUID();
    const original = randomUUID();
    const correction = randomUUID();
    const payloads = [];
    let resuming = false;
    let evaluations = 0;
    const provider = createServer(async (request, response) => {
      if (!request.url.startsWith('/v1/messages')) {
        response.writeHead(404).end();
        return;
      }
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const data = JSON.parse(Buffer.concat(chunks).toString());
      const evaluator = JSON.stringify(data.system).includes('evaluating a stop-condition hook');
      if (evaluator) evaluations++;
      else payloads.push(data.messages);
      response.writeHead(200, { 'Content-Type': 'text/event-stream' });
      const event = (type, data) => response.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`);
      event('message_start', { message: {
        id: 'msg_interrupt_fixture', type: 'message', role: 'assistant', model: data.model,
        content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 8, output_tokens: 1 },
      } });
      event('content_block_start', { index: 0, content_block: { type: 'text', text: '' } });
      event('content_block_delta', { index: 0, delta: { type: 'text_delta',
        text: evaluator ? JSON.stringify({ ok: resuming, reason: 'Synthetic goal evaluator.' })
          : resuming ? 'Continuation confirmed.' : 'Fixture started.',
      } });
      if (resuming || evaluator || (earlierEvaluation && payloads.length === 1)) {
        event('content_block_stop', { index: 0 });
        event('message_delta', { delta: { stop_reason: 'end_turn', stop_sequence: null }, usage: { output_tokens: 4 } });
        event('message_stop', {});
        response.end();
      }
      // Leave the initial provider stream open until the selected interrupt.
    });
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 20_000);
    let releaseCorrection, correctionSent, closeInput;
    const ready = new Promise(resolve => { releaseCorrection = resolve; });
    const sent = new Promise(resolve => { correctionSent = resolve; });
    const done = new Promise(resolve => { closeInput = resolve; });
    const message = (uuid, content) => ({
      type: 'user', uuid, session_id: session, parent_tool_use_id: null,
      origin: { kind: 'human' }, message: { role: 'user', content },
    });
    async function* input() {
      yield message(original, condition ? '/goal ' + condition : 'Keep the synthetic stream open.');
      await ready;
      yield { ...message(correction, 'Do not process this queued correction.'), priority: 'later' };
      correctionSent();
      await done;
    }
    let native, inspection, continuation;
    try {
      provider.listen(0, '127.0.0.1');
      await once(provider, 'listening');
      const options = {
        cwd: directory, pathToClaudeCodeExecutable: CLAUDE_TEST_NATIVE_BINARY,
        env: {
          HOME: directory, CLAUDE_CONFIG_DIR: directory, PATH: '/usr/bin:/bin',
          ANTHROPIC_BASE_URL: `http://127.0.0.1:${provider.address().port}`,
          ANTHROPIC_API_KEY: 'fixture-only', DISABLE_TELEMETRY: '1',
          DISABLE_AUTOUPDATER: '1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
          CLAUDE_CODE_GOAL_CHECKIN_MINUTES: '0',
        },
        settingSources: [], tools: [], includePartialMessages: true,
        abortController: abort, persistSession: true,
      };
      native = query({ prompt: input(), options: { ...options, sessionId: session } });
      let capabilities;
      for (;;) {
        const { value, done } = await native.next();
        assert.equal(done, false);
        if (value.type === 'system' && value.subtype === 'init') capabilities = value.capabilities;
        if (value.type === 'stream_event' && value.event.type === 'content_block_delta'
            && payloads.length === (earlierEvaluation ? 2 : 1)) break;
      }
      const callsBeforeInterrupt = earlierEvaluation ? 2 : 1;
      const evaluationsBeforeInterrupt = earlierEvaluation ? 1 : 0;
      assert.equal(payloads.length, callsBeforeInterrupt);
      assert.equal(evaluations, evaluationsBeforeInterrupt);
      assert.ok(capabilities.includes('interrupt_receipt_v1'));
      assert.ok(capabilities.includes('interrupt_cancel_queued_v1'));
      releaseCorrection();
      await sent;
      const receipt = await native.interrupt({ cancelQueued: true });
      assert.deepEqual(receipt, { still_queued: [], cancelled: [correction] });
      for (;;) {
        const { value, done } = await native.next();
        assert.equal(done, false);
        if (value.type === 'result') {
          assert.equal(value.session_id, session);
          assert.equal(value.is_error, !earlierEvaluation);
          assert.equal(value.subtype, earlierEvaluation ? 'success' : 'error_during_execution');
          assert.deepEqual(value.user_message_uuids, [original]);
          if (earlierEvaluation) {
            assert.equal(typeof value.result, 'string');
            assert.ok(value.result.trim() && Buffer.byteLength(value.result) <= 64 * 1024);
          }
          break;
        }
      }
      assert.equal(payloads.length, callsBeforeInterrupt);
      closeInput();
      native.close();

      resuming = true;
      if (condition) {
        async function* status() {
          yield message(randomUUID(), '/goal');
        }
        inspection = query({ prompt: status(), options: { ...options, resume: session } });
        let snapshot;
        for await (const event of inspection) {
          if (event.type === 'result') {
            snapshot = event;
            break;
          }
        }
        assert.equal(snapshot.session_id, session);
        assert.ok(snapshot.result.includes(condition), snapshot.result);
        assert.match(snapshot.result, /Goal active:.*\(not yet evaluated\)/);
        assert.equal(payloads.length, callsBeforeInterrupt);
        assert.equal(evaluations, evaluationsBeforeInterrupt);
        inspection.close();
      }
      async function* followup() {
        yield message(randomUUID(), 'This is a new original after the interruption.');
      }
      continuation = query({ prompt: followup(), options: { ...options, resume: session } });
      let resumed;
      for await (const event of continuation) {
        if (event.type === 'result') {
          resumed = event;
          break;
        }
      }
      assert.equal(resumed.session_id, session);
      assert.equal(resumed.result, 'Continuation confirmed.');
      assert.equal(payloads.length, callsBeforeInterrupt + 1);
      assert.equal(evaluations, evaluationsBeforeInterrupt + (condition ? 1 : 0));
      assert.match(JSON.stringify(payloads.at(-1)), /new original after the interruption/);
      assert.doesNotMatch(JSON.stringify(payloads.at(-1)), /Do not process this queued correction/);
    } finally {
      clearTimeout(deadline);
      closeInput();
      abort.abort();
      native?.close();
      inspection?.close();
      continuation?.close();
      provider.closeAllConnections();
      provider.close();
      await rm(directory, { recursive: true, force: true });
    }
  });
}
