/** Container-local CDP provider: Chromium uses the launcher's hostname proxy.
 * Betterwright's managed upstream proxy instead resolves locally and CONNECTs
 * literal IPs, which is incompatible with a DNS-less, hostname-only allowlist.
 * No package patch, external browser, published port or host network is needed.
 */
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm, copyFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { BetterWright } from 'betterwright';

export class SandboxBrowser {
  vault = false;
  downloadPolicy = 'ask';
  #pending;
  #client;
  #process;
  #profile;
  #onExit = () => this.#process?.kill('SIGKILL');

  async #start() {
    const root = '/home/node/.cache/pi-browser';
    await mkdir(root, { recursive: true, mode: 0o700 });
    this.#profile = await mkdtemp(join(root, 'session-'));
    try {
      const runtime = join(this.#profile, 'browser/runtime');
      await mkdir(runtime, { recursive: true, mode: 0o700 });
      await copyFile('/opt/betterwright/adblock-cache/ad-blocker-2.18.2.bin',
        join(runtime, 'ad-blocker-2.18.2.bin'));
      const args = ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
        '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
        '--disable-component-update', '--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=0', '--user-data-dir=' + this.#profile];
      if (process.env.SANDBOX_NETWORK_MODE !== 'unrestricted') {
        args.push('--proxy-server=http://127.0.0.1:3128', '--proxy-bypass-list=<-loopback>');
      }
      this.#process = spawn('/opt/betterwright/.betterwright/chromium/linux-x64/betterchromium',
        [...args, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
      process.once('exit', this.#onExit);
      const endpoint = await new Promise((resolve, reject) => {
        const lines = createInterface({ input: this.#process.stderr });
        const timer = setTimeout(() => finish(new Error('Browser startup timed out')), 60000);
        let diagnostic = '';
        const onError = error => finish(error);
        const onExit = code => finish(new Error(`Browser exited (${code}): ${diagnostic.slice(-2000)}`));
        const finish = (error, value) => {
          clearTimeout(timer); lines.removeAllListeners(); lines.close();
          this.#process.off('error', onError); this.#process.off('exit', onExit);
          if (error) reject(error); else resolve(value);
        };
        this.#process.once('error', onError); this.#process.once('exit', onExit);
        lines.on('line', line => {
          diagnostic += line + '\n';
          const match = /^DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/[^\s]+)$/.exec(line);
          if (match) finish(null, match[1]);
        });
      });
      // Continue draining Chromium diagnostics after its readiness message.
      this.#process.stderr.resume();
      this.#client = new BetterWright({ provider: { cdpUrl: endpoint },
        home: this.#profile, headless: true, vault: false, downloadPolicy: this.downloadPolicy });
      return this.#client;
    } catch (error) {
      await this.#cleanup();
      throw error;
    }
  }

  async run(code, options) {
    this.#pending ??= this.#start().catch(error => { this.#pending = undefined; throw error; });
    return (await this.#pending).run(code, options);
  }

  async #cleanup() {
    process.off('exit', this.#onExit);
    const child = this.#process;
    this.#process = undefined;
    if (child && child.exitCode === null && child.signalCode === null) {
      await new Promise(resolve => {
        const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
        child.kill('SIGTERM');
      });
    }
    if (this.#profile) await rm(this.#profile, { recursive: true, force: true });
    this.#profile = undefined;
  }

  async close() {
    try { await this.#pending; await this.#client?.close(); }
    finally { await this.#cleanup(); this.#client = undefined; this.#pending = undefined; }
  }
}
