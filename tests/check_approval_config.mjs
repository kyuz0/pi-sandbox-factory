// Run inside a built development image: node --experimental-transform-types tests/check_approval_config.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const root = resolve(process.argv[2] ?? '/opt/pi-security');
const { loadConfig, applyUserConfig, applyProjectConfig } = await import(
  pathToFileURL(`${root}/packages/pi-auto-review/src/review/config.ts`).href);
const config = applyUserConfig(loadConfig(), JSON.parse(
  readFileSync(`${root}/config/auto-review.json`, 'utf8')));
assert.equal(config.model, 'current');
assert.equal(config.maxTokens, 32768);
assert.equal(config.reasoning, 'low');
assert.equal(config.interactionMode, 'automatic');
assert.equal(config.retainedContext, true);
assert.equal(config.reviewerConversation, true);
assert.equal(config.investigationTools, false);
// Workspace configuration must not remove original instructions or turn on tools.
for (const override of [{ retainedContext: false }, { reviewerConversation: false },
  { investigationTools: true }, { model: 'another/reviewer' }]) {
  assert.throws(() => applyProjectConfig(config, override));
}
assert.throws(() => applyUserConfig(config, { investigationTools: true }));
assert.equal(applyProjectConfig(config, { timeoutMs: 1000 }).timeoutMs, 1000);
console.log('Approval configuration: conversation without tools; workspace restrictions enforced.');

const permissions = JSON.parse(readFileSync(`${root}/config/permissions.json`, 'utf8'));
assert.equal(permissions.permission.ask_user_question, 'allow');
assert.equal(permissions.permission['*'], 'ask');
assert.equal(permissions.permission.advisor_ask, 'ask');
assert.equal(permissions.permission.external_directory, 'ask');
console.log('Question tool is allowed directly; other permission boundaries remain reviewed.');
