import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createMatrixStatusBroker } from './matrix-broker.mjs';

test('preflight and the sole Claude tool use one fixed owner selection', async () => {
  const command = [process.execPath, '-e', `
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => raw += chunk);
    process.stdin.on('end', () => {
      if (process.argv[1] !== '--body-status') process.exit(1);
      process.stdout.write(JSON.stringify(JSON.parse(raw)));
    });
  `, '--'];
  const source = { being_ref: 'fixture-being', embodiment_id: 'fixture-body' };
  const broker = createMatrixStatusBroker({
    command, source,
    createSdkMcpServer: value => value,
    tool: (name, _description, _schema, call) => ({ name, call }),
  });
  const expected = { source: { ...source } };
  source.being_ref = 'replacement';
  command[0] = '/does-not-exist';

  assert.deepEqual(await broker.readStatus(), expected);
  assert.deepEqual(broker.server.tools.map(({ name }) => name), ['daimon_status']);
  const selected = await broker.server.tools[0].call({ source });
  assert.deepEqual(JSON.parse(selected.content[0].text), expected);
});
