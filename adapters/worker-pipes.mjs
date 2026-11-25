import { once } from 'node:events';
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { isAbsolute } from 'node:path';

const MAX_FRAME = 128 * 1024;
const MAX_OUTCOME_FRAME = 512 * 1024;
export const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;

export function closed(value, fields) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === fields.length
    && fields.every(field => Object.hasOwn(value, field));
}

export async function* frames(stream) {
  let pending = Buffer.alloc(0);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  for await (const bytes of stream) {
    let start = 0;
    while (start < bytes.length) {
      const end = bytes.indexOf(10, start);
      const part = bytes.subarray(start, end < 0 ? bytes.length : end);
      if (pending.length + part.length > MAX_FRAME) throw new Error('Frame exceeds bound');
      pending = Buffer.concat([pending, part]);
      if (end < 0) break;
      yield JSON.parse(decoder.decode(pending));
      pending = Buffer.alloc(0);
      start = end + 1;
    }
  }
  if (pending.length) throw new Error('Unterminated frame');
}

export async function writeFrame(stream, value, signal) {
  const data = Buffer.from(JSON.stringify(value) + '\n');
  if (data.length > MAX_OUTCOME_FRAME + 1) throw new Error('Frame exceeds bound');
  if (!stream.write(data)) await once(stream, 'drain', { signal });
}

export async function privateBytes(path, limit) {
  if (typeof path !== 'string' || !isAbsolute(path)) throw new Error('Owner profile required');
  const fd = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await fd.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) || info.nlink !== 1) {
      throw new Error('Owner profile must be private');
    }
    const buffer = Buffer.alloc(limit + 1);
    let size = 0;
    while (size < buffer.length) {
      const { bytesRead } = await fd.read(buffer, size, buffer.length - size);
      if (bytesRead === 0) break;
      size += bytesRead;
    }
    if (size === buffer.length) throw new Error('Owner profile exceeds bound');
    return buffer.subarray(0, size);
  } finally {
    await fd.close();
  }
}
