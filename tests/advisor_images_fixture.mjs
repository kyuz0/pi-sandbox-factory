// A real socket round-trip and tool call, with synthetic provider/model replies.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {writeFile,mkdtemp,rm} from 'node:fs/promises';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==';
if(process.argv[2]==='service') {
  const {serveAdvisor}=await import('/opt/advisor/lib/advisor/remote.mjs');
  await serveAdvisor('/run/advisor/images.sock',{cancel(){},async ask(_context,params){
    assert.deepEqual(params.images,[{mimeType:'image/png',data:png}]);
    assert.equal(params.question,'Describe the selected image');
    return {answer:'ADVISOR_IMAGES_OK',sessionUsage:{calls:1,totalTokens:0}};
  }});
} else if(process.argv[2]==='mount') {
  const {stageImages}=await import('/opt/advisor/lib/advisor/images.mjs');
  const {sandboxInvocation}=await import('/opt/advisor/lib/advisor/codex.mjs');
  const {runProcess}=await import('/opt/advisor/lib/advisor/process.mjs');
  const root=await mkdtemp('/tmp/advisor-image-mount-');
  const images=await stageImages(root,[{mimeType:'image/png',data:png}]);
  try {
    const code="from pathlib import Path; import base64,errno\np=Path('/images/1.png')\nassert base64.b64encode(p.read_bytes()).decode() == '"+png+"'\nassert not Path('/workspace').exists()\ntry: p.write_text('changed')\nexcept OSError as e: assert e.errno == errno.EROFS\nelse: raise AssertionError('Image mount is writable')";
    const inv=await sandboxInvocation({executable:'/usr/bin/python3',containerRuntime:true},root+'/home',['-c',code],{auth:false,imagesDir:images.directory});
    const result=await runProcess(inv.command,inv.args,{env:inv.env,timeoutMs:30000});
    assert.equal(result.code,0,result.stderr);assert.equal(result.reason,null);
    console.log('PASS selected image readable, image mount read-only, workspace absent in isolated CLI');
  } finally {await images.close();await rm(root,{recursive:true,force:true});}
} else {
  await writeFile('/workspace/advisor-image.png' ,Buffer.from(png,'base64'));
  await writeFile('/home/node/.pi/agent/models.json',JSON.stringify({providers:{fixture:{baseUrl:'http://127.0.0.1:18711/v1',api:'openai-completions',apiKey:'fixture-key',models:[{id:'fixture-model',contextWindow:32000,maxTokens:4096}]}}}));
  createServer(async(req,res)=>{
    if(req.method==='GET'){res.end('ready');return;}
    try {
      let body='';for await(const chunk of req)body+=chunk;
      const request=JSON.parse(body),messages=request.messages;
      const reviewing=messages.some(m=>['system','developer'].includes(m.role)&&/Review one proposed coding-agent action|fail-closed permission reviewer/.test(JSON.stringify(m.content)));
      let delta={role:'assistant',content:'ADVISOR_IMAGES_DONE'},finish='stop';
      if(reviewing)delta.content=JSON.stringify({outcome:'allow',risk_level:'low',user_authorization:'high',rationale:'Synthetic advisor image check.'});
      else {
        const tool=request.tools.find(t=>t.function.name==='advisor_ask');
        assert.equal(tool.function.parameters.properties.images.type,'array');
        const replies=messages.filter(m=>m.role==='tool');
        if(replies.length)assert.match(JSON.stringify(replies),/ADVISOR_IMAGES_OK/);
        else {
          delta={role:'assistant',tool_calls:[{index:0,id:'image-check',type:'function',function:{name:'advisor_ask',arguments:JSON.stringify({mode:'consult',question:'Describe the selected image',images:['advisor-image.png']})}}]};
          finish='tool_calls';
        }
      }
      res.writeHead(200,{'Content-Type':'text/event-stream'});
      for(const [d,f] of [[delta,null],[{},finish]])res.write('data: '+JSON.stringify({id:'image-check',object:'chat.completion.chunk',created:1,model:'fixture-model',choices:[{index:0,delta:d,finish_reason:f}]})+'\n\n');
      res.end('data: [DONE]\n\n');
    } catch(e) { console.error(e);res.writeHead(500);res.end(String(e)); }
  }).listen(18711,'127.0.0.1');
}
