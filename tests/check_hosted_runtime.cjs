const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {fork} = require('node:child_process');
const root='/usr/local/lib/node_modules/@earendil-works/pi-coding-agent';
const agent='/home/node/.pi/agent';
const extension=fs.readdirSync('/opt/pendant').find(p=>p.startsWith('cdervis.vscode-pi-'));
const dist='/opt/pendant/'+extension+'/dist';
const sdk=require(dist+'/pi-sdk.cjs');
const read = p => JSON.parse(fs.readFileSync(p));
async function check() {
 const expected=read(agent+'/settings.json');
 const credentials=read(agent+'/auth.json');
 assert.equal(credentials.azure.env.AZURE_OPENAI_DEPLOYMENT_NAME_MAP,'gpt-4o=team-gpt');
 assert.equal(fs.statSync(agent+'/auth.json').mode & 0o777,0o600);
 assert(!fs.existsSync('/home/node/.aws/credentials'));
 assert(!fs.existsSync('/private/credentials.json'));
 assert(!JSON.stringify(credentials).includes('fixture-secret'));
 for (const [client,core] of [ ['Pi',await import(root+'/dist/core/model-runtime.js')], ['Pendant',sdk['@earendil-works/pi-coding-agent']()] ]) {
  const rt=await core.ModelRuntime.create({authPath:agent+'/auth.json',modelsPath:agent+'/models.json',modelsStorePath:agent+'/models-store.json',allowModelNetwork:false});
  for (const id of ['openrouter','together','azure','amazon-bedrock']) {
   const auth=await rt.getAuth(id);
   assert(auth,id+' native credentials resolve');
   assert.equal(auth.auth.apiKey,'factory-inference');
   if(id==='amazon-bedrock')assert.equal(auth.env.AWS_BEDROCK_SKIP_AUTH,'1');
  }
  const model=rt.getModel(expected.defaultProvider,expected.defaultModel);
  assert(model);assert(model.contextWindow>1000);assert(model.api);
  for(const id of ['openrouter','together','azure','amazon-bedrock']) {
   const selected=id==='azure'?rt.getModel(id,'gpt-4o'):id==='amazon-bedrock'?model:rt.getModels(id).find(m=>id==='openrouter'?m.api==='anthropic-messages':m.api==='openai-completions');
   assert(selected,id+' fixture model');
   const reply=await rt.completeSimple(selected,{messages:[{role:'user',content:'test',timestamp:Date.now()}]},{maxTokens:16,signal:AbortSignal.timeout(15000)});
   assert.notEqual(reply.stopReason,'error',JSON.stringify(reply));
   assert.equal(reply.content.filter(c=>c.type==='text').map(c=>c.text).join(''),'OK',id);
   console.log('PASS '+client+' '+id+': native streamed reply through isolated credentials');
  }
 }
 const worker=fork(dist+'/pi-sdk-worker.cjs',[],{cwd:'/workspace',env:process.env,silent:true,serialization:'advanced'});
 let timer;
 try {
  await new Promise((resolve,reject)=>{
   timer=setTimeout(()=>reject(Error('Pendant worker startup timed out')),90000);
   worker.on('error',reject);worker.stderr.on('data',()=>{});worker.stdout.on('data',()=>{});
   worker.on('message',m=>{
    if(m.type==='sdk_bridge_ready')worker.send({type:'sdk_bridge_request',requestId:'create',workspaceGeneration:1,sessionKey:'hosted',sessionGeneration:1,command:{type:'session_create',target:{kind:'new',cwd:'/workspace'}}});
    if(m.type==='sdk_bridge_response'&&m.requestId==='create') {
     if(m.error)return reject(Error(JSON.stringify(m.error)));
     worker.send({type:'sdk_bridge_request',requestId:'state',workspaceGeneration:1,sessionKey:'hosted',sessionGeneration:1,command:{type:'session_get_state'}});
    }
    if(m.type==='sdk_bridge_response'&&m.requestId==='state') {
     try {
      assert.equal(m.result.model.provider,expected.defaultProvider);
      assert.equal(m.result.model.id,expected.defaultModel);
      resolve();
     }catch(e){reject(e);}
    }
   });
   const hostVersion=read('/opt/pendant/'+extension+'/package.json').version;
   worker.send({type:'sdk_worker_bootstrap',protocolVersion:3,hostVersion,workspaceId:'hosted-check',workspaceCwd:'/workspace',workspaceGeneration:1,runtimeOwnerGeneration:1,agentDirectory:agent,agentDirectorySource:'explicit',offline:true,extensionMode:'rpc'});
   worker.send({type:'sdk_bridge_hello',protocolVersion:3,hostKind:'vscode',hostVersion,workspaceId:'hosted-check',workspaceGeneration:1,piSdkPackage:'@earendil-works/pi-coding-agent',piSdkVersion:sdk['@earendil-works/pi-coding-agent']().VERSION,capabilities:['sessions','models','settings','packages','resources','extension_ui']});
  });
  console.log('PASS actual Pendant worker: new chat uses the saved provider and profile model');
 } finally {clearTimeout(timer);worker.kill();}
}
check().catch(e=>{console.error(e);process.exitCode=1});
