import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { test } from 'node:test';

import { acpFrames } from './frames.mjs';

async function decode(message, options) {
  const wire = Buffer.from(JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n');
  const stream = Readable.from([wire.subarray(0, 500_000), wire.subarray(500_000)]);
  const messages = [];
  for await (const frame of acpFrames(stream, options)) messages.push(frame);
  return messages;
}

test('ACP allows a Qwen-sized command list only on an opted-in profile', async () => {
  const commands = {
    method: 'session/update',
    params: { sessionId: 'selected', update: {
      sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'fixture', description: 'a'.repeat(650_346) }],
    } },
  };
  const options = { allowLargeCommandList: true };
  assert.deepEqual(await decode(commands, options), [{ jsonrpc: '2.0', ...commands }]);
  await assert.rejects(decode(commands), /exceeds bound/);
  await assert.rejects(decode({ id: 1, ...commands }, options), /exceeds bound/);
  await assert.rejects(decode({ id: 2, result: 'a'.repeat(650_346) }, options), /exceeds bound/);
  commands.params.update.availableCommands[0].description = 'a'.repeat(768 * 1024);
  await assert.rejects(decode(commands, options), /exceeds bound/);
});
