import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm, lstat, symlink } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { reconcile, providerId, syncFile } from '../../containers/dev/local-model-manager/scripts/sync-local-models.mjs';

const empty = () => ({ version: 1, entries: {} });
const endpoint = port => `http://localhost:${port}`;
const found = (port, id = 'fixture', extra = {}) => ({ endpoint: endpoint(port), status: 'model-list', models: [{ id, contextWindow: 32768, imageSupport: null, ...extra }] });
const remote = { baseUrl: 'https://example.test/v1', apiKey: '$PRIVATE_KEY', models: [{ id: 'remote' }], headers: { Example: 'keep' } };
test('shutdown 8000 and startup 8080/8081 removes only managed endpoint and preserves remote', () => {
  const first = reconcile({ providers: { remote }, other: { keep: true } }, empty(), [found(8000)]);
  const next = reconcile(first.config, first.manifest, [{ endpoint: endpoint(8000), status: 'closed' }, found(8080, 'same-id'), found(8081, 'same-id')]);
  assert.equal(next.config.providers[providerId(endpoint(8000))], undefined);
  assert.deepEqual(next.config.providers.remote, remote);
  assert.deepEqual(next.config.other, { keep: true });
  assert.equal(Object.keys(next.config.providers).length, 3);
  assert.equal(next.changes.filter(c => c.action === 'add').length, 2);
});
test('timeout/auth/http errors retain models; unscanned ports are untouched', () => {
  const first = reconcile({}, empty(), [found(8000), found(8080)]);
  for (const status of ['timeout', 'http-error', 'probe-error', 'invalid-model-list']) {
    const next = reconcile(first.config, first.manifest, [{ endpoint: endpoint(8000), status }]);
    assert.deepEqual(next.config, first.config);
    assert.equal(next.warnings.length, 1);
  }
});
test('successful inventories replace model lists and empty inventory removes managed provider', () => {
  const first = reconcile({}, empty(), [found(8000, 'old')]);
  const next = reconcile(first.config, first.manifest, [found(8000, 'new')]);
  assert.deepEqual(next.config.providers[providerId(endpoint(8000))].models.map(m => m.id), ['new']);
  const removed = reconcile(next.config, next.manifest, [{ endpoint: endpoint(8000), status: 'empty-model-list' }]);
  assert.deepEqual(removed.config.providers, {});
});
test('unknown context blocks creation, unknown vision emits text with warning, known image emits image', () => {
  const unknown = reconcile({}, empty(), [found(8000, 'fixture', { contextWindow: null })]);
  assert.equal(Object.keys(unknown.config.providers).length, 0);
  const text = reconcile({}, empty(), [found(8000)]);
  assert.deepEqual(text.config.providers[providerId(endpoint(8000))].models[0].input, ['text']);
  assert.match(text.warnings[0].reason, /unknown/);
  const image = reconcile({}, empty(), [found(8000, 'fixture', { imageSupport: true, contextWindow: 2048 })]);
  const m = image.config.providers[providerId(endpoint(8000))].models[0];
  assert.deepEqual(m.input, ['text', 'image']); assert.equal(m.maxTokens, 2048);
});
test('user edits produce conflicts; adoption is explicit and preserves provider/model customization', () => {
  const original = { providers: { custom: { baseUrl: `${endpoint(8000)}/v1`, headers: { keep: 'value' }, models: [{ id: 'fixture', samplingParams: { temperature: 0.4 } }] }, remote } };
  assert.equal(reconcile(original, empty(), [found(8000)]).conflicts.length, 1);
  const adopted = reconcile(original, empty(), [found(8000)], { adoptLocal: true });
  const id = providerId(endpoint(8000));
  assert.equal(Object.keys(adopted.config.providers).length, 2);
  assert.equal(adopted.config.providers.custom, undefined);
  assert.deepEqual(adopted.config.providers[id].headers, { keep: 'value' });
  assert.deepEqual(adopted.config.providers[id].models[0].samplingParams, { temperature: 0.4 });
  adopted.config.providers[id].models[0].contextWindow = 1000;
  const conflict = reconcile(adopted.config, adopted.manifest, [{ endpoint: endpoint(8000), status: 'closed' }]);
  assert.equal(conflict.conflicts.length, 1); assert.ok(conflict.config.providers[id]);
});
test('stale server labels are replaced using endpoint identity and the served model ID', () => {
  const original = { providers: { halogen: { name: 'Halogen', baseUrl: `${endpoint(8000)}/v1`, models: [{ id: 'old-model' }] }, remote } };
  const result = reconcile(original, empty(), [found(8000, 'served-model')], { adoptLocal: true });
  const id = providerId(endpoint(8000));
  assert.equal(result.config.providers.halogen, undefined);
  assert.equal(result.config.providers[id].name, undefined);
  assert.deepEqual(result.config.providers[id].models.map(m => m.id), ['served-model']);
  assert.equal(result.changes[0].previousProvider, 'halogen');
  assert.equal(result.changes[0].action, 'replace');
  assert.deepEqual(result.config.providers.remote, remote);
});
test('router/loading inventory retained; non-loopback writes rejected; reconciliation idempotent', () => {
  const first = reconcile({}, empty(), [found(8000)]);
  assert.equal(reconcile(first.config, first.manifest, [found(8000)]).changes.length, 0);
  assert.deepEqual(reconcile(first.config, first.manifest, [found(8000, 'new', { availability: 'loading' })]).config, first.config);
  assert.throws(() => reconcile({}, empty(), [{ endpoint: 'http://example.test:8000', status: 'closed' }]), /loopback/);
});
test('preview writes nothing; atomic write preserves unrelated data, creates private backup and is idempotent', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pi-sync-test-')), file = join(root, 'models.json');
  try {
    const original = JSON.stringify({ providers: { remote } });
    await writeFile(file, original);
    const preview = await syncFile(file, [found(8000)]);
    assert.equal(preview.mode, 'preview'); assert.equal(await readFile(file, 'utf8'), original);
    await assert.rejects(lstat(`${file}.local-lab-state.json`), { code: 'ENOENT' });
    const applied = await syncFile(file, [found(8000)], { write: true });
    assert.equal(await readFile(applied.backup, 'utf8'), original);
    assert.equal((await lstat(file)).mode & 0o777, 0o600);
    assert.deepEqual(JSON.parse(await readFile(file, 'utf8')).providers.remote, remote);
    const again = await syncFile(file, [found(8000)], { write: true });
    assert.equal(again.changes.length, 0); assert.equal(again.backup, null);
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('invalid JSON, symlinks and existing writer locks fail without modifying target', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pi-sync-test-')), file = join(root, 'models.json');
  try {
    await writeFile(file, '{bad');
    await assert.rejects(syncFile(file, [found(8000)], { write: true }));
    assert.equal(await readFile(file, 'utf8'), '{bad');
    await writeFile(file, '{}'); await writeFile(`${file}.local-lab.lock`, 'busy');
    await assert.rejects(syncFile(file, [found(8000)], { write: true }), { code: 'EEXIST' });
    const link = join(root, 'linked.json'); await symlink(file, link);
    await assert.rejects(syncFile(link, [found(8000)], { write: true }), /non-regular/);
    assert.equal(await readFile(file, 'utf8'), '{}');
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('interrupted ownership update recovered from journal; later user edits stop recovery', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pi-sync-test-')), file = join(root, 'models.json');
  try {
    const generated = reconcile({}, empty(), [found(8000)]);
    const afterConfig = JSON.stringify(generated.config), afterState = JSON.stringify(generated.manifest);
    const journal = { target: file, stateFile: `${file}.local-lab-state.json`, beforeConfig: '{}', beforeState: null, afterConfig, afterState };
    await writeFile(file, afterConfig);
    await writeFile(`${file}.local-lab-journal.json`, JSON.stringify(journal));
    const result = await syncFile(file, [found(8000)], { write: true });
    assert.equal(result.conflicts.length, 0);
    assert.deepEqual(JSON.parse(await readFile(`${file}.local-lab-state.json`, 'utf8')).entries, generated.manifest.entries);
    await writeFile(`${file}.local-lab-journal.json`, JSON.stringify(journal));
    await writeFile(file, '{"userEdit":true}');
    await assert.rejects(syncFile(file, [found(8000)], { write: true }), /later edits/);
    assert.equal(await readFile(file, 'utf8'), '{"userEdit":true}');
  } finally { await rm(root, { recursive: true, force: true }); }
});
