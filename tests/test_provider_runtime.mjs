import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, readFile, cp, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {locked, guard} from '../pi_sandbox_factory/providers/provider-lock.mjs';

async function fixture(t, adapter) {
  const root = await mkdtemp(join(tmpdir(), 'provider-test-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  await mkdir(join(root, 'agent'));
  for (const file of ['provider-runner.mjs', 'provider-lock.mjs'])
    await cp(resolve('pi_sandbox_factory/providers', file), join(root, file));
  await writeFile(join(root, 'adapter.mjs'), adapter);
  await writeFile(join(root, 'providers.json'), JSON.stringify([{id:'test', directory:root,
    manifest:{entry:'adapter.mjs', settings:{endpoint:{type:'text', default:'default-endpoint'}}}, settings:{}}]));
  return {root, run(request) { return new Promise((done, reject) => {
    const child = spawn(process.execPath, [join(root,'provider-runner.mjs')], {env:{...process.env, PI_CODING_AGENT_DIR:join(root,'agent')}});
    let stdout='',stderr='';child.stdout.on('data', d=>stdout+=d);child.stderr.on('data',d=>stderr+=d);
    child.on('error',reject);child.on('close',code=>done({code,stdout,stderr}));child.stdin.end(JSON.stringify(request));
  }); }};
}

test('dispatch supplies settings and credential through stdin; unknown actions fail closed', async t => {
  const f=await fixture(t, `export async function run({action,settings,secret}) {
    if(secret!=='fixture-key'||settings.endpoint!=='default-endpoint')throw Error('bad contract');
    return {state:'ready',message:action}; }`);
  for(const action of ['status','preview','refresh']){
    const result=await f.run({id:'test',action,secret:'fixture-key'});
    assert.equal(result.code,0);assert.equal(JSON.parse(result.stdout).message,action);
    assert.ok(!result.stdout.includes('fixture-key'));
  }
  assert.equal((await f.run({id:'test',action:'delete'})).code,1);
  assert.equal((await f.run({id:'missing',action:'status'})).code,1);
});

test('provider exceptions and invalid responses cannot leak a key', async t => {
  for(const code of [`throw Error('fixture-key')`, `return {state:'invalid',message:'fixture-key'}`]){
    const f=await fixture(t, `export async function run(){${code}}`);
    const result=await f.run({id:'test',action:'refresh',secret:'fixture-key'});
    assert.equal(result.code,1);assert.ok(!(result.stdout+result.stderr).includes('fixture-key'));
    await assert.rejects(access(join(f.root,'agent/models.refresh.lock')));
  }
});

test('launcher and extension commands share one lock; failure releases it',async t=>{
  const f=await fixture(t, `export async function run(){return {state:'ready',message:'done'}}`);
  await locked(join(f.root,'agent'),async()=>assert.equal((await f.run({id:'test',action:'refresh'})).code,1));
  assert.equal((await f.run({id:'test',action:'refresh'})).code,0);
  await assert.rejects(locked(join(f.root,'agent'),async()=>{throw Error('failure')}));
  assert.equal((await f.run({id:'test',action:'refresh'})).code,0);
  const old=process.env.PI_CODING_AGENT_DIR;process.env.PI_CODING_AGENT_DIR=join(f.root,'agent');
  t.after(()=>{if(old===undefined)delete process.env.PI_CODING_AGENT_DIR;else process.env.PI_CODING_AGENT_DIR=old});
  let command,calls=0,notice;
  guard({registerCommand(name,value){command=value}}).registerCommand('models',{handler:async()=>calls++});
  await locked(join(f.root,'agent'),()=>command.handler('',{ui:{notify:message=>notice=message}}));
  assert.equal(calls,0);assert.match(notice,/already running/);
  await command.handler('',{});assert.equal(calls,1);
});

test('authoring example previews without writing and preserves other providers',async t=>{
  const root=await mkdtemp(join(tmpdir(),'example-provider-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const {run}=await import('../examples/provider/adapter.mjs');
  const original=global.fetch;t.after(()=>global.fetch=original);
  global.fetch=async()=>({ok:true,status:200,json:async()=>({data:[{id:'test-model'}]})});
  const file=join(root,'models.json');await writeFile(file,JSON.stringify({providers:{other:{models:[{id:'keep'}]}}}));
  const before=await readFile(file,'utf8');
  const request={agentDir:root,settings:{model:'test-model'},endpoint:'http://127.0.0.1:19431/r/company/v1',secret:'factory-inference'};
  assert.equal((await run({...request,action:'preview'})).state,'ready');assert.equal(await readFile(file,'utf8'),before);
  assert.equal((await run({...request,action:'refresh'})).state,'ready');
  assert.equal(JSON.parse(await readFile(file,'utf8')).providers.other.models[0].id,'keep');
  global.fetch=async()=>({ok:false,status:401});
  assert.equal((await run({...request,action:'refresh'})).state,'needs-auth');
});


test('isolated provider receives a proxy endpoint and placeholder even if a caller supplies a secret',async t=>{
  const f=await fixture(t, `export async function run({endpoint,secret}) {
    if(endpoint!=='http://127.0.0.1:19431/r/test/v1'||secret!=='factory-inference')throw Error('bad isolation contract');
    return {state:'ready',message:'proxy configured'}; }`);
  const file=join(f.root,'providers.json');const data=JSON.parse(await readFile(file,'utf8'));
  data[0].manifest.inference={basePath:'/v1'};await writeFile(file,JSON.stringify(data));
  const reply=await f.run({id:'test',action:'refresh',secret:'must-not-reach-adapter'});
  assert.equal(reply.code,0);assert(!reply.stdout.includes('must-not-reach-adapter'));
});
