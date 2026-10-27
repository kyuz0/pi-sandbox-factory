#!/usr/bin/env node
// Initialize the shared model catalogue before an editor or agent session exists.
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';
import { readSettings, formatResult } from './local-models-command.mjs';
import { expandTargets, scan } from './discover-local-models.mjs';
import { syncFile } from './sync-local-models.mjs';

export async function initializeModels(agentDir, { preview = false, scanModels = scan, log = console.log } = {}) {
  const settings = await readSettings(join(agentDir, 'local-pi-models.json'));
  const reports = await scanModels(expandTargets(settings.host, settings.ports));
  const target = join(agentDir, 'models.json');
  const result = await syncFile(target, reports, { write: !preview, adoptLocal: true,
    maxTokens: settings.maxTokens,
    ...(settings.thinkingOverrides !== undefined ? { thinkingOverrides: settings.thinkingOverrides } : {}) });
  log(formatResult(result));
  if (preview) return result;
  let providers = {};
  try { providers = JSON.parse(await readFile(target, 'utf8')).providers ?? {}; }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const usable = reports.flatMap(report => report.status === 'model-list' ? report.models.filter(model =>
    ['unknown','loaded','ready','running'].includes(model.availability ?? 'unknown') &&
    Object.values(providers).some(provider => provider.baseUrl?.replace(/\/$/, '') === report.endpoint+'/v1' &&
      provider.models?.some(saved => saved.id === model.id && Number.isSafeInteger(saved.contextWindow) && saved.contextWindow > 0))
  ) : []);
  if (!usable.length) throw Object.assign(new Error('No usable local model was discovered. Start the server on the configured ports and ensure it reports its context limit (or supply that limit in private model configuration). Use Refresh models in the manager after starting the server.'), { code: 'NO_USABLE_MODEL' });
  log(`Local model catalogue ready: ${usable.map(model => model.id).join(', ')}`);
  return { ...result, models: usable.map(model => model.id) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const args = process.argv.slice(2);
    if (args.some(arg => arg !== '--preview')) throw new Error('Usage: initialize-models.mjs [--preview]');
    await initializeModels(process.env.PI_CODING_AGENT_DIR ?? join(homedir(), '.pi/agent'), { preview: args.includes('--preview') });
  } catch (error) { console.error(error.message); process.exitCode = error.code === 'NO_USABLE_MODEL' ? 3 : 1; }
}
