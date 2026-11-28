// One explicit foreground turn over Goose ACP v1.
import { runAcpTurn, validateSessionId } from './turn.mjs';

const PREFIX = '_goose/unstable/';

function isSelectedCatalog(catalog, expected) {
  if (!Array.isArray(catalog?.tools)) return false;
  const names = catalog.tools.map(tool => tool?.name);
  if (names.length !== expected.length || names.some(name => typeof name !== 'string')) return false;
  return [...names].sort().every((name, index) => name === expected[index]);
}

export async function runGooseTurn({
  binary, cwd, env, mcpServers, toolNames, text, beforeSubmit, signal, nativeSessionId, interruptSignal,
}) {
  if (!Array.isArray(toolNames) || !toolNames.length
      || toolNames.some(name => typeof name !== 'string' || !name)
      || new Set(toolNames).size !== toolNames.length) {
    throw new TypeError('Invalid Goose foreground input');
  }
  const expected = [...toolNames].sort();
  return runAcpTurn({
    binary, args: [], cwd, text, beforeSubmit, signal, interruptSignal,
    env: {
      ...env, GOOSE_DISABLE_SESSION_NAMING: 'true',
      GOOSE_DISABLE_SKILLS: 'true', GOOSE_SLASH_COMMANDS_ENABLED: 'false',
    },
    unavailable: 'goose_unavailable',
    openFailure: 'goose_catalog_unverified',
    async openSession(request, initialized) {
      if (initialized.agentCapabilities?._meta?.goose?.nativeSkills?.enabled !== false) {
        throw new Error('The ACP process did not verify that native skills are disabled');
      }
      const configured = await request(PREFIX + 'config/extensions/list', {});
      if (!Array.isArray(configured?.extensions)) throw new Error('Goose extensions unavailable');
      if (configured.extensions.some(entry => entry?.enabled !== false)) {
        throw new Error('Unexpected configured Goose extension');
      }
      let sessionId;
      if (nativeSessionId === undefined) {
        const started = await request('session/new', { cwd, mcpServers });
        sessionId = validateSessionId(started?.sessionId);
      } else {
        sessionId = validateSessionId(nativeSessionId);
        if (initialized.agentCapabilities?.loadSession !== true) {
          throw new Error('Goose session load unavailable');
        }
        const loaded = await request('session/load', { sessionId, cwd, mcpServers }, update => {
          if (update?.sessionId !== sessionId) {
            throw new Error('Goose history came from another session');
          }
        });
        if (!loaded || typeof loaded !== 'object' || Array.isArray(loaded)
            || ('sessionId' in loaded && loaded.sessionId !== sessionId)) {
          throw new Error('Goose session load unconfirmed');
        }
      }
      const selected = await request(PREFIX + 'tools/list', { sessionId });
      if (!isSelectedCatalog(selected, expected)) throw new Error('Goose tool catalog mismatch');
      return sessionId;
    },
  });
}
