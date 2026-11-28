import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { basename, isAbsolute } from 'node:path';
import { closed } from '../worker-pipes.mjs';

const MAX_BYTES = 4 * 1024 * 1024;

export async function retainedImages(attachments) {
  if (!Array.isArray(attachments) || !attachments.length || attachments.length > 8) {
    throw new Error('Invalid retained image selection');
  }
  let remaining = MAX_BYTES;
  const images = [];
  for (const image of attachments) {
    if (!closed(image, ['path', 'mime']) || typeof image.path !== 'string'
        || !isAbsolute(image.path) || !['image/png', 'image/jpeg'].includes(image.mime)
        || !/^[a-f0-9]{64}$/.test(basename(image.path))) {
      throw new Error('Unsupported retained image');
    }
    const file = await open(image.path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const info = await file.stat();
      if (!info.isFile() || !info.size || info.size > remaining) {
        throw new Error('Retained images exceed the submission bound');
      }
      const bytes = Buffer.alloc(info.size);
      let offset = 0;
      while (offset < bytes.length) {
        const { bytesRead } = await file.read(bytes, offset, bytes.length - offset, offset);
        if (!bytesRead) break;
        offset += bytesRead;
      }
      if (offset !== info.size || createHash('sha256').update(bytes).digest('hex') !== basename(image.path)) {
        throw new Error('Retained image digest differs from its reference');
      }
      remaining -= info.size;
      images.push({ type: 'image', mimeType: image.mime, data: bytes.toString('base64') });
    } finally {
      await file.close();
    }
  }
  return images;
}
