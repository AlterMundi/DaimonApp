// One foreground turn on a Gateway-owned pair of pipes.
import { once } from 'node:events';
import { execFile } from 'node:child_process';
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

import { createMatrixStatusBroker } from './matrix-broker.mjs';
import { runClaudeTurn } from './turn.mjs';

const MAX_FRAME = 128 * 1024;
const MAX_OUTCOME_FRAME = 512 * 1024;
const VERSION = 'daimon-gateway.claude-turn/v1';
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const exec = promisify(execFile);

function closed(value, fields) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === fields.length
    && fields.every(field => Object.hasOwn(value, field));
}

async function* frames(stream) {
  let pending = Buffer.alloc(0);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  for await (const bytes of stream) {
    let start = 0;
    while (start < bytes.length) {
      const end = bytes.indexOf(10, start);
      const part = bytes.subarray(start, end < 0 ? bytes.length : end);
      if (pending.length + part.length > MAX_FRAME) throw new Error('Frame exceeds bound');
      pending = Buffer.concat([pending, part]);
      if (end < 0) break;
      yield JSON.parse(decoder.decode(pending));
      pending = Buffer.alloc(0);
      start = end + 1;
    }
  }
  if (pending.length) throw new Error('Unterminated frame');
}

async function writeFrame(stream, value, signal) {
  const data = Buffer.from(JSON.stringify(value) + '\n');
  if (data.length > MAX_OUTCOME_FRAME + 1) throw new Error('Frame exceeds bound');
  if (!stream.write(data)) await once(stream, 'drain', { signal });
}

async function privateBytes(path, limit) {
  if (typeof path !== 'string' || !isAbsolute(path)) throw new Error('Owner profile required');
  const fd = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await fd.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) || info.nlink !== 1) {
      throw new Error('Owner profile must be private');
    }
    const buffer = Buffer.alloc(limit + 1);
    let size = 0;
    while (size < buffer.length) {
      const { bytesRead } = await fd.read(buffer, size, buffer.length - size);
      if (bytesRead === 0) break;
      size += bytesRead;
    }
    if (size === buffer.length) throw new Error('Owner profile exceeds bound');
    return buffer.subarray(0, size);
  } finally {
    await fd.close();
  }
}

async function ownerProfile(path) {
  const value = JSON.parse(await privateBytes(path, 16 * 1024));
  if (!closed(value, ['sdk', 'binary', 'cwd', 'home', 'configurationDirectory',
      'cliVersion', 'model', 'apiKeyFile', 'maxBudgetUsd', 'matrixStatusCommand', 'body'])
      || !closed(value.body, ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'])
      || ![value.sdk, value.binary, value.cwd, value.home, value.configurationDirectory, value.apiKeyFile]
        .every(item => typeof item === 'string' && isAbsolute(item))
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

async function providerEnvironment(profile, signal) {
  const key = (await privateBytes(profile.apiKeyFile, 4096)).toString('utf8').trim();
  if (!/^[!-~]+$/.test(key)) throw new Error('Invalid provider credential');
  const env = {
    PATH: '/usr/bin:/bin', HOME: profile.home, CLAUDE_CONFIG_DIR: profile.configurationDirectory,
    ANTHROPIC_API_KEY: key, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
  };
  const { stdout } = await exec(profile.binary, ['auth', 'status'], {
    cwd: profile.cwd, env, signal, timeout: 5000, maxBuffer: 8192,
  });
  const auth = JSON.parse(stdout);
  if (auth.loggedIn !== true || auth.authMethod !== 'api_key'
    || auth.apiKeySource !== 'ANTHROPIC_API_KEY' || auth.apiProvider !== 'firstParty') {
    throw new Error('Selected API authentication unavailable');
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
  try {
    const profile = await ownerProfile(path);
    const first = (await input.next()).value;
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'text', 'body'])
      || first.schema !== VERSION || first.type !== 'start'
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
        outcome: { phase: 'not_submitted', reason: 'claude_api_auth_unverified' },
      }, stop.signal);
      return;
    }
    const { query, createSdkMcpServer, tool } = await import(pathToFileURL(profile.sdk));
    const expectedBody = profile.body;
    const broker = createMatrixStatusBroker({
      command: profile.matrixStatusCommand, source: {
        being_ref: expectedBody.beingRef, embodiment_id: expectedBody.embodimentId,
      }, createSdkMcpServer, tool, signal: stop.signal,
    });
    const outcome = await runClaudeTurn({
      query, broker, expectedBody, toolNames: ['daimon_status'], signal: stop.signal,
      input: { id: first.inputId, sessionId: first.sessionId, text: first.text },
      profile: {
        binary: profile.binary, cwd: profile.cwd, cliVersion: profile.cliVersion,
        model: profile.model, persistSession: true, maxTurns: 2,
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
  }
}

main().catch(() => {
  // The owner correlates a worker abort against its own durable decision.
  // Provider diagnostics and input bytes stay outside this protocol.
  process.exitCode = 1;
});
