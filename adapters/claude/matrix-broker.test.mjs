import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { createMatrixStatusBroker } from './matrix-broker.mjs';

test('the Claude tool reads the fixed owner body and rejects later generation drift', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'claude-broker-'));
  try {
    const observation = join(dir, 'body.json');
    const command = [process.execPath, '-e', `
      const { readFileSync } = require('node:fs');
      if (process.argv[2] !== '--body-status') process.exit(1);
      const request = JSON.parse(readFileSync(0, 'utf8'));
      const status = JSON.parse(readFileSync(process.argv[1], 'utf8'));
      if (request.source.being_ref !== status.being_ref
          || request.source.embodiment_id !== status.local_origin.embodiment_id) process.exit(1);
      process.stdout.write(JSON.stringify(status));
    `, '--', observation];
    const expectedBody = {
      beingRef: 'fixture-being', embodimentId: 'fixture-body',
      incarnationId: 'fixture-live', manifestHash: 'fixture-manifest',
    };
    const status = {
      schema: 'dm.runtime.status/v1', integrity: 'ok', being_ref: expectedBody.beingRef,
      manifest_hash: expectedBody.manifestHash,
      local_origin: {
        embodiment_id: expectedBody.embodimentId, incarnation_id: expectedBody.incarnationId,
      },
    };
    await writeFile(observation, JSON.stringify(status));
    const broker = createMatrixStatusBroker({
      command, expectedBody, createSdkMcpServer: value => value,
      tool: (name, _description, _schema, call) => ({ name, call }),
    });
    expectedBody.beingRef = 'replacement';
    command[0] = '/does-not-exist';

    assert.deepEqual(await broker.readStatus(), status);
    assert.deepEqual(broker.server.tools.map(({ name }) => name), ['daimon_status']);
    const selected = await broker.server.tools[0].call({ source: expectedBody });
    assert.deepEqual(JSON.parse(selected.content[0].text), status);

    for (const drift of [
      { ...status, manifest_hash: 'another-manifest' },
      { ...status, local_origin: { ...status.local_origin, incarnation_id: 'another-incarnation' } },
    ]) {
      await writeFile(observation, JSON.stringify(drift));
      const refused = await broker.server.tools[0].call({});
      assert.deepEqual(refused, {
        isError: true, content: [{ type: 'text', text: 'Matrix body unavailable.' }],
      });
    }
  } finally {
    await rm(dir, { recursive: true });
  }
});
