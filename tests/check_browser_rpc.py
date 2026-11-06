"""Exercise the installed Pi CLI's browser/viewer/question handoff with fixture replies."""
import json
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
    send({'id':'viewer', 'type':'prompt', 'message':'RUN_VIEWER_ONE'})
    deadline, questions = time.monotonic() + 180, 0
    while time.monotonic() < deadline:
        line = lines.get(timeout=max(1, deadline - time.monotonic()))
        assert line is not None, errors
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get('type') == 'extension_ui_request' and event.get('method') == 'select':
            questions += 1
            assert 'Open the live browser' in json.dumps(event), event
            send({'type':'extension_ui_response','id':event['id'],'value':event['options'][0]})
        if event.get('type') == 'agent_settled':
            break
    results = [e for e in events if e.get('type') == 'tool_execution_end']
    assert len(results) == 4, json.dumps(events)
    assert not any(e.get('isError') for e in results), [(e['toolName'],e['result'].get('content')) for e in results if e.get('isError')]
    assert [e['toolName'] for e in results] == ['browser','browser_viewer','ask_user_question','browser']
    assert 'VIEWER_ONE' in json.dumps(results[-1]), results
    assert questions == 1, questions
    print('PASS actual Pi CLI: browser, viewer link, question and same-session continuation')
finally:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
