import { runAcpTurn, validateSessionId } from './turn.mjs';

function readSelection(state, category) {
  const options = state?.configOptions?.filter(option => option.category === category);
  if (options?.length !== 1 || typeof options[0].id !== 'string') {
    throw new Error('Antigravity did not identify the selected configuration');
  }
  return options[0];
}

/** Use the paired, sandboxed agy account for one journaled native turn. */
export async function runAntigravityTurn({
  binary, cwd, env, model, effort, mcpServers = [], nativeSessionId, text, beforeSubmit, signal, allowedReadTools = [], instructions, images, onInputAccepted,
}) {
  if (typeof model !== 'string' || !model || typeof effort !== 'string' || !effort) {
    throw new TypeError('Select the Antigravity model and reasoning effort');
  }
  return runAcpTurn({
    binary, args: ['acp', '--sandbox', '--disable-telemetry', '--include-default-customizations=false'], cwd, env, text, beforeSubmit, signal, instructions, images, onInputAccepted,
    unavailable: 'antigravity_cli_unavailable',
    openFailure: 'antigravity_cli_session_unconfirmed',
    allowLargeCommandList: true,
    selectPermission({ toolCall, options }) {
      if (!allowedReadTools.includes(toolCall?.name) || !Array.isArray(options)) return;
      const once = options.filter(option => option?.kind === 'allow_once'
        && typeof option.optionId === 'string' && option.optionId.length <= 128);
      if (once.length === 1) return once[0].optionId;
    },
    async openSession(request, initialized) {
      if (initialized.agentInfo?.name !== 'Antigravity ACP Server') {
        throw new Error('Antigravity ACP identity unconfirmed');
      }
      let state;
      let sessionId;
      if (nativeSessionId === undefined) {
        state = await request('session/new', { cwd, mcpServers });
        sessionId = validateSessionId(state?.sessionId);
      } else {
        sessionId = validateSessionId(nativeSessionId);
        if (initialized.agentCapabilities?.loadSession !== true) {
          throw new Error('Antigravity session load unavailable');
        }
        state = await request('session/load', { cwd, mcpServers, sessionId }, update => {
          if (update?.sessionId !== sessionId) {
            throw new Error('Antigravity history came from another session');
          }
        });
        if (!state || ('sessionId' in state && state.sessionId !== sessionId)) {
          throw new Error('Antigravity session load unconfirmed');
        }
      }

      for (const [category, value] of [['model', model], ['thought_level', effort]]) {
        const option = readSelection(state, category);
        if (option.currentValue !== value) {
          state = await request('session/set_config_option', {
            sessionId, configId: option.id, value,
          });
        }
      }
      if (readSelection(state, 'model').currentValue !== model
          || readSelection(state, 'thought_level').currentValue !== effort) {
        throw new Error('Antigravity did not apply the requested model and effort');
      }
      return sessionId;
    },
  });
}
