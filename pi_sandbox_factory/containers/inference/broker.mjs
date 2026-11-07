import http from 'node:http';
import https from 'node:https';
import fs from 'node:fs';
import {pipeline} from 'node:stream';
import {SignatureV4} from '@smithy/signature-v4';
import {Sha256} from '@aws-crypto/sha256-js';
import {readCredentials} from './credentials.mjs';

const requestHeaders = ['content-type', 'accept', 'anthropic-version', 'anthropic-beta'];
const responseHeaders = ['content-type', 'content-encoding', 'retry-after'];
const idPattern = /^[a-z][a-z0-9-]{0,63}$/;
const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function compileRoutes(values, {allowHttpFixture=false}={}) {
  const routes = new Map();
  for (const [id, value] of Object.entries(values)) {
    if (!idPattern.test(id)) throw Error('Invalid route ID.');
    const origin = new URL(value.origin);
    if ((origin.protocol !== 'https:' && !(allowHttpFixture && origin.protocol === 'http:')) ||
        origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw Error('Invalid upstream origin.');
    if (!['bearer', 'header', 'sigv4'].includes(value.auth.type)) throw Error('Invalid authentication type.');
    if (value.auth.type === 'header' && !['api-key', 'x-api-key'].includes(value.auth.header)) throw Error('Invalid authentication header.');
    if (value.auth.type === 'sigv4' && !/^[a-z]{2}(?:-[a-z]+)+-\d+$/.test(value.auth.region)) throw Error('Invalid AWS region.');
    const operations = value.operations.map(op => {
      if (!['GET','POST'].includes(op.method) || !op.path.startsWith('/') || op.path.includes('..')) throw Error('Invalid route operation.');
      if (op.upstreamPath && (!op.upstreamPath.startsWith('/') || /[?%\\{}]/.test(op.upstreamPath) || op.upstreamPath.includes('..') || op.upstreamPath.includes('//'))) throw Error('Invalid upstream path.');
      const pattern = op.path.split('{model}').map(escape).join('(?:[A-Za-z0-9._-]|%[a-fA-F0-9]{2})+');
      for (const [key, values] of Object.entries(op.query || {})) {
        if (!/^[a-z][a-z0-9_-]*$/.test(key) || !Array.isArray(values) || values.some(v => typeof v !== 'string')) throw Error('Invalid query rule.');
      }
      return {...op, pattern:new RegExp('^'+pattern+'$')};
    });
    routes.set(id, {...value, origin, operations});
  }
  return routes;
}

export function createBroker(routes, credentials, {idleMs=120000, totalMs=1800000, maxBody=32*1024*1024, maxBuffered=64*1024*1024, concurrency=8}={}) {
  let active = 0, buffered = 0;
  function fail(res, status) {
    if (res.destroyed || res.writableEnded) return;
    if (res.headersSent) { res.destroy(); return; }
    const message = ({401:'Provider authentication failed. Replace the credential in Factory.',
      403:'The provider refused access to this model or operation.',429:'The provider rate or usage limit was reached.',
      413:'Inference request is too large.',404:'Inference route is not available.',
      503:'Inference connection is unavailable. Check its configuration in Factory.'})[status] || 'Inference request failed.';
    res.writeHead(status, {'content-type':'application/json'});
    res.end(JSON.stringify({error:{type:'upstream_error',message,status}}));
  }
  const server = http.createServer({maxHeaderSize:16384}, async (req,res) => {
    let upstream, deadline, held = 0, counted = false, finished = false;
    const cleanup = () => {
      if (finished) return;
      finished = true;
      clearTimeout(deadline);
      if (upstream && !upstream.destroyed) upstream.destroy();
      if (counted) active--;
      buffered -= held;
    };
    res.on('close', cleanup);
    try {
      if (active >= concurrency) return fail(res,503);
      if (!req.url.startsWith('/') || req.url.startsWith('//') || /[\\\x00-\x20#]/.test(req.url) || req.headers.upgrade) return fail(res,400);
      const match = /^\/r\/([a-z][a-z0-9-]{0,63})(\/[^?]*)(?:\?(.*))?$/.exec(req.url);
      if (!match) return fail(res,404);
      const route = routes.get(match[1]);
      if (!route) return fail(res,404);
      const rawPath = match[2];
      let decoded;
      try { decoded = decodeURIComponent(rawPath); } catch { return fail(res,400); }
      if (decoded.includes('%') || decoded.includes('\\') || decoded.includes('//') ||
          decoded.split('/').some(s => s === '..' || s === '.') || /[\x00-\x20\x7f]/.test(decoded)) return fail(res,400);
      const op = route.operations.find(op => op.method === req.method && op.pattern.test(rawPath));
      if (!op) return fail(res,404);
      const upstreamPath = op.upstreamPath || rawPath;
      const query = new URLSearchParams(match[3] || '');
      for (const [key,value] of query) {
        if (!op.query?.[key]?.includes(value) || query.getAll(key).length !== 1) return fail(res,400);
      }
      const secret = credentials(match[1]);
      if (secret?.origin !== route.origin.origin) return fail(res,503);
      if (route.auth.type === 'sigv4' ? !(secret?.accessKeyId && secret.secretAccessKey) : !secret?.key) return fail(res,503);
      if (Number(req.headers['content-length']) > maxBody) return fail(res,413);
      active++; counted = true;
      deadline = setTimeout(() => { fail(res,504); cleanup(); },totalMs);
      const chunks = [];
      for await (const chunk of req) {
        if (finished) return;
        if (held + chunk.length > maxBody || buffered + chunk.length > maxBuffered) return fail(res,413);
        held += chunk.length; buffered += chunk.length; chunks.push(chunk);
      }
      if (finished) return;
      const body = Buffer.concat(chunks);
      let headers = {'accept-encoding':'identity', 'content-length':String(body.length)};
      for (const key of requestHeaders) if (req.headers[key]) headers[key] = req.headers[key];
      const url = route.origin;
      headers.host = url.host;
      if (route.auth.type === 'sigv4') {
        const signer = new SignatureV4({credentials:secret, region:route.auth.region, service:'bedrock', sha256:Sha256});
        const signed = await signer.sign({protocol:url.protocol,hostname:url.hostname,port:url.port ? Number(url.port) : undefined,
          method:req.method,path:upstreamPath,query:Object.fromEntries(query),headers,body});
        headers = signed.headers;
      } else if (route.auth.type === 'header') headers[route.auth.header] = secret.key;
      else headers.authorization = 'Bearer '+secret.key;
      if (finished) return;
      upstream = (url.protocol === 'https:' ? https : http).request({protocol:url.protocol,hostname:url.hostname,port:url.port,
        method:req.method,path:upstreamPath+(match[3] ? '?'+match[3] : ''),headers,timeout:idleMs}, async response => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          if (response.headers['retry-after']) res.setHeader('retry-after',response.headers['retry-after']);
          const status=response.statusCode;
          if ((status>=300&&status<400)||status===401||status===403) {
            response.destroy();return fail(res,status>=300&&status<400?502:status);
          }
          // Preserve native context-limit errors so Pi can compact and retry.
          // Limit error bodies and redact every credential field before returning them.
          try {
            const chunks=[];let size=0;
            for await(const chunk of response){size+=chunk.length;if(size>65536)throw Error('Large error');chunks.push(chunk);}
            const parsed=JSON.parse(Buffer.concat(chunks).toString('utf8'));
            let safe=JSON.stringify(parsed);
            for(const field of ['key','accessKeyId','secretAccessKey','sessionToken']) {
              if(secret[field])safe=safe.split(JSON.stringify(secret[field]).slice(1,-1)).join('[redacted]');
            }
            const errorType=response.headers['x-amzn-errortype'];
            const headers={'content-type':'application/json'};
            if(typeof errorType==='string'&&/^[A-Za-z0-9_.:#-]{1,256}$/.test(errorType)&&!Object.values(secret).some(v=>v&&errorType.includes(v)))headers['x-amzn-errortype']=errorType;
            if(!finished){res.writeHead(status,headers);res.end(safe);}
          } catch {response.destroy();fail(res,status);}
          return;
        }
        const safe = {};
        for (const key of responseHeaders) if (response.headers[key]) safe[key] = response.headers[key];
        res.writeHead(response.statusCode,safe); res.flushHeaders();
        pipeline(response,res,()=>{});
      });
      upstream.on('timeout',()=>{ fail(res,504); cleanup(); });
      upstream.on('error',()=>fail(res,502));
      upstream.end(body);
    } catch { fail(res,502); }
  });
  server.headersTimeout = 15000;
  server.requestTimeout = 120000;
  server.timeout = 0;
  server.on('connect', (_req,socket) => socket.end('HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n'));
  server.on('upgrade', (_req,socket) => socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n'));
  return server;
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  try {
    const [routesFile,secretsFile,socket] = process.argv.slice(2);
    const routes = compileRoutes(JSON.parse(fs.readFileSync(routesFile,'utf8')));
    const server = createBroker(routes,id => readCredentials(secretsFile)[id]);
    fs.rmSync(socket,{force:true});
    server.listen(socket,()=>fs.chmodSync(socket,0o666));
    server.on('error',()=>{ console.error('Inference service could not start.'); process.exit(1); });
    for (const signal of ['SIGTERM','SIGINT']) process.on(signal,()=>{server.close();server.closeAllConnections();});
  } catch { console.error('Invalid inference service configuration.'); process.exitCode = 1; }
}
