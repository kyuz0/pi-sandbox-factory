// Exercise the shipped Pendant worker over its own IPC protocol, not the Pi CLI.
const assert = require('node:assert/strict');
const { fork } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const extension = fs.readdirSync('/opt/pendant').find(name => name.startsWith('cdervis.vscode-pi-'));
const directory = path.join('/opt/pendant', extension);
const version = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'))).version;
const sdkVersion = require(path.join(directory, 'dist/pi-sdk.cjs'))['@earendil-works/pi-coding-agent']().VERSION;
const worker = fork(path.join(directory, 'dist/pi-sdk-worker.cjs'), [], {
  cwd: '/workspace', env: process.env, silent: true, serialization: 'advanced',
});
const pending = new Map();
const sessions = new Map();
const diagnostics = [];
let sequence = 0;
let errors = '';
let failure;
worker.stderr.on('data', chunk => { errors = (errors + chunk).slice(-16000); });
worker.stdout.on('data', () => {});
let readyResolve, readyReject;
const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
function fail(error) {
  failure ??= error;
  readyReject(error);
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
  pending.clear();
}
function request(command, sessionKey) {
  if (failure) return Promise.reject(failure);
  const requestId = 'request-' + (++sequence);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(requestId); reject(new Error('Timed out: ' + command.type)); }, 180000);
    pending.set(requestId, { resolve, reject, timer });
    worker.send({ type: 'sdk_bridge_request', requestId, workspaceGeneration: 1,
      ...(sessionKey ? { sessionKey, sessionGeneration: 1 } : {}), command });
  });
}
worker.on('message', message => {
  if (message.type === 'sdk_bridge_ready') return readyResolve(message);
  if (['sdk_worker_failure', 'sdk_bridge_rejected', 'runtime_interrupted'].includes(message.type))
    return fail(new Error(JSON.stringify(message)));
  if (message.type === 'diagnostic') diagnostics.push(message);
  if (message.type === 'sdk_bridge_response') {
    const item = pending.get(message.requestId);
    if (!item) return;
    pending.delete(message.requestId); clearTimeout(item.timer);
    if (message.error) item.reject(new Error(JSON.stringify(message.error)));
    else item.resolve(message.result);
  }
  if (message.type === 'session_event') sessions.get(message.sessionKey)?.events.push(message.event);
  if (message.type === 'extension_ui_request') {
    const session = sessions.get(message.sessionKey);
    try {
      assert(session?.allowDialog, 'Unexpected permission dialog: ' + JSON.stringify(message.request));
      session.dialogs++;
      const prompt = message.request;
      let result;
      if (prompt.kind === 'confirm') result = { type: 'confirmed', confirmed: true };
      else {
        assert.equal(prompt.kind, 'select');
        const value = prompt.options.find(x => x === 'Yes') ?? prompt.options.find(x =>
          /allow|yes/i.test(x) && !/session|always/i.test(x));
        assert(value, 'No one-shot approval choice');
        result = { type: 'value', value };
      }
      request({ type: 'extension_ui_response', uiRequestId: message.uiRequestId, result }, message.sessionKey).catch(fail);
    } catch (error) { fail(error); }
  }
});
worker.on('error', fail);
worker.on('exit', code => { if (pending.size) fail(new Error('Pendant worker exited: ' + code + '\n' + errors)); });
worker.send({ type: 'sdk_worker_bootstrap', protocolVersion: 3, hostVersion: version,
  workspaceId: 'sandbox-integration', workspaceCwd: '/workspace', workspaceGeneration: 1,
  runtimeOwnerGeneration: 1, agentDirectory: '/home/node/.pi/agent', agentDirectorySource: 'explicit',
  offline: false, extensionMode: 'rpc' });
worker.send({ type: 'sdk_bridge_hello', protocolVersion: 3, hostKind: 'vscode', hostVersion: version,
  workspaceId: 'sandbox-integration', workspaceGeneration: 1,
  piSdkPackage: '@earendil-works/pi-coding-agent', piSdkVersion: sdkVersion,
  capabilities: ['sessions', 'models', 'settings', 'packages', 'resources', 'extension_ui'] });

