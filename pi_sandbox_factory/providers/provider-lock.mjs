import {mkdir,open,unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {homedir} from 'node:os';
export async function locked(agentDir,fn){
  await mkdir(agentDir,{recursive:true,mode:0o700});
  const path=join(agentDir,'models.refresh.lock');
  let file;
  try{file=await open(path,'wx',0o600)}catch(e){if(e.code==='EEXIST')throw Error('A model refresh is already running. If it was interrupted, close Pi/Pendant and remove models.refresh.lock from the private agent directory.');throw e}
  try{await file.writeFile(String(process.pid));return await fn()}finally{await file.close();await unlink(path)}
}
export function guard(pi){
  return new Proxy(pi,{get(target,key){
    if(key==='registerCommand')return (name,command)=>target.registerCommand(name,{...command,handler:async(...args)=>{
      try{return await locked(process.env.PI_CODING_AGENT_DIR??join(homedir(),'.pi/agent'),()=>command.handler(...args))}
      catch(error){args[1]?.ui?.notify(error.message,'error')}
    }});
    const value=target[key];return typeof value==='function'?value.bind(target):value;
  }});
}
