/** Synthetic popup login. No real account, provider key or external website. */
import http from 'node:http';
import {randomBytes} from 'node:crypto';
import {createInterface} from 'node:readline';

const session = randomBytes(24).toString('hex');
const api = randomBytes(24).toString('hex');
const foreign = randomBytes(24).toString('hex');
let authenticatedRequests = 0;
const style = '<style>body{font:22px system-ui;padding:32px;background:#eef4fa;color:#182230}input,button{font:inherit;padding:10px;margin:12px 0;display:block}button{background:#235adc;color:white;border:0;border-radius:6px}</style>';
const handler = async (request,response) => {
  const url = new URL(request.url,'http://' + request.headers.host);
  response.setHeader('Cache-Control','no-store');
  if (url.hostname === '127.0.0.2') {
    response.setHeader('Set-Cookie',`foreign_session=${foreign}; HttpOnly; Path=/`);
    response.end('<title>Other service</title><h1>Unrelated service session</h1>');return;
  }
  if (url.pathname === '/api/whoami') {
    const cookies = request.headers.cookie ?? '';
    const authenticated = cookies.split('; ').includes('sample_session=' + session) && cookies.split('; ').includes('api_session=' + api);
    if (authenticated) {
      authenticatedRequests++;
      console.log(JSON.stringify({type:'authenticated_request',count:authenticatedRequests}));
    }
    response.writeHead(authenticated ? 200 : 401,{'Content-Type':'application/json'});
    response.end(JSON.stringify({authenticated}));return;
  }
  response.setHeader('Content-Type','text/html; charset=utf-8');
  if (url.pathname === '/login' && request.method === 'POST') {
    let body='';for await(const chunk of request){body+=chunk;if(body.length>4096){response.writeHead(413);response.end();return;}}
    const form=new URLSearchParams(body);
    if (form.get('username') !== 'synthetic-user' || form.get('password') !== 'synthetic-only') {response.writeHead(403);response.end('Use the synthetic fixture account.');return;}
    response.setHeader('Set-Cookie',[
      `sample_session=${session}; HttpOnly; SameSite=Lax; Path=/`,
      `api_session=${api}; HttpOnly; SameSite=Lax; Path=/api`,
      'off_path=NOT_FOR_API; HttpOnly; Path=/private',
    ]);
    response.end('<title>Login complete</title><script>opener.postMessage("signed-in",location.origin);window.close()</script>');return;
  }
  if (url.pathname === '/login') {
    response.end('<title>Sample sign-in popup</title>'+style+'<h1>Sample sign-in</h1><form method="post"><label>Test username<input id="username" name="username" autocomplete="off"></label><label>Test password<input id="password" name="password" type="password" autocomplete="off"></label><button id="next">Next</button></form>');return;
  }
  if (url.pathname === '/workspace') {
    response.end('<title>Sample expense workspace</title>'+style+'<h1>Signed in</h1><p id="status">Ready for the local expense client.</p>');return;
  }
  response.end('<title>Sample expense service</title>'+style+'<h1>Sample expense service</h1><p>Use only the invented test account.</p><button id="signin">Sign in</button><script>document.querySelector("button").onclick=()=>window.open("/login","sample-login","width=640,height=540");window.addEventListener("message",e=>{if(e.origin===location.origin&&e.data==="signed-in")location.href="/workspace"})</script>');
};
const servers=['127.0.0.1','127.0.0.2'].map(()=>http.createServer(handler));
await Promise.all(servers.map((server,index)=>new Promise(resolve=>server.listen(18740,'127.0.0.'+(index+1),resolve))));
// Values go only to the host test controller, never the Pi model or its tools.
console.log(JSON.stringify({ready:true,secrets:[session,api,foreign]}));
const input=createInterface({input:process.stdin});
for await(const _ of input) {}
await Promise.all(servers.map(server=>new Promise(resolve=>server.close(resolve))));
