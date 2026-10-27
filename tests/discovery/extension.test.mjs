import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { registerLocalModels } from '../../containers/dev/local-model-manager/scripts/local-models-command.mjs';

async function setup(overrides = {}) {
  const root = await mkdtemp(join(tmpdir(), 'pi-extension-test-'));
  const messages = [], notifications = [], refreshes = [], scans = [], syncs = [];
  let command;
  const ctx = { isIdle: () => true, ui: { notify: (...args) => notifications.push(args) }, modelRegistry: { refresh: async options => { refreshes.push(options); return { errors: new Map(), aborted: false }; } } };
  registerLocalModels({ registerCommand: (name, value) => { assert.equal(name, 'local-models'); command = value; }, sendMessage: (message, options) => { assert.equal(options.triggerTurn, false); messages.push(message.content); } }, {
    getAgentDir: () => root,
    scanModels: async targets => { scans.push(targets); return []; },
    syncModels: async (target, reports, options) => { syncs.push({ target, options }); return { target, mode: options.write ? 'write' : 'preview', changes: [{ provider: 'endpoint-id', previousProvider: 'old-label', action: 'replace' }], warnings: [], conflicts: [], backup: null }; },
    ...overrides,
  });
  return { root, messages, notifications, refreshes, scans, syncs, ctx, run: args => command.handler(args, ctx), close: () => rm(root, { recursive: true, force: true }) };
}
test('command refresh scans configured ranges, adopts local entries and reloads only changed providers', async () => {
  const s = await setup();
  try {
    await s.run('refresh');
    assert.equal(s.scans[0].length, 1);
    assert.equal(s.syncs[0].target, join(s.root, 'models.json'));
    assert.deepEqual(s.syncs[0].options, { write: true, adoptLocal: true, maxTokens: 4096 });
    assert.deepEqual(s.refreshes[0].providers, ['endpoint-id', 'old-label']);
    assert.equal(s.refreshes[0].allowNetwork, false);
    assert.ok(s.refreshes[0].signal);
  } finally { await s.close(); }
});
test('preview is read-only; saved ports persist and control subsequent scans', async () => {
  const s = await setup();
  try {
    await s.run('ports 9000-9002,9001');
    assert.equal(JSON.parse(await readFile(join(s.root, 'local-pi-models.json'), 'utf8')).ports, '9000-9002,9001');
    await s.run('preview');
    assert.equal(s.scans[0].length, 3);
    assert.equal(s.syncs[0].options.write, false);
    assert.equal(s.refreshes.length, 0);
  } finally { await s.close(); }
});
test('invalid ranges, remote hosts and invalid actions cannot scan or write', async () => {
  const s = await setup();
  try {
    await s.run('ports 1-65535'); await s.run('refresh extra'); await s.run('unknown');
    await writeFile(join(s.root, 'local-pi-models.json'), JSON.stringify({ host: 'example.test' }));
    await s.run('refresh');
    assert.equal(s.scans.length, 0); assert.equal(s.syncs.length, 0);
    assert.equal(s.notifications.filter(([, level]) => level === 'error').length, 4);
  } finally { await s.close(); }
});
test('concurrent commands and active model turns are blocked', async () => {
  let release;
  const s = await setup({ scanModels: () => new Promise(resolve => { release = resolve; }) });
  try {
    const first = s.run('refresh');
    while (!release) await new Promise(resolve => setImmediate(resolve));
    await s.run('refresh');
    assert.ok(s.notifications.some(([message]) => message.includes('already running')));
    release([]); await first;
    s.ctx.isIdle = () => false;
    await s.run('refresh');
    assert.ok(s.notifications.some(([message]) => message.includes('current Pi turn')));
  } finally { await s.close(); }
});
test('reload failure distinguishes saved configuration from failed discovery', async () => {
  const s = await setup();
  try {
    s.ctx.modelRegistry.refresh = async () => { throw new Error('fixture reload failure'); };
    await s.run('refresh');
    assert.ok(s.notifications.some(([message]) => message.includes('was saved, but Pi reload failed')));
  } finally { await s.close(); }
});
test('settings pass exact thinking overrides to refresh and reject invalid overrides before scanning', async () => {
  const s = await setup();
  try {
    const file = join(s.root, 'local-pi-models.json');
    const thinkingOverrides = [{ endpoint: 'http://localhost:8000', model: 'alias', profile: 'dwarfstar-deepseek41' }];
    await writeFile(file, JSON.stringify({ thinkingOverrides }));
    await s.run('preview');
    assert.deepEqual(s.syncs[0].options.thinkingOverrides, thinkingOverrides);
    await s.run('ports 8080');
    assert.deepEqual(JSON.parse(await readFile(file, 'utf8')).thinkingOverrides, thinkingOverrides);
    await writeFile(file, JSON.stringify({ thinkingOverrides: [{ ...thinkingOverrides[0], profile: 'invalid' }] }));
    await s.run('refresh');
    assert.equal(s.scans.length, 1);
    assert.ok(s.notifications.some(([message]) => message.includes('Unknown thinking profile')));
  } finally { await s.close(); }
});
