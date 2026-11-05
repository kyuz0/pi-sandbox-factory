import {readFile, writeFile, rename} from 'node:fs/promises';
import {join} from 'node:path';

// Example for a text-only model with a documented 128K context and 16K output.
// Replace these limits and capabilities with those of your service.
export async function run({action, agentDir, settings, secret}) {
  const file = join(agentDir, 'models.json');
  let config;
  try { config = JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; config = {}; }
  const previous = config.providers?.company;
  const apiKey = secret || previous?.apiKey;
  if (!apiKey) return {state: 'needs-auth', message: 'Enter the company API key.'};
  if (action === 'status') return {state: 'ready', message: 'Credential saved; connectivity has not been checked.'};
  if (!settings.endpoint || !settings.model) return {state: 'error', message: 'Set the endpoint and model ID in Configuration.'};
  const response = await fetch(settings.endpoint.replace(/\/$/, '') + '/models', {
    headers: {Authorization: `Bearer ${apiKey}`}, redirect: 'error', signal: AbortSignal.timeout(30000)
  });
  if ([401, 403].includes(response.status)) return {state: 'needs-auth', message: 'The service rejected the key.'};
  if (!response.ok) return {state: 'error', message: `Model listing returned HTTP ${response.status}.`};
  const catalogue = await response.json();
  if (!catalogue.data?.some(model => model.id === settings.model)) return {state: 'error', message: 'Model ID was not found in the catalogue.'};
  if (action === 'preview') return {state: 'ready', message: `Would configure ${settings.model}.`};
  config.providers ??= {};
  config.providers.company = {
    baseUrl: settings.endpoint, api: 'openai-completions', apiKey,
    models: [{id: settings.model, name: settings.model, input: ['text'], reasoning: false,
      contextWindow: 131072, maxTokens: 16384, cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0}}]
  };
  const temporary = file + '.company-new';
  await writeFile(temporary, JSON.stringify(config, null, 2) + '\n', {mode: 0o600, flag: 'wx'});
  await rename(temporary, file);
  return {state: 'ready', message: `Configured ${settings.model}.`, changed: true};
}
