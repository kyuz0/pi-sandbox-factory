import { test } from 'node:test';
import assert from 'node:assert/strict';
import { expandTargets, probe, scan, readJson } from '../../containers/dev/local-model-manager/scripts/discover-local-models.mjs';

test('explicit ranges deduplicate and reject invalid or excessive scans', () => {
  assert.equal(expandTargets('localhost', '8000-8009,8080-8089,8000').length, 20);
  for (const ports of ['0', '65536', '9000-8000', '1-300', 'abc', '8000,']) assert.throws(() => expandTargets('localhost', ports));
  assert.equal(expandTargets('::1', '8000')[0], 'http://[::1]:8000');
});
const fixture = (models, props = {}) => ({ fetchImpl: async url => Response.json(url.endsWith('/props') ? props : { data: models }) });
test('effective server context is distinct from trained context', async () => {
  const result = await probe('http://localhost:8000', fixture([{ id: 'fixture', meta: { n_ctx_train: 131072 } }], { default_generation_settings: { n_ctx: 32768 }, modalities: { vision: false } }));
  assert.equal(result.models[0].contextWindow, 32768);
  assert.equal(result.models[0].trainedContext, 131072);
  assert.equal(result.models[0].imageSupport, false);
});
test('unknown capabilities remain unknown and router props are not assigned to every model', async () => {
  const result = await probe('http://localhost:8000', fixture([{ id: 'vision-name' }, { id: 'other' }], { default_generation_settings: { n_ctx: 32768 }, modalities: { vision: true } }));
  assert.equal(result.models[0].contextWindow, null);
  assert.equal(result.models[0].imageSupport, null);
});
test('DwarfStar advertised metadata is retained without claiming a verified build', async () => {
  const result = await probe('http://localhost:8000', fixture([{ id: 'fixture', owned_by: 'ds4.c', context_length: 262144, supported_parameters: ['tools'], top_provider: { max_completion_tokens: 4096 } }]));
  assert.equal(result.models[0].contextWindow, 262144);
  assert.equal(result.models[0].imageSupport, null);
  assert.equal(result.models[0].maxCompletionTokensAdvertised, 4096);
});
test('per-model advertised input modalities enable vision without borrowing another model capability', async () => {
  const result = await probe('http://localhost:8000', fixture([
    { id: 'vision', architecture: { input_modalities: ['text', 'image'] } },
    { id: 'text', architecture: { input_modalities: ['text'] } },
    { id: 'unknown', architecture: { input_modalities: 'image' } },
  ], { modalities: { vision: true }, default_generation_settings: { n_ctx: 32768 } }));
  assert.deepEqual(result.models.map(m => m.imageSupport), [true, false, null]);
  assert.match(result.models[0].imageSupportEvidence, /architecture.input_modalities/);
  assert.equal(result.models[0].contextWindow, null);
  const active = await probe('http://localhost:8000', fixture([{ id: 'vision', architecture: { input_modalities: ['text', 'image'] } }], { modalities: { vision: false } }));
  assert.equal(active.models[0].imageSupport, false);
  assert.equal(active.models[0].imageSupportEvidence, '/props.modalities.vision');
});
test('closed ports, HTTP errors, malformed lists and timeouts stay distinct', async () => {
  assert.equal((await probe('http://localhost:1', { fetchImpl: async () => { throw new TypeError('fetch failed', { cause: { code: 'ECONNREFUSED' } }); } })).status, 'closed');
  assert.equal((await probe('http://localhost:1', { fetchImpl: async () => new Response('', { status: 404 }) })).status, 'http-error');
  assert.equal((await probe('http://localhost:1', { fetchImpl: async () => Response.json({ data: [{}] }) })).status, 'invalid-model-list');
  assert.equal((await probe('http://localhost:1', { fetchImpl: async () => { throw new DOMException('timeout', 'TimeoutError'); } })).status, 'timeout');
});
test('requests forbid redirects and bound response size', async () => {
  await assert.rejects(readJson('http://localhost:1', { fetchImpl: async (url, options) => {
    assert.equal(options.redirect, 'manual');
    assert.ok(options.signal);
    return new Response('x'.repeat(1024 * 1024 + 1));
  } }), /1 MiB/);
});
test('scan deduplicates targets and bounds concurrent requests', async () => {
  let active = 0, peak = 0, calls = 0;
  const results = await scan(['http://localhost:1', 'http://localhost:2', 'http://localhost:1'], { concurrency: 1, fetchImpl: async () => {
    calls++; active++; peak = Math.max(peak, active);
    await new Promise(resolve => setImmediate(resolve)); active--;
    return Response.json({ data: [] });
  } });
  assert.equal(results.length, 2); assert.equal(calls, 2); assert.equal(peak, 1);
});
