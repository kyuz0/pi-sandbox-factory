import { createPiExtension } from 'betterwright/pi-extension';
import { SandboxBrowser } from './browser.mjs';

export default function extension(pi) {
  createPiExtension({ browser: new SandboxBrowser() })(pi);
}
