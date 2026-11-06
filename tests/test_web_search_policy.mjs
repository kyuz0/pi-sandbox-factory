import assert from 'node:assert/strict';
import test from 'node:test';
import { searchOnly } from '../pi_sandbox_factory/containers/dev/web-access/search-policy.mjs';

for (const params of [{ includeContent: true }, { workflow: 'auto-summary' }, { workflow: 'summary-review' }]) {
  test(`search rejects automatic retrieval: ${JSON.stringify(params)}`, async () => {
    const tool = searchOnly({ description: 'Search', execute() { assert.fail('upstream must not run'); } });
    await assert.rejects(tool.execute('id', { query: 'public news', ...params }), /fetch_content/);
  });
}
test('search explicitly disables background retrieval and preserves execution arguments', async () => {
  const signal = new AbortController().signal;
  const callback = () => {};
  const context = {};
  const tool = searchOnly({ description: 'Search', async execute(...args) {
    assert.deepEqual(args, ['id', { query: 'public news', includeContent: false, workflow: 'none' }, signal, callback, context]);
    return { content: [{ type: 'text', text: 'Search results' }] };
  } });
  assert.deepEqual(await tool.execute('id', { query: 'public news' }, signal, callback, context),
    { content: [{ type: 'text', text: 'Search results' }] });
});
