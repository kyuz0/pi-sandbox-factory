import {initializeModels} from '/opt/pi-local-model-manager/scripts/initialize-models.mjs';
export async function run({action,agentDir}) {
  if(action==='status')return {state:'ready',message:'Local model discovery uses the host ports selected in Configuration.'};
  const messages=[];
  try {
    const result=await initializeModels(agentDir,{preview:action==='preview',log:line=>messages.push(line)});
    return {state:'ready',message:messages.join('\n'),changed:action==='refresh',providers:[...new Set(result.changes.flatMap(c=>[c.provider,...(c.previousProvider?[c.previousProvider]:[])]))]};
  } catch(error) {
    if(error.code==='NO_USABLE_MODEL')return {state:'offline',message:error.message};
    throw error;
  }
}