async function create(key, allowDialog = false) {
  sessions.set(key, { events: [], dialogs: 0, allowDialog });
  return request({ type: 'session_create', target: { kind: 'new', cwd: '/workspace' } }, key);
}
async function waitForReply(key, marker) {
  const deadline = Date.now() + 180000;
  let state;
  while (Date.now() < deadline) {
    state = await request({ type: 'session_get_state' }, key);
    if (state.idle && state.messages.some(m => m.role === 'assistant' && JSON.stringify(m.content).includes(marker)))
      return state;
    const last = state.messages.at(-1);
    assert(last?.stopReason !== 'error', JSON.stringify(last));
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Pendant did not finish ' + key + ': ' + JSON.stringify(state));
}
async function main() {
  const readyTimeout = setTimeout(() => fail(new Error('Pendant startup timed out')), 90000);
  let handshake;
  try { handshake = await ready; } finally { clearTimeout(readyTimeout); }
  assert.equal(handshake.compatibilityReport.compatible, true);
  assert.equal(handshake.compatibilityReport.piSdkVersion, sdkVersion);
  const inventory = await create('inventory');
  const commands = new Set(inventory.commands.map(c => c.name));
  assert(commands.has('local-models'), 'Model discovery extension missing');
  if (process.argv.includes('--ssh-live')) {
    const alias = process.env.TEST_SSH_ALIAS;
    assert(/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$/.test(alias ?? ''), 'Set TEST_SSH_ALIAS to an explicitly assigned host');
    assert(inventory.tools.some(t => t.name === 'bash_escalate'), 'Reviewed escalation unavailable');
    await request({ type: 'session_set_model', provider: process.env.TEST_MODEL_PROVIDER, modelId: process.env.TEST_MODEL_ID, persist: false }, 'inventory');
    const command = `ssh -o ConnectTimeout=15 ${alias} 'printf SSH_ACCESS_TEST_OK'`;
    await request({ type: 'session_prompt', text: `Run exactly this read-only connectivity check on my configured SSH host: ${command}. Use bash_escalate because the SSH agent and connection sockets are outside the inner command sandbox. This read-only SSH check is explicitly authorized. Do not modify remote files, install anything, forward the SSH agent or inspect credentials. Report the result.`, images: [], source: 'interactive' }, 'inventory');
    const deadline = Date.now() + 600000;
    let state;
    while (Date.now() < deadline) {
      state = await request({ type: 'session_get_state' }, 'inventory');
      const results = state.messages.filter(m => m.role === 'toolResult');
      if (state.idle && results.length) {
        assert(results.some(r => r.toolName === 'bash_escalate' && !r.isError && JSON.stringify(r.content).includes('SSH_ACCESS_TEST_OK')), 'No successful reviewed SSH result: ' + JSON.stringify(results));
        console.log('PASS live local model selected bash_escalate; reviewer approved; configured SSH host returned the marker');
        return;
      }
      if (state.messages.at(-1)?.stopReason === 'error') throw new Error(JSON.stringify(state.messages.at(-1)));
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error('Live SSH session did not complete; inspect the saved session before retrying');
  }
  if (process.argv.includes('--advisor')) {
    assert(commands.has('advisor'), 'Advisor command missing');
    for (const name of ['advisor_ask', 'advisor_status'])
      assert(inventory.tools.some(t => t.name === name), 'Advisor tool missing: ' + name);
    await request({ type: 'session_prompt', text: '/advisor usage', images: [], source: 'interactive' }, 'inventory');
    const state = await request({ type: 'session_get_state' }, 'inventory');
    assert(!JSON.stringify(state.messages).includes('connection failed'), JSON.stringify(state.messages));
    assert(state.messages.some(m => m.customType === 'advisor-report'), 'Advisor usage response missing');
    console.log('PASS actual Pendant startup: advisor tools, command and remote usage');
    return;
  }
  if (process.argv.includes('--initialized')) {
    const expected = process.env.TEST_INITIAL_MODEL;
    assert(expected, 'Set TEST_INITIAL_MODEL');
    const models = await request({ type: 'models_list', cwd: '/workspace' });
    assert(JSON.stringify(models).includes(expected), 'Initial model absent from fresh Pendant catalogue');
    assert(inventory.model?.id === expected, 'Fresh session did not select the initial model: '+JSON.stringify(inventory.model));
    console.log('PASS fresh actual Pendant startup: initial model available and selected before any slash command');
    return;
  }
  if (process.argv.includes('--discovery')) {
    const file = '/home/node/.pi/agent/models.json';
    const before = fs.readFileSync(file, 'utf8');
    await request({ type: 'session_prompt', text: '/local-models preview', images: [], source: 'interactive' }, 'inventory');
    assert.equal(fs.readFileSync(file, 'utf8'), before, 'Preview wrote models.json');
    await request({ type: 'session_prompt', text: '/local-models refresh', images: [], source: 'interactive' }, 'inventory');
    const state = await request({ type: 'session_get_state' }, 'inventory');
    assert(JSON.stringify(state.messages).includes('Local models'), JSON.stringify(state));
    const models = await request({ type: 'models_list', cwd: '/workspace' });
    assert(JSON.stringify(models).includes('Qwen3.8-27B-UD-Q4_K_XL'), JSON.stringify(models));
    assert(Object.values(JSON.parse(fs.readFileSync(file)).providers).some(p => p.baseUrl === 'http://local-model.internal:8000/v1'));
    console.log('PASS actual Pendant discovery preview, refresh and model catalogue');
    return;
  }
  const selectedOptions = fs.existsSync('/opt/sandbox/options.json')
    ? JSON.parse(fs.readFileSync('/opt/sandbox/options.json')) : {};
  assert.equal(inventory.tools.some(t => t.name === 'browser'), !!selectedOptions.browser);
  if (process.argv.includes('--browser')) {
    await request({ type: 'session_dispose', reason: 'replacement' }, 'inventory');
    for (const scenario of ['ALLOW', 'DENY']) {
      const key = 'browser-' + scenario;
      await create(key);
      await request({ type: 'session_set_model', provider: 'fixture', modelId: 'fixture-model', persist: false }, key);
      await request({ type: 'session_prompt', text: 'RUN_BROWSER_' + scenario, images: [], source: 'interactive' }, key);
      const state = await waitForReply(key, 'BROWSER_DONE');
      const results = state.messages.filter(m => m.role === 'toolResult');
      assert.equal(results.length, scenario === 'ALLOW' ? 3 : 1);
      if (scenario === 'ALLOW') {
        assert(results.every(r => !r.isError), JSON.stringify(results));
        assert(JSON.stringify(results).includes('BROWSER_STATE_OK'));
        assert(JSON.stringify(results).includes('Example Domain'));
        assert(results.some(r => r.content.some(c => c.type === 'image')), 'Screenshot missing');
      } else {
        assert(results[0].isError, 'Denied browser call executed');
        assert(!JSON.stringify(results[0]).includes('DENY_BY_FIXTURE_EXECUTED'));
      }
      await request({ type: 'session_dispose', reason: 'replacement' }, key);
    }
    console.log('PASS Pendant Betterwright: interaction, persistent state, screenshot, navigation, approval denial');
    return;
  }
  if (process.argv.includes('--features')) {
    const selected = JSON.parse(fs.readFileSync('/opt/sandbox/options.json'));
    assert.equal(commands.has('goal'), selected.goals);
    assert.equal(commands.has('schedule-prompt'), selected.scheduling);
    const extras = fs.existsSync('/opt/sandbox/extra-resources.json');
    assert.equal(commands.has('skill:fixture-guide'), extras);
    const bash = inventory.tools.find(t => t.name === 'bash');
    assert.equal(!!bash.source?.path?.includes('/opt/pi-security/'), selected.inner_sandbox);
    assert.equal(inventory.tools.some(t => t.name === 'bash_escalate'), selected.inner_sandbox && selected.approval !== 'off');
    await request({ type: 'session_dispose', reason: 'replacement' }, 'inventory');
    for (const scenario of (selected.inner_sandbox && selected.approval !== 'off' ? ['BASH', 'BOUNDARY'] : ['BASH'])) {
      const key = 'feature-' + scenario;
      const expectDialog = selected.approval === 'manual' && (!selected.inner_sandbox || scenario === 'BOUNDARY');
      await create(key, expectDialog);
      await request({ type: 'session_set_model', provider: 'fixture', modelId: 'fixture-model', persist: false }, key);
      await request({ type: 'session_prompt', text: 'RUN_FEATURE_' + scenario, images: [], source: 'interactive' }, key);
      const state = await waitForReply(key, 'FEATURE_DONE');
      const results = state.messages.filter(m => m.role === 'toolResult');
      const text = JSON.stringify(results);
      assert(text.includes('FEATURE_' + scenario + '_OK') && !results.some(r => r.isError), text);
      if (scenario === 'BASH') assert.equal(text.includes('FEATURE_HOME_READABLE'), !selected.inner_sandbox, text);
      assert.equal(sessions.get(key).dialogs > 0, expectDialog);
      await request({ type: 'session_dispose', reason: 'replacement' }, key);
    }
    console.log('PASS Pendant feature modes: ' + selected.approval + ', inner=' + selected.inner_sandbox);
    return;
  }
  for (const name of ['goal', 'skill:pi-goal-writer',
    'schedule-prompt', 'auto-review-approve', 'auto-review-break-glass', 'auto-review-policy-audit'])
    assert(commands.has(name), 'Missing embedded-Pi command: ' + name);
  assert.equal(commands.has('subagents-guide'), process.env.SANDBOX_SUBAGENTS === '1');
  if (fs.existsSync('/opt/websec/prompts'))
    for (const file of fs.readdirSync('/opt/websec/prompts'))
      if (file.endsWith('.md')) assert(commands.has(file.slice(0, -3)), 'Missing websec phase prompt: ' + file);
  assert(inventory.tools.some(t => t.name === 'bash' && t.source.path.includes('/opt/pi-security/')),
    'Pendant must load sandboxed Bash, not its built-in Bash');
  const models = await request({ type: 'models_list', cwd: '/workspace' });
  if (process.argv.includes('--fresh')) {
    assert.equal(inventory.model, undefined, 'Fresh configuration unexpectedly has a model');
  } else {
    assert(JSON.stringify(models).includes('fixture-model'), 'models.json missing from Pendant catalogue');
  }
  console.log(`PASS actual Pendant ${version} worker (embedded Pi ${sdkVersion}): shared models, extensions, skills, sandboxed Bash`);
  await request({ type: 'session_dispose', reason: 'replacement' }, 'inventory');
  if (process.argv.includes('--fresh')) return;

  if (process.argv.includes('--websec')) {
    for (const outcome of ['ALLOW', 'DENY']) {
      const key = 'websec-' + outcome.toLowerCase();
      await create(key);
      await request({ type: 'session_set_model', provider: 'fixture', modelId: 'fixture-model', persist: false }, key);
      await request({ type: 'session_prompt', text: 'RUN_WEBSEC_MCP_' + outcome,
        images: [], source: 'interactive' }, key);
      const state = await waitForReply(key, 'WEBSEC_REVIEW_DONE');
      const results = state.messages.filter(m => m.role === 'toolResult' &&
        m.toolName === 'mcp__burp__get_proxy_http_history_summary');
      assert.equal(results.length, 1, JSON.stringify(state.messages));
      const text = JSON.stringify(results);
      if (outcome === 'ALLOW') assert(text.includes('WEBSEC_MCP_OK') && !results[0].isError, text);
      else assert(results[0].isError && /denied|blocked/i.test(text) && !text.includes('WEBSEC_MCP_OK'), text);
      assert.equal(sessions.get(key).dialogs, 0);
      await request({ type: 'session_dispose', reason: 'replacement' }, key);
      console.log('PASS actual Pendant worker: host MCP automatic review ' + outcome.toLowerCase());
    }
    return;
  }

  fs.writeFileSync('/tmp/DEFER_BY_FIXTURE.txt', 'Synthetic external-directory permission fixture.');
  const scenarios = ['ALLOW', 'DENY', 'DEFER', 'ESCALATE', 'GOAL', 'SCHEDULE', 'BUSY', 'REJECT'];
  if (process.env.SANDBOX_SUBAGENTS === '1') scenarios.push('SUBAGENT', 'SUBAGENT_ASYNC_DEFER');
  for (const scenario of scenarios) {
    const automation = ['GOAL', 'SCHEDULE', 'BUSY', 'REJECT'].includes(scenario);
    const key = scenario.toLowerCase();
    const expectsDialog = ['DEFER', 'SCHEDULE', 'BUSY', 'SUBAGENT_ASYNC_DEFER'].includes(scenario);
    const initial = await create(key, expectsDialog);
    await request({ type: 'session_set_model', provider: 'fixture', modelId: 'fixture-model', persist: false }, key);
    await request({ type: 'session_prompt', text: `PENDANT_WORKER_FIXTURE RUN_${automation ? 'AUTOMATION' : 'SECURITY'}_${scenario}`,
      images: [], source: 'interactive' }, key);
    const marker = automation ? 'AUTOMATION_' + (['SCHEDULE', 'BUSY'].includes(scenario) ? 'SCHEDULE' : scenario) + '_DONE'
      : 'SANDBOX_INFERENCE_OK';
    const state = await waitForReply(key, marker);
    const results = state.messages.filter(m => m.role === 'toolResult');
    const text = JSON.stringify(results);
    assert(results.length, 'No tools executed: ' + scenario);
    if (scenario.startsWith('SUBAGENT')) {
      if (scenario === 'SUBAGENT_ASYNC_DEFER') {
        const ended = sessions.get(key).events.find(e => e.type === 'tool_execution_end' && e.toolName === 'subagent');
        const details = ended?.result?.details ?? results[0].details;
        assert(details?.asyncDir, 'Missing async child status directory: ' + JSON.stringify(ended));
        const statusPath = path.join(details.asyncDir, 'status.json');
        let status;
        const deadline = Date.now() + 180000;
        while (Date.now() < deadline) {
          if (failure) throw failure;
          if (fs.existsSync(statusPath)) {
            status = JSON.parse(fs.readFileSync(statusPath));
            if (['complete', 'failed', 'partial', 'paused', 'stopped', 'rejected'].includes(status.state)) break;
          }
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        assert.equal(status?.state, 'complete', JSON.stringify(status));
        assert(JSON.stringify(status).includes('SUBAGENT_FIXTURE_OK'));
        assert.equal(fs.readFileSync('/workspace/child-defer-fixture.txt', 'utf8'), 'DEFER_BY_FIXTURE');
      } else {
        assert(text.includes('SUBAGENT_FIXTURE_OK'), text);
        assert(!results.some(r => r.isError));
      }
      assert(!fs.existsSync('/workspace/child-denied-fixture.txt'));
    } else if (scenario === 'DENY') {
      assert(/denied|blocked/i.test(text));
      assert(!fs.existsSync('/workspace/denied-fixture.txt'));
    } else if (scenario === 'GOAL') {
      assert.deepEqual(results.map(r => r.toolName), ['create_goal', 'bash', 'update_goal']);
      assert(text.includes('AUTOMATION_GOAL_BASH_OK'));
      assert(JSON.stringify(state.messages).includes('AUTOMATION_GOAL_FIRST_TURN'));
    } else if (scenario === 'REJECT') {
      assert.equal(results.length, 1);
      assert(results[0].isError && /denied|blocked/i.test(text));
      const jobs = JSON.parse(fs.readFileSync('/workspace/.pi/schedule-prompts.json')).jobs;
      assert(!jobs.some(j => j.name === 'automation-rejected'));
    } else if (['SCHEDULE', 'BUSY'].includes(scenario)) {
      assert.deepEqual(results.map(r => r.toolName), ['schedule_prompt', 'bash', 'bash_escalate', 'bash_escalate']);
      assert(text.includes('AUTOMATION_SCHEDULE_BASH_OK') && text.includes('DEFER_BY_FIXTURE'));
      assert(results.at(-1).isError);
      assert(!fs.existsSync('/workspace/automation-denied.txt'));
      assert.equal(state.sessionId, initial.sessionId);
      assert.equal(state.messages.filter(m => m.role === 'user' && JSON.stringify(m.content).includes('AUTOMATION_TIMER_FIRE')).length, 1);
    } else {
      assert(text.includes({ ALLOW: 'ALLOW_EXECUTED', DEFER: 'DEFER_BY_FIXTURE', ESCALATE: 'ESCALATE_EXECUTED' }[scenario]));
      assert(!results.some(r => r.isError));
    }
    assert.equal(sessions.get(key).dialogs > 0, expectsDialog);
    await request({ type: 'session_dispose', reason: 'replacement' }, key);
    console.log('PASS actual Pendant worker: ' + key);
  }
}
main().catch(error => {
  console.error(error, '\nWorker diagnostics:', JSON.stringify(diagnostics), '\nWorker stderr:', errors);
  process.exitCode = 1;
}).finally(() => {
  if (worker.connected) worker.send({ type: 'sdk_bridge_dispose', workspaceGeneration: 1, reason: 'host_deactivation' });
  const timer = setTimeout(() => worker.kill('SIGKILL'), 15000);
  worker.once('exit', () => clearTimeout(timer));
  timer.unref();
});
