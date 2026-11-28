import { closed, frames, privateBytes, UUID, writeFrame } from '../worker-pipes.mjs';

export const BODY = ['beingRef', 'embodimentId', 'incarnationId', 'manifestHash'];

export async function readBodyGuidance(path) {
  const guidance = new TextDecoder('utf-8', { fatal: true })
    .decode(await privateBytes(path, 6 * 1024)).trim();
  if (!guidance || guidance.includes('\0')) throw new Error('Invalid receiving body guidance');
  return guidance;
}

export async function runBoundedWorker(schema, profile, runTurn) {
  const pipe = frames(process.stdin);
  const stop = new AbortController();
  try {
    const input = (await pipe.next()).value;
    if (!closed(input, ['schema', 'type', 'inputId', 'sessionId', 'text', 'body', 'workspace', 'resume'])
        || input.schema !== schema || input.type !== 'start'
        || !UUID.test(input.inputId) || !UUID.test(input.sessionId)
        || input.workspace !== profile.cwd
        || (input.resume !== null && typeof input.resume !== 'string')
        || !closed(input.body, BODY) || !BODY.every(key => input.body[key] === profile.body[key])) {
      throw new Error('Invalid ACP foreground start');
    }
    const correlation = { schema, inputId: input.inputId, sessionId: input.sessionId };
    async function beforeSubmit(nativeSessionId) {
      await writeFrame(process.stdout, {
        ...correlation, type: 'prepare_submission', nativeSessionId, workspace: input.workspace,
      }, stop.signal);
      const decision = (await pipe.next()).value;
      if (!closed(decision, ['schema', 'type', 'inputId', 'sessionId', 'committed'])
          || !Object.entries(correlation).every(([name, value]) => decision[name] === value)
          || decision.type !== 'submission_decision' || decision.committed !== true) return false;
      void pipe.next().then(() => stop.abort(), () => stop.abort());
      return true;
    }
    const outcome = await runTurn(input, stop.signal, beforeSubmit);
    await writeFrame(process.stdout, { ...correlation, type: 'outcome', outcome }, stop.signal);
  } finally {
    process.stdin.destroy();
  }
}
