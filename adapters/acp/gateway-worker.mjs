import { once } from 'node:events';
import { lstat, realpath } from 'node:fs/promises';
import { createConnection } from 'node:net';
import { isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { observeMatrixBody, readDmkObservation, validObservationCommand } from '../owner-observation.mjs';
import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';
import { CONTROLLER, callController, controllerBridge, controllerCallKey, controllerError } from './controller-bridge.mjs';
import { runAntigravityTurn } from './antigravity-turn.mjs';
import { runGooseTurn } from './goose-turn.mjs';
import { retainedImages } from './images.mjs';
import { sharedSkill } from './shared-skills.mjs';
import { validateSessionId } from './turn.mjs';
import { recallProperties, sharedMemory, validSharedMemory } from './shared-memory.mjs';

const GOOSE_SCHEMA = 'daimon-gateway.goose-turn/v1';
const AGY_SCHEMA = 'daimon-gateway.antigravity-turn/v2';
const STATUS = 'daimon_status';
const MEMORY = 'dmk_read_selected';
const SKILL = 'shared_skill';
const RECALL = 'dmk_recall';
const BINDING = ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'];

function validMemory(value) {
  return closed(value, ['command', 'inputId', 'pool', 'recordUid', 'revision', 'bodyRef'])
    && validObservationCommand(value.command)
    && typeof value.inputId === 'string' && UUID.test(value.inputId)
    && typeof value.pool === 'string' && /^[a-z][a-z0-9_-]{0,39}$/.test(value.pool)
    && typeof value.recordUid === 'string' && UUID.test(value.recordUid)
    && Number.isSafeInteger(value.revision) && value.revision > 0
    && typeof value.bodyRef === 'string' && value.bodyRef.length > 0 && value.bodyRef.length <= 240;
}

function validBinding(profile) {
  return closed(profile.body, BINDING)
    && BINDING.every(key => typeof profile.body[key] === 'string'
      && profile.body[key].length > 0 && profile.body[key].length <= 240)
    && validObservationCommand(profile.matrixStatusCommand)
    && (profile.sharedSkillsDirectory === undefined || (typeof profile.sharedSkillsDirectory === 'string'
      && isAbsolute(profile.sharedSkillsDirectory)))
    && (profile.selectedMemory === undefined || validMemory(profile.selectedMemory))
    && (profile.sharedMemory === undefined || validSharedMemory(profile.sharedMemory));
}

function observe(profile, signal) {
  return observeMatrixBody(profile.matrixStatusCommand, profile.body, signal);
}

async function readSelectedMemory(binding, signal) {
  const memory = binding.selectedMemory;
  await observe(binding, signal);
  const payload = await readDmkObservation(memory.command, {
    action: 'read', pool: memory.pool, record_uid: memory.recordUid, expected_revision: memory.revision,
    offset: 0,
  }, signal);
  const page = payload?.pools?.[0];
  const result = page?.result;
  if (payload?.being_ref !== binding.body.beingRef || payload.body_ref !== memory.bodyRef
      || !Array.isArray(payload.pools) || payload.pools.length !== 1 || page.pool !== memory.pool
      || result?.status !== 'ok' || result.record?.record_uid !== memory.recordUid
      || result.record.revision !== memory.revision || result.complete !== true
      || result.raw_offset !== 0 || result.next_offset !== null || typeof result.raw !== 'string'
      || Buffer.byteLength(result.raw) > 8192) {
    throw new Error('Selected DMK record unavailable');
  }
  return { pool: memory.pool, record_uid: memory.recordUid, revision: memory.revision, text: result.raw,
    ...(typeof result.authority_note === 'string' ? { authority_note: result.authority_note } : {}),
  };
}

function toolDefinition(name, description, properties = {}) {
  return { name, description, annotations: { readOnlyHint: true },
    inputSchema: { type: 'object', properties, additionalProperties: false },
  };
}

async function serveMcp(binding) {
  if (!validBinding(binding)) throw new Error('Invalid MCP binding');
  for await (const request of frames(process.stdin)) {
    if (!Object.hasOwn(request, 'id')) continue;
    const response = { jsonrpc: '2.0', id: request.id };
    const params = request.params;
    switch (request.method) {
      case 'initialize':
        response.result = {
          protocolVersion: params?.protocolVersion, capabilities: { tools: {} },
          serverInfo: { name: 'matrix-status', version: '1' },
        };
        break;
      case 'tools/list':
        response.result = { tools: [
          ...(binding.controller ? [{
            name: CONTROLLER,
            description: 'Coordinate with owned conversations. Start with capabilities and use coordination_inputs to select the current original.',
            inputSchema: {
              type: 'object', required: ['operation', 'arguments'], additionalProperties: false,
              properties: { operation: { type: 'string' }, arguments: { type: 'object' } },
            },
          }] : []),
          toolDefinition(STATUS, 'Read authenticated metadata for this Matrix body.'),
          ...(binding.selectedMemory ? [toolDefinition(MEMORY, 'Read the one memory selected by the owner.')] : []),
          ...(binding.sharedMemory ? [toolDefinition(RECALL,
            'Search or read the receiving being’s DMK. After search, pass the selected record_uid and pool to this same tool with action read.',
            recallProperties)] : []),
          ...(binding.sharedSkillsDirectory ? [toolDefinition(SKILL,
            'List installed shared skills or read the current instructions for one installed skill.',
            { name: { type: 'string', maxLength: 80 } })] : []),
        ] };
        break;
      case 'tools/call':
        if (params?.name === CONTROLLER && binding.controller) {
          try {
            const args = { ...params.arguments };
            delete args.toolSummary;
            await observe(binding, AbortSignal.timeout(8000));
            response.result = await callController(binding.controller, args, AbortSignal.timeout(40_000));
          } catch {
            response.result = controllerError('Current receiving body unavailable.');
          }
          break;
        }
        if (params?.name === RECALL && binding.sharedMemory) {
          try {
            const signal = AbortSignal.timeout(8000);
            await observe(binding, signal);
            // agy may attach an explanation for its permission prompt.
            const args = { ...params.arguments };
            delete args.toolSummary;
            const value = await sharedMemory(binding, args, signal);
            response.result = { content: [{ type: 'text', text: JSON.stringify(value) }] };
          } catch {
            response.result = { isError: true, content: [{ type: 'text', text: 'Shared memory unavailable for this request.' }] };
          }
          break;
        }
        if (params?.name === SKILL && binding.sharedSkillsDirectory) {
          try {
            const args = params.arguments ?? {};
            const name = args.name;
            if (!(closed(args, []) || (closed(args, ['name']) && typeof name === 'string'))) {
              throw new Error('Invalid skill selector');
            }
            await observe(binding, AbortSignal.timeout(8000));
            const value = await sharedSkill(binding.sharedSkillsDirectory, name);
            response.result = { content: [{ type: 'text', text: JSON.stringify(value) }] };
          } catch {
            response.result = { isError: true, content: [{ type: 'text', text: 'Selected skill unavailable.' }] };
          }
          break;
        }
        if ((params?.name === STATUS || (params?.name === MEMORY && binding.selectedMemory))
            && (params.arguments === undefined || closed(params.arguments, []))) {
          try {
            const signal = AbortSignal.timeout(8_000);
            const value = params.name === STATUS
              ? await observe(binding, signal) : await readSelectedMemory(binding, signal);
            response.result = { content: [{ type: 'text', text: JSON.stringify(value) }] };
          } catch {
            response.result = { isError: true, content: [{ type: 'text', text: 'Selected observation unavailable.' }] };
          }
          break;
        }
        // An unselected tool shares the generic method rejection.
      default:
        response.error = { code: -32601, message: 'Operation unavailable' };
    }
    await writeFrame(process.stdout, response);
  }
}

async function gooseEnvironment(profile) {
  const state = await lstat(profile.stateRoot);
  if (!state.isDirectory() || state.uid !== process.getuid() || (state.mode & 0o077)) {
    throw new Error('Private Goose state directory required');
  }
  const key = (await privateBytes(profile.providerKeyFile, 4096)).toString('utf8').trim();
  if (!/^[!-~]+$/.test(key)) throw new Error('Invalid provider credential');
  return {
    HOME: profile.stateRoot, PATH: '/usr/bin:/bin',
    XDG_CONFIG_HOME: join(profile.stateRoot, 'config'), XDG_DATA_HOME: join(profile.stateRoot, 'data'),
    XDG_STATE_HOME: join(profile.stateRoot, 'state'), XDG_CACHE_HOME: join(profile.stateRoot, 'cache'),
    GOOSE_PROVIDER: profile.provider, GOOSE_MODEL: profile.model, GOOSE_MAX_TURNS: '2',
    [profile.provider === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY']: key,
    ...(profile.providerPort ? { OPENAI_HOST: `http://127.0.0.1:${profile.providerPort}` } : {}),
  };
}

async function main(path) {
  const stop = new AbortController();
  const deadline = setTimeout(() => stop.abort(), 125_000);
  stop.signal.addEventListener('abort', () => process.stdin.destroy(), { once: true });
  const pipe = frames(process.stdin);
  let bridge;
  try {
    const profile = JSON.parse(await privateBytes(path, 16 * 1024));
    const agy = profile?.adapter === 'agy';
    const schema = agy ? AGY_SCHEMA : GOOSE_SCHEMA;
    const fields = ['binary', 'cwd', 'model', 'matrixStatusCommand', 'body',
      ...(agy ? ['adapter', 'home', 'effort'] : ['stateRoot', 'provider', 'providerKeyFile'])];
    const absolute = value => typeof value === 'string' && isAbsolute(value);
    if (agy && (!absolute(profile.home) || typeof profile.effort !== 'string' || !profile.effort)) {
      throw new Error('Invalid Antigravity owner profile');
    }
    if (agy && Object.hasOwn(profile, 'bodyGuidanceFile')) {
      fields.push('bodyGuidanceFile');
      if (!absolute(profile.bodyGuidanceFile)) throw new Error('Invalid Antigravity guidance path');
    }
    if (agy && Object.hasOwn(profile, 'sharedSkillsDirectory')) fields.push('sharedSkillsDirectory');
    if (agy && Object.hasOwn(profile, 'sharedMemory')) fields.push('sharedMemory');
    if (profile && Object.hasOwn(profile, 'selectedMemory')) fields.push('selectedMemory');
    if (profile && Object.hasOwn(profile, 'providerPort')) fields.push('providerPort');
    if (!closed(profile, fields) || !validBinding(profile)
        || ![profile.binary, profile.cwd].every(absolute)
        || (!agy && (![profile.stateRoot, profile.providerKeyFile].every(absolute)
          || !['openai', 'anthropic'].includes(profile.provider)))
        || (fields.includes('providerPort') && (profile.provider !== 'openai'
          || !Number.isInteger(profile.providerPort) || profile.providerPort < 1 || profile.providerPort > 65535))
        || typeof profile.model !== 'string' || !profile.model || profile.model.length > 128) {
      throw new Error('Invalid ACP owner profile');
    }
    const first = (await pipe.next()).value;
    const topic = agy || Object.hasOwn(first ?? {}, 'workspace');
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'text', 'body',
      ...(topic ? ['workspace', 'resumeNativeSessionId', ...(!agy ? ['storeId'] : [])] : []),
      ...(agy && Object.hasOwn(first ?? {}, 'attachments') ? ['attachments'] : []),
      ...(agy && first?.controller === true ? ['controller'] : [])])
        || first.schema !== schema || first.type !== 'start'
        || typeof first.inputId !== 'string' || typeof first.sessionId !== 'string'
        || !UUID.test(first.inputId) || !UUID.test(first.sessionId)
        || !closed(first.body, BINDING) || !BINDING.every(key => first.body[key] === profile.body[key])) {
      throw new Error('Invalid ACP foreground start');
    }
    if (topic) {
      if (first.workspace !== profile.cwd || await realpath(profile.cwd) !== profile.cwd) {
        throw new Error('ACP workspace differs from the owner selection');
      }
      if (!agy) {
        if (typeof first.storeId !== 'string' || !UUID.test(first.storeId)
            || await realpath(profile.stateRoot) !== profile.stateRoot
            || (await privateBytes(join(profile.stateRoot, 'goose-topic-store-id'), 64)).toString('utf8').trim() !== first.storeId) {
          throw new Error('Goose session store differs from the owner selection');
        }
        if (profile.selectedMemory?.inputId === first.inputId) {
          throw new Error('One-original memory is unavailable in a resumable Goose history');
        }
      }
      if (first.resumeNativeSessionId !== null) {
        const selected = validateSessionId(first.resumeNativeSessionId);
        if (agy && !UUID.test(selected)) throw new Error('Invalid Antigravity session ID');
      }
    }
    const correlation = { schema, inputId: first.inputId, sessionId: first.sessionId };
    const env = agy ? { HOME: profile.home, PATH: '/usr/bin:/bin' } : await gooseEnvironment(profile);
    const selectedMemory = profile.selectedMemory?.inputId === first.inputId ? profile.selectedMemory : undefined;
    const { sharedSkillsDirectory } = profile;
    const binding = { body: profile.body, matrixStatusCommand: profile.matrixStatusCommand,
      selectedMemory, sharedSkillsDirectory, sharedMemory: profile.sharedMemory };
    if (first.controller === true) {
      bridge = await controllerBridge(correlation, process.stdout, stop);
      binding.controller = bridge.access;
    }
    let instructions;
    if (agy && profile.bodyGuidanceFile) {
      const document = new TextDecoder('utf-8', { fatal: true })
        .decode(await privateBytes(profile.bodyGuidanceFile, 6 * 1024)).trim();
      if (!document || document.includes('\0')) throw new Error('Invalid Antigravity receiving guidance');
      instructions = '[Receiving body instructions from your signed Gateway profile]\n' + document
        + (profile.sharedMemory ? '\nUse dmk_recall when past experience or decisions matter.' : '')
        + (sharedSkillsDirectory ? '\nFor any installed skill or SKILL.md path mentioned in the body instructions, load it with the MCP tool shared_skill using the skill name. Use that tool for skills instead of read_file, shell commands or absolute paths.' : '')
        + (bridge ? '\nFor an owned conversation request, use the MCP interaction_controller. If you need the gateway coordination skill, call shared_skill with name daimon-gateway. Then call interaction_controller with operation capabilities and arguments {} to discover current routing.' : '')
        + '\nThe following content block is the current original.';
    }
    let images;
    if (agy && first.attachments !== undefined) {
      try {
        images = await retainedImages(first.attachments);
      } catch {
        await writeFrame(process.stdout, { ...correlation, type: 'outcome',
          outcome: { phase: 'not_submitted', reason: 'antigravity_attachment_unavailable' } }, stop.signal);
        return;
      }
    }
    const interrupt = new AbortController();
    let providerUnavailable = false;
    let reportAcceptance = false;
    let receipt;
    const controllerGrants = new Map();
    function accept(nativeSessionId) {
      if (!reportAcceptance) return;
      receipt ??= writeFrame(process.stdout, { ...correlation, type: 'input_accepted', nativeSessionId }, stop.signal);
      return receipt;
    }
    const run = agy ? runAntigravityTurn : runGooseTurn;
    const outcome = await run({
      binary: profile.binary, cwd: profile.cwd, env, signal: stop.signal,
      nativeSessionId: first.resumeNativeSessionId ?? undefined,
      interruptSignal: topic ? interrupt.signal : undefined,
      ...(agy ? { model: profile.model, effort: profile.effort,
        instructions, images,
        onInputAccepted: accept,
        async onToolPermission(nativeSessionId, toolCall) {
          if (toolCall.name !== 'mcp_matrix_' + CONTROLLER) return true;
          const key = controllerCallKey(toolCall.rawInput);
          if (!bridge || !reportAcceptance || !key || controllerGrants.size >= 8) return false;
          await accept(nativeSessionId);
          controllerGrants.set(key, (controllerGrants.get(key) ?? 0) + 1);
          return true;
        },
        allowedTools: ['mcp_matrix_' + STATUS, ...(bridge ? ['mcp_matrix_' + CONTROLLER] : []), ...(selectedMemory ? ['mcp_matrix_' + MEMORY] : []),
          ...(sharedSkillsDirectory ? ['mcp_matrix_' + SKILL] : []),
          ...(profile.sharedMemory ? ['mcp_matrix_' + RECALL] : [])],
      } : {}),
      mcpServers: [{ name: 'matrix', command: process.execPath,
        args: [fileURLToPath(import.meta.url), '--matrix-mcp'],
        env: [{ name: 'DAIMON_OBSERVATION', value: JSON.stringify(binding) }],
      }],
      toolNames: ['matrix__' + STATUS, ...(selectedMemory ? ['matrix__' + MEMORY] : [])], text: first.text,
      async beforeSubmit(nativeSessionId) {
        if ((agy && !UUID.test(nativeSessionId))
            || (first.resumeNativeSessionId && first.resumeNativeSessionId !== nativeSessionId)) return false;
        await observe(binding, stop.signal);
        if (profile.providerPort) {
          const socket = createConnection({ host: '127.0.0.1', port: profile.providerPort });
          try {
            await once(socket, 'connect', {
              signal: AbortSignal.any([stop.signal, AbortSignal.timeout(1000)]),
            });
          } catch {
            stop.signal.throwIfAborted();
            providerUnavailable = true;
            return false;
          } finally {
            socket.destroy();
          }
        }
        await writeFrame(process.stdout, { ...correlation, type: 'prepare_submission', nativeSessionId,
          ...(topic ? { workspace: profile.cwd, ...(!agy ? { storeId: first.storeId } : {}) } : {}),
          ...(agy ? { inputAcceptance: true, workAcceptance: true } : {}),
          ...(topic ? { targetedInterrupt: true } : {}) }, stop.signal);
        const decision = (await pipe.next()).value;
        const extensions = ['observeAcceptance', 'requireWork'].filter(field => agy && decision?.[field] === true);
        if (topic && decision?.targetedInterrupt === true) extensions.push('targetedInterrupt');
        if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed', ...extensions])
            || (decision.requireWork === true && decision.observeAcceptance !== true)
            || decision.schema !== schema || decision.type !== 'submission_decision'
            || decision.inputId !== first.inputId || decision.sessionId !== first.sessionId
            || decision.committed !== true) return false;
        reportAcceptance = decision.observeAcceptance === true;
        async function* commands() {
          for await (const command of pipe) {
            if (decision.targetedInterrupt === true && command.type === 'interrupt'
                && closed(command, ['schema', 'type', 'inputId', 'sessionId'])
                && command.schema === schema && command.inputId === first.inputId
                && command.sessionId === first.sessionId) {
              interrupt.abort();
              bridge?.interrupt();
              continue;
            }
            yield command;
          }
        }
        const pendingCommands = commands();
        if (bridge) {
          void bridge.serve(pendingCommands, nativeSessionId, key => {
            const count = controllerGrants.get(key);
            if (!count) return false;
            if (count === 1) controllerGrants.delete(key);
            else controllerGrants.set(key, count - 1);
            return true;
          }).catch(() => stop.abort());
        } else {
          void pendingCommands.next().then(() => stop.abort(), () => stop.abort());
        }
        return true;
      },
    });
    if (providerUnavailable && outcome.phase === 'not_submitted') {
      outcome.reason = 'goose_provider_unavailable';
    }
    await writeFrame(process.stdout, { ...correlation, type: 'outcome', outcome }, stop.signal);
  } finally {
    clearTimeout(deadline);
    process.stdin.destroy();
    await bridge?.close();
  }
}

try {
  const [flag, path, ...rest] = process.argv.slice(2);
  if (flag === '--profile' && path && !rest.length) await main(path);
  else if (flag === '--matrix-mcp' && !path) await serveMcp(JSON.parse(process.env.DAIMON_OBSERVATION));
  else throw new Error('Explicit worker mode required');
} catch {
  process.exitCode = 1;
}
