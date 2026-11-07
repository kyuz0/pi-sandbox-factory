import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {locked} from './provider-lock.mjs';
try{
  let input='';for await(const part of process.stdin){input+=part;if(input.length>65536)throw Error('Request too large')}
  const request=JSON.parse(input);
  if(!['status','preview','refresh'].includes(request.action))throw Error('Unknown action');
  const packages=JSON.parse(await readFile(new URL('./providers.json',import.meta.url),'utf8'));
  const provider=packages.find(p=>p.id===request.id);if(!provider)throw Error('Provider not installed');
  const agentDir=process.env.PI_CODING_AGENT_DIR??join(homedir(),'.pi/agent');
  const adapter=await import(pathToFileURL(join(provider.directory,provider.manifest.entry)));
  const settings=Object.fromEntries(Object.entries(provider.manifest.settings??{}).filter(([,s])=>s.type!=='secret').map(([key,s])=>[key,s.default??'']));
  Object.assign(settings,provider.settings);
  const route=provider.manifest.inference;
  const endpoint=route?`http://127.0.0.1:19431/r/${provider.id}${route.basePath??''}`:undefined;
  const secret=route?'factory-inference':request.secret;
  const result=await locked(agentDir,()=>adapter.run({action:request.action,agentDir,settings,secret,endpoint}));
  if(!['ready','offline','needs-auth','error'].includes(result?.state)||typeof result.message!=='string')throw Error('Invalid provider result');
  process.stdout.write(JSON.stringify(result)+'\n');
}catch{process.stderr.write('Provider operation failed. Check its settings and connection.\n');process.exitCode=1}
