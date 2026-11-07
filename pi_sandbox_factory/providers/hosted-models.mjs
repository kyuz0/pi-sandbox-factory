// Executed in the sandbox. Requests arrive on stdin; replies never contain credentials.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
import {locked} from '/opt/sandbox/provider-lock.mjs';
const root = process.env.FACTORY_PI_RUNTIME || '/usr/local/lib/node_modules/@earendil-works/pi-coding-agent';
const {AuthStorage, readStoredCredential} = await import(pathToFileURL(root + '/dist/core/auth-storage.js'));
const {ModelRuntime} = await import(pathToFileURL(root + '/dist/core/model-runtime.js'));
const {SettingsManager} = await import(pathToFileURL(root + '/dist/core/settings-manager.js'));
const {stripJsonComments} = await import(pathToFileURL(root + '/dist/utils/json.js'));
const {configureHttpDispatcher} = await import(pathToFileURL(root + '/dist/core/http-dispatcher.js'));
configureHttpDispatcher();
const dir = process.env.PI_CODING_AGENT_DIR || path.join(os.homedir(), '.pi/agent');
const authPath = path.join(dir, 'auth.json');
const modelsPath = path.join(dir, 'models.json');
const ids = ['openrouter', 'together', 'azure', 'amazon-bedrock'];
const auth = AuthStorage.create(authPath);
const read = (file, fallback = {}) => fs.existsSync(file) ? JSON.parse(stripJsonComments(fs.readFileSync(file, 'utf8'))) : fallback;
function write(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
  const temp = file + '.' + process.pid + '.tmp';
  try { fs.writeFileSync(temp, typeof value === 'string' ? value : JSON.stringify(value, null, 2) + '\n', {mode: 0o600}); fs.renameSync(temp, file); }
  finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}
const runtime = () => ModelRuntime.create({authPath, modelsPath, modelsStorePath: path.join(dir, 'models-store.json'), allowModelNetwork: false});
function status(id) {
  const c = readStoredCredential(id, authPath);
  return {provider: id, configured: !!c, has_key: !!c?.key};
}
function safeModel(model) {
  return {id: model.id, name: model.name, api: model.api, contextWindow: model.contextWindow,
    maxTokens: model.maxTokens, reasoning: model.reasoning, input: model.input};
}
async function main(r) {
  if (r.action === 'status') return {providers: ids.map(status)};
  if (!ids.includes(r.provider)) throw Error('Unsupported provider.');
  const id = r.provider;
  if (r.action === 'configure') {
    if (!r.endpoint?.startsWith('http://127.0.0.1:19431/r/'+id)) throw Error('Invalid inference endpoint.');
    const old = readStoredCredential(id, authPath);
    const env = {};
    if (id === 'azure') {
      env.AZURE_OPENAI_BASE_URL = r.endpoint;
      if (old?.env?.AZURE_OPENAI_DEPLOYMENT_NAME_MAP) env.AZURE_OPENAI_DEPLOYMENT_NAME_MAP = old.env.AZURE_OPENAI_DEPLOYMENT_NAME_MAP;
    }
    if (id === 'amazon-bedrock') Object.assign(env,{AWS_REGION:r.region,AWS_BEDROCK_SKIP_AUTH:'1',AWS_BEDROCK_FORCE_HTTP1:'1'});
    await auth.modify(id,async () => ({type:'api_key',key:'factory-inference',env}));
    const config = read(modelsPath, {providers:{}});
    config.providers ||= {};
    const provider = config.providers[id] ||= {};
    provider.baseUrl = r.endpoint;
    provider.apiKey = 'factory-inference';
    for (const model of provider.models || []) model.baseUrl = r.endpoint;
    write(modelsPath,config);
    return status(id);
  }
  if (r.action === 'remove') {
    await auth.delete(id);
    const config=read(modelsPath,{providers:{}});
    if(config.providers?.[id]) delete config.providers[id].apiKey;
    write(modelsPath,config);
    return status(id);
  }
  const rt = await runtime();
  if (r.action === 'catalogue') {
    let warning = '';
    if (r.refresh) {
      try {
        const result = await rt.refresh({providers: [id], allowNetwork: true, force: true, signal: AbortSignal.timeout(20000)});
        if (result.aborted || result.errors?.size) warning = 'Catalogue refresh failed; showing saved models.';
      } catch { warning = 'Catalogue refresh failed; showing saved models.'; }
    }
    return {models: rt.getModels(id).map(safeModel), warning};
  }
  const model = rt.getModel(id, r.model);
  if (!model) throw Error('Choose a model from the catalogue.');
  if (r.action === 'select') {
    if (id === 'azure' && r.deployment) {
      if (/[,=\r\n]/.test(r.deployment)) throw Error('Invalid Azure deployment name.');
      await auth.modify(id, async current => {
        if (!current) throw Error('Configure the provider first.');
        const env = {...current.env};
        const map = new Map((env.AZURE_OPENAI_DEPLOYMENT_NAME_MAP || '').split(',').filter(Boolean).map(s => s.split('=')));
        map.set(model.id, r.deployment);
        env.AZURE_OPENAI_DEPLOYMENT_NAME_MAP = [...map].map(([k,v]) => `${k}=${v}`).join(',');
        return {...current, env};
      });
    }
    let chosen = model.id;
    if (id === 'amazon-bedrock' && r.profile_id && r.profile_id !== model.id) {
      chosen = r.profile_id;
      const config = read(modelsPath, {providers: {}});
      config.providers ||= {};
      const provider = config.providers[id] ||= {};
      provider.models ||= [];
      // Copy the selected model's actual metadata, including API compatibility.
      const {provider: ignored, ...definition} = model;
      provider.models = provider.models.filter(m => m.id !== chosen);
      provider.models.push({...definition, id: chosen, name: model.name + ' · ' + chosen});
      write(modelsPath, config);
    }
    const settings = SettingsManager.create('/workspace', dir);
    settings.setDefaultModelAndProvider(id, chosen);
    await settings.flush();
    if (settings.drainErrors().length) throw Error("Could not save the default model.");
    return {provider: id, model: chosen};
  }
  if (r.action === 'test') {
    const testModel = id === 'amazon-bedrock' && r.profile_id ? {...model, id:r.profile_id} : model;
    const env = id === 'azure' && r.deployment ? {AZURE_OPENAI_DEPLOYMENT_NAME_MAP: `${model.id}=${r.deployment}`} : undefined;
    const reply = await rt.completeSimple(testModel, {messages: [{role:'user', content:'Reply with OK.', timestamp:Date.now()}]}, {env, maxTokens: 64, signal: AbortSignal.timeout(45000)});
    if (reply.stopReason === 'error' || reply.stopReason === 'aborted') {
      const reason = String(reply.errorMessage || 'Check model access, endpoint and network settings.').replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 600);
      throw Error('The model request failed: ' + reason);
    }
    return {ok: true};
  }
  throw Error('Unknown operation.');
}
let input = '';
try {
  for await (const chunk of process.stdin) {
    input += chunk;
    if(input.length>65536)throw Error('Request too large.');
  }
  console.log(JSON.stringify(await locked(dir,()=>main(JSON.parse(input)))));
} catch (error) {
  // Test requests contain a fixed prompt and placeholder credentials. Other native errors stay private.
  const allowed = ['Enter ', 'Choose ', 'Invalid Azure', 'The model request failed:', 'Configure the provider first.', 'A model refresh is already running.'];
  const message = allowed.some(p => error.message.startsWith(p)) ? error.message : 'Provider operation failed. Check the connection settings and retry.';
  console.log(JSON.stringify({error: message})); process.exitCode = 1;
}
