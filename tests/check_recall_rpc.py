"""Exercise installed recall tools against a synthetic compacted Pi session."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

mode = json.loads(Path('/opt/sandbox/options.json').read_text())['compaction_recall']
assert os.environ['COMPACTION_RECALL_MODE'] == ('full' if mode == 'full' else 'lite')
stamp = '2026-01-01T00:00:00.000Z'
rows = [
    {'type': 'session', 'version': 3, 'id': 'recall-fixture', 'timestamp': stamp, 'cwd': '/workspace'},
    {'type': 'message', 'id': 'old-recall', 'parentId': None, 'timestamp': stamp,
     'message': {'role': 'user', 'content': 'For the cobalt reporting service, we agreed to use TCP port 8123.', 'timestamp': 0}},
    {'type': 'message', 'id': 'live-recall', 'parentId': 'old-recall', 'timestamp': stamp,
     'message': {'role': 'user', 'content': 'Continue working on the service.', 'timestamp': 1}},
    {'type': 'compaction', 'id': 'compact-recall', 'parentId': 'live-recall', 'timestamp': stamp,
     'firstKeptEntryId': 'live-recall', 'summary': 'The user is building a service.', 'tokensBefore': 1000},
]
for client in ('cli', 'pendant'):
    rows[0]['id'] = 'recall-fixture-' + client
    Path('/tmp/recall-' + client + '.jsonl').write_text('\n'.join(map(json.dumps, rows)) + '\n')
process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model',
                            '--session', '/tmp/recall-cli.jsonl', '--approve'],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd='/workspace')
lines, errors, events = queue.Queue(), [], []
def read_stdout():
    for line in process.stdout:
        lines.put(line)
    lines.put(None)
threading.Thread(target=read_stdout, daemon=True).start()
threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()
try:
    process.stdin.write(json.dumps({'type': 'prompt', 'message': 'RUN_RECALL: Which TCP port did we choose for the cobalt reporting service?'}) + '\n')
    process.stdin.flush()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        line = lines.get(timeout=max(1, deadline - time.monotonic()))
        assert line is not None, errors
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        assert not (event.get('type') == 'extension_ui_request' and event.get('method') in ('select', 'confirm', 'input')), event
        if event.get('type') == 'agent_settled':
            break
    results = [e for e in events if e.get('type') == 'tool_execution_end']
    assert len(results) == (0 if mode == 'off' else 3 if mode == 'full' else 2), json.dumps(events)
    assert all(not r.get('isError') and '8123' in json.dumps(r) for r in results), json.dumps(results)
    assert 'RECALL_DONE' in json.dumps(events), json.dumps(events)
    print('PASS actual Pi CLI: recall ' + mode + ', compacted history and no approval dialogs')
finally:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill();process.wait()
