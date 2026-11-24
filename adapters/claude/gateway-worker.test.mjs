import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const executable = fileURLToPath(new URL('gateway-worker.mjs', import.meta.url));
const correlation = {
  schema: 'daimon-gateway.claude-turn/v1',
  inputId: 'bd55cfc3-710f-44b8-b778-d15be1b77997',
  sessionId: '3d5ef97e-bd13-4ee1-9f4c-f2807b2b472b',
};
const original = 'Reply using this selected fixture original.';
const realSdk = process.env.CLAUDE_TEST_SDK_PATH;
const realBinary = process.env.CLAUDE_TEST_BINARY;
const realCliVersion = process.env.CLAUDE_TEST_CLI_VERSION ?? '2.1.323';

test('worker sends one native input only after exact owner persistence decision',
  { timeout: 12_000 }, async () => {
    const root = await mkdtemp(join(tmpdir(), 'gateway-claude-worker-'));
    const sdk = join(root, 'fixture.mjs');
    const selection = join(root, 'profile.json');
    const exposure = join(root, 'submitted.txt');
    try {
      await writeFile(sdk, `
        import { writeFile } from 'node:fs/promises';
        export const tool = (name) => ({ name });
        export const createSdkMcpServer = (description) => description;
        export function query({ prompt, options }) {
          return {
            async initializationResult() { return { claude_code_version: 'fixture-version' }; },
            async mcpServerStatus() { return [{
              name: 'matrix', source: 'sdk', status: 'connected', tools: options.mcpServers.matrix.tools
            }]; },
            async *[Symbol.asyncIterator]() {
              for await (const request of prompt) {
                await writeFile(${JSON.stringify(exposure)}, request.message.content, { flag: 'wx' });
                if (request.message.content === 'Synthetic loss after native input.') return;
                yield { type: 'result', subtype: 'success', is_error: false,
                  session_id: request.session_id, result: 'Qualified fixture reply.' };
              }
            },
            close() {},
          };
        }
      `);
      const body = { beingRef: 'being-test', embodimentId: 'body-test',
        incarnationId: 'incarnation-test', manifestHash: 'manifest-test' };
      const status = {
        schema: 'dm.runtime.status/v1', integrity: 'ok', manifest_hash: body.manifestHash,
        being_ref: body.beingRef, local_origin: {
          embodiment_id: body.embodimentId, incarnation_id: body.incarnationId,
        },
      };
      const profile = {
        sdk, cwd: root, home: root, configurationDirectory: root, binary: process.execPath,
        cliVersion: 'fixture-version', model: 'fixture-model',
        matrixStatusCommand: [process.execPath, '-e', 'console.log(process.argv[1])',
          JSON.stringify(status), '--'],
        body,
      };
      await writeFile(selection, JSON.stringify(profile), { mode: 0o600 });

      const decisions = ['disconnected', 'rejected', 'wrong-correlation', 'committed', 'result-lost'];
      if (realSdk && realBinary) decisions.push('real-sdk-rejected');
      for (const decision of decisions) {
        if (decision === 'real-sdk-rejected') {
          await writeFile(selection, JSON.stringify({ ...profile,
            sdk: realSdk, binary: realBinary, cliVersion: realCliVersion, model: 'sonnet',
          }));
        }
        const worker = spawn(process.execPath, [executable, '--profile', selection], {
          stdio: ['pipe', 'pipe', 'ignore'],
        });
        const exited = once(worker, 'close');
        const lines = createInterface({ input: worker.stdout })[Symbol.asyncIterator]();
        try {
          const text = decision === 'result-lost' ? 'Synthetic loss after native input.' : original;
          worker.stdin.write(JSON.stringify({ ...correlation, type: 'start', text }) + '\n');
          assert.deepEqual(JSON.parse((await lines.next()).value),
            { ...correlation, type: 'prepare_submission' });
          await assert.rejects(readFile(exposure), { code: 'ENOENT' });
          if (decision === 'disconnected') worker.stdin.end();
          else {
            worker.stdin.write(JSON.stringify({ ...correlation, type: 'submission_decision',
              sessionId: decision === 'wrong-correlation' ? correlation.inputId : correlation.sessionId,
              committed: decision !== 'rejected' && decision !== 'real-sdk-rejected',
            }) + '\n');
          }
          const frame = JSON.parse((await lines.next()).value);
          const committed = ['committed', 'result-lost'].includes(decision);
          const outcome = decision === 'committed'
            ? { phase: 'completed', sessionId: correlation.sessionId, text: 'Qualified fixture reply.' }
            : committed
              ? { phase: 'uncertain', reason: 'claude_result_unobserved', sessionId: correlation.sessionId }
              : { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' };
          assert.deepEqual(frame, { ...correlation, type: 'outcome', outcome }, decision);
          if (committed) {
            assert.equal(await readFile(exposure, 'utf8'), text);
            await rm(exposure);
          } else {
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
          }
          assert.equal((await exited)[0], 0);
        } finally {
          worker.kill();
          await exited;
        }
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
