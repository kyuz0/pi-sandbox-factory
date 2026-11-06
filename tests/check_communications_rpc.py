"""Exercise the installed Pi CLI's Slack tools and credential boundaries with fixture replies."""
import json
import os
import queue
import subprocess
import threading
import time

process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model', '--no-session', '--approve'],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
lines, errors, events = queue.Queue(), [], []
def read_stdout():
    for line in process.stdout:
        lines.put(line)
    lines.put(None)
threading.Thread(target=read_stdout, daemon=True).start()
threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()
def send(value):
    process.stdin.write(json.dumps(value) + '\n')
    process.stdin.flush()
try:
    send({'id':'viewer', 'type':'prompt', 'message':'RUN_COMMUNICATIONS'})
    deadline, questions = time.monotonic() + 180, 0
    while time.monotonic() < deadline:
        line = lines.get(timeout=max(1, deadline - time.monotonic()))
        assert line is not None, errors
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        assert not (event.get('type') == 'extension_ui_request' and event.get('method') in ('select', 'confirm', 'input', 'editor')), 'Unexpected approval dialog: ' + str(event)
        if event.get('type') == 'agent_settled':
            break
    results = [e for e in events if e.get('type') == 'tool_execution_end']
    assert len(results) == 6, json.dumps(events)
    assert 'invalid_auth' in json.dumps(results[0]), results[0]
    assert 'SLACK_USER_TOKEN' in json.dumps(results[1]), results[1]
    assert 'Synthetic integration review: deny' in json.dumps(results[2]), results[2]
    assert all(result.get('isError') for result in results[:5]), results
    assert 'CREDENTIAL_ENV_EMPTY' in json.dumps(results[5]) and not results[5].get('isError'), results[5]
    assert 'xoxb-sandbox-fixture-only' not in json.dumps(events), 'Credential disclosed'
    print('PASS actual Pi CLI: Slack through proxy, missing search token, denied send, private credentials')

finally:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
