import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const executable = fileURLToPath(new URL('gateway-worker.mjs', import.meta.url));
const correlation = {
  schema: 'daimon-gateway.claude-turn/v2',
  inputId: 'bd55cfc3-710f-44b8-b778-d15be1b77997',
  sessionId: '3d5ef97e-bd13-4ee1-9f4c-f2807b2b472b',
};
const nativeSessionId = '627b6f7e-50a1-46ad-90d2-684c5faf97c3';
const priorSessionId = '7da8a4c1-f56b-43f8-ba35-e9d6fa710e64';
const original = 'Reply using this selected fixture original.';
const realBinary = process.env.CLAUDE_TEST_BINARY;

test('worker sends one native input only after exact owner persistence decision',
  { timeout: 12_000 }, async () => {
    const root = await mkdtemp(join(tmpdir(), 'gateway-claude-worker-'));
    const sdk = join(root, 'fixture.mjs');
    const cli = join(root, 'claude-fixture');
    const selection = join(root, 'profile.json');
    const exposure = join(root, 'submitted.txt');
    const apiKeyFile = join(root, 'provider.key');
    const subscriptionEmail = 'owner@example.test';
    const accountDriftCwd = join(root, 'other-account');
    const fixtureKey = 'sk-ant-api03-fixture-not-a-provider-credential';
    try {
      await mkdir(accountDriftCwd);
      await writeFile(apiKeyFile, fixtureKey + '\n', { mode: 0o600 });
      await writeFile(cli, `#!${process.execPath}
if (process.argv.slice(2).join(' ') !== 'auth status') process.exit(2);
const key = process.env.ANTHROPIC_API_KEY;
console.log(JSON.stringify(key === ${JSON.stringify(fixtureKey)}
  ? { loggedIn: true, authMethod: 'api_key', apiProvider: 'firstParty', apiKeySource: 'ANTHROPIC_API_KEY' }
  : { loggedIn: true, authMethod: 'claude.ai', apiProvider: 'firstParty',
      email: ${JSON.stringify(subscriptionEmail)}, apiKeySource: key ?? null }));
`, { mode: 0o700 });
      await writeFile(sdk, `
        import { writeFile } from 'node:fs/promises';
        import assert from 'node:assert/strict';
        export const tool = (name) => ({ name });
        export const createSdkMcpServer = (description) => description;
        export function query({ prompt, options }) {
          if (options.env.CLAUDE_CONFIG_DIR) {
            assert.equal(options.env.ANTHROPIC_API_KEY, ${JSON.stringify(fixtureKey)});
          } else {
            assert.equal(options.env.HOME, ${JSON.stringify(root)});
            assert.equal(options.env.ANTHROPIC_API_KEY, undefined);
            assert.equal(options.env.CLAUDE_CODE_OAUTH_TOKEN, undefined);
          }
          assert.equal(process.env.ANTHROPIC_API_KEY, undefined);
          if (options.env.CLAUDE_CONFIG_DIR) {
            assert.equal(options.maxTurns, options.tools.length ? 6 : 2);
            assert.equal(options.maxBudgetUsd, 0.10);
          } else {
            assert.equal(Object.hasOwn(options, 'maxTurns'), false);
            assert.equal(Object.hasOwn(options, 'maxBudgetUsd'), false);
          }
          assert.equal(options.systemPrompt.snapshot, false);
          assert.match(options.systemPrompt.append, /CompAII fixture · claude@itaca/);
          assert.ok(!options.systemPrompt.append.includes(${JSON.stringify(subscriptionEmail)}));
          return {
            async initializationResult() {
              return { claude_code_version: 'fixture-version', account: {
                email: options.cwd === ${JSON.stringify(accountDriftCwd)}
                  ? 'other@example.test' : ${JSON.stringify(subscriptionEmail)},
                apiProvider: 'firstParty', subscriptionType: 'fixture-plan',
              }};
            },
            async mcpServerStatus() { return [{
              name: 'matrix', source: 'sdk', status: 'connected', tools: options.mcpServers.matrix.tools
            }]; },
            async *[Symbol.asyncIterator]() {
              for await (const request of prompt) {
                const ownerDefault = request.message.content === 'Synthetic private default.';
                const paired = ownerDefault || request.message.content === 'Synthetic private tool grant.';
                assert.equal(options.permissionMode, paired ? 'bypassPermissions' : 'dontAsk');
                assert.equal(options.systemPrompt.append.includes(
                  'The paired human wrote the current user message in Interaction.'), paired);
                assert.equal(options.allowDangerouslySkipPermissions, paired ? true : undefined);
                assert.equal(options.settings.sandbox?.enabled, paired ? false : undefined);
                const expectedTools = ownerDefault
                  ? ['Bash', 'Edit', 'Glob', 'Grep', 'NotebookEdit', 'Read', 'Write']
                  : paired ? ['Bash', 'Read'] : [];
                assert.deepEqual(options.tools, expectedTools);
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
        sdk, cwd: root, home: root, configurationDirectory: root, binary: cli, apiKeyFile, maxBudgetUsd: 0.10,
        cliVersion: 'fixture-version', model: 'fixture-model', displayName: 'CompAII fixture · claude@itaca',
        hostTools: ['Read', 'Bash'],
        matrixStatusCommand: [process.execPath, '-e', 'console.log(process.argv[1])',
          JSON.stringify(status), '--'],
        body,
      };
      await writeFile(selection, JSON.stringify(profile), { mode: 0o600 });

      const {
        apiKeyFile: _keyFile, configurationDirectory: _directory, maxBudgetUsd: _qualificationBudget,
        ...commonProfile
      } = profile;
      const subscription = { ...commonProfile, subscriptionEmail };
      const decisions = ['disconnected', 'rejected', 'wrong-correlation', 'profile-changed', 'committed', 'result-lost',
        'companion-after-human', 'companion-resume', 'owner-default',
        'subscription-committed', 'subscription-wrong-account', 'subscription-account-drift'];
      let restrictedScope;
      let hostScope;
      // Native bootstrap with a synthetic key timed out offline.
      // Exercise the native auth selector here with the isolated fixture SDK.
      if (realBinary) decisions.push('native-auth-rejected');
      for (const decision of decisions) {
        if (decision === 'owner-default') {
          const { hostTools: _tools, ...defaultProfile } = profile;
          await writeFile(selection, JSON.stringify(defaultProfile));
        }
        if (decision === 'subscription-committed') await writeFile(selection, JSON.stringify(subscription));
        if (decision === 'subscription-wrong-account') {
          await writeFile(selection, JSON.stringify({ ...subscription, subscriptionEmail: 'other@example.test' }));
        }
        if (decision === 'subscription-account-drift') {
          await writeFile(selection, JSON.stringify({ ...subscription, cwd: accountDriftCwd }));
        }
        if (decision === 'native-auth-rejected') {
          await writeFile(selection, JSON.stringify({ ...profile, binary: realBinary }));
        }
        const worker = spawn(process.execPath, [executable, '--profile', selection], {
          env: {},
          stdio: ['pipe', 'pipe', 'ignore'],
        });
        const exited = once(worker, 'close');
        const lines = createInterface({ input: worker.stdout })[Symbol.asyncIterator]();
        try {
          const humanOriginal = ['committed', 'owner-default'].includes(decision);
          const text = decision === 'owner-default' ? 'Synthetic private default.'
            : humanOriginal ? 'Synthetic private tool grant.'
            : decision === 'result-lost' ? 'Synthetic loss after native input.' : original;
          const previousScope = decision === 'companion-after-human' ? hostScope
            : decision === 'companion-resume' ? restrictedScope : undefined;
          const resume = previousScope ? { sessionId: priorSessionId, scope: previousScope } : null;
          const expectedSession = decision === 'companion-resume' ? priorSessionId : nativeSessionId;
          worker.stdin.write(JSON.stringify({ ...correlation, type: 'start', freshNativeSessionId: nativeSessionId,
            resume, humanOriginal, text, body }) + '\n');
          const first = JSON.parse((await lines.next()).value);
          if (['subscription-wrong-account', 'subscription-account-drift'].includes(decision)) {
            assert.deepEqual(first, { ...correlation, type: 'outcome',
              outcome: { phase: 'not_submitted', reason: 'claude_subscription_auth_unverified' },
            });
            assert.equal((await exited)[0], 0);
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
            continue;
          }
          assert.match(first.sessionScope, /^[a-f0-9]{64}$/);
          if (decision === 'disconnected') restrictedScope = first.sessionScope;
          if (decision === 'committed') hostScope = first.sessionScope;
          assert.deepEqual(first,
            { ...correlation, type: 'prepare_submission', nativeSessionId: expectedSession, sessionScope: first.sessionScope });
          await assert.rejects(readFile(exposure), { code: 'ENOENT' });
          if (decision === 'profile-changed') {
            await writeFile(selection, JSON.stringify({ ...profile, body: { ...body, incarnationId: 'replaced' } }));
          }
          if (decision === 'disconnected') worker.stdin.end();
          else {
            worker.stdin.write(JSON.stringify({ ...correlation, type: 'submission_decision',
              sessionId: decision === 'wrong-correlation' ? correlation.inputId : correlation.sessionId,
              committed: decision !== 'rejected' && decision !== 'native-auth-rejected',
            }) + '\n');
          }
          const frame = JSON.parse((await lines.next()).value);
          const completed = ['committed', 'subscription-committed', 'companion-after-human', 'companion-resume', 'owner-default'].includes(decision);
          const committed = completed || decision === 'result-lost';
          const outcome = completed
            ? { phase: 'completed', sessionId: expectedSession, text: 'Qualified fixture reply.' }
            : committed
              ? { phase: 'uncertain', reason: 'claude_result_unobserved', sessionId: nativeSessionId }
              : { phase: 'not_submitted', reason: 'gateway_submission_not_recorded' };
          assert.deepEqual(frame, { ...correlation, type: 'outcome', outcome }, decision);
          if (committed) {
            assert.equal(await readFile(exposure, 'utf8'), text);
            await rm(exposure);
          } else {
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
          }
          assert.equal((await exited)[0], 0);
          if (decision === 'profile-changed') await writeFile(selection, JSON.stringify(profile));
        } finally {
          worker.kill();
          await exited;
        }
      }
      await writeFile(selection, JSON.stringify(profile));
      for (const key of ['wrong-fixture-key', '']) {
        await writeFile(apiKeyFile, key);
        const worker = spawn(process.execPath, [executable, '--profile', selection], {
          env: { ANTHROPIC_API_KEY: fixtureKey }, stdio: ['pipe', 'pipe', 'ignore'],
        });
        const exited = once(worker, 'close');
        const lines = createInterface({ input: worker.stdout })[Symbol.asyncIterator]();
        try {
          worker.stdin.end(JSON.stringify({ ...correlation, type: 'start', freshNativeSessionId: nativeSessionId,
            resume: null, humanOriginal: false, text: original, body }) + '\n');
          assert.deepEqual(JSON.parse((await lines.next()).value), {
            ...correlation, type: 'outcome',
            outcome: { phase: 'not_submitted', reason: 'claude_api_auth_unverified' },
          });
          assert.equal((await exited)[0], 0);
          await assert.rejects(readFile(exposure), { code: 'ENOENT' });
        } finally {
          worker.kill();
          await exited;
        }
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
