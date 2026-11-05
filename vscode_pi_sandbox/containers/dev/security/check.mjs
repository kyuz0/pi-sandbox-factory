// Exercise real nested execution without a real model or private documents.
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, rmSync, readFileSync, realpathSync} from 'node:fs';
import {join} from 'node:path';
import {createJiti} from 'jiti';
const {runSandboxedCommand} = await createJiti(import.meta.url, {tryNative: false}).import('./packages/pi-sandbox/src/runner.ts');
import {validatePublicHostname} from './packages/pi-sandbox/src/network-policy.mjs';

for (const name of ['pi-auto-review', 'pi-sandbox']) {
  assert.equal(realpathSync('/opt/pi-security/node_modules/@erichll/' + name), '/opt/pi-security/packages/' + name);
}
console.log('PASS review and sandbox packages resolve directly to the pinned fork source');

const secretDir = mkdtempSync('/home/node/nested-check-');
const secret = join(secretDir, 'private.txt');
writeFileSync(secret, 'fixture-secret');
const fixture = mkdtempSync(join(process.cwd(), '.nested-check-'));
const quote = s => `'${s.replaceAll("'", "'\\''")}'`;
async function run(command, allow = false) {
  let output = '';
  const reviews = [];
  const result = await runSandboxedCommand({
    command, cwd: fixture, onData: data => { output += data.toString(); },
    review: async () => 'deny',
    reviewDomain: async endpoint => { reviews.push(endpoint); return allow ? 'allow' : 'deny'; },
  });
  return {...result, output, reviews};
}
try {
  let r = await run('printf NESTED_OK; printf saved > allowed.txt');
  assert.equal(r.exitCode, 0, r.output);
  assert.match(r.output, /NESTED_OK/);
  assert.equal(readFileSync(join(fixture, 'allowed.txt'), 'utf8'), 'saved');
  writeFileSync(join(fixture, '.env'), 'unchanged');
  r = await run('printf changed > .env');
  assert.notEqual(r.exitCode, 0, 'Inner sandbox changed a protected workspace file');
  assert.equal(readFileSync(join(fixture, '.env'), 'utf8'), 'unchanged');
  r = await run('python -c ' + quote('import pypdf, fitz, PyPDF2, docx, openpyxl, pptx; from reportlab.pdfgen.canvas import Canvas; c=Canvas("fixture.pdf"); c.drawString(20, 20, "DOCUMENT_OK"); c.save(); assert "DOCUMENT_OK" in pypdf.PdfReader("fixture.pdf").pages[0].extract_text()'));
  assert.equal(r.exitCode, 0, r.output);
  console.log('PASS document libraries process a PDF inside sandboxed Bash');
  r = await run('cat ' + quote(secret));
  assert.notEqual(r.exitCode, 0, 'Inner sandbox exposed private home file');
  r = await run('printf modified > /opt/pi-security/config/auto-review.json');
  assert.notEqual(r.exitCode, 0, 'Inner sandbox modified reviewer policy');
  r = await run('python3 -c ' + quote('import socket; socket.socket(socket.AF_UNIX)'));
  assert.notEqual(r.exitCode, 0, 'Unix socket filter was not applied');
  assert.match(r.output, /Operation not permitted|Permission denied/);
  r = await run('curl --noproxy "*" --connect-timeout 2 --max-time 4 https://1.1.1.1');
  assert.notEqual(r.exitCode, 0, 'Inner sandbox allowed direct network access');
  console.log('PASS nested Bash: writable workspace, private-home denial, immutable policy, Unix-socket filtering, direct-network denial');
  if (process.env.SANDBOX_NETWORK_MODE === 'allowlist') {
    assert.equal(await validatePublicHostname('example.com'), 'example.com');
    assert.equal(await validatePublicHostname('127.0.0.1'), undefined);
    assert.equal(await validatePublicHostname('https://example.com/path'), undefined);
  }
  const url = process.argv[2] || 'https://example.com';
  r = await run('curl --silent --show-error --max-time 30 --output /dev/null --write-out "%{http_code}" ' + quote(url), true);
  assert.equal(r.exitCode, 0, r.output);
  // Match the launcher's check contract: an unauthenticated 401/404 still proves
  // the allowed destination is reachable; proxy/gateway failures do not.
  const status = r.output.trim().slice(-3);
  assert.match(status, /^\d{3}$/, r.output);
  assert.ok(!['000', '403', '502', '503', '504'].includes(status), r.output);
  assert.ok(r.reviews.length > 0, 'Connection bypassed the review callback');
  r = await run('curl --fail --silent --show-error --max-time 15 https://example.com >/dev/null');
  assert.notEqual(r.exitCode, 0, 'Denied connection succeeded');
  assert.ok(r.reviews.length > 0, 'Denied connection never reached reviewer');
  console.log('PASS nested network: hostname validation, reviewed connection through outer network, denied connection');
} finally {
  rmSync(secretDir, {recursive: true, force: true});
  rmSync(fixture, {recursive: true, force: true});
}
