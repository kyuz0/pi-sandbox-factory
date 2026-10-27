import { test } from 'node:test';
import assert from 'node:assert/strict';
import { probe } from '../../containers/dev/local-model-manager/scripts/discover-local-models.mjs';
import { thinkingConfig, validateThinkingOverrides } from '../../containers/dev/local-model-manager/scripts/thinking.mjs';
import { reconcile, providerId } from '../../containers/dev/local-model-manager/scripts/sync-local-models.mjs';

const endpoint = 'http://localhost:8000';
const state = () => ({ version: 1, entries: {} });
const provider = result => result.config.providers[providerId(endpoint)];
const metadata = (id, owned_by, extra = {}) => ({ id, owned_by, context_length: 262144, supported_parameters: ['reasoning_effort'], architecture: { input_modalities: ['text'] }, ...extra });
async function report(models, props = {}) {
  return probe(endpoint, { fetchImpl: async url => Response.json(url.endsWith('/props') ? props : { data: models }) });
}

test('engine/family defaults expose distinct Qwen3.8 modes and record their assumed provenance', async () => {
  for (const [engine, profile, xhigh] of [['ds4.c', 'dwarfstar-qwen', 'high'], ['gufo', 'gufo-qwen', 'xhigh'], ['llamacpp', 'llama-qwen', 'xhigh']]) {
    const r = await report([metadata('Qwen3.8-Flash-Next-UD-Q4_K_XL', engine)]);
    assert.equal(r.models[0].thinkingProfile, profile);
    assert.match(r.models[0].thinkingEvidence, /family default.*unverified/);
    const result = reconcile({}, state(), [r]);
    const m = provider(result).models[0];
    assert.equal(m.reasoning, true);
    assert.equal(m.thinkingLevelMap.xhigh, xhigh);
    assert.equal(m.thinkingLevelMap.high, null);
    assert.equal(m.compat.thinkingFormat, 'chat-template');
    assert.deepEqual(m.compat.chatTemplateKwargs.enable_thinking, { $var: 'thinking.enabled' });
    assert.deepEqual(result.manifest.entries[providerId(endpoint)].thinking[m.id], { source: 'default', profile });
    assert.match(result.warnings[0].reason, /unverified/);
  }
});

test('DeepSeek defaults use named effort controls and account for engine differences', async () => {
  const cases = [
    ['DeepSeek-V4-Flash-0731-IQ2XXS', 'ds4.c', 'dwarfstar-deepseek-v4', { high: 'high', low: null, max: null }],
    ['DeepSeek-V4-Flash-0731-IQ2XXS', 'gufo', 'gufo-deepseek-v4', { low: 'low', high: 'high', max: 'max' }],
    ['deepseek-v4.1-flash', 'ds4.c', 'dwarfstar-deepseek41', { low: 'low', medium: 'medium', high: 'high', max: 'max' }],
  ];
  for (const [id, engine, expected, levels] of cases) {
    const r = await report([metadata(id, engine)]);
    assert.equal(r.models[0].thinkingProfile, expected);
    const m = provider(reconcile({}, state(), [r])).models[0];
    for (const [level, value] of Object.entries(levels)) assert.equal(m.thinkingLevelMap[level], value);
  }
  assert.equal(thinkingConfig('dwarfstar-deepseek-v4', undefined, 393216).thinkingLevelMap.max, 'max');
  assert.equal((await report([metadata('deepseek-v4.1-flash', 'gufo')])).models[0].thinkingProfile, null);
});

test('classic Qwen3 toggles thinking; unknown engines/templates and thinking-only variants stay unknown', async () => {
  const r = await report([metadata('Qwen3-32B-Q4_K_M', 'llamacpp')]);
  assert.equal(r.models[0].thinkingProfile, 'llama-thinking-toggle');
  assert.deepEqual(thinkingConfig(r.models[0].thinkingProfile).compat.chatTemplateKwargs, { enable_thinking: { $var: 'thinking.enabled' } });
  for (const [id, engine] of [['Qwen3.8-Flash-Next', 'unknown'], ['Qwen3-32B-Thinking-2507', 'llamacpp'], ['Qwen3-Coder-Next', 'llamacpp'], ['DeepSeek-R1', 'llamacpp']]) {
    const result = reconcile({}, state(), [await report([metadata(id, engine)])]);
    assert.equal(provider(result).models[0].reasoning, false);
    assert.match(result.warnings[0].reason, /unknown/);
  }
  const router = await report([metadata('Qwen3.8-27B', undefined), metadata('other', undefined)], { chat_template: 'template' });
  assert.equal(router.models[0].thinkingProfile, null, 'generic router props cannot identify every model template');
  const alias = await report([metadata('qwen3.8-flash-next', 'ds4.c', { name: 'DeepSeek-V4.1-Flash' })]);
  assert.equal(alias.models[0].thinkingProfile, 'dwarfstar-deepseek41');
  const display = await report([metadata('deepseek-v4.1-flash', 'ds4.c', { name: 'DeepSeek V4.1 Flash' })]);
  assert.equal(display.models[0].thinkingProfile, 'dwarfstar-deepseek41');
});

