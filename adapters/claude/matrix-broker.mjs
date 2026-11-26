// The owner selects this command and its binding, not Claude or the input.
import { inspectMatrixStatus } from '../owner-observation.mjs';

export function bodyMatches(status, expected) {
  return status?.schema === 'dm.runtime.status/v1'
    && status.integrity === 'ok'
    && status.being_ref === expected.beingRef
    && status.manifest_hash === expected.manifestHash
    && status.local_origin?.embodiment_id === expected.embodimentId
    && status.local_origin?.incarnation_id === expected.incarnationId;
}

/** Build the private status read and Claude's tool over one owner selection. */
export function createMatrixStatusBroker({ command, expectedBody, createSdkMcpServer, tool, signal }) {
  if (!Array.isArray(command) || !command[0]?.startsWith('/') || !expectedBody?.beingRef
      || !expectedBody.embodimentId || !expectedBody.incarnationId || !expectedBody.manifestHash) {
    throw new TypeError('Expected an owner-selected Matrix observation command and body');
  }
  const selectedCommand = [...command];
  const selectedBody = { ...expectedBody };
  const selectedSource = { being_ref: selectedBody.beingRef, embodiment_id: selectedBody.embodimentId };
  const readStatus = () => inspectMatrixStatus(selectedCommand, selectedSource, signal);
  const read = tool('daimon_status', 'Read authenticated metadata for this Matrix body.', {}, async () => {
    try {
      const status = await readStatus();
      if (!bodyMatches(status, selectedBody)) throw new Error('Matrix body changed');
      return { content: [{ type: 'text', text: JSON.stringify(status) }] };
    } catch {
      return { isError: true, content: [{ type: 'text', text: 'Matrix body unavailable.' }] };
    }
  }, { alwaysLoad: true });
  return { readStatus, server: createSdkMcpServer({ name: 'matrix-status', tools: [read] }) };
}
