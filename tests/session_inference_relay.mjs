/** Fixed-model test relay to a managed socket; never mounts credential storage. */
import http from 'node:http';
import {parseArgs} from 'node:util';
const {values}=parseArgs({options:{socket:{type:'string'},route:{type:'string'},model:{type:'string'},port:{type:'string',default:'18200'}}});
if(!values.socket||!values.route?.startsWith('/r/')||!values.model)throw Error('Specify --socket, --route and --model.');
let sequence=0,completed=0;
const active=new Map();
const server=http.createServer(async(request,response)=>{
  if(request.method==='GET'&&request.url==='/health'){
    response.setHeader('Content-Type','application/json');
    response.end(JSON.stringify({ready:true,completed,active:[...active.values()].map(r=>({id:r.id,seconds:Math.round((Date.now()-r.started)/1000),idleSeconds:Math.round((Date.now()-r.lastChunk)/1000),receivedBytes:r.receivedBytes}))}));return;
  }
  if(request.method==='GET'&&request.url==='/api/v1/models'){
    response.setHeader('Content-Type','application/json');response.end(JSON.stringify({data:[{id:values.model}]}));return;
  }
  if(request.method!=='POST'||!request.url?.startsWith('/api/v1/messages')){response.writeHead(404);response.end();return;}
  let body='';
  for await(const chunk of request){body+=chunk;if(body.length>4*1024*1024){response.writeHead(413);response.end();return;}}
  try{if(JSON.parse(body).model!==values.model)throw Error();}catch{response.writeHead(400);response.end('Invalid test model');return;}
  const item={id:++sequence,started:Date.now(),lastChunk:Date.now(),receivedBytes:0};active.set(item.id,item);
  const upstream=http.request({socketPath:values.socket,path:values.route,method:'POST',headers:{'content-type':'application/json','anthropic-version':'2023-06-01','content-length':Buffer.byteLength(body)}},incoming=>{
    response.writeHead(incoming.statusCode,{'content-type':incoming.headers['content-type']??'application/json'});
    incoming.on('data',chunk=>{item.receivedBytes+=chunk.length;item.lastChunk=Date.now();});
    incoming.on('error',()=>response.destroy());
    incoming.pipe(response);
  });
  upstream.on('error',()=>{if(!response.headersSent)response.writeHead(502);response.end('Test inference relay unavailable');});
  response.on('close',()=>{active.delete(item.id);completed++;upstream.destroy();});upstream.end(body);
});
server.listen(Number(values.port),'127.0.0.1',()=>console.log('Synthetic test inference relay ready.'));
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>server.close(()=>process.exit(0)));
