import fs from 'node:fs';
import path from 'node:path';

export function readCredentials(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return {}; throw error; }
}

export function updateCredentials(file, request) {
  if (!/^[a-z][a-z0-9-]{0,63}$/.test(request.id)) throw Error('Invalid connection name.');
  const values = readCredentials(file);
  if (request.remove) delete values[request.id];
  else {
    const origin = new URL(request.origin);
    if (!['https:', 'http:'].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw Error('Invalid origin.');
    const current = values[request.id];
    const supplied = request.credentials || {};
    const fields = request.auth === 'sigv4' ? ['accessKeyId','secretAccessKey','sessionToken'] : ['key'];
    const retaining = fields.every(field => !supplied[field]);
    const entry = retaining && current?.origin === origin.origin ? {...current} : {origin:origin.origin};
    for (const field of fields) {
      const value = request.credentials?.[field];
      if (value !== undefined && !retaining) {
        if (typeof value !== 'string' || value.length > 16384 || /[\r\n\0]/.test(value)) throw Error('Invalid credential.');
        entry[field] = value;
      }
    }
    if (request.auth === 'sigv4') {
      delete entry.key;
      if (!entry.accessKeyId || !entry.secretAccessKey) throw Error('Enter complete credentials.');
    } else {
      delete entry.accessKeyId; delete entry.secretAccessKey; delete entry.sessionToken;
      if (!entry.key) throw Error('Enter complete credentials.');
    }
    values[request.id] = entry;
  }
  fs.mkdirSync(path.dirname(file), {recursive:true, mode:0o700});
  const temp = file + '.' + process.pid + '.tmp';
  try {
    const fd = fs.openSync(temp, 'wx', 0o600);
    try { fs.writeFileSync(fd, JSON.stringify(values)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temp, file);
    const directory = fs.openSync(path.dirname(file), 'r');
    try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
  } finally { fs.rmSync(temp, {force:true}); }
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  try {
    let input = '';
    for await (const part of process.stdin) {
      input += part;
      if (input.length > 65536) throw Error('Request too large.');
    }
    const request = JSON.parse(input);
    if (request.status) console.log(JSON.stringify({configured:Object.keys(readCredentials(process.argv[2]))}));
    else { updateCredentials(process.argv[2], request); console.log('{"ok":true}'); }
  } catch { console.error('Could not update inference credentials.'); process.exitCode = 1; }
}
