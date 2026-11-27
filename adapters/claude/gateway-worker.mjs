// One foreground turn on a Gateway-owned pair of pipes.
import { execFile, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { constants } from 'node:fs';
import { access, mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

import { bodyMatches, createMatrixStatusBroker } from './matrix-broker.mjs';
import { runClaudeTurn, SKILL_NAMESPACE } from './turn.mjs';

import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';

const VERSION = 'daimon-gateway.claude-turn/v2';
const HOST_TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'NotebookEdit'];
const exec = promisify(execFile);

function turnScope(profile, bytes, skills, foundation, hostTools, fullAccess, controller, sessionInstructions, messaging) {
  const selector = profile.sharedDmk;
  return createHash('sha256')
    .update(JSON.stringify([
      profile.home, profile.cwd, profile.subscriptionEmail ?? null,
      profile.configurationDirectory ?? null, profile.apiKeyFile ?? null,
      selector?.command ?? null, selector?.bodyRef ?? null,
      profile.sharedSkillsDirectory ?? null, skills,
      foundation?.revision ?? null,
      hostTools, fullAccess ? 'bypassPermissions' : false,
      ...(fullAccess ? [{ controller }] : []),
      ...(hostTools.includes('Bash') && profile.hostToolDirectory ? [profile.hostToolDirectory] : []),
      ...(sessionInstructions ? [{ sessionInstructions }] : []),
      ...(messaging ? [{ messaging: messaging.revision }] : []),
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
  const guidance = Object.hasOwn(value ?? {}, 'bodyGuidanceFile') ? ['bodyGuidanceFile'] : [];
  const memory = Object.hasOwn(value ?? {}, 'sharedDmk') ? ['sharedDmk'] : [];
  const skills = Object.hasOwn(value ?? {}, 'sharedSkillsDirectory') ? ['sharedSkillsDirectory'] : [];
  const skillAnchor = Object.hasOwn(value ?? {}, 'skillResumeAnchor') ? ['skillResumeAnchor'] : [];
  const skillContinuity = Object.hasOwn(value ?? {}, 'skillContinuity') ? ['skillContinuity'] : [];
  const foundation = Object.hasOwn(value ?? {}, 'matrixFoundation') ? ['matrixFoundation'] : [];
  const messaging = Object.hasOwn(value ?? {}, 'matrixMessaging') ? ['matrixMessaging'] : [];
  const hostTools = Object.hasOwn(value ?? {}, 'hostTools') ? ['hostTools'] : [];
  const hostToolDirectory = Object.hasOwn(value ?? {}, 'hostToolDirectory') ? ['hostToolDirectory'] : [];
  const budget = Object.hasOwn(value ?? {}, 'maxBudgetUsd') ? ['maxBudgetUsd'] : [];
  if (!closed(value, ['sdk', 'binary', 'cwd', 'home', ...authFields,
      'cliVersion', 'model', ...effort, ...displayName, ...guidance, ...memory, ...skills, ...skillAnchor, ...skillContinuity, ...foundation, ...messaging, ...hostTools,
      ...hostToolDirectory, ...budget, 'matrixStatusCommand', 'body'])
      || !closed(value.body, ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'])
      || ![value.sdk, value.binary, value.cwd, value.home, ...paths]
        .every(item => typeof item === 'string' && isAbsolute(item))
      || (skills.length > 0 && (typeof value.sharedSkillsDirectory !== 'string'
        || !isAbsolute(value.sharedSkillsDirectory)))
      || (skillAnchor.length > 0 && (!skills.length
        || !Array.isArray(value.skillResumeAnchor)
        || value.skillResumeAnchor.length < 2 || value.skillResumeAnchor.length > 16
        || new Set(value.skillResumeAnchor).size !== value.skillResumeAnchor.length
        || !value.skillResumeAnchor.every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))))
      || (skillContinuity.length > 0 && (!skills.length
        || !closed(value.skillContinuity, ['layoutRevision',
          ...(Object.hasOwn(value.skillContinuity ?? {}, 'previousRevision') ? ['previousRevision'] : [])])
        || !Object.values(value.skillContinuity).every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))))
      || (messaging.length > 0 && !(typeof value.matrixMessaging === 'string'
        ? isAbsolute(value.matrixMessaging)
        : closed(value.matrixMessaging, ['connection', 'objectToolSchemas'])
          && typeof value.matrixMessaging.connection === 'string'
          && isAbsolute(value.matrixMessaging.connection)
          && value.matrixMessaging.objectToolSchemas === true))
      || (hostTools.length > 0 && (!Array.isArray(value.hostTools)
        || value.hostTools.length !== new Set(value.hostTools).size
        || !value.hostTools.every(name => HOST_TOOLS.includes(name))))
      || (hostToolDirectory.length > 0 && (typeof value.hostToolDirectory !== 'string'
        || !isAbsolute(value.hostToolDirectory) || /[:\0\r\n]/.test(value.hostToolDirectory)))
      || (subscription && (typeof value.subscriptionEmail !== 'string'
        || value.subscriptionEmail.length > 254 || !/^[^\s@]+@[^\s@]+$/.test(value.subscriptionEmail)))
      || (guidance.length > 0 && (typeof value.bodyGuidanceFile !== 'string'
        || !isAbsolute(value.bodyGuidanceFile)))
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

async function bodyGuidance(profile, fullAccess) {
  if (!fullAccess || !profile.bodyGuidanceFile) return undefined;
  const bytes = await privateBytes(profile.bodyGuidanceFile, 16 * 1024);
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes).trim();
  if (!text || text.includes('\0')) throw new Error('Invalid body guidance');
  return text;
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

async function matrixMessaging(profile, fullAccess) {
  if (!fullAccess || !profile.matrixMessaging) return undefined;
  const selection = profile.matrixMessaging;
  const objectToolSchemas = typeof selection !== 'string';
  const connectionBytes = await privateBytes(objectToolSchemas ? selection.connection : selection, 128 * 1024);
  const { command } = JSON.parse(connectionBytes);
  const bindingFile = Array.isArray(command) ? command.at(-1) : undefined;
  const moduleArgs = ['-I', '-m', 'daimon_matrix.agent_chat', '--binding'];
  if (!Array.isArray(command) || command.length !== 6
      || !command.every(arg => typeof arg === 'string' && arg.length > 0 && arg.length <= 4096)
      || !isAbsolute(command[0]) || !isAbsolute(bindingFile)
      || !moduleArgs.every((arg, index) => command[index + 1] === arg)) {
    throw new Error('Invalid native Matrix messaging connection');
  }
  const bindingBytes = await privateBytes(bindingFile, 16 * 1024);
  const binding = JSON.parse(bindingBytes);
  if (binding.schema !== 'dm.agent-chat.binding/v1'
      || typeof binding.client_config !== 'string' || !isAbsolute(binding.client_config)) {
    throw new Error('Invalid native Matrix messaging binding');
  }
  const clientBytes = await privateBytes(binding.client_config, 16 * 1024);
  const { schema, expected_server, capability, runtime_id } = JSON.parse(clientBytes);
  const observerArgs = profile.matrixStatusCommand;
  const observerIndex = observerArgs.indexOf('--binding');
  if (observerIndex < 1 || observerArgs.lastIndexOf('--binding') !== observerIndex
      || !observerArgs.includes('--body-status')) {
    throw new Error('Messaging requires an authenticated Matrix observation binding');
  }
  const observerBytes = await privateBytes(observerArgs[observerIndex + 1], 32 * 1024);
  const observer = JSON.parse(observerBytes);
  const observed = observer.observation;
  if (!observed?.client_config || typeof binding.socket !== 'string' || !isAbsolute(binding.socket)
      || typeof observed.socket !== 'string' || !isAbsolute(observed.socket)) {
    throw new Error('Matrix messaging and identity observation socket selections required');
  }
  const [messagingSocket, observationSocket] = await Promise.all([
    realpath(binding.socket), realpath(observed.socket),
  ]);
  // Cluster serves the signed Tribe view alongside the base Matrix view under
  // the same runtime writer. Keep both clients bound to that exact runtime.
  const standaloneTribe = basename(observationSocket) === 'matrix.sock'
    && messagingSocket === join(dirname(observationSocket), 'tribe.sock');
  if ((messagingSocket !== observationSocket && !standaloneTribe)
      || !(await stat(messagingSocket)).isSocket() || !(await stat(observationSocket)).isSocket()) {
    throw new Error('Matrix messaging and identity observation must use the same runtime');
  }
  const observedClient = JSON.parse(await privateBytes(observed.client_config, 16 * 1024));
  const methods = ['messaging.delivery', 'messaging.inbox', 'messaging.reply', 'messaging.send'];
  const now = Date.now();
  const timed = capability?.schema === 'dm.local.capability/v1';
  const validity = timed ? capability : capability?.validity;
  const valid = Number.isSafeInteger(validity?.not_before_ms) && validity.not_before_ms <= now
    && (timed ? Number.isSafeInteger(validity.not_after_ms) && now < validity.not_after_ms
      : capability?.schema === 'dm.local.capability/v2'
        && closed(validity, ['mode', 'not_before_ms']) && validity.mode === 'until-revoked');
  if (schema !== 'dm.local.client-config/v3'
      || observedClient.schema !== schema
      || observer.source?.being_ref !== profile.body.beingRef
      || observer.source?.embodiment_id !== profile.body.embodimentId
      || typeof runtime_id !== 'string' || runtime_id !== observedClient.runtime_id
      || expected_server?.embodiment_id !== profile.body.embodimentId
      || expected_server?.incarnation_id !== profile.body.incarnationId
      || !['body_ref', 'embodiment_id', 'incarnation_id', 'principal_id'].every(name =>
        typeof expected_server?.[name] === 'string'
        && expected_server[name] === observedClient.expected_server?.[name])
      || !valid || capability?.status !== 'active' || !Array.isArray(capability.methods)
      || JSON.stringify([...capability.methods].sort()) !== JSON.stringify(methods)) {
    throw new Error('Matrix messaging grant differs from the selected live body');
  }
  return {
    server: nativeStdio(profile.home, [command[0], ...moduleArgs, bindingFile, 'mcp',
      ...(objectToolSchemas ? ['--object-tool-schemas'] : [])]),
    objectToolSchemas,
    tools: methods.map(method => method.replace('.', '_')),
    revision: createHash('sha256').update(connectionBytes).update(bindingBytes).update(clientBytes)
      .update(observerBytes).digest('hex'),
  };
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

function skillFrontmatter(bytes, digest) {
  const text = bytes.toString('utf8');
  // Preserve unknown native metadata verbatim. Only the conventional
  // metadata.version string is ignored. Malformed headers stay revision-bound.
  if (!/^\uFEFF?---/.test(text)) return null;
  const header = /^---\r?\n([\s\S]*?)^---[ \t]*(?:\r?\n|$)/m.exec(text);
  if (!header || header.index !== 0) return digest;
  const lines = header[1].split(/\r?\n/);
  const validScalar = value => /^"(?:[^"\\]|\\.)*"$/.test(value)
    || /^'(?:[^']|'')*'$/.test(value)
    || /^[A-Za-z0-9_./@%+()][^\r\n]*$/.test(value);
  let metadata = false;
  const topKeys = new Set();
  const metadataKeys = new Set();
  for (const [index, line] of lines.entries()) {
    if (!line) continue;
    const field = /^( {2})?([A-Za-z0-9_-]+):(?: (.+))?$/.exec(line);
    if (!field) return header[1];
    const [, indent, key, value] = field;
    const keys = indent ? metadataKeys : topKeys;
    if (keys.has(key) || (indent && !metadata)) return header[1];
    keys.add(key);
    if (!indent) metadata = key === 'metadata' && value === undefined;
    if (value === undefined ? !!indent || !metadata : !validScalar(value)) return header[1];
    if (indent && key === 'version' && /^"[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.]+)?"$/.test(value)) {
      lines[index] = ['metadata.version', 'semver'];
    }
  }
  return lines;
}

