import { runAcpTurn, validateSessionId } from './turn.mjs';

/** Run a turn using an owner-selected Qwen profile and an exact topic binding. */
export async function runQwenTurn({
  binary, cwd, env, mcpServers, nativeSessionId, text, beforeSubmit, signal,
}) {
  return runAcpTurn({
    binary, args: ['--acp', '--no-telemetry'], cwd, env, text, beforeSubmit, signal,
    unavailable: 'qwen_unavailable',
    openFailure: 'qwen_session_unconfirmed',
    allowLargeCommandList: true,
    async openSession(request, initialized) {
      if (initialized.agentInfo?.name !== 'qwen-code') throw new Error('Qwen Code ACP required');
      if (nativeSessionId !== undefined) {
        const sessionId = validateSessionId(nativeSessionId);
        if (initialized.agentCapabilities?.loadSession !== true) {
          throw new Error('Qwen Code ACP session load unavailable');
        }
        // A failed load must never create a fresh session for this original.
        const loaded = await request('session/load', { cwd, mcpServers, sessionId }, update => {
          if (update?.sessionId !== sessionId) {
            throw new Error('Qwen Code history came from a different session');
          }
        });
        if (!loaded || typeof loaded !== 'object' || Array.isArray(loaded)
            || ('sessionId' in loaded && loaded.sessionId !== sessionId)) {
          throw new Error('Qwen Code session load did not confirm the selected session');
        }
        return sessionId;
      }
      const started = await request('session/new', { cwd, mcpServers });
      return started?.sessionId;
    },
  });
}
