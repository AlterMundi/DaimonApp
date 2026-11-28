import { lstat, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { closed, privateBytes } from '../worker-pipes.mjs';
import { observeMatrixBody, validObservationCommand } from '../owner-observation.mjs';
import { BODY, readBodyGuidance, runBoundedWorker } from './bounded-worker.mjs';
import { runQwenTurn } from './qwen-turn.mjs';

const SCHEMA = 'daimon-gateway.qwen-turn/v1';
const SETTINGS = fileURLToPath(new URL('./qwen-pilot-settings.json', import.meta.url));
const TOKEN_PLAN = 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1';

async function requireCleanProviderSettings(cwd, home) {
  // In this pinned release, the model registry can override endpoint env vars.
  const paths = [
    join(cwd, '.qwen', 'settings.json'),
    join(home, '.qwen', 'settings.json'),
    join(home, '.qwen', '.env'),
    join(home, '.env'),
  ];
  for (let path = cwd; ; path = dirname(path)) {
    paths.push(join(path, '.qwen', '.env'), join(path, '.env'));
    if (dirname(path) === path) break;
  }
  await Promise.all(Array.from(new Set(paths), async path => {
    try {
      await lstat(path);
    } catch (error) {
      if (error.code === 'ENOENT') return;
      throw error;
    }
    throw new Error('Qwen pilot requires an isolated provider configuration');
  }));
}

async function run(path) {
  const profile = JSON.parse(await privateBytes(path, 32 * 1024));
  if (!closed(profile, ['body', 'binary', 'cwd', 'stateRoot', 'model', 'providerKeyFile',
    'bodyGuidanceFile', 'matrixStatusCommand'])
      || ![profile.binary, profile.cwd, profile.stateRoot, profile.providerKeyFile,
        profile.bodyGuidanceFile].every(value => typeof value === 'string' && isAbsolute(value))
      || !validObservationCommand(profile.matrixStatusCommand)
      || !/^[a-z0-9][a-z0-9._-]{0,127}$/.test(profile.model)
      || !closed(profile.body, BODY)
      || !BODY.every(key => typeof profile.body[key] === 'string' && profile.body[key].length > 0)) {
    throw new Error('Invalid Qwen owner profile');
  }
  const state = await lstat(profile.stateRoot);
  if (!state.isDirectory() || state.uid !== process.getuid() || (state.mode & 0o077)) {
    throw new Error('Private Qwen state directory required');
  }

  await runBoundedWorker(SCHEMA, profile, async (input, signal, beforeSubmit) => {
    await requireCleanProviderSettings(await realpath(profile.cwd), await realpath(profile.stateRoot));
    if (!(await lstat(SETTINGS)).isFile()) throw new Error('Qwen pilot settings required');
    const document = await readBodyGuidance(profile.bodyGuidanceFile);
    await observeMatrixBody(profile.matrixStatusCommand, profile.body, signal);
    const credential = (await privateBytes(profile.providerKeyFile, 4096)).toString('utf8').trim();
    if (!/^[!-~]+$/.test(credential)) throw new Error('Invalid Qwen subscription credential');
    const env = {
      HOME: profile.stateRoot,
      XDG_CONFIG_HOME: join(profile.stateRoot, 'config'),
      XDG_CACHE_HOME: join(profile.stateRoot, 'cache'),
      PATH: `${dirname(process.execPath)}:/usr/bin:/bin`,
      LANG: 'C.UTF-8',
      QWEN_CODE_SYSTEM_SETTINGS_PATH: SETTINGS,
      QWEN_CODE_SYSTEM_DEFAULTS_PATH: SETTINGS,
      OPENAI_API_KEY: credential,
      OPENAI_BASE_URL: TOKEN_PLAN,
      OPENAI_MODEL: profile.model,
    };
    return runQwenTurn({
      binary: profile.binary, cwd: profile.cwd, env, signal,
      mcpServers: [], nativeSessionId: input.resume ?? undefined, freshSessionId: input.sessionId,
      model: profile.model, text: input.text,
      instructions: '[Receiving body instructions from your signed Gateway profile]\n'
        + document + '\nThe following content block is the current original.',
      beforeSubmit,
    });
  });
}

try {
  const [flag, profile, ...extra] = process.argv.slice(2);
  if (flag !== '--profile' || !profile || extra.length) throw new Error('Qwen owner profile required');
  await run(profile);
} catch {
  process.exitCode = 1;
}
