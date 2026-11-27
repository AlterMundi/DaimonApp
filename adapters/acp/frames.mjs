const MAX_FRAME = 512 * 1024;
const MAX_COMMANDS_FRAME = 768 * 1024;

function isCommandList(message) {
  const update = message.params?.update;
  return message.method === 'session/update' && !('id' in message)
    && update?.sessionUpdate === 'available_commands_update'
    && Array.isArray(update.availableCommands);
}

// Qwen Code advertises its installed command and skill catalog in a single
// notification. Keep the larger envelope specific to that notification.
export async function* acpFrames(stream, { allowLargeCommandList = false } = {}) {
  const decoder = new TextDecoder('utf8', { fatal: true });
  const maximum = allowLargeCommandList ? MAX_COMMANDS_FRAME : MAX_FRAME;
  let pending = Buffer.alloc(0);
  for await (const bytes of stream) {
    let start = 0;
    while (start < bytes.length) {
      const end = bytes.indexOf(10, start);
      const part = bytes.subarray(start, end < 0 ? bytes.length : end);
      if (pending.length + part.length > maximum) throw new Error('ACP frame exceeds bound');
      pending = Buffer.concat([pending, part]);
      if (end < 0) break;
      const message = JSON.parse(decoder.decode(pending));
      if (message?.jsonrpc !== '2.0') throw new Error('Invalid ACP message');
      if (pending.length > MAX_FRAME && !isCommandList(message)) {
        throw new Error('ACP frame exceeds bound');
      }
      pending = Buffer.alloc(0);
      start = end + 1;
      yield message;
    }
  }
  if (pending.length) throw new Error('Unterminated ACP frame');
}
