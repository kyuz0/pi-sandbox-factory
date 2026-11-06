"""Exercise the installed Pi CLI's web search and page retrieval with fixture replies."""
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
    send({'id':'viewer', 'type':'prompt', 'message':'RUN_WEB_ONLY' if os.environ.get('WEB_ONLY') else 'RUN_WEB_ACCESS'})
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
    if os.environ.get('WEB_ONLY'):
        assert len(results) == 2 and all(result.get('isError') for result in results), results
        assert '503' in json.dumps(results[0]), results[0]
        assert 'disabled provider' in json.dumps(results[1]), results[1]
        print('PASS actual Pi CLI: Only SearXNG never falls back; explicit Exa override rejected')
    else:
        assert len(results) == 7, json.dumps(events)
        assert not results[0].get('isError'), results[0]
        assert not results[1].get('isError'), results[1]
        assert 'Comprehensions' in json.dumps(results[1]), results[1]
        assert any(s in json.dumps(results[2]) for s in ('403', 'Forbidden', 'denied')), results[2]
        for result in results[3:5]:
            assert result.get('isError'), result
            assert 'use fetch_content' in json.dumps(result), result
        assert results[6].get('isError'), results[6]
        assert 'Synthetic integration review: deny' in json.dumps(results[6]), results[6]
        notices = [e for e in events if e.get('type') == 'extension_ui_request' and e.get('method') == 'notify' and 'Auto-review' in e.get('message', '')]
        assert len(notices) == 3, notices
        assert all('fetch_content' in n['message'] for n in notices), notices
        assert all('Synthetic integration review:' in n['message'] for n in notices), notices
        print('PASS actual Pi CLI: live Exa search, allowed Python page, blocked unselected page')

finally:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
