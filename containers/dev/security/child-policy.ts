import { readFileSync, existsSync } from 'node:fs';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { registerRequiredChildExtensions } from 'pi-subagents/required-child-extensions';

export default function childPolicy(pi: ExtensionAPI) {
  const file = '/opt/sandbox/options.json';
  const selected = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  const automatic = (selected.approval ?? 'automatic') === 'automatic';
  const inner = selected.inner_sandbox !== false;
  const paths = [
    automatic ? '/opt/pi-security/packages/pi-auto-review/src/index.ts' : '/opt/pi-security/approval-mode.ts',
    '/opt/pi-security/node_modules/@gotgenes/pi-permission-system/src/index.ts',
    ...(inner && selected.approval !== 'off' ? ['/opt/pi-security/packages/pi-reviewed-escalation/index.ts'] : []),
    ...(inner ? ['/opt/pi-security/packages/pi-sandbox/src/index.ts'] : []),
    '/opt/pi-security/child-policy.ts',
  ];
  let registration: ReturnType<typeof registerRequiredChildExtensions> | undefined;
  pi.on('session_start', (_event, ctx) => {
    registration?.dispose();
    registration = registerRequiredChildExtensions({ sessionId: ctx.sessionManager.getSessionId(),
      requireForAllRunners: true, extensions: paths.map((path, index) => ({ id: 'container-policy-' + index, path })) });
  });
  pi.on('before_agent_start', event => {
    let systemPrompt = event.systemPrompt;
    for (const name of ['profile.md', 'document-tools.md', 'security.md']) {
      const path = name === 'security.md' && existsSync('/opt/pi-security/config/security.md')
        ? '/opt/pi-security/config/security.md' : '/opt/sandbox/' + name;
      const guidance = readFileSync(path, 'utf8').trim();
      if (!systemPrompt.includes(guidance)) systemPrompt += '\n\n' + guidance;
    }
    systemPrompt += '\nSaved sandbox settings: ' + JSON.stringify(selected) + '. Use only enabled capabilities.';
    return { systemPrompt };
  });
  pi.on('session_shutdown', () => { registration?.dispose(); registration = undefined; });
}
