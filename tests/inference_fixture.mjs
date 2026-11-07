// Offline upstream fixture. Real API keys are never used by this test.
import https from 'node:https';
import fs from 'node:fs';
import {compileRoutes,createBroker} from '/app/broker.mjs';
import {readCredentials} from '/app/credentials.mjs';
const sse = (res,event,data) => res.write(`${event?'event: '+event+'\n':''}data: ${JSON.stringify(data)}\n\n`);
const server=https.createServer({key:fs.readFileSync('/fixture/tls.key'),cert:fs.readFileSync('/fixture/tls.crt')},(req,res)=>{
 let text='';req.on('data',chunk=>text+=chunk);req.on('end',()=>{
  const path=req.url.split('?')[0],body=JSON.parse(text||'{}');
  const provider=path.startsWith('/api/')?'openrouter':path.startsWith('/v1/')?'together':path.startsWith('/model/')?'amazon-bedrock':'azure';
  const credentials=readCredentials('/private/credentials.json')[provider];
  const authorized=provider==='azure'?req.headers['api-key']===credentials.key:provider==='amazon-bedrock'?
    req.headers.authorization?.startsWith('AWS4-HMAC-SHA256 Credential=fixture-access/')&&req.headers['x-amz-security-token']==='fixture-session':
    req.headers.authorization==='Bearer '+credentials.key;
  if(!authorized){res.writeHead(401);return res.end();}
  if(provider==='azure'&&body.model!=='team-gpt'){res.writeHead(404,{'content-type':'application/json'});return res.end(JSON.stringify({error:{message:'DeploymentNotFound: select an existing Azure deployment.'}}));}
  if(path.endsWith('/messages')&&(!Number.isInteger(body.max_tokens)||body.max_tokens<1)){res.writeHead(400,{'content-type':'application/json'});return res.end(JSON.stringify({error:{message:'max_tokens must be a positive integer'}}));}
  if(provider==='amazon-bedrock'){res.writeHead(200,{'content-type':'application/vnd.amazon.eventstream'});return res.end(fs.readFileSync('/fixture/bedrock.bin'));}
  res.writeHead(200,{'content-type':'text/event-stream'});
  if(path.endsWith('/messages')) {
    sse(res,'message_start',{type:'message_start',message:{id:'fixture',type:'message',role:'assistant',model:body.model,content:[],usage:{input_tokens:1,output_tokens:0}}});
    sse(res,'content_block_start',{type:'content_block_start',index:0,content_block:{type:'text',text:''}});
    sse(res,'content_block_delta',{type:'content_block_delta',index:0,delta:{type:'text_delta',text:'OK'}});
    sse(res,'content_block_stop',{type:'content_block_stop',index:0});
    sse(res,'message_delta',{type:'message_delta',delta:{stop_reason:'end_turn'},usage:{output_tokens:1}});
    sse(res,'message_stop',{type:'message_stop'});
  } else if(path.endsWith('/responses')) {
    const item={id:'msg_fixture',type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text:'OK',annotations:[]}]};
    sse(res,'response.created',{type:'response.created',response:{id:'fixture',status:'in_progress',output:[]}});
    sse(res,'response.output_item.added',{type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}});
    sse(res,'response.content_part.added',{type:'response.content_part.added',item_id:item.id,output_index:0,content_index:0,part:{type:'output_text',text:'',annotations:[]}});
    sse(res,'response.output_text.delta',{type:'response.output_text.delta',item_id:item.id,output_index:0,content_index:0,delta:'OK'});
    sse(res,'response.output_item.done',{type:'response.output_item.done',output_index:0,item});
    sse(res,'response.completed',{type:'response.completed',response:{id:'fixture',status:'completed',output:[item],usage:{input_tokens:1,output_tokens:1,total_tokens:2}}});
  } else {
    sse(res,'',{id:'fixture',object:'chat.completion.chunk',model:body.model,choices:[{index:0,delta:{role:'assistant',content:'OK'},finish_reason:null}]});
    sse(res,'',{id:'fixture',object:'chat.completion.chunk',model:body.model,choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}});
    res.write('data: [DONE]\n\n');
  }
  res.end();
 });
});
await new Promise(resolve=>server.listen(18444,'127.0.0.1',resolve));
const routes=compileRoutes(JSON.parse(fs.readFileSync('/fixture/routes.json')));
const broker=createBroker(routes,id=>readCredentials('/private/credentials.json')[id]);
fs.rmSync('/run/inference/proxy.sock',{force:true});broker.listen('/run/inference/proxy.sock',()=>fs.chmodSync('/run/inference/proxy.sock',0o666));