test('managed reasoning:false defaults migrate; defaults follow engine changes and remain idempotent', async () => {
  const oldReport = { endpoint, status: 'model-list', models: [{ id: 'Qwen3.8-Flash-Next', contextWindow: 262144, imageSupport: false }] };
  const old = reconcile({}, state(), [oldReport]);
  delete old.manifest.entries[providerId(endpoint)].thinking; // pre-thinking sidecar
  const r = await report([metadata('Qwen3.8-Flash-Next', 'gufo')]);
  const migrated = reconcile(old.config, old.manifest, [r]);
  assert.equal(provider(migrated).models[0].reasoning, true);
  assert.equal(reconcile(migrated.config, migrated.manifest, [r]).changes.length, 0);
  const changed = reconcile(migrated.config, migrated.manifest, [await report([metadata('Qwen3.8-Flash-Next', 'ds4.c')])]);
  assert.equal(provider(changed).models[0].thinkingLevelMap.xhigh, 'high');
  const unknown = reconcile(changed.config, changed.manifest, [oldReport]);
  assert.equal(provider(unknown).models[0].reasoning, false);
  assert.equal(provider(unknown).models[0].thinkingLevelMap, undefined);
});

test('adopted custom model/provider controls survive; exact overrides replace only selected thinking controls', async () => {
  const id = 'Qwen3.8-Flash-Next';
  const r = await report([metadata(id, 'gufo')]);
  for (const custom of [{ reasoning: false }, { reasoning: true, thinkingLevelMap: { off: null, high: 'custom' }, compat: { thinkingFormat: 'openai' } }]) {
    const original = { providers: { manual: { baseUrl: `${endpoint}/v1`, models: [{ id, ...custom, samplingParams: { temperature: 0.6 } }] } } };
    const result = reconcile(original, state(), [r], { adoptLocal: true });
    const m = provider(result).models[0];
    for (const [key, value] of Object.entries(custom)) assert.deepEqual(m[key], value);
    assert.deepEqual(m.samplingParams, { temperature: 0.6 });
    assert.equal(result.manifest.entries[providerId(endpoint)].thinking[id].source, 'preserved');
    const overridden = reconcile(result.config, result.manifest, [r], { thinkingOverrides: [{ endpoint, model: id, profile: 'gufo-qwen', thinkingLevelMap: { off: 'none', high: 'xhigh' } }] });
    assert.equal(provider(overridden).models[0].reasoning, true);
    assert.equal(provider(overridden).models[0].thinkingLevelMap.high, 'xhigh');
    assert.equal(provider(overridden).models[0].thinkingLevelMap.low, null);
    assert.deepEqual(provider(overridden).models[0].samplingParams, { temperature: 0.6 });
  }
  const inherited = { providers: { manual: { baseUrl: `${endpoint}/v1`, compat: { thinkingFormat: 'deepseek', supportsReasoningEffort: true }, models: [{ id, reasoning: true }] } } };
  const result = reconcile(inherited, state(), [r], { adoptLocal: true });
  assert.equal(provider(result).models[0].compat, undefined);
  assert.deepEqual(provider(result).compat, inherited.providers.manual.compat);
  const disabled = reconcile(result.config, result.manifest, [r], { thinkingOverrides: [{ endpoint, model: id, profile: 'disabled' }] });
  assert.equal(provider(disabled).models[0].reasoning, false);
});

test('overrides validate exact loopback identities and reject invalid maps before reconciliation', () => {
  const valid = { endpoint: `${endpoint}/`, model: 'alias', profile: 'gufo-qwen' };
  assert.equal(validateThinkingOverrides([valid])[0].endpoint, endpoint);
  for (const changes of [{ endpoint: 'https://localhost:8000' }, { endpoint: 'http://example.com:8000' }, { endpoint: `${endpoint}/v1` }, { model: '' }, { profile: 'guess' }, { thinkingLevelMap: { low: 25 } }, { thinkingLevelMap: { bogus: 'high' } }, { profile: 'disabled', thinkingLevelMap: { high: 'high' } }]) {
    assert.throws(() => validateThinkingOverrides([{ ...valid, ...changes }]));
  }
  assert.throws(() => validateThinkingOverrides([valid, valid]), /Duplicate/);
});
