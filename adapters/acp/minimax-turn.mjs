import { loadAcpSession, runAcpTurn, validateSessionId } from './turn.mjs';

/** Run one MiniMax Code turn without replacing an existing topic session. */
export async function runMiniMaxTurn({
  binary, cwd, env, mcpServers, nativeSessionId, text, guidanceFile, beforeSubmit, signal,
}) {
  const args = ['acp'];
  if (guidanceFile) args.push('--append-system-prompt-file', guidanceFile);
  return runAcpTurn({
    binary, args, cwd, env, text, beforeSubmit, signal,
    unavailable: 'minimax_unavailable', openFailure: 'minimax_session_unconfirmed',
    allowLargeCommandList: true,
    async openSession(request, initialized) {
      const { name, version } = initialized.agentInfo ?? {};
      if (name !== 'minimax-code' || version !== '0.8.0') {
        throw new Error('Qualified MiniMax Code ACP required');
      }
      if (nativeSessionId !== undefined) {
        await loadAcpSession(request, initialized, { cwd, mcpServers, sessionId: nativeSessionId });
        return nativeSessionId;
      }
      const started = await request('session/new', { cwd, mcpServers });
      return validateSessionId(started?.sessionId);
    },
  });
}
