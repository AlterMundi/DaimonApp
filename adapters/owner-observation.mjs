// Bounded foreground operations using the owner-selected local reader.
import { execFile } from 'node:child_process';

function query(command, flag, input, signal, env, maxBuffer) {
  return new Promise((resolve, reject) => {
    const child = execFile(command[0], [...command.slice(1), flag], {
      signal, env, timeout: 8_000, maxBuffer, encoding: 'utf8',
    }, (error, stdout) => {
      if (error) {
        reject(new Error('Selected owner observation unavailable'));
        return;
      }
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error('Invalid owner observation')); }
    });
    child.stdin.on('error', reject);
    child.stdin.end(JSON.stringify(input));
  });
}

export function inspectMatrixStatus(command, source, signal, env) {
  return query(command, '--body-status', { source }, signal, env, 16 * 1024);
}

export function readDmkObservation(command, request, signal) {
  return query(command, '--request-stdin', request, signal, { PATH: '/usr/bin:/bin' }, 32 * 1024);
}
