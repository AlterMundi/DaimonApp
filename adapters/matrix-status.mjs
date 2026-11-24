// Read only the authenticated observation selected by the owner.
import { execFile } from 'node:child_process';

export function inspectMatrixStatus(command, source, signal, env) {
  return new Promise((resolve, reject) => {
    const child = execFile(command[0], [...command.slice(1), '--body-status'], {
      signal, env, timeout: 8_000, maxBuffer: 16 * 1024, encoding: 'utf8',
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
