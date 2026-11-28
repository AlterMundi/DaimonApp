import { isAbsolute } from 'node:path';
import { readDmkObservation } from '../owner-observation.mjs';
import { closed, privateBytes, UUID } from '../worker-pipes.mjs';

const POOL = /^[a-z][a-z0-9_-]{0,39}$/;
const SAFE_FIELDS = ['action', 'query', 'pool', 'record_uid', 'offset', 'expected_revision'];

export const recallProperties = {
  action: { type: 'string', enum: ['search', 'read'] },
  query: { type: 'string', maxLength: 256 },
  pool: { type: 'string', maxLength: 40 },
  record_uid: { type: 'string' },
  offset: { type: 'integer', minimum: 0 },
  expected_revision: { type: 'integer', minimum: 1 },
};

export function validSharedMemory(value) {
  return closed(value, ['command', 'bindingFile', 'bodyRef'])
    && Array.isArray(value.command) && value.command.length >= 2 && value.command.length <= 16
    && value.command.every(arg => typeof arg === 'string' && arg.length > 0 && arg.length <= 4096)
    && isAbsolute(value.command[0])
    && typeof value.bindingFile === 'string' && isAbsolute(value.bindingFile)
    && typeof value.bodyRef === 'string' && value.bodyRef.length > 0 && value.bodyRef.length <= 240;
}

export async function sharedMemory(binding, request, signal) {
  if (!request || typeof request !== 'object' || Array.isArray(request)
      || Object.keys(request).some(key => !SAFE_FIELDS.includes(key))) {
    throw new Error('Invalid DMK read request');
  }
  const { action, pool, query, record_uid, offset = 0, expected_revision } = request;
  if ((pool !== undefined && (typeof pool !== 'string' || !POOL.test(pool)))
      || !Number.isSafeInteger(offset) || offset < 0
      || (expected_revision !== undefined
        && (!Number.isSafeInteger(expected_revision) || expected_revision < 1))) {
    throw new Error('Invalid DMK read bounds');
  }
  if (action === 'search') {
    if (typeof query !== 'string' || !query.trim() || Buffer.byteLength(query) > 1024
      || offset !== 0 || record_uid !== undefined || expected_revision !== undefined) {
      throw new Error('Invalid DMK search');
    }
  } else if (action !== 'read' || !pool || typeof record_uid !== 'string' || !UUID.test(record_uid)
      || query !== undefined || (offset > 0 && expected_revision === undefined)) {
    throw new Error('Invalid DMK record selection');
  }
  const selection = binding.sharedMemory;
  const config = JSON.parse(await privateBytes(selection.bindingFile, 16 * 1024));
  if (config?.schema !== 'hmk.deep-recall.binding/v1'
      || config.being_ref !== binding.body.beingRef || config.body_ref !== selection.bodyRef
      || !Array.isArray(config.pools) || !config.pools.length || config.pools.length > 8
      || !config.pools.every(item => typeof item.name === 'string' && POOL.test(item.name))) {
    throw new Error('Shared memory differs from the selected being or body');
  }
  const result = await readDmkObservation(
    [...selection.command, '--binding', selection.bindingFile], request, signal,
  );
  const pools = config.pools.map(item => item.name);
  if (result?.being_ref !== binding.body.beingRef || result.body_ref !== selection.bodyRef
      || !Array.isArray(result.pools) || result.pools.length > pools.length
      || !result.pools.every(item => pools.includes(item?.pool) && (!pool || pool === item.pool))) {
    throw new Error('DMK response differs from the selected memory binding');
  }
  return result;
}