async function sharedSkillInventory(root) {
  if (!root) return { names: [], revision: null, layoutRevision: null };
  const names = [];
  const revision = createHash('sha256');
  const layout = createHash('sha256');
  for (const name of (await readdir(root)).sort()) {
    if (name.startsWith('.')) continue;
    const file = join(root, name, 'SKILL.md');
    const entry = await stat(file).catch(error => {
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
      throw error;
    });
    if (!entry?.isFile()) continue;
    const path = await realpath(file);
    const bytes = await readFile(path);
    const digest = createHash('sha256').update(bytes).digest('hex');
    revision.update(JSON.stringify([name, path, digest]));
    layout.update(JSON.stringify([name, path, skillFrontmatter(bytes, digest)]));
    names.push(`${SKILL_NAMESPACE}:${name}`);
  }
  if (!names.length) throw new Error('Selected shared skills directory is empty');
  return { names, revision: revision.digest('hex'), layoutRevision: layout.digest('hex') };
}

function skillScopeRevision(profile, inventory) {
  const continuity = profile.skillContinuity;
  if (continuity && continuity.layoutRevision === inventory.layoutRevision) {
    return continuity.previousRevision ?? 'skill-layout/v1:' + inventory.layoutRevision;
  }
  const anchor = profile.skillResumeAnchor;
  return anchor?.includes(inventory.revision) ? anchor[0] : inventory.revision;
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

async function observeRuntime(path) {
  const profile = await ownerProfile(path);
  if (!profile.subscriptionEmail) return {};
  const deadline = AbortSignal.timeout(10000);
  const env = await providerEnvironment(profile, deadline);
  // The SDK suppresses account-limit retrieval under this option. The
  // observer explicitly reads /usage and does not submit model work.
  delete env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC;
  const { query } = await import(pathToFileURL(profile.sdk));
  const abortController = new AbortController();
  const cancel = () => abortController.abort();
  deadline.addEventListener('abort', cancel, { once: true });
  let permit;
  const ready = new Promise(resolve => { permit = resolve; });
  const prompt = (async function* () {
    if (!await ready) return;
    // This is a fixed account query. No caller text can enter this session.
    yield { type: 'user', parent_tool_use_id: null, message: { role: 'user', content: '/usage' } };
  })();
  const native = query({ prompt, options: {
    abortController, env, cwd: profile.cwd, pathToClaudeCodeExecutable: profile.binary,
    model: profile.model, effort: profile.effort, tools: [], settingSources: [],
    persistSession: false, strictMcpConfig: true,
  } });
  try {
    const { account, claude_code_version: cliVersion } = await native.initializationResult();
    if (cliVersion !== profile.cliVersion || account?.email !== profile.subscriptionEmail
        || account.apiProvider !== 'firstParty' || !account.subscriptionType || account.apiKeySource != null
        || !(await native.supportedCommands()).some(command => /^\/?usage$/.test(command.name))) return {};
    permit(true);
    let model, weekly, session;
    for await (const event of native) {
      if (event.type === 'system' && event.subtype === 'init'
          && typeof event.model === 'string' && /^claude-[a-z0-9-]{1,96}$/.test(event.model)) {
        model = event.model;
      }
      if (event.type === 'assistant') {
        const limits = event.usage_report?.rate_limits?.limits;
        if (Array.isArray(limits)) {
          const readWindow = (kind, group) => {
            const matches = limits.filter(window => window?.kind === kind && window.group === group
              && window.scope == null && Number.isFinite(window.percent) && window.percent >= 0 && window.percent <= 100);
            if (matches.length !== 1) return;
            const reset = Date.parse(matches[0].resets_at);
            if (Number.isFinite(reset) && reset > Date.now()) {
              return { available: 100 - matches[0].percent, resets_at: Math.floor(reset / 1000) };
            }
          };
          weekly = readWindow('weekly_all', 'weekly');
          session = readWindow('session', 'session');
        }
      }
      if (event.type === 'result') {
        if (event.subtype === 'success' && event.is_error === false && event.local_command === 'usage'
            && event.duration_api_ms === 0) return { model, weekly, session };
        return {};
      }
    }
    return {};
  } finally {
    permit(false);
    native.close();
    deadline.removeEventListener('abort', cancel);
  }
}

async function main() {
  const [flag, path, ...extra] = process.argv.slice(2);
  if (flag === '--observe-runtime' && extra.length === 0) {
    process.stdout.write(JSON.stringify(await observeRuntime(path)) + '\n');
    return;
  }
  if (flag === '--skill-resume-anchor' && extra.length === 0) {
    const profile = await ownerProfile(path);
    if (!profile.sharedSkillsDirectory) throw new Error('Shared skill selection required');
    const { revision, layoutRevision } = await sharedSkillInventory(profile.sharedSkillsDirectory);
    process.stdout.write(JSON.stringify({ revision, layoutRevision }) + '\n');
    return;
  }
  if (flag !== '--profile' || extra.length) throw new Error('Owner profile required');
  const stop = new AbortController();
  const timeout = setTimeout(() => stop.abort(), 125_000);
  stop.signal.addEventListener('abort', () => process.stdin.destroy(), { once: true });
  const input = frames(process.stdin);
  let scratch;
  try {
    let profile = await ownerProfile(path);
    const first = (await input.next()).value;
    const controllerSelected = first?.controller === true;
    const nativeGoalCommand = first?.nativeGoalCommand === true;
    const sessionInstructions = first?.sessionInstructions;
    const workspace = first?.workspace;
    const historySeed = first?.historySeed;
    const fromCodex = closed(historySeed, ['turn', 'human', 'assistant', 'harness'])
      && historySeed.harness === 'codex';
    const exactQuote = closed(historySeed, ['source', 'revision', 'assistant'])
      && typeof historySeed.source === 'string'
      && ['delivery:', 'telegram-result:'].some(prefix =>
        historySeed.source.startsWith(prefix) && UUID.test(historySeed.source.slice(prefix.length)))
      && typeof historySeed.revision === 'string' && /^[a-f0-9]{64}$/.test(historySeed.revision)
      && typeof historySeed.assistant === 'string' && !!historySeed.assistant.trim();
    const attachments = first?.attachments;
    const routedHuman = first?.routedHuman === true;
    const routedHostAccess = first?.routedHostAccess === true;
    const fullAccess = first?.humanOriginal === true || routedHostAccess;
    const alternates = Object.hasOwn(first ?? {}, 'resumeAlternates') ? first.resumeAlternates : [];
    const validResume = prior => closed(prior, ['sessionId', 'scope'])
      && typeof prior.sessionId === 'string' && UUID.test(prior.sessionId)
      && prior.sessionId !== first.freshNativeSessionId
      && typeof prior.scope === 'string' && /^[a-f0-9]{64}$/.test(prior.scope);
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'freshNativeSessionId', 'resume', 'humanOriginal', 'text', 'body',
      ...(Object.hasOwn(first ?? {}, 'resumeAlternates') ? ['resumeAlternates'] : []),
      ...(controllerSelected ? ['controller'] : []), ...(routedHuman ? ['routedHuman'] : []), ...(routedHostAccess ? ['routedHostAccess'] : []),
      ...(nativeGoalCommand ? ['nativeGoalCommand'] : []),
      ...(attachments === undefined ? [] : ['attachments']),
      ...(sessionInstructions === undefined ? [] : ['sessionInstructions']),
      ...(workspace === undefined ? [] : ['workspace']),
      ...(historySeed === undefined ? [] : ['historySeed'])])
      || (workspace !== undefined && (!fullAccess || typeof workspace !== 'string'
        || !isAbsolute(workspace) || workspace.includes('\0') || Buffer.byteLength(workspace) > 4096))
      || (historySeed !== undefined && (!fullAccess
        || (!exactQuote && ((!fromCodex && !closed(historySeed, ['turn', 'human', 'assistant']))
          || !Number.isSafeInteger(historySeed.turn) || historySeed.turn < 1
          || ![historySeed.human, historySeed.assistant].every(text => typeof text === 'string' && text.trim())))
        || Buffer.byteLength(JSON.stringify(historySeed)) > 12 * 1024))
      || (routedHostAccess && !routedHuman)
      || (routedHuman && first.humanOriginal)
      || (controllerSelected && !fullAccess)
      || (nativeGoalCommand && first.humanOriginal !== true)
      || (nativeGoalCommand && (typeof first.text !== 'string' || !/^\/goal(?: |$)/.test(first.text.trimEnd())))
      || first.schema !== VERSION || first.type !== 'start'
      || typeof first.humanOriginal !== 'boolean'
      || ![first.inputId, first.sessionId, first.freshNativeSessionId]
        .every(value => typeof value === 'string' && UUID.test(value))
      || first.freshNativeSessionId === first.sessionId
      || (first.resume !== null && !validResume(first.resume))
      || !Array.isArray(alternates) || alternates.length > 7 || !alternates.every(validResume)
      || (attachments !== undefined && (first.humanOriginal !== true || nativeGoalCommand
        || !Array.isArray(attachments) || attachments.length === 0 || attachments.length > 8
        || !attachments.every(file => closed(file, ['path', 'name', 'mime'])
          && typeof file.path === 'string' && isAbsolute(file.path) && file.path.length <= 4096
          && typeof file.name === 'string' && file.name.length <= 240
          && typeof file.mime === 'string' && file.mime.length <= 128)))
      || typeof first.text !== 'string' || (!first.text.trim() && attachments === undefined)
      || Buffer.byteLength(first.text) > 16 * 1024
      || (sessionInstructions !== undefined && (typeof sessionInstructions !== 'string'
        || Buffer.byteLength(sessionInstructions) > 16 * 1024))
      || !closed(first.body, Object.keys(profile.body))
      || !Object.keys(profile.body).every(key => first.body[key] === profile.body[key])) {
      throw new Error('Invalid foreground start');
    }
    const correlation = { schema: VERSION, inputId: first.inputId, sessionId: first.sessionId };
    const profileCwd = profile.cwd;
    async function directoryIdentity(directory) {
      const info = await stat(directory, { bigint: true });
      if (!info.isDirectory()) throw new Error('Selected Claude workspace is not a directory');
      return `${info.dev}:${info.ino}`;
    }
    let selectedDirectory;
    if (workspace !== undefined) {
      try {
        selectedDirectory = await directoryIdentity(workspace);
      } catch {
        await writeFrame(process.stdout, { ...correlation, type: 'outcome',
          outcome: { phase: 'not_submitted', reason: 'claude_workspace_unavailable' },
        }, stop.signal);
        return;
      }
      profile = { ...profile, cwd: workspace };
    }
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
    const [binding, skills, foundation, guidance, messaging] = await Promise.all([
      sharedDmkBinding(profile), sharedSkillInventory(profile.sharedSkillsDirectory), matrixFoundation(profile),
      bodyGuidance(profile, fullAccess), matrixMessaging(profile, fullAccess),
    ]);
    if (binding || skills.names.length) scratch = await mkdtemp(join(tmpdir(), 'daimon-claude-'));
    const sharedDmk = binding ? await sharedDmkServer(profile, binding, scratch) : undefined;
    const sharedSkills = skills.names.length
      ? await sharedSkillPlugin(profile.sharedSkillsDirectory, skills.names, scratch) : undefined;
    const hostTools = fullAccess ? [...(profile.hostTools ?? HOST_TOOLS)].sort() : [];
    if (hostTools.includes('Bash')) {
      // The API-key path needs subprocess credential isolation. The paired
      // subscription environment contains no provider credential variables.
      // On Linux the scrub option also confines Bash in a user namespace.
      if (!profile.subscriptionEmail) env.CLAUDE_CODE_SUBPROCESS_ENV_SCRUB = '1';
      if (profile.hostToolDirectory) env.PATH += `:${profile.hostToolDirectory}`;
    }
    let sharedDmkWriter;
    if (sharedDmk && hostTools.includes('Bash') && profile.hostToolDirectory) {
      const command = join(profile.hostToolDirectory, 'dmk');
      const executable = await access(command, constants.X_OK).then(() => true, () => false);
      if (executable) sharedDmkWriter = command;
    }
    const scopeInputs = [profile, binding ?? '', skillScopeRevision(profile, skills), foundation,
      hostTools, fullAccess, controllerSelected, sessionInstructions];
    const continuityScope = turnScope(...scopeInputs);
    const activeScope = messaging ? turnScope(...scopeInputs, messaging) : continuityScope;
    // Messaging is an owner-selected capability for this turn. Keep the same
    // paired history when it is added, and retain already indexed chat scopes.
    const previous = [first.resume, ...alternates].find(prior =>
      prior?.scope === continuityScope || prior?.scope === activeScope);
    const scope = previous?.scope ?? continuityScope;
    const resume = previous !== undefined;
    const nativeSessionId = previous?.sessionId ?? first.freshNativeSessionId;
    async function scopeStillActive() {
      let current = await ownerProfile(path);
      if (workspace !== undefined) {
        if (current.cwd !== profileCwd
          || await directoryIdentity(workspace).catch(() => undefined) !== selectedDirectory) return false;
        current = { ...current, cwd: workspace };
      }
      if (!Object.keys(expectedBody).every(key => current.body[key] === expectedBody[key])) return false;
      const [bytes, inventory, currentFoundation, currentGuidance, currentMessaging] = await Promise.all([
        sharedDmkBinding(current), sharedSkillInventory(current.sharedSkillsDirectory), matrixFoundation(current),
        bodyGuidance(current, fullAccess), matrixMessaging(current, fullAccess),
      ]);
      const currentTools = fullAccess ? [...(current.hostTools ?? HOST_TOOLS)].sort() : [];
      return current.bodyGuidanceFile === profile.bodyGuidanceFile && currentGuidance === guidance
        && inventory.revision === skills.revision
        && currentMessaging?.objectToolSchemas === messaging?.objectToolSchemas
        && turnScope(current, bytes ?? '', skillScopeRevision(current, inventory), currentFoundation, currentTools, fullAccess, controllerSelected, sessionInstructions, currentMessaging) === activeScope
        && (!currentFoundation || await probeFoundation(currentFoundation.server, expectedBody, current.cwd, stop.signal));
    }
    const broker = createMatrixStatusBroker({
      command: profile.matrixStatusCommand, expectedBody,
      createSdkMcpServer, tool, signal: stop.signal,
    });
    const pending = new Map();
    let nextCall = 0;
    let committed = false;
    let steeringSelected = false;
    let acceptingSteers = false;
    let steerClosed = false;
    let wakeSteering;
    const steers = [];
    const seenSteers = new Set();
    const steering = fullAccess ? {
      async *messages() {
        while (!steerClosed) {
          if (steers.length) yield steers.shift();
          else await new Promise(resolve => { wakeSteering = resolve; });
        }
      },
    } : undefined;
    const steerOptions = steering && {
      messages: steering.messages(),
      enabled: () => steeringSelected,
      admit: scopeStillActive,
      async ready() {
        acceptingSteers = true;
        await writeFrame(process.stdout, { ...correlation, type: 'steer_ready' }, stop.signal);
      },
      close() {
        if (steeringSelected) committed = false;
        acceptingSteers = false;
        steerClosed = true;
        wakeSteering?.();
      },
      async result(ids, text) {
        await writeFrame(process.stdout, { ...correlation, type: 'steer_result', ids, text }, stop.signal);
      },
    };
    async function receiveGatewayInput() {
      try {
        for await (const reply of input) {
          if (steeringSelected && reply.type === 'steer') {
            if (!closed(reply, ['schema', 'type', 'inputId', 'sessionId', 'id', 'text'])
              || reply.schema !== VERSION || reply.inputId !== first.inputId
              || reply.sessionId !== first.sessionId || typeof reply.id !== 'string'
              || !UUID.test(reply.id) || reply.id === first.inputId || seenSteers.has(reply.id)
              || typeof reply.text !== 'string' || !reply.text.trim()
              || Buffer.byteLength(reply.text) > 16 * 1024 || seenSteers.size >= 8) {
              throw new Error('Invalid steer input');
            }
            seenSteers.add(reply.id);
            if (acceptingSteers) {
              steers.push({ id: reply.id, text: reply.text });
              wakeSteering?.();
            }
            continue;
          }
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
      query, broker, expectedBody, toolNames: ['daimon_status'], signal: stop.signal, steering: steerOptions,
      input: { id: first.inputId, sessionId: nativeSessionId, text: first.text, attachments, resume, nativeGoalCommand,
        historySeed: (!resume || exactQuote || fromCodex) && !nativeGoalCommand ? historySeed : undefined },
      profile: {
        binary: profile.binary, cwd: profile.cwd, cliVersion: profile.cliVersion,
        model: profile.model, effort: profile.effort, subscriptionEmail: profile.subscriptionEmail,
        displayName: profile.displayName,
        sharedDmk, sharedDmkWriter, sharedSkills, matrixFoundation: foundation, matrixMessaging: messaging, hostTools, controller,
        fullAccess, routedHuman, bodyGuidance: guidance, sessionInstructions,
        persistSession: true,
        ...(profile.maxBudgetUsd === undefined ? {} : {
          maxBudgetUsd: profile.maxBudgetUsd,
          maxTurns: sharedDmk || sharedSkills || foundation || messaging || hostTools.length || controller ? 6 : 2,
        }),
        env,
      },
      async beforeSubmit(inputId, sessionId) {
        if (inputId !== first.inputId || sessionId !== nativeSessionId) return false;
        if (!await scopeStillActive()) return false;
        await writeFrame(process.stdout, { ...correlation, type: 'prepare_submission',
          nativeSessionId: sessionId, sessionScope: scope,
          ...(workspace === undefined ? {} : { workspace }),
          ...(steering ? { steering: true } : {}) }, stop.signal);
        const decision = (await input.next()).value;
        steeringSelected = !!steering && decision?.steering === true;
        if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed',
          ...(steeringSelected ? ['steering'] : [])])
          || decision.schema !== VERSION || decision.type !== 'submission_decision'
          || decision.inputId !== inputId || decision.sessionId !== first.sessionId
          || decision.committed !== true) return false;
        void receiveGatewayInput().catch(() => stop.abort());
        committed = await scopeStillActive();
        if (committed && fullAccess && profile.maxBudgetUsd === undefined) clearTimeout(timeout);
        return committed;
      },
    });
    if (outcome.reason === 'claude_resume_session_missing' && previous) {
      outcome.resumeUnavailable = previous;
    }
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
