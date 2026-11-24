// The owner selects this command and its binding, not Claude or the input.
import { execFile } from 'node:child_process';

function inspect(command, source, signal) {
  return new Promise((resolve, reject) => {
    const child = execFile(command[0], [...command.slice(1), '--body-status'], {
      signal, timeout: 8_000, maxBuffer: 16 * 1024, encoding: 'utf8',
    }, (error, stdout) => {
      if (error) {
        reject(new Error('Authenticated Matrix body observation unavailable'));
        return;
      }
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error('Invalid authenticated Matrix body observation')); }
    });
    child.stdin.on('error', reject);
    child.stdin.end(JSON.stringify({ source }));
  });
}

/** Build the private status read and Claude's tool over one owner selection. */
export function createMatrixStatusBroker({ command, source, createSdkMcpServer, tool, signal }) {
  if (!Array.isArray(command) || !command[0]?.startsWith('/') || !source?.being_ref
      || !source.embodiment_id) {
    throw new TypeError('Expected an owner-selected Matrix observation command and body');
  }
  const selectedCommand = [...command];
  const selectedSource = { being_ref: source.being_ref, embodiment_id: source.embodiment_id };
  const readStatus = () => inspect(selectedCommand, selectedSource, signal);
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
