import { lstat, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';
import { runQwenTurn } from './qwen-turn.mjs';

const SCHEMA = 'daimon-gateway.qwen-turn/v1';
const BODY = ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'];
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
  if (!closed(profile, ['body', 'binary', 'cwd', 'stateRoot', 'model', 'providerKeyFile'])
      || ![profile.binary, profile.cwd, profile.stateRoot, profile.providerKeyFile].every(isAbsolute)
      || !/^[a-z0-9][a-z0-9._-]{0,127}$/.test(profile.model)
      || !closed(profile.body, BODY)
      || !BODY.every(key => typeof profile.body[key] === 'string' && profile.body[key].length > 0)) {
    throw new Error('Invalid Qwen owner profile');
  }
  const state = await lstat(profile.stateRoot);
  if (!state.isDirectory() || state.uid !== process.getuid() || (state.mode & 0o077)) {
    throw new Error('Private Qwen state directory required');
  }

  const pipe = frames(process.stdin);
  const stop = new AbortController();
  try {
    const first = (await pipe.next()).value;
    if (!closed(first, ['schema', 'type', 'inputId', 'sessionId', 'text', 'body', 'workspace', 'resume'])
        || first.schema !== SCHEMA || first.type !== 'start'
        || !UUID.test(first.inputId) || !UUID.test(first.sessionId)
        || first.workspace !== profile.cwd
        || (first.resume !== null && typeof first.resume !== 'string')
        || !closed(first.body, BODY) || !BODY.every(key => first.body[key] === profile.body[key])) {
      throw new Error('Invalid Qwen foreground start');
    }
    const correlation = { schema: SCHEMA, inputId: first.inputId, sessionId: first.sessionId };
    await requireCleanProviderSettings(await realpath(profile.cwd), await realpath(profile.stateRoot));
    if (!(await lstat(SETTINGS)).isFile()) throw new Error('Qwen pilot settings required');
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
    const outcome = await runQwenTurn({
      binary: profile.binary, cwd: profile.cwd, env, signal: stop.signal,
      mcpServers: [], nativeSessionId: first.resume ?? undefined, freshSessionId: first.sessionId,
      model: profile.model, text: first.text,
      async beforeSubmit(nativeSessionId) {
        await writeFrame(process.stdout, {
          ...correlation, type: 'prepare_submission', nativeSessionId, workspace: first.workspace,
        }, stop.signal);
        const decision = (await pipe.next()).value;
        if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed'])
            || !Object.entries(correlation).every(([name, value]) => decision[name] === value)
            || decision.type !== 'submission_decision' || decision.committed !== true) return false;
        void pipe.next().then(() => stop.abort(), () => stop.abort());
        return true;
      },
    });
    await writeFrame(process.stdout, { ...correlation, type: 'outcome', outcome }, stop.signal);
  } finally {
    process.stdin.destroy();
  }
}

try {
  const [flag, profile, ...extra] = process.argv.slice(2);
  if (flag !== '--profile' || !profile || extra.length) throw new Error('Qwen owner profile required');
  await run(profile);
} catch {
  process.exitCode = 1;
}
