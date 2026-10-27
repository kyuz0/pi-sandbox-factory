import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp,readFile,writeFile,rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { initializeModels } from '../../containers/dev/local-model-manager/scripts/initialize-models.mjs';
const endpoint='http://local-model.internal:8000';
const report={endpoint,status:'model-list',models:[{id:'local-test',contextWindow:8192,imageSupport:false}]};
async function setup(run) { const root=await mkdtemp(join(tmpdir(),'initial-models-'));try{await run(root);}finally{await rm(root,{recursive:true,force:true});} }
test('initial catalogue is written without loading Pi or selecting a model',async()=>setup(async root=>{
 const result=await initializeModels(root,{scanModels:async()=>[report],log:()=>{}});
 assert.deepEqual(result.models,['local-test']);
 const config=JSON.parse(await readFile(join(root,'models.json'),'utf8'));
 assert(Object.values(config.providers).some(p=>p.models[0].contextWindow===8192));
}));
test('unreachable server fails clearly and preserves unrelated providers',async()=>setup(async root=>{
 const config={providers:{remote:{baseUrl:'https://example.test/v1',models:[{id:'keep'}]}}};
 await writeFile(join(root,'models.json'),JSON.stringify(config));
 await assert.rejects(initializeModels(root,{scanModels:async()=>[{endpoint,status:'probe-error',models:[]}],log:()=>{}}),/No usable local model/);
 assert.deepEqual(JSON.parse(await readFile(join(root,'models.json'),'utf8')),config);
}));
test('unknown context cannot produce a supposedly ready fresh catalogue',async()=>setup(async root=>{
 await assert.rejects(initializeModels(root,{scanModels:async()=>[{...report,models:[{id:'unknown',contextWindow:null}]}],log:()=>{}}),/context limit/);
}));
test('preview does not create models.json and does not require a ready server',async()=>setup(async root=>{
 await initializeModels(root,{preview:true,scanModels:async()=>[{endpoint,status:'probe-error',models:[]}],log:()=>{}});
 await assert.rejects(readFile(join(root,'models.json')), {code:'ENOENT'});
}));
