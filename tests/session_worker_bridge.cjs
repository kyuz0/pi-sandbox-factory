// Test-only JSON bridge to the actual shipped Pendant worker, not the Pi CLI.
const {fork}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const provider=process.argv[2],modelId=process.argv[3];
const directory=path.join('/opt/pendant',fs.readdirSync('/opt/pendant').find(n=>n.startsWith('cdervis.vscode-pi-')));
const version=JSON.parse(fs.readFileSync(path.join(directory,'package.json'))).version;
const sdkVersion=require(path.join(directory,'dist/pi-sdk.cjs'))['@earendil-works/pi-coding-agent']().VERSION;
const worker=fork(path.join(directory,'dist/pi-sdk-worker.cjs'),[],{cwd:'/workspace',env:process.env,silent:true,serialization:'advanced'});
const pending=new Map();let sequence=0,generation=1;
let starts=0;
let readyResolve,readyReject;
const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;});
const output=value=>console.log(JSON.stringify(value));
function request(command){return new Promise((resolve,reject)=>{
 const requestId='session-test-'+(++sequence),timer=setTimeout(()=>{pending.delete(requestId);reject(Error('Pendant request timed out: '+command.type));},180000);
 pending.set(requestId,{resolve,reject,timer});
 worker.send({type:'sdk_bridge_request',requestId,workspaceGeneration:1,sessionKey:'workflow',sessionGeneration:generation,command});
});}
worker.stderr.pipe(process.stderr);
// The worker can log outside IPC. Drain this pipe so a long session cannot
// block inference or settlement on an unread stdout buffer.
worker.stdout.resume();
worker.on('error',readyReject);
worker.on('message',message=>{
 if(message.type==='sdk_bridge_ready')return readyResolve(message);
 if(message.type==='sdk_bridge_response'){
  const item=pending.get(message.requestId);if(!item)return;
  pending.delete(message.requestId);clearTimeout(item.timer);
  if(message.error)item.reject(Error(JSON.stringify(message.error)));
  else{generation=message.result?.sessionGeneration??generation;item.resolve(message.result);}
 }
 // Emit one settled marker after the matching prompt's state is idle. The
 // worker also emits one; forwarding both races the next host-driven turn.
 if(message.type==='session_event') {
  if(message.event.type==='agent_start')starts++;
  if(message.event.type!=='agent_settled')output(message.event);
 }
 if(message.type==='extension_ui_request')output({type:'extension_ui_request',method:message.request.kind,...message.request});
 if(['sdk_worker_failure','sdk_bridge_rejected','runtime_interrupted'].includes(message.type))readyReject(Error(JSON.stringify(message)));
});
worker.send({type:'sdk_worker_bootstrap',protocolVersion:3,hostVersion:version,workspaceId:'session-workflow-test',workspaceCwd:'/workspace',workspaceGeneration:1,runtimeOwnerGeneration:1,agentDirectory:'/home/node/.pi/agent',agentDirectorySource:'explicit',offline:false,extensionMode:'rpc'});
worker.send({type:'sdk_bridge_hello',protocolVersion:3,hostKind:'vscode',hostVersion:version,workspaceId:'session-workflow-test',workspaceGeneration:1,piSdkPackage:'@earendil-works/pi-coding-agent',piSdkVersion:sdkVersion,capabilities:['sessions','models','settings','packages','resources','extension_ui']});
let closing=false;
async function close(){if(closing)return;closing=true;try{await request({type:'session_dispose',reason:'replacement'});}catch{}worker.kill('SIGTERM');}
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>close().finally(()=>process.exit()));
(async()=>{
 const handshake=await ready;if(!handshake.compatibilityReport.compatible)throw Error('Incompatible shipped Pendant worker');
 const inventory=await request({type:'session_create',target:{kind:'new',cwd:'/workspace'}});
 if(!inventory.tools.some(t=>t.name==='browser_session_export'))throw Error('Session export tool not installed');
 if(process.argv.includes('--all-file-tools'))await request({type:'session_set_active_tools',names:[...new Set([...inventory.tools.map(t=>t.name),'grep','find','ls'])]});
 await request({type:'session_set_model',provider,modelId,persist:false});
 for await(const line of readline.createInterface({input:process.stdin})){
  const command=JSON.parse(line);if(command.type!=='prompt')throw Error('Only prompt is supported');
  const beforeStarts=starts;
  await request({type:'session_prompt',text:command.message,images:[],source:'interactive'});
  const end=Date.now()+600000;let idle=false;
  while(Date.now()<end){const state=await request({type:'session_get_state'});if(starts>beforeStarts&&state.idle){idle=true;break;}await new Promise(resolve=>setTimeout(resolve,100));}
  if(!idle)throw Error('Pendant live-model turn did not finish');
  output({type:'agent_settled'});
 }
 await close();
})().catch(async error=>{console.error(error);await close();process.exitCode=1;});
