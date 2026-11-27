import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
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
const historySeed = { turn: 12, human: 'Check the layout.', assistant: 'I can move the section next.' };
const codexSeed = { ...historySeed, harness: 'codex' };
const exactQuote = { source: 'delivery:37da8c68-c490-404d-93a4-e4d6741a4397',
  revision: 'a'.repeat(64), assistant: 'Earlier proposal selected by the paired human.' };
const telegramQuote = { ...exactQuote,
  source: exactQuote.source.replace('delivery:', 'telegram-result:') };
const realBinary = process.env.CLAUDE_TEST_BINARY;

test('worker sends one native input only after exact owner persistence decision',
  { timeout: 20_000 }, async () => {
    const root = await mkdtemp(join(tmpdir(), 'gateway-claude-worker-'));
    const observerServer = createServer();
    const foreignServer = createServer();
    const tribeServer = createServer();
    const sdk = join(root, 'fixture.mjs');
    const cli = join(root, 'claude-fixture');
    const selection = join(root, 'profile.json');
    const exposure = join(root, 'submitted.txt');
    const apiKeyFile = join(root, 'provider.key');
    const bodyGuidanceFile = join(root, 'body-guidance.md');
    const sharedSkillsDirectory = join(root, 'skills');
    const skill = join(sharedSkillsDirectory, 'sample', 'SKILL.md');
    const skillBody = 'name: sample\nmetadata:\n';
    const skillDocument = (version, text) => '---\n' + skillBody + '  version: "' + version + '"\n---\n' + text;
    const initialSkill = skillDocument('1.2.3', 'Synthetic skill: first.');
    const subscriptionEmail = 'owner@example.test';
    const accountDriftCwd = join(root, 'other-account');
    const alternateWorkspace = join(root, 'selected-workspace');
    const fixtureKey = 'sk-ant-api03-fixture-not-a-provider-credential';
    try {
      await mkdir(accountDriftCwd);
      await mkdir(alternateWorkspace);
      await writeFile(bodyGuidanceFile, 'Synthetic body guidance: first.', { mode: 0o600 });
      await mkdir(join(sharedSkillsDirectory, 'sample'), { recursive: true });
      await writeFile(skill, initialSkill);
      const hash = input => createHash('sha256').update(input).digest('hex');
      const updatedSkill = skillDocument('1.2.4', 'Synthetic skill: updated.');
      const inventory = text => hash(JSON.stringify(['sample', skill, hash(text)]));
      const skillResumeAnchor = [inventory(initialSkill),
        inventory(skillDocument('1.2.2', 'Older approved skill text.'))];
      const skillContinuity = {
        layoutRevision: hash(JSON.stringify(['sample', skill, ['name: sample', 'metadata:', ['metadata.version', 'semver'], '']])),
        previousRevision: inventory(initialSkill),
      };
      assert.ok(!skillResumeAnchor.includes(inventory(updatedSkill)));
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
        const matrixChatTools = ['messaging_delivery', 'messaging_inbox', 'messaging_reply', 'messaging_send'];
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
          assert.deepEqual(options.skills, ['compaii-shared:sample']);
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
            async supportedCommands() { return [{name: 'compaii-shared:sample'}]; },
            async mcpServerStatus() { return [{
              name: 'matrix', source: 'sdk', status: 'connected', tools: options.mcpServers.matrix.tools
            }, ...(options.mcpServers.matrix_chat ? [{
              name: 'matrix_chat', source: 'dynamic', status: 'connected',
              tools: matrixChatTools.map(name => ({ name })),
            }] : [])]; },
            async *[Symbol.asyncIterator]() {
              for await (const request of prompt) {
                const { content } = request.message;
                const text = Array.isArray(content) ? content.at(-1).text : content;
                const expectedQuote = text === 'Synthetic paired Telegram quote.'
                  ? ${JSON.stringify(telegramQuote)} : text === 'Synthetic paired Conversation quote.'
                    ? ${JSON.stringify(exactQuote)} : null;
                const fromCodex = text === 'Synthetic prior Codex exchange.';
                if (expectedQuote || fromCodex) assert.ok(Array.isArray(content), text);
                assert.equal(Array.isArray(content), options.systemPrompt.append.includes('Gateway attached retained context'));
                if (Array.isArray(content)) {
                  const seed = fromCodex ? ${JSON.stringify(codexSeed)} : expectedQuote ?? ${JSON.stringify(historySeed)};
                  assert.equal(content[0].text, 'Gateway historical context (JSON):\\n' + JSON.stringify(seed));
                }
                const atSelectedWorkspace = text === 'Synthetic selected workspace.';
                if (atSelectedWorkspace) {
                  assert.equal(options.cwd, ${JSON.stringify(alternateWorkspace)});
                  assert.equal(options.resume, undefined);
                }
                const ownerDefault = text === 'Synthetic private default.';
                const objectSchemas = text === 'Synthetic paired Tribe chat tools.';
                const withMessaging = objectSchemas || text === 'Synthetic paired chat tools.';
                const paired = ownerDefault || withMessaging || !!expectedQuote || atSelectedWorkspace || fromCodex || text === 'Synthetic private tool grant.';
                assert.equal(!!options.mcpServers.matrix_chat, withMessaging);
                if (withMessaging) {
                  assert.equal(options.mcpServers.matrix_chat.args.at(-1),
                    objectSchemas ? '--object-tool-schemas' : 'mcp');
                }
                for (const tool of matrixChatTools) {
                  assert.equal(options.allowedTools.includes('mcp__matrix_chat__' + tool), withMessaging);
                }
                assert.equal(options.permissionMode, paired ? 'bypassPermissions' : 'dontAsk');
                assert.equal(options.systemPrompt.append.includes(
                  'The paired human supplied the current input.'), paired);
                assert.equal(options.systemPrompt.append.includes(
                  'The Claude subscription account is a service credential and does not identify the sender.'), paired);
                assert.equal(options.systemPrompt.append.includes('Synthetic body guidance:'), paired);
                if (options.resume === ${JSON.stringify(priorSessionId)} && paired) {
                  assert.match(options.systemPrompt.append, /Synthetic body guidance: updated/);
                }
                assert.equal(options.allowDangerouslySkipPermissions, paired ? true : undefined);
                assert.equal(options.settings.sandbox?.enabled, paired ? false : undefined);
                const expectedTools = ownerDefault
                  ? ['Bash', 'Edit', 'Glob', 'Grep', 'NotebookEdit', 'Read', 'Write']
                  : paired ? ['Bash', 'Read'] : [];
                assert.deepEqual(options.tools, [...expectedTools, 'Skill']);
                assert.equal(options.env.CLAUDE_CODE_SUBPROCESS_ENV_SCRUB,
                  options.env.CLAUDE_CONFIG_DIR && paired ? '1' : undefined);
                await writeFile(${JSON.stringify(exposure)}, text, { flag: 'wx' });
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
        hostTools: ['Read', 'Bash'], bodyGuidanceFile, sharedSkillsDirectory, skillResumeAnchor,
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
      const matrixMessaging = join(root, 'chat-connection.json');
      const chatBinding = join(root, 'chat-binding.json');
      const chatClient = join(root, 'chat-client.json');
      const chatSocket = join(root, 'matrix.sock');
      const tribeSocket = join(root, 'tribe.sock');
      const foreignSocket = join(root, 'foreign.sock');
      const observerBinding = join(root, 'observer-binding.json');
      const observerClient = join(root, 'observer-client.json');
      observerServer.listen(chatSocket);
      foreignServer.listen(foreignSocket);
      tribeServer.listen(tribeSocket);
      await Promise.all([observerServer, foreignServer, tribeServer].map(server => once(server, 'listening')));
      const binding = { schema: 'dm.agent-chat.binding/v1', client_config: chatClient, socket: chatSocket };
      await writeFile(matrixMessaging, JSON.stringify({ command: [process.execPath, '-I', '-m', 'daimon_matrix.agent_chat', '--binding', chatBinding] }), { mode: 0o600 });
      await writeFile(chatBinding, JSON.stringify(binding), { mode: 0o600 });
      const chatGrant = {
        schema: 'dm.local.client-config/v3',
        runtime_id: 'fixture-runtime',
        expected_server: { body_ref: 'fixture', principal_id: 'fixture',
          embodiment_id: body.embodimentId, incarnation_id: body.incarnationId },
        capability: { schema: 'dm.local.capability/v2', status: 'active',
          validity: { mode: 'until-revoked', not_before_ms: 0 },
          methods: ['messaging.inbox', 'messaging.delivery', 'messaging.send', 'messaging.reply'] },
      };
      await writeFile(chatClient, JSON.stringify(chatGrant), { mode: 0o600 });
      await writeFile(observerClient, JSON.stringify(chatGrant), { mode: 0o600 });
      await writeFile(observerBinding, JSON.stringify({
        source: { being_ref: body.beingRef, embodiment_id: body.embodimentId },
        observation: { socket: chatSocket, client_config: observerClient },
      }), { mode: 0o600 });
      const messagingProfile = { ...profile, skillContinuity, matrixMessaging,
        matrixStatusCommand: [...profile.matrixStatusCommand, '--binding', observerBinding, '--body-status'] };
      const refusedMessaging = ['messaging-foreign', 'messaging-foreign-socket', 'messaging-expired', 'messaging-broad-grant'];
      const decisions = ['disconnected', 'rejected', 'wrong-correlation', 'profile-changed', 'committed', 'result-lost', 'skill-changed-during-submission',
        'updated-guidance-resume', 'quoted-resume', 'telegram-quoted-resume', 'codex-seeded-resume', 'changed-skill-metadata', 'workspace-selected', 'workspace-replaced', 'workspace-missing', 'companion-after-human', 'companion-resume', 'companion-selected-resume', 'owner-default',
        'subscription-committed', 'subscription-wrong-account', 'subscription-account-drift',
        'messaging-paired', 'messaging-paired-tribe', 'messaging-paired-isolated',
        'messaging-binding-changed', 'messaging-unpaired', ...refusedMessaging];
      let restrictedScope;
      let hostScope;
      // Native bootstrap with a synthetic key timed out offline.
      // Exercise the native auth selector here with the isolated fixture SDK.
      if (realBinary) decisions.push('native-auth-rejected');
      for (const decision of decisions) {
        if (decision === 'updated-guidance-resume') {
          await writeFile(bodyGuidanceFile, 'Synthetic body guidance: updated.');
          await writeFile(skill, updatedSkill);
          await writeFile(selection, JSON.stringify({ ...profile, skillContinuity }));
        }
        if (decision === 'changed-skill-metadata') {
          await writeFile(skill, '---\nname: sample\nallowed-tools: Read\n---\nSynthetic skill: updated.');
        }
        if (decision === 'owner-default') {
          const { hostTools: _tools, ...defaultProfile } = profile;
          await writeFile(selection, JSON.stringify(defaultProfile));
        }
        if (decision.startsWith('messaging-')) await writeFile(selection, JSON.stringify(messagingProfile));
        if (decision === 'messaging-paired-tribe') {
          await writeFile(chatBinding, JSON.stringify({ ...binding, socket: tribeSocket }));
          await writeFile(selection, JSON.stringify({ ...messagingProfile,
            matrixMessaging: { connection: matrixMessaging, objectToolSchemas: true } }));
        }
        if (decision === 'messaging-binding-changed') await writeFile(chatBinding, JSON.stringify(binding));
        if (decision === 'messaging-foreign-socket') {
          await writeFile(chatClient, JSON.stringify(chatGrant));
          await writeFile(chatBinding, JSON.stringify({ ...binding, socket: foreignSocket }));
        }
        if (decision === 'messaging-expired') {
          await writeFile(chatBinding, JSON.stringify(binding));
          const { validity: _validity, ...grant } = chatGrant.capability;
          await writeFile(chatClient, JSON.stringify({ ...chatGrant, capability: {
            ...grant, schema: 'dm.local.capability/v1', not_before_ms: 0, not_after_ms: 1,
          } }));
        }
        if (decision === 'messaging-foreign') {
          await writeFile(chatClient, JSON.stringify({ ...chatGrant,
            expected_server: { ...chatGrant.expected_server, embodiment_id: 'foreign' } }));
        }
        if (decision === 'messaging-broad-grant') {
          await writeFile(chatClient, JSON.stringify({ ...chatGrant,
            capability: { ...chatGrant.capability, methods: [...chatGrant.capability.methods, 'runtime.admin'] } }));
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
          const pairedMessaging = decision.startsWith('messaging-paired');
          const messagingChanged = decision === 'messaging-binding-changed';
          const humanOriginal = pairedMessaging || messagingChanged || ['committed', 'owner-default', 'updated-guidance-resume', 'quoted-resume', 'telegram-quoted-resume', 'codex-seeded-resume', 'changed-skill-metadata', 'workspace-selected', 'workspace-replaced', 'workspace-missing', ...refusedMessaging].includes(decision);
          const text = decision === 'owner-default' ? 'Synthetic private default.'
            : decision === 'messaging-paired-tribe' ? 'Synthetic paired Tribe chat tools.'
            : pairedMessaging || messagingChanged ? 'Synthetic paired chat tools.'
            : decision === 'telegram-quoted-resume' ? 'Synthetic paired Telegram quote.'
            : decision === 'quoted-resume' ? 'Synthetic paired Conversation quote.'
            : decision === 'workspace-selected' ? 'Synthetic selected workspace.'
            : decision === 'codex-seeded-resume' ? 'Synthetic prior Codex exchange.'
            : humanOriginal ? 'Synthetic private tool grant.'
            : decision === 'result-lost' ? 'Synthetic loss after native input.' : original;
          const previousScope = ['companion-after-human', 'companion-selected-resume', 'updated-guidance-resume', 'quoted-resume', 'telegram-quoted-resume', 'codex-seeded-resume', 'changed-skill-metadata', 'workspace-selected', 'messaging-paired-tribe'].includes(decision) ? hostScope
            : ['companion-resume', 'messaging-paired-isolated'].includes(decision) ? restrictedScope : undefined;
          const resume = previousScope ? { sessionId: priorSessionId, scope: previousScope } : null;
          const alternateId = '37da8c68-c490-404d-93a4-e4d6741a4397';
          const hasAlternate = decision === 'companion-selected-resume';
          const expectedSession = hasAlternate ? alternateId
            : ['companion-resume', 'updated-guidance-resume', 'quoted-resume', 'telegram-quoted-resume', 'codex-seeded-resume', 'messaging-paired-tribe'].includes(decision) ? priorSessionId : nativeSessionId;
          const workspace = decision === 'updated-guidance-resume' ? root
            : ['workspace-selected', 'workspace-replaced'].includes(decision) ? alternateWorkspace
            : decision === 'workspace-missing' ? join(root, 'absent') : undefined;
          worker.stdin.write(JSON.stringify({ ...correlation, type: 'start', freshNativeSessionId: nativeSessionId,
            resume, humanOriginal, text, body,
            ...(workspace === undefined ? {} : { workspace }),
            ...(['changed-skill-metadata', 'updated-guidance-resume'].includes(decision) ? { historySeed } : {}),
            ...(decision === 'quoted-resume' ? { historySeed: exactQuote } : {}),
            ...(decision === 'telegram-quoted-resume' ? { historySeed: telegramQuote } : {}),
            ...(decision === 'codex-seeded-resume' ? { historySeed: codexSeed } : {}),
            ...(hasAlternate ? { resumeAlternates: [{ sessionId: alternateId, scope: restrictedScope }] } : {}),
          }) + '\n');
          const firstLine = await lines.next();
          if (refusedMessaging.includes(decision)) {
            assert.equal(firstLine.done, true);
            assert.equal((await exited)[0], 1);
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
            continue;
          }
          const first = JSON.parse(firstLine.value);
          if (decision === 'workspace-missing') {
            assert.deepEqual(first, { ...correlation, type: 'outcome',
              outcome: { phase: 'not_submitted', reason: 'claude_workspace_unavailable' } });
            assert.equal((await exited)[0], 0);
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
            continue;
          }
          if (['subscription-wrong-account', 'subscription-account-drift'].includes(decision)) {
            assert.deepEqual(first, { ...correlation, type: 'outcome',
              outcome: { phase: 'not_submitted', reason: 'claude_subscription_auth_unverified' },
            });
            assert.equal((await exited)[0], 0);
            await assert.rejects(readFile(exposure), { code: 'ENOENT' });
            continue;
          }
          assert.match(first.sessionScope ?? JSON.stringify(first), /^[a-f0-9]{64}$/, decision);
          if (decision === 'messaging-paired-tribe') assert.equal(first.sessionScope, hostScope);
          if (decision === 'disconnected') restrictedScope = first.sessionScope;
          if (decision === 'committed') hostScope = first.sessionScope;
          assert.deepEqual(first,
            { ...correlation, type: 'prepare_submission', nativeSessionId: expectedSession,
              sessionScope: first.sessionScope, ...(workspace === undefined ? {} : { workspace }),
              ...(humanOriginal ? { steering: true } : {}) });
          await assert.rejects(readFile(exposure), { code: 'ENOENT' });
          if (decision === 'profile-changed') {
            await writeFile(selection, JSON.stringify({ ...profile, body: { ...body, incarnationId: 'replaced' } }));
          }
          if (decision === 'skill-changed-during-submission') await writeFile(skill, 'Temporary raced change.');
          if (messagingChanged) await writeFile(chatBinding, JSON.stringify({ ...binding, socket: tribeSocket }));
          if (decision === 'workspace-replaced') {
            await rename(alternateWorkspace, join(root, 'prior-workspace'));
            await mkdir(alternateWorkspace);
          }
          if (decision === 'disconnected') worker.stdin.end();
          else {
            worker.stdin.write(JSON.stringify({ ...correlation, type: 'submission_decision',
              sessionId: decision === 'wrong-correlation' ? correlation.inputId : correlation.sessionId,
              committed: decision !== 'rejected' && decision !== 'native-auth-rejected',
            }) + '\n');
          }
          const frame = JSON.parse((await lines.next()).value);
          const completed = pairedMessaging || ['committed', 'subscription-committed', 'workspace-selected', 'updated-guidance-resume', 'quoted-resume', 'telegram-quoted-resume', 'codex-seeded-resume', 'changed-skill-metadata', 'companion-after-human', 'companion-resume', 'companion-selected-resume', 'owner-default', 'messaging-unpaired'].includes(decision);
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
          if (decision === 'skill-changed-during-submission') await writeFile(skill, initialSkill);
          if (decision === 'changed-skill-metadata') await writeFile(skill, updatedSkill);
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
      await Promise.all([observerServer, foreignServer, tribeServer].map(server =>
        new Promise(resolve => server.close(resolve))));
      await rm(root, { recursive: true, force: true });
    }
  });
