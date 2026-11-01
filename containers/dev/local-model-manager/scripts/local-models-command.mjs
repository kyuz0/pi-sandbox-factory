import { readFile, mkdir, open, rename, unlink, lstat } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { expandTargets, scan } from './discover-local-models.mjs';
import { DEFAULT_MAX_TOKENS } from './model-limits.mjs';
import { isLocalEndpoint, syncFile } from './sync-local-models.mjs';
import { validateThinkingOverrides } from './thinking.mjs';

export const defaults = Object.freeze({ host: 'local-model.internal', ports: '8000', maxTokens: DEFAULT_MAX_TOKENS });
const help = '/local-models preview — scan and show proposed changes\n/local-models refresh — scan, adopt existing local entries, save models.json and refresh Pi\n/local-models ports 8000-8009,8080-8089 — save scan ranges\n/local-models status — show configuration and target';

function validate(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('Invalid local-pi-models.json');
  if (Object.keys(config).some(key => !['host', 'ports', 'maxTokens', 'thinkingOverrides'].includes(key))) throw new Error('Unsupported local model configuration field');
  const settings = { ...defaults, ...config };
  if (typeof settings.host !== 'string' || typeof settings.ports !== 'string') throw new Error('host and ports must be strings');
  const targets = expandTargets(settings.host, settings.ports);
  if (!targets.every(isLocalEndpoint)) throw new Error('Refresh supports loopback hosts or local-model.internal:8000');
  if (!Number.isSafeInteger(settings.maxTokens) || settings.maxTokens < 1) throw new Error('maxTokens must be a positive integer');
  if (settings.thinkingOverrides !== undefined) settings.thinkingOverrides = validateThinkingOverrides(settings.thinkingOverrides);
  return settings;
}
export async function readSettings(file) {
  try {
    const stat = await lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Refusing non-regular local model configuration');
    return validate(JSON.parse(await readFile(file, 'utf8')));
  } catch (error) { if (error.code === 'ENOENT') return { ...defaults }; throw error; }
}
async function saveSettings(file, settings) {
  validate(settings);
  await mkdir(dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${randomUUID()}.tmp`;
  let handle;
  try {
    handle = await open(temporary, 'wx', 0o600);
    await handle.writeFile(`${JSON.stringify(settings, null, 2)}\n`);
    await handle.sync(); await handle.close(); handle = null;
    await rename(temporary, file);
  } finally {
    await handle?.close();
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

export function formatResult(result) {
  const lines = [`Local models ${result.mode}: ${result.target}`];
  for (const change of result.changes) {
    lines.push(`${change.action}: ${change.previousProvider ? `${change.previousProvider} → ` : ''}${change.provider}${change.endpoint ? ` (${change.endpoint})` : ''}${change.reason ? `: ${change.reason}` : ''}`);
    for (const model of change.models ?? []) lines.push(`  ${model.id}: context ${model.contextWindow}, output ${model.maxTokens}, input ${model.input.join('+')}${model.reasoning !== undefined ? `, thinking ${model.reasoning ? (model.thinkingLevels?.join('/') || 'custom') : 'disabled'} (${model.thinking?.profile ?? model.thinking?.source ?? 'unknown'})` : ''}`);
  }
  if (!result.changes.length) lines.push('No model changes.');
  for (const warning of result.warnings) lines.push(`Warning: ${warning.endpoint ?? warning.provider}${warning.model ? ` / ${warning.model}` : ''}: ${warning.reason}`);
  for (const conflict of result.conflicts) lines.push(`Conflict: ${conflict.provider}: ${conflict.reason}`);
  if (result.backup) lines.push(`Backup: ${result.backup}`);
  return lines.join('\n');
}

export function registerLocalModels(pi, { getAgentDir, scanModels = scan, syncModels = syncFile } = {}) {
  let busy = false;
  const show = content => pi.sendMessage({ customType: 'local-models', content, display: true, details: {} }, { triggerTurn: false });
  pi.registerCommand('local-models', {
    description: 'Preview or refresh local models.json; configure scan ports',
    getArgumentCompletions: prefix => ['preview', 'refresh', 'ports', 'status', 'help'].filter(value => value.startsWith(prefix)).map(value => ({ value, label: value })),
    handler: async (args, ctx) => {
      const [action = 'help', ...rest] = args.trim().split(/\s+/).filter(Boolean);
      if (action === 'help') { show(help); return; }
      if (!['ports', 'status', 'preview', 'refresh'].includes(action)) { ctx.ui.notify(`Unknown local-models action.\n${help}`, 'error'); return; }
      if (busy) { ctx.ui.notify('A local-models command is already running.', 'warning'); return; }
      busy = true;
      let written = false;
      try {
        const agentDir = getAgentDir(), configFile = join(agentDir, 'local-pi-models.json'), target = join(agentDir, 'models.json');
        const settings = await readSettings(configFile);
        if (action === 'ports') {
          if (rest.length !== 1) throw new Error('Usage: /local-models ports 8000-8009,8080-8089');
          await saveSettings(configFile, { ...settings, ports: rest[0] });
          show(`Saved scan ports: ${rest[0]}\nConfig: ${configFile}\nRun /local-models preview or /local-models refresh.`); return;
        }
        if (rest.length) throw new Error(`Usage: /local-models ${action}`);
        const targets = expandTargets(settings.host, settings.ports);
        if (action === 'status') {
          show(`Host: ${settings.host}\nPorts: ${settings.ports}\nTargets: ${targets.length}\nOutput allowance: ${settings.maxTokens}\nThinking: engine/model-family defaults; ${settings.thinkingOverrides?.length ?? 0} exact overrides\nModels: ${target}\nConfig: ${configFile}`); return;
        }
        if (!ctx.isIdle()) throw new Error('Wait for the current Pi turn to finish before refreshing models');
        ctx.ui.notify(`Scanning ${targets.length} configured local endpoints…`, 'info');
        const reports = await scanModels(targets);
        const result = await syncModels(target, reports, { write: action === 'refresh', adoptLocal: true, maxTokens: settings.maxTokens, ...(settings.thinkingOverrides !== undefined ? { thinkingOverrides: settings.thinkingOverrides } : {}) });
        written = action === 'refresh';
        show(formatResult(result));
        if (written) {
          const providers = [...new Set(result.changes.flatMap(change => [change.provider, ...(change.previousProvider ? [change.previousProvider] : [])]))];
          if (providers.length) {
            if (typeof ctx.modelRegistry.refresh !== 'function') throw new Error('This Pi release needs /model to reload the saved file');
            const refreshed = await ctx.modelRegistry.refresh({ providers, allowNetwork: false, signal: AbortSignal.timeout(15000) });
            if (refreshed?.aborted || refreshed?.errors?.size) throw new Error('Pi model registry refresh did not complete; open /model to reload');
          }
          ctx.ui.notify('Local model refresh complete. Use /model to select a model.', result.conflicts.length ? 'warning' : 'info');
        }
      } catch (error) {
        ctx.ui.notify(`${written ? 'models.json was saved, but Pi reload failed: ' : 'Local model refresh failed: '}${error.message}`, 'error');
      } finally { busy = false; }
    },
  });
}
