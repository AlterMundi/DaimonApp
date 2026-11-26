// One foreground turn on a Gateway-owned pair of pipes.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

import { createMatrixStatusBroker } from './matrix-broker.mjs';
import { runClaudeTurn, SKILL_NAMESPACE } from './turn.mjs';

import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';

const VERSION = 'daimon-gateway.claude-turn/v2';
const exec = promisify(execFile);

function turnScope(profile, bytes, skills) {
  const selector = profile.sharedDmk;
  return createHash('sha256')
    .update(JSON.stringify([
      profile.home, profile.cwd, profile.subscriptionEmail ?? null,
      profile.configurationDirectory ?? null, profile.apiKeyFile ?? null,
      selector?.command ?? null, selector?.bodyRef ?? null,
      profile.sharedSkillsDirectory ?? null, skills,
    ]))
    .update(bytes)
    .digest('hex');
}

async function ownerProfile(path) {
  const value = JSON.parse(await privateBytes(path, 16 * 1024));
  const subscription = Object.hasOwn(value ?? {}, 'subscriptionEmail');
  const authFields = subscription ? ['subscriptionEmail'] : ['configurationDirectory', 'apiKeyFile'];
  const paths = subscription ? [] : [value?.configurationDirectory, value?.apiKeyFile];
  const effort = Object.hasOwn(value ?? {}, 'effort') ? ['effort'] : [];
  const displayName = Object.hasOwn(value ?? {}, 'displayName') ? ['displayName'] : [];
  const memory = Object.hasOwn(value ?? {}, 'sharedDmk') ? ['sharedDmk'] : [];
  const skills = Object.hasOwn(value ?? {}, 'sharedSkillsDirectory') ? ['sharedSkillsDirectory'] : [];
  if (!closed(value, ['sdk', 'binary', 'cwd', 'home', ...authFields,
      'cliVersion', 'model', ...effort, ...displayName, ...memory, ...skills,
      'maxBudgetUsd', 'matrixStatusCommand', 'body'])
      || !closed(value.body, ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'])
      || ![value.sdk, value.binary, value.cwd, value.home, ...paths]
        .every(item => typeof item === 'string' && isAbsolute(item))
      || (skills.length > 0 && (typeof value.sharedSkillsDirectory !== 'string'
        || !isAbsolute(value.sharedSkillsDirectory)))
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

async function sharedDmkBinding(profile) {
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
  return bytes;
}

async function sharedDmkServer(profile, bytes, directory) {
  const { command } = profile.sharedDmk;
  const snapshot = join(directory, 'binding.json');
  await writeFile(snapshot, bytes, { mode: 0o600, flag: 'wx' });
  return { type: 'stdio', command: '/usr/bin/env',
    args: ['-i', 'PATH=/usr/bin:/bin', `HOME=${profile.home}`, ...command, '--binding', snapshot],
    alwaysLoad: true };
}

async function sharedSkillInventory(root) {
  if (!root) return { names: [], revision: null };
  const names = [];
  const revision = createHash('sha256');
  for (const name of (await readdir(root)).sort()) {
    if (name.startsWith('.')) continue;
    const file = join(root, name, 'SKILL.md');
    const entry = await stat(file).catch(error => {
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
      throw error;
    });
    if (!entry?.isFile()) continue;
    const path = await realpath(file);
    const digest = createHash('sha256').update(await readFile(path)).digest('hex');
    revision.update(JSON.stringify([name, path, digest]));
    names.push(`${SKILL_NAMESPACE}:${name}`);
  }
  if (!names.length) throw new Error('Selected shared skills directory is empty');
  return { names, revision: revision.digest('hex') };
}

async function sharedSkillPlugin(root, names, directory) {
  const path = join(directory, 'shared-skills');
  const manifest = join(path, '.claude-plugin');
  await mkdir(manifest, { recursive: true });
  await writeFile(join(manifest, 'plugin.json'), JSON.stringify({ name: SKILL_NAMESPACE, version: '1.0.0' }),
    { mode: 0o600, flag: 'wx' });
  await symlink(root, join(path, 'skills'), 'dir');
  return { path, names };
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
  let scratch;
  try {
    const profile = await ownerProfile(path);
    const first = (await input.next()).value;
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'freshNativeSessionId', 'resume', 'text', 'body'])
      || first.schema !== VERSION || first.type !== 'start'
      || ![first.inputId, first.sessionId, first.freshNativeSessionId]
        .every(value => typeof value === 'string' && UUID.test(value))
      || first.freshNativeSessionId === first.sessionId
      || (first.resume !== null && (!closed(first.resume, ['sessionId', 'scope'])
        || typeof first.resume.sessionId !== 'string' || !UUID.test(first.resume.sessionId)
        || first.resume.sessionId === first.freshNativeSessionId
        || typeof first.resume.scope !== 'string' || !/^[a-f0-9]{64}$/.test(first.resume.scope)))
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
    const [binding, skills] = await Promise.all([
      sharedDmkBinding(profile), sharedSkillInventory(profile.sharedSkillsDirectory),
    ]);
    if (binding || skills.names.length) scratch = await mkdtemp(join(tmpdir(), 'daimon-claude-'));
    const sharedDmk = binding ? await sharedDmkServer(profile, binding, scratch) : undefined;
    const sharedSkills = skills.names.length
      ? await sharedSkillPlugin(profile.sharedSkillsDirectory, skills.names, scratch) : undefined;
    const scope = turnScope(profile, binding ?? '', skills.revision);
    const resume = first.resume?.scope === scope;
    const nativeSessionId = resume ? first.resume.sessionId : first.freshNativeSessionId;
    async function scopeStillActive() {
      const current = await ownerProfile(path);
      if (!Object.keys(expectedBody).every(key => current.body[key] === expectedBody[key])) return false;
      const [bytes, inventory] = await Promise.all([
        sharedDmkBinding(current), sharedSkillInventory(current.sharedSkillsDirectory),
      ]);
      return turnScope(current, bytes ?? '', inventory.revision) === scope;
    }
    const broker = createMatrixStatusBroker({
      command: profile.matrixStatusCommand, expectedBody,
      createSdkMcpServer, tool, signal: stop.signal,
    });
    const outcome = await runClaudeTurn({
      query, broker, expectedBody, toolNames: ['daimon_status'], signal: stop.signal,
      input: { id: first.inputId, sessionId: nativeSessionId, text: first.text, resume },
      profile: {
        binary: profile.binary, cwd: profile.cwd, cliVersion: profile.cliVersion,
        model: profile.model, effort: profile.effort, subscriptionEmail: profile.subscriptionEmail,
        displayName: profile.displayName,
        sharedDmk, sharedSkills,
        persistSession: true, maxTurns: sharedDmk || sharedSkills ? 6 : 2,
        maxBudgetUsd: profile.maxBudgetUsd, env,
      },
      async beforeSubmit(inputId, sessionId) {
        if (inputId !== first.inputId || sessionId !== nativeSessionId) return false;
        if (!await scopeStillActive()) return false;
        await writeFrame(process.stdout, { ...correlation, type: 'prepare_submission',
          nativeSessionId: sessionId, sessionScope: scope }, stop.signal);
        const decision = (await input.next()).value;
        if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed'])
          || decision.schema !== VERSION || decision.type !== 'submission_decision'
          || decision.inputId !== inputId || decision.sessionId !== first.sessionId
          || decision.committed !== true) return false;
        // A closed owner pipe or a second command cancels this attempt.
        void input.next().then(() => stop.abort(), () => stop.abort());
        return scopeStillActive();
      },
    });
    await writeFrame(process.stdout, { ...correlation, type: 'outcome', outcome }, stop.signal);
  } finally {
    clearTimeout(timeout);
    process.stdin.destroy();
    if (scratch) await rm(scratch, { recursive: true, force: true });
  }
}

main().catch(() => {
  // The owner correlates a worker abort against its own durable decision.
  // Provider diagnostics and input bytes stay outside this protocol.
  process.exitCode = 1;
});
