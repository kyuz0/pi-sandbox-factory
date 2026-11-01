#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { isDeepStrictEqual, parseArgs } from 'node:util';
import { readFile, lstat, open, rename, unlink, mkdir } from 'node:fs/promises';
import { dirname, resolve, join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';
import { expandTargets, scan } from './discover-local-models.mjs';
import { DEFAULT_MAX_TOKENS } from './model-limits.mjs';
import { validateThinkingOverrides, thinkingConfig, hasExplicitThinking, applyThinking } from './thinking.mjs';

const object = value => value && typeof value === 'object' && !Array.isArray(value);
const hash = value => createHash('sha256').update(value).digest('hex');
const encode = value => `${JSON.stringify(value, null, 2)}\n`;
export function isLocalEndpoint(endpoint) {
  const url = new URL(endpoint);
  if (url.protocol === 'http:' && url.hostname === 'local-model.internal' && !url.username && !url.password) return true;
  const host = url.hostname;
  return host === 'localhost' || host === '[::1]' || /^127\.(?:\d{1,3}\.){2}\d{1,3}$/.test(host);
}
export function providerId(endpoint) { return `local-lab-${hash(endpoint).slice(0, 16)}`; }

export function reconcile(config, manifest, reports, { adoptLocal = false, maxTokens = DEFAULT_MAX_TOKENS, thinkingOverrides = [] } = {}) {
  if (!object(config) || config.providers !== undefined && !object(config.providers)) throw new Error('Invalid models.json providers');
  if (!object(manifest) || manifest.version !== 1 || !object(manifest.entries)) throw new Error('Invalid ownership manifest');
  if (!Number.isSafeInteger(maxTokens) || maxTokens < 1) throw new Error('maxTokens must be a positive integer');
  const overrides = validateThinkingOverrides(thinkingOverrides);
  const next = structuredClone(config), state = structuredClone(manifest);
  next.providers ??= {};
  const changes = [], warnings = [], conflicts = [];
  const seen = new Set();
  for (const report of reports) {
    if (!isLocalEndpoint(report.endpoint)) throw new Error('Model sync currently accepts literal loopback endpoints or the configured host-model gateway');
    if (seen.has(report.endpoint)) throw new Error('Duplicate endpoint report');
    seen.add(report.endpoint);
    const owned = Object.entries(state.entries).filter(([, e]) => e.endpoint === report.endpoint).map(([id]) => id);
    const adopt = adoptLocal ? Object.entries(next.providers).filter(([id, p]) => {
      if (state.entries[id] || !object(p)) return false;
      try { const url = new URL(p.baseUrl); return isLocalEndpoint(url.href) && url.href.replace(/\/$/, '') === `${report.endpoint}/v1`; } catch { return false; }
    }).map(([id]) => id) : [];
    const ids = [...owned, ...adopt];
    if (ids.length > 1 && adopt.length) {
      conflicts.push({ provider: ids.join(', '), reason: 'Multiple provider configurations share this endpoint; resolve their settings before adoption' });
      continue;
    }
    if (!ids.length) {
      const existing = Object.entries(next.providers).filter(([, p]) => p?.baseUrl?.replace(/\/$/, '') === `${report.endpoint}/v1`);
      if (existing.length) {
        conflicts.push({ provider: existing.map(([id]) => id).join(', '), reason: 'Existing local provider is unowned; use --adopt-local to refresh it' });
        continue;
      }
      ids.push(providerId(report.endpoint));
    }
    for (const id of ids) {
      const previous = next.providers[id], entry = state.entries[id];
      if (entry && !isDeepStrictEqual(previous, entry.generated) || previous && !entry && !adopt.includes(id)) {
        conflicts.push({ provider: id, reason: 'Existing or edited provider is user-owned; left unchanged' }); continue;
      }
      if (entry && previous?.baseUrl !== `${report.endpoint}/v1`) {
        conflicts.push({ provider: id, reason: 'Owned provider endpoint changed; left unchanged' }); continue;
      }
      if (report.status === 'closed' || report.status === 'empty-model-list') {
        if (previous) {
          delete next.providers[id]; delete state.entries[id];
          changes.push({ provider: id, action: 'remove', reason: report.status });
        }
        continue;
      }
      if (report.status !== 'model-list') {
        if (previous) warnings.push({ provider: id, reason: `${report.status}; retained last known models` });
        continue;
      }
      if (!Array.isArray(report.models) || new Set(report.models.map(m => m.id)).size !== report.models.length) throw new Error('Invalid discovery report');
      if (report.models.some(m => !['unknown', 'loaded', 'ready', 'running'].includes(m.availability ?? 'unknown'))) {
        warnings.push({ provider: id, reason: 'Model availability is transitional or unknown; retained provider' }); continue;
      }
      const destination = adopt.includes(id) ? providerId(report.endpoint) : id;
      const models = [];
      const thinking = {};
      for (const model of report.models) {
        if (!Number.isSafeInteger(model.contextWindow) || model.contextWindow < 1) {
          warnings.push({ provider: destination, endpoint: report.endpoint, model: model.id, reason: 'Context unknown; new entry skipped or previous entry retained' });
          const old = previous?.models?.find(m => m.id === model.id);
          if (old) {
            models.push(structuredClone(old));
            thinking[model.id] = entry?.thinking?.[model.id] ?? { source: 'preserved' };
          }
          continue;
        }
        if (model.imageSupport === null || model.imageSupport === undefined) warnings.push({ provider: destination, endpoint: report.endpoint, model: model.id, reason: 'Image support unknown; emitted text-only input' });
        const old = previous?.models?.find(m => m.id === model.id);
        let generatedModel = { ...old, id: model.id, name: old?.name ?? model.id, contextWindow: model.contextWindow,
          maxTokens: Math.min(maxTokens, model.contextWindow, model.maxCompletionTokensAdvertised ?? maxTokens),
          input: model.imageSupport === true ? ['text', 'image'] : ['text'], reasoning: old?.reasoning ?? false,
          cost: old?.cost ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
        const override = overrides.find(item => item.endpoint === report.endpoint && item.model === model.id);
        // Older managed entries emitted only reasoning:false. Upgrade that
        // generated default, while preserving explicit settings on adoption.
        const priorSource = entry?.thinking?.[model.id]?.source;
        const legacyDefault = entry && !priorSource && old?.reasoning === false && !old.thinkingLevelMap && !hasExplicitThinking({ compat: old.compat }, previous);
        const custom = hasExplicitThinking(old, previous) && priorSource !== 'default' && priorSource !== 'override' && !legacyDefault;
        const selected = override?.profile ?? (!custom ? model.thinkingProfile : null);
        if (selected) {
          generatedModel = applyThinking(generatedModel, thinkingConfig(selected, override?.thinkingLevelMap, model.contextWindow));
          thinking[model.id] = { source: override ? 'override' : 'default', profile: selected };
          if (!override && model.thinkingWarning) warnings.push({ provider: destination, endpoint: report.endpoint, model: model.id, reason: model.thinkingWarning });
        } else if (custom) thinking[model.id] = { source: 'preserved' };
        else {
          generatedModel = applyThinking(generatedModel, thinkingConfig('disabled'));
          thinking[model.id] = { source: 'default', profile: null };
          warnings.push({ provider: destination, endpoint: report.endpoint, model: model.id, reason: model.thinkingWarning ?? 'Thinking controls unknown; no family default applied' });
        }
        models.push(generatedModel);
      }
      if (!models.length) continue;
      if (destination !== id && next.providers[destination]) {
        conflicts.push({ provider: id, reason: 'Endpoint provider identity already exists; left unchanged' }); continue;
      }
      const generated = { ...previous, baseUrl: `${report.endpoint}/v1`, api: 'openai-completions', apiKey: previous?.apiKey ?? 'not-needed',
        compat: previous?.compat ?? { supportsDeveloperRole: false, supportsReasoningEffort: false }, models };
      // An adopted provider label describes old configuration, not the current server.
      if (destination !== id) delete generated.name;
      if (!isDeepStrictEqual(previous, generated)) {
        changes.push({ provider: destination, endpoint: report.endpoint, action: destination !== id ? 'replace' : previous ? 'update' : 'add',
          ...(destination !== id ? { previousProvider: id } : {}),
          models: models.map(m => ({ id: m.id, input: m.input, contextWindow: m.contextWindow, maxTokens: m.maxTokens,
            reasoning: m.reasoning, thinking: thinking[m.id],
            thinkingLevels: Object.entries(m.thinkingLevelMap ?? {}).filter(([, value]) => value !== null).map(([level]) => level) })) });
      }
      // Migration itself is a change even when all provider fields match.
      else if (destination !== id) changes.push({ provider: destination, endpoint: report.endpoint, action: 'replace', previousProvider: id });
      if (destination !== id) { delete next.providers[id]; delete state.entries[id]; }
      next.providers[destination] = generated;
      state.entries[destination] = { endpoint: report.endpoint, generated: structuredClone(generated), evidence: structuredClone(report.models), thinking };
    }
  }
  return { config: next, manifest: state, changes, warnings, conflicts };
}

async function readOptional(file) {
  try {
    const stat = await lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Refusing non-regular file: ${file}`);
    return await readFile(file, 'utf8');
  } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
async function atomic(file, content) {
  const temporary = `${file}.${randomUUID()}.tmp`;
  const handle = await open(temporary, 'wx', 0o600);
  try { await handle.writeFile(content); await handle.sync(); }
  finally { await handle.close(); }
  try {
    await rename(temporary, file);
    const directory = await open(dirname(file), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  } finally { await unlink(temporary).catch(e => { if (e.code !== 'ENOENT') throw e; }); }
}
async function recover(target, stateFile, journalFile) {
  const raw = await readOptional(journalFile);
  if (!raw) return false;
  const journal = JSON.parse(raw);
  if (journal.target !== target || journal.stateFile !== stateFile || typeof journal.afterConfig !== 'string' || typeof journal.afterState !== 'string') throw new Error('Invalid recovery journal');
  const current = await readOptional(target), state = await readOptional(stateFile);
  if (current !== journal.beforeConfig && current !== journal.afterConfig || state !== journal.beforeState && state !== journal.afterState) throw new Error('Interrupted sync conflicts with later edits; restore backup manually');
  if (current === journal.afterConfig) await atomic(stateFile, journal.afterState);
  // If config never committed, ownership never changed.
  else if (state !== journal.beforeState) throw new Error('Interrupted sync state inconsistent');
  await unlink(journalFile);
  return true;
}

export async function syncFile(target, reports, options = {}) {
  target = resolve(target);
  const stateFile = `${target}.local-lab-state.json`, journalFile = `${target}.local-lab-journal.json`, lockFile = `${target}.local-lab.lock`;
  if (options.write) await mkdir(dirname(target), { recursive: true, mode: 0o700 });
  let lock;
  try {
    if (options.write) lock = await open(lockFile, 'wx', 0o600);
    const journal = await readOptional(journalFile);
    if (journal && !options.write) throw new Error('Interrupted sync pending; use --write to recover before preview');
    if (journal) await recover(target, stateFile, journalFile);
    const beforeConfig = await readOptional(target), beforeState = await readOptional(stateFile);
    const result = reconcile(beforeConfig === null ? {} : JSON.parse(beforeConfig), beforeState === null ? { version: 1, entries: {} } : JSON.parse(beforeState), reports, options);
    const afterConfig = encode(result.config), afterState = encode(result.manifest);
    let backup = null;
    if (options.write && (result.changes.length || beforeState !== afterState && Object.keys(result.manifest.entries).length)) {
      if (await readOptional(target) !== beforeConfig || await readOptional(stateFile) !== beforeState) throw new Error('Configuration changed during sync; rerun preview');
      const suffix = `${Date.now()}-${randomUUID()}`;
      if (beforeConfig !== null) { backup = `${target}.${suffix}.bak`; await atomic(backup, beforeConfig); }
      if (beforeState !== null) await atomic(`${stateFile}.${suffix}.bak`, beforeState);
      await atomic(journalFile, encode({ target, stateFile, beforeConfig, beforeState, afterConfig, afterState }));
      // Check again after preparing the journal; external writers do not honor our lock.
      if (await readOptional(target) !== beforeConfig || await readOptional(stateFile) !== beforeState) {
        await unlink(journalFile); throw new Error('Configuration changed before commit; rerun preview');
      }
      await atomic(target, afterConfig);
      await atomic(stateFile, afterState);
      await unlink(journalFile);
    }
    return { target, mode: options.write ? 'write' : 'preview', changes: result.changes, warnings: result.warnings, conflicts: result.conflicts, backup };
  } finally { if (lock) { await lock.close(); await unlink(lockFile); } }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { values } = parseArgs({ options: { host: { type: 'string' }, ports: { type: 'string' }, target: { type: 'string' }, write: { type: 'boolean' }, 'adopt-local': { type: 'boolean' }, 'max-tokens': { type: 'string' }, 'thinking-overrides': { type: 'string' } } });
    if (!values.host || !values.ports) throw new Error('Supply --host localhost --ports 8000-8009,8080-8089; preview is default; --write applies it');
    const targets = expandTargets(values.host, values.ports);
    if (!targets.every(isLocalEndpoint)) throw new Error('Sync supports loopback only; remote configuration remains untouched');
    const target = values.target ?? join(process.env.PI_CODING_AGENT_DIR ?? join(homedir(), '.pi/agent'), 'models.json');
    const thinkingOverrides = values['thinking-overrides'] ? validateThinkingOverrides(JSON.parse(await readFile(values['thinking-overrides'], 'utf8'))) : [];
    const reports = await scan(targets);
    console.log(JSON.stringify(await syncFile(target, reports, { write: values.write, adoptLocal: values['adopt-local'], maxTokens: values['max-tokens'] ? Number(values['max-tokens']) : DEFAULT_MAX_TOKENS, thinkingOverrides }), null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
