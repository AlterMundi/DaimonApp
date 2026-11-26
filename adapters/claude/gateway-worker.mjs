// One foreground turn on a Gateway-owned pair of pipes.
import { execFile } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

import { createMatrixStatusBroker } from './matrix-broker.mjs';
import { runClaudeTurn } from './turn.mjs';

import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';

const VERSION = 'daimon-gateway.claude-turn/v1';
const exec = promisify(execFile);

async function ownerProfile(path) {
  const value = JSON.parse(await privateBytes(path, 16 * 1024));
  const subscription = Object.hasOwn(value ?? {}, 'subscriptionEmail');
  const authFields = subscription ? ['subscriptionEmail'] : ['configurationDirectory', 'apiKeyFile'];
  const paths = subscription ? [] : [value?.configurationDirectory, value?.apiKeyFile];
  const effort = Object.hasOwn(value ?? {}, 'effort') ? ['effort'] : [];
  const displayName = Object.hasOwn(value ?? {}, 'displayName') ? ['displayName'] : [];
  const memory = Object.hasOwn(value ?? {}, 'sharedDmk') ? ['sharedDmk'] : [];
  if (!closed(value, ['sdk', 'binary', 'cwd', 'home', ...authFields,
      'cliVersion', 'model', ...effort, ...displayName, ...memory, 'maxBudgetUsd', 'matrixStatusCommand', 'body'])
      || !closed(value.body, ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'])
      || ![value.sdk, value.binary, value.cwd, value.home, ...paths]
        .every(item => typeof item === 'string' && isAbsolute(item))
      || (subscription && (typeof value.subscriptionEmail !== 'string'
        || value.subscriptionEmail.length > 254 || !/^[^\s@]+@[^\s@]+$/.test(value.subscriptionEmail)))
      || (effort.length > 0 && !['low', 'medium', 'high', 'xhigh', 'max'].includes(value.effort))
      || (displayName.length > 0 && (typeof value.displayName !== 'string'
        || value.displayName !== value.displayName.trim()
        || !/^[\p{L}\p{M}\p{N} .@·_-]{1,80}$/u.test(value.displayName)))
      || !Number.isFinite(value.maxBudgetUsd) || value.maxBudgetUsd <= 0
      || ![value.cliVersion, value.model, ...Object.values(value.body)]
        .every(item => typeof item === 'string' && item.length > 0 && item.length <= 240)
      || !Array.isArray(value.matrixStatusCommand)
      || value.matrixStatusCommand.length < 1 || value.matrixStatusCommand.length > 16
      || !value.matrixStatusCommand.every(item => typeof item === 'string' && item.length <= 4096)
      || !isAbsolute(value.matrixStatusCommand[0])) {
    throw new Error('Invalid owner profile');
  }
  return value;
}

async function sharedDmkServer(profile, retainDirectory) {
  if (!Object.hasOwn(profile, 'sharedDmk')) return undefined;
  if (!closed(profile.sharedDmk, ['command', 'bindingFile', 'bodyRef'])) {
    throw new Error('Invalid shared DMK selection');
  }
  const { command, bindingFile, bodyRef } = profile.sharedDmk;
  if (!Array.isArray(command) || command.length < 2 || command.length > 8
      || !command.every(value => typeof value === 'string' && value.length > 0 && value.length <= 4096)
      || !isAbsolute(command[0]) || typeof bindingFile !== 'string' || !isAbsolute(bindingFile)
      || typeof bodyRef !== 'string' || bodyRef.length < 1 || bodyRef.length > 240) {
    throw new Error('Invalid shared DMK selection');
  }
  const bytes = await privateBytes(bindingFile, 16 * 1024);
  const binding = JSON.parse(bytes);
  if (binding?.schema !== 'hmk.deep-recall.binding/v1'
      || binding.being_ref !== profile.body.beingRef || binding.body_ref !== bodyRef) {
    throw new Error('Shared DMK differs from selected body or being');
  }
  const directory = await mkdtemp(join(tmpdir(), 'daimon-claude-dmk-'));
  retainDirectory(directory);
  const snapshot = join(directory, 'binding.json');
  await writeFile(snapshot, bytes, { mode: 0o600, flag: 'wx' });
  return { type: 'stdio', command: '/usr/bin/env',
    args: ['-i', 'PATH=/usr/bin:/bin', `HOME=${profile.home}`, ...command, '--binding', snapshot],
    alwaysLoad: true };
}

async function providerEnvironment(profile, signal) {
  const env = {
    PATH: '/usr/bin:/bin', HOME: profile.home, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
  };
  if (profile.apiKeyFile) {
    const key = (await privateBytes(profile.apiKeyFile, 4096)).toString('utf8').trim();
    if (!/^[!-~]+$/.test(key)) throw new Error('Invalid provider credential');
    env.ANTHROPIC_API_KEY = key;
    env.CLAUDE_CONFIG_DIR = profile.configurationDirectory;
  }
  const { stdout } = await exec(profile.binary, ['auth', 'status'], {
    cwd: profile.cwd, env, signal, timeout: 5000, maxBuffer: 8192,
  });
  const auth = JSON.parse(stdout);
  const selected = profile.subscriptionEmail
    ? auth.authMethod === 'claude.ai' && auth.email === profile.subscriptionEmail && auth.apiKeySource == null
    : auth.authMethod === 'api_key' && auth.apiKeySource === 'ANTHROPIC_API_KEY';
  if (auth.loggedIn !== true || auth.apiProvider !== 'firstParty' || !selected) {
    throw new Error('Selected Claude authentication unavailable');
  }
  return env;
}

async function main() {
  const [flag, path, ...extra] = process.argv.slice(2);
  if (flag !== '--profile' || extra.length) throw new Error('Owner profile required');
  const stop = new AbortController();
  const timeout = setTimeout(() => stop.abort(), 125_000);
  stop.signal.addEventListener('abort', () => process.stdin.destroy(), { once: true });
  const input = frames(process.stdin);
  let dmkDirectory;
  try {
    const profile = await ownerProfile(path);
    const first = (await input.next()).value;
    const resume = Object.hasOwn(first ?? {}, 'resume');
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'text', 'body', ...(resume ? ['resume'] : [])])
      || first.schema !== VERSION || first.type !== 'start'
      || (resume && first.resume !== true)
      || typeof first.inputId !== 'string' || typeof first.sessionId !== 'string'
      || !UUID.test(first.inputId) || !UUID.test(first.sessionId)
      || typeof first.text !== 'string' || !first.text.trim()
      || Buffer.byteLength(first.text) > 16 * 1024
      || !closed(first.body, Object.keys(profile.body))
      || !Object.keys(profile.body).every(key => first.body[key] === profile.body[key])) {
      throw new Error('Invalid foreground start');
    }
    const correlation = { schema: VERSION, inputId: first.inputId, sessionId: first.sessionId };
    let env;
    try {
      env = await providerEnvironment(profile, stop.signal);
    } catch {
      await writeFrame(process.stdout, { ...correlation, type: 'outcome',
        outcome: { phase: 'not_submitted', reason: profile.subscriptionEmail
          ? 'claude_subscription_auth_unverified' : 'claude_api_auth_unverified' },
      }, stop.signal);
      return;
    }
    const { query, createSdkMcpServer, tool } = await import(pathToFileURL(profile.sdk));
    const expectedBody = profile.body;
    const sharedDmk = await sharedDmkServer(profile, directory => { dmkDirectory = directory; });
    const broker = createMatrixStatusBroker({
      command: profile.matrixStatusCommand, expectedBody,
      createSdkMcpServer, tool, signal: stop.signal,
    });
    const outcome = await runClaudeTurn({
      query, broker, expectedBody, toolNames: ['daimon_status'], signal: stop.signal,
      input: { id: first.inputId, sessionId: first.sessionId, text: first.text, resume },
      profile: {
        binary: profile.binary, cwd: profile.cwd, cliVersion: profile.cliVersion,
        model: profile.model, effort: profile.effort, subscriptionEmail: profile.subscriptionEmail,
        displayName: profile.displayName,
        sharedDmk,
        persistSession: true, maxTurns: sharedDmk ? 6 : 2,
        maxBudgetUsd: profile.maxBudgetUsd, env,
      },
      async beforeSubmit(inputId, sessionId) {
        if (inputId !== first.inputId || sessionId !== first.sessionId) return false;
        await writeFrame(process.stdout, { ...correlation, type: 'prepare_submission',
          nativeSessionId: sessionId }, stop.signal);
        const decision = (await input.next()).value;
        if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed'])
          || decision.schema !== VERSION || decision.type !== 'submission_decision'
          || decision.inputId !== inputId || decision.sessionId !== sessionId
          || decision.committed !== true) return false;
        // A closed owner pipe or a second command cancels this attempt.
        void input.next().then(() => stop.abort(), () => stop.abort());
        return true;
      },
    });
    await writeFrame(process.stdout, { ...correlation, type: 'outcome', outcome }, stop.signal);
  } finally {
    clearTimeout(timeout);
    process.stdin.destroy();
    if (dmkDirectory) await rm(dmkDirectory, { recursive: true, force: true });
  }
}

main().catch(() => {
  // The owner correlates a worker abort against its own durable decision.
  // Provider diagnostics and input bytes stay outside this protocol.
  process.exitCode = 1;
});
