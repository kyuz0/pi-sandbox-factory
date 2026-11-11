import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createAgentSession} from '/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/sdk.js';
const enabled = JSON.parse(fs.readFileSync('/opt/sandbox/options.json')).question_forms !== false;
const {session, extensionsResult} = await createAgentSession({cwd:'/workspace',agentDir:'/home/node/.pi/agent'});
try {
  assert.deepEqual(extensionsResult.errors, []);
  const names = session.getAllTools().map(t => t.name);
  assert.equal(names.includes('ask_user_question'), enabled);
  assert(names.includes('bash_escalate'), 'Reviewed escalation missing');
  console.log('PASS installed Pi: question forms ' + enabled + ', reviewed escalation retained');
} finally { session.dispose(); }
