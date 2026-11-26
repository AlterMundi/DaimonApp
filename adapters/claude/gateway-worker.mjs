// One foreground turn on a Gateway-owned pair of pipes.
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { constants } from 'node:fs';
import { access, mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

import { bodyMatches, createMatrixStatusBroker } from './matrix-broker.mjs';
import { runClaudeTurn, SKILL_NAMESPACE } from './turn.mjs';

import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';

const VERSION = 'daimon-gateway.claude-turn/v2';
const HOST_TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'NotebookEdit'];
const exec = promisify(execFile);

function turnScope(profile, bytes, skills, foundation, hostTools, humanOriginal, sessionInstructions) {
  const selector = profile.sharedDmk;
  return createHash('sha256')
    .update(JSON.stringify([
      profile.home, profile.cwd, profile.subscriptionEmail ?? null,
      profile.configurationDirectory ?? null, profile.apiKeyFile ?? null,
      selector?.command ?? null, selector?.bodyRef ?? null,
      profile.sharedSkillsDirectory ?? null, skills,
      foundation?.revision ?? null,
      hostTools, humanOriginal ? 'bypassPermissions' : false,
      ...(hostTools.includes('Bash') && profile.hostToolDirectory ? [profile.hostToolDirectory] : []),
      ...(sessionInstructions ? [{ sessionInstructions }] : []),
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
  const foundation = Object.hasOwn(value ?? {}, 'matrixFoundation') ? ['matrixFoundation'] : [];
  const hostTools = Object.hasOwn(value ?? {}, 'hostTools') ? ['hostTools'] : [];
  const hostToolDirectory = Object.hasOwn(value ?? {}, 'hostToolDirectory') ? ['hostToolDirectory'] : [];
  const budget = Object.hasOwn(value ?? {}, 'maxBudgetUsd') ? ['maxBudgetUsd'] : [];
  if (!closed(value, ['sdk', 'binary', 'cwd', 'home', ...authFields,
      'cliVersion', 'model', ...effort, ...displayName, ...memory, ...skills, ...foundation, ...hostTools,
      ...hostToolDirectory, ...budget, 'matrixStatusCommand', 'body'])
      || !closed(value.body, ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'])
      || ![value.sdk, value.binary, value.cwd, value.home, ...paths]
        .every(item => typeof item === 'string' && isAbsolute(item))
      || (skills.length > 0 && (typeof value.sharedSkillsDirectory !== 'string'
        || !isAbsolute(value.sharedSkillsDirectory)))
      || (hostTools.length > 0 && (!Array.isArray(value.hostTools)
        || value.hostTools.length !== new Set(value.hostTools).size
        || !value.hostTools.every(name => HOST_TOOLS.includes(name))))
      || (hostToolDirectory.length > 0 && (typeof value.hostToolDirectory !== 'string'
        || !isAbsolute(value.hostToolDirectory) || /[:\0\r\n]/.test(value.hostToolDirectory)))
      || (subscription && (typeof value.subscriptionEmail !== 'string'
        || value.subscriptionEmail.length > 254 || !/^[^\s@]+@[^\s@]+$/.test(value.subscriptionEmail)))
      || (effort.length > 0 && !['low', 'medium', 'high', 'xhigh', 'max'].includes(value.effort))
      || (displayName.length > 0 && (typeof value.displayName !== 'string'
        || value.displayName !== value.displayName.trim()
        || !/^[\p{L}\p{M}\p{N} .@·_-]{1,80}$/u.test(value.displayName)))
      || (budget.length > 0 && (!Number.isFinite(value.maxBudgetUsd) || value.maxBudgetUsd <= 0))
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
  return nativeStdio(profile.home, [...command, '--binding', snapshot]);
}

function nativeStdio(home, command) {
  return { type: 'stdio', command: '/usr/bin/env',
    args: ['-i', 'PATH=/usr/bin:/bin', `HOME=${home}`, ...command], alwaysLoad: true };
}

async function matrixFoundation(profile) {
  if (!Object.hasOwn(profile, 'matrixFoundation')) return undefined;
  const selection = profile.matrixFoundation;
  if (!closed(selection, ['command', 'tools'])) throw new Error('Invalid Matrix Foundation selection');
  const { command, tools } = selection;
  if (!Array.isArray(command) || command.length > 32
      || !command.every(arg => typeof arg === 'string' && arg.length > 0 && arg.length <= 8192)
      || typeof command[0] !== 'string' || !isAbsolute(command[0])
      || !Array.isArray(tools) || !tools.length || tools.length > 64
      || !tools.includes('daimon_status')
      || new Set(tools).size !== tools.length
      || !tools.every(name => typeof name === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(name))) {
    throw new Error('Invalid Matrix Foundation command or catalog');
  }
  const rootAt = command.indexOf('--runtime-root');
  const root = command[rootAt + 1];
  if (rootAt < 1 || command.lastIndexOf('--runtime-root') !== rootAt || !root || !isAbsolute(root)) {
    throw new Error('Matrix Foundation runtime root required');
  }
  const bytes = await privateBytes(join(root, 'client.json'), 16 * 1024);
  const { schema, expected_server, capability } = JSON.parse(bytes);
  const now = Date.now();
  if (schema !== 'dm.local.client-config/v3'
      || expected_server?.embodiment_id !== profile.body.embodimentId
      || expected_server?.incarnation_id !== profile.body.incarnationId
      || capability?.status !== 'active'
      || !Number.isSafeInteger(capability.not_before_ms) || capability.not_before_ms > now
      || !Number.isSafeInteger(capability.not_after_ms) || capability.not_after_ms <= now) {
    throw new Error('Matrix Foundation grant differs from the selected live body');
  }
  const revision = createHash('sha256').update(JSON.stringify([command, [...tools].sort()])).update(bytes).digest('hex');
  return { server: nativeStdio(profile.home, command), tools, revision };
}

async function probeFoundation(server, body, cwd, signal) {
  const deadline = AbortSignal.any([signal, AbortSignal.timeout(8_000)]);
  const child = spawn(server.command, server.args, { cwd, signal: deadline, stdio: ['pipe', 'pipe', 'ignore'] });
  const exited = once(child, 'close').catch(() => undefined);
  const input = frames(child.stdout);
  const send = request => writeFrame(child.stdin, { jsonrpc: '2.0', ...request }, deadline);
  child.stdin.on('error', () => child.kill());
  try {
    await send({ id: 1, method: 'initialize', params: {
      protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'daimon-gateway', version: '2' },
    } });
    const { value: initialized } = await input.next();
    if (initialized?.id !== 1 || initialized.result?.protocolVersion !== '2025-06-18') return false;
    await send({ method: 'notifications/initialized' });
    await send({ id: 2, method: 'tools/call', params: { name: 'daimon_status', arguments: {} } });
    const { value: observed } = await input.next();
    const status = observed?.result;
    return observed?.id === 2 && status?.isError === false && status.structuredContent?.ok === true
      && bodyMatches(status.structuredContent.result, body);
  } finally {
    child.stdin.end();
    child.kill();
    await exited;
  }
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
    const controllerSelected = first?.controller === true;
    const sessionInstructions = first?.sessionInstructions;
    const routedHuman = first?.routedHuman === true;
    const routedHostAccess = first?.routedHostAccess === true;
    const fullAccess = first?.humanOriginal === true || routedHostAccess;
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'freshNativeSessionId', 'resume', 'humanOriginal', 'text', 'body',
      ...(controllerSelected ? ['controller'] : []), ...(routedHuman ? ['routedHuman'] : []), ...(routedHostAccess ? ['routedHostAccess'] : []),
      ...(sessionInstructions === undefined ? [] : ['sessionInstructions'])])
      || (routedHostAccess && !routedHuman)
      || (routedHuman && (first.humanOriginal || controllerSelected))
      || (controllerSelected && first.humanOriginal !== true)
      || first.schema !== VERSION || first.type !== 'start'
      || typeof first.humanOriginal !== 'boolean'
      || ![first.inputId, first.sessionId, first.freshNativeSessionId]
        .every(value => typeof value === 'string' && UUID.test(value))
      || first.freshNativeSessionId === first.sessionId
      || (first.resume !== null && (!closed(first.resume, ['sessionId', 'scope'])
        || typeof first.resume.sessionId !== 'string' || !UUID.test(first.resume.sessionId)
        || first.resume.sessionId === first.freshNativeSessionId
        || typeof first.resume.scope !== 'string' || !/^[a-f0-9]{64}$/.test(first.resume.scope)))
      || typeof first.text !== 'string' || !first.text.trim()
      || Buffer.byteLength(first.text) > 16 * 1024
      || (sessionInstructions !== undefined && (typeof sessionInstructions !== 'string'
        || Buffer.byteLength(sessionInstructions) > 16 * 1024))
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
    const [binding, skills, foundation] = await Promise.all([
      sharedDmkBinding(profile), sharedSkillInventory(profile.sharedSkillsDirectory), matrixFoundation(profile),
    ]);
    if (binding || skills.names.length) scratch = await mkdtemp(join(tmpdir(), 'daimon-claude-'));
    const sharedDmk = binding ? await sharedDmkServer(profile, binding, scratch) : undefined;
    const sharedSkills = skills.names.length
      ? await sharedSkillPlugin(profile.sharedSkillsDirectory, skills.names, scratch) : undefined;
    const hostTools = fullAccess ? [...(profile.hostTools ?? HOST_TOOLS)].sort() : [];
    if (hostTools.includes('Bash')) {
      env.CLAUDE_CODE_SUBPROCESS_ENV_SCRUB = '1';
      if (profile.hostToolDirectory) env.PATH += `:${profile.hostToolDirectory}`;
    }
    let sharedDmkWriter;
    if (sharedDmk && hostTools.includes('Bash') && profile.hostToolDirectory) {
      const command = join(profile.hostToolDirectory, 'dmk');
      const executable = await access(command, constants.X_OK).then(() => true, () => false);
      if (executable) sharedDmkWriter = command;
    }
    const scope = turnScope(profile, binding ?? '', skills.revision, foundation, hostTools, fullAccess, sessionInstructions);
    const resume = first.resume?.scope === scope;
    const nativeSessionId = resume ? first.resume.sessionId : first.freshNativeSessionId;
    async function scopeStillActive() {
      const current = await ownerProfile(path);
      if (!Object.keys(expectedBody).every(key => current.body[key] === expectedBody[key])) return false;
      const [bytes, inventory, currentFoundation] = await Promise.all([
        sharedDmkBinding(current), sharedSkillInventory(current.sharedSkillsDirectory), matrixFoundation(current),
      ]);
      const currentTools = fullAccess ? [...(current.hostTools ?? HOST_TOOLS)].sort() : [];
      return turnScope(current, bytes ?? '', inventory.revision, currentFoundation, currentTools, fullAccess, sessionInstructions) === scope
        && (!currentFoundation || await probeFoundation(currentFoundation.server, expectedBody, current.cwd, stop.signal));
    }
    const broker = createMatrixStatusBroker({
      command: profile.matrixStatusCommand, expectedBody,
      createSdkMcpServer, tool, signal: stop.signal,
    });
    const pending = new Map();
    let nextCall = 0;
    let committed = false;
    async function receiveControllerReplies() {
      try {
        for await (const reply of input) {
          if (!closed(reply, ['schema', 'type', 'inputId', 'sessionId', 'callId', 'success', 'text'])
            || reply.schema !== VERSION || reply.type !== 'controller_reply'
            || reply.inputId !== first.inputId || reply.sessionId !== first.sessionId
            || typeof reply.success !== 'boolean' || typeof reply.text !== 'string'
            || !pending.has(reply.callId)) throw new Error('Invalid controller reply');
          const resolve = pending.get(reply.callId);
          pending.delete(reply.callId);
          resolve({ isError: !reply.success, content: [{ type: 'text', text: reply.text }] });
        }
      } finally {
        stop.abort();
        for (const resolve of pending.values()) {
          resolve({ isError: true, content: [{ type: 'text', text: 'Controller result unconfirmed. Inspect retained state.' }] });
        }
        pending.clear();
      }
    }
    let controller;
    if (controllerSelected) {
      const { z } = createRequire(profile.sdk)('zod');
      const controllerTool = tool('interaction_controller',
        'Call the shared Gateway conversation controller. Call capabilities with empty arguments to inspect the available operations.',
        { operation: z.string().min(1).max(64), arguments: z.record(z.string(), z.unknown()) },
        async ({ operation, arguments: args }) => {
          if (!committed || stop.signal.aborted || Buffer.byteLength(JSON.stringify(args)) > 15600) {
            return { isError: true, content: [{ type: 'text', text: 'Controller call is unavailable for this turn or arguments.' }] };
          }
          const callId = ++nextCall;
          const response = new Promise(resolve => { pending.set(callId, resolve); });
          try {
            await writeFrame(process.stdout, { ...correlation, type: 'controller_call', nativeSessionId,
              callId, operation, arguments: args }, stop.signal);
          } catch {
            process.stdin.destroy();
          }
          return response;
        }, { alwaysLoad: true });
      controller = createSdkMcpServer({ name: 'gateway', tools: [controllerTool] });
    }
    const outcome = await runClaudeTurn({
      query, broker, expectedBody, toolNames: ['daimon_status'], signal: stop.signal,
      input: { id: first.inputId, sessionId: nativeSessionId, text: first.text, resume },
      profile: {
        binary: profile.binary, cwd: profile.cwd, cliVersion: profile.cliVersion,
        model: profile.model, effort: profile.effort, subscriptionEmail: profile.subscriptionEmail,
        displayName: profile.displayName,
        sharedDmk, sharedDmkWriter, sharedSkills, matrixFoundation: foundation, hostTools, controller,
        fullAccess, routedHuman, sessionInstructions,
        persistSession: true,
        ...(profile.maxBudgetUsd === undefined ? {} : {
          maxBudgetUsd: profile.maxBudgetUsd,
          maxTurns: sharedDmk || sharedSkills || foundation || hostTools.length || controller ? 6 : 2,
        }),
        env,
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
        // After exposure only exact outstanding replies may arrive on this pipe.
        void receiveControllerReplies().catch(() => stop.abort());
        committed = await scopeStillActive();
        if (committed && fullAccess && profile.maxBudgetUsd === undefined) clearTimeout(timeout);
        return committed;
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
