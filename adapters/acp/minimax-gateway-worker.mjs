import { execFile } from 'node:child_process';
import { lstat, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, join } from 'node:path';
import { promisify } from 'node:util';

import { observeMatrixBody, validObservationCommand } from '../owner-observation.mjs';
import { closed, privateBytes } from '../worker-pipes.mjs';
import { BODY, readBodyGuidance, runBoundedWorker } from './bounded-worker.mjs';
import { runMiniMaxTurn } from './minimax-turn.mjs';

const SCHEMA = 'daimon-gateway.minimax-turn/v1';
const exec = promisify(execFile);

async function requireSelectedAccount(profile, env, signal) {
  const { stdout } = await exec(profile.binary, ['provider', 'list', '--json'], {
    cwd: profile.cwd, env, signal, timeout: 12_000, maxBuffer: 32 * 1024,
  });
  const selected = JSON.parse(stdout);
  const active = selected.providers?.filter(provider => provider.active);
  if (selected.minimaxModelSource !== 'token_plan'
      || !Array.isArray(active) || active.length !== 1 || active[0].kind !== 'minimax-oauth') {
    throw new Error('MiniMax Global Token Plan account required');
  }
}

async function run(path) {
  const profile = JSON.parse(await privateBytes(path, 32 * 1024));
  if (!closed(profile, ['body', 'binary', 'cwd', 'stateRoot', 'bodyGuidanceFile', 'matrixStatusCommand'])
      || ![profile.binary, profile.cwd, profile.stateRoot, profile.bodyGuidanceFile]
        .every(value => typeof value === 'string' && isAbsolute(value))
      || !validObservationCommand(profile.matrixStatusCommand) || !closed(profile.body, BODY)
      || !BODY.every(key => typeof profile.body[key] === 'string' && profile.body[key].length > 0)) {
    throw new Error('Invalid MiniMax owner profile');
  }
  const state = await lstat(profile.stateRoot);
  if (!state.isDirectory() || state.uid !== process.getuid() || (state.mode & 0o077)
      || await realpath(profile.stateRoot) !== profile.stateRoot
      || await realpath(profile.cwd) !== profile.cwd) {
    throw new Error('Invalid MiniMax state directory or workspace');
  }
  await runBoundedWorker(SCHEMA, profile, async (input, signal, beforeSubmit) => {
    const env = {
      HOME: profile.stateRoot,
      MINIMAX_DATA_DIR: join(profile.stateRoot, '.minimax'),
      PATH: `${dirname(process.execPath)}:/usr/bin:/bin`,
      LANG: 'C.UTF-8',
    };
    await readBodyGuidance(profile.bodyGuidanceFile);
    await observeMatrixBody(profile.matrixStatusCommand, profile.body, signal);
    await requireSelectedAccount(profile, env, signal);
    return runMiniMaxTurn({
      binary: profile.binary, cwd: profile.cwd, env, signal, beforeSubmit,
      nativeSessionId: input.resume ?? undefined, text: input.text,
      guidanceFile: profile.bodyGuidanceFile, mcpServers: [],
    });
  });
}

try {
  const [flag, profile, ...extra] = process.argv.slice(2);
  if (flag !== '--profile' || !profile || extra.length) throw new Error('MiniMax owner profile required');
  await run(profile);
} catch {
  process.exitCode = 1;
}
