import { loadAcpSession, runAcpTurn, validateSessionId } from './turn.mjs';

/** Run a turn using an owner-selected Qwen profile and an exact topic binding. */
export async function runQwenTurn({
  binary, cwd, env, mcpServers, nativeSessionId, freshSessionId, model, text, instructions, beforeSubmit, signal,
}) {
  const args = ['--acp', '--no-telemetry'];
  if (model) args.push('--bare', '--auth-type', 'openai', '--model', model);
  function verifyModel(selection) {
    if (!model) return;
    const { currentModelId, availableModels } = selection.models ?? {};
    const entry = availableModels?.length === 1 && availableModels[0];
    if (entry?.modelId !== currentModelId || entry?._meta?.baseModelId !== model
        || entry._meta.authType !== 'openai' || entry._meta.isRuntime !== true) {
      throw new Error('Qwen Code selected a different model or provider');
    }
  }
  return runAcpTurn({
    binary, args, cwd, env, text, instructions, beforeSubmit, signal,
    unavailable: 'qwen_unavailable',
    openFailure: 'qwen_session_unconfirmed',
    allowLargeCommandList: true,
    async openSession(request, initialized) {
      if (initialized.agentInfo?.name !== 'qwen-code'
          || (model && initialized.agentInfo.version !== '0.28.7')) {
        throw new Error('Qualified Qwen Code ACP required');
      }
      if (nativeSessionId !== undefined) {
        const sessionId = nativeSessionId;
        const loaded = await loadAcpSession(request, initialized, { cwd, mcpServers, sessionId });
        verifyModel(loaded);
        return sessionId;
      }
      const params = { cwd, mcpServers };
      if (freshSessionId !== undefined) {
        params._meta = { 'qwen-code/sessionId': validateSessionId(freshSessionId) };
      }
      const started = await request('session/new', params);
      if (freshSessionId !== undefined && started?.sessionId !== freshSessionId) {
        throw new Error('Qwen Code created a different native session');
      }
      if (model) verifyModel(started ?? {});
      return started?.sessionId;
    },
  });
}
