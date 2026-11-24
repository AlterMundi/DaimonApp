// The owner selects this command and its binding, not Claude or the input.
import { inspectMatrixStatus } from '../matrix-status.mjs';

/** Build the private status read and Claude's tool over one owner selection. */
export function createMatrixStatusBroker({ command, source, createSdkMcpServer, tool, signal }) {
  if (!Array.isArray(command) || !command[0]?.startsWith('/') || !source?.being_ref
      || !source.embodiment_id) {
    throw new TypeError('Expected an owner-selected Matrix observation command and body');
  }
  const selectedCommand = [...command];
  const selectedSource = { being_ref: source.being_ref, embodiment_id: source.embodiment_id };
  const readStatus = () => inspectMatrixStatus(selectedCommand, selectedSource, signal);
  const read = tool('daimon_status', 'Read authenticated metadata for this Matrix body.', {}, async () => {
    try {
      const status = await readStatus();
      return { content: [{ type: 'text', text: JSON.stringify(status) }] };
    } catch {
      return { isError: true, content: [{ type: 'text', text: 'Matrix body unavailable.' }] };
    }
  });
  return { readStatus, server: createSdkMcpServer({ name: 'matrix-status', tools: [read] }) };
}
