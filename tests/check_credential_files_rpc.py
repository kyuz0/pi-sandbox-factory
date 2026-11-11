"""Check common credential-file protection through actual Pi tools."""
import json
import queue
import subprocess
import threading
import time

protected = json.load(open('/tmp/credential-files-protected.json'))
p = subprocess.Popen(
    ['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
lines = queue.Queue()
errors = []

def read_lines():
    for line in p.stdout:
        lines.put(line)
    lines.put(None)

threading.Thread(target=read_lines, daemon=True).start()
threading.Thread(target=lambda: errors.extend(p.stderr.readlines()), daemon=True).start()
try:
    p.stdin.write(json.dumps({'id': 'credential-files', 'type': 'prompt', 'message': 'RUN_CREDENTIAL_FILES'}) + '\n')
    p.stdin.flush()
    events = []
    deadline = time.monotonic() + 120
    while True:
        line = lines.get(timeout=max(1, deadline - time.monotonic()))
        assert line is not None, ''.join(errors)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        assert not (
            event.get('type') == 'extension_ui_request'
            and event.get('method') in ('select', 'confirm')
        ), 'Unexpected permission dialog'
        if event.get('type') == 'agent_settled':
            break

    results = [event for event in events if event.get('type') == 'tool_execution_end']
    assert len(results) == 4, json.dumps(events)
    assert all(bool(result.get('isError')) is protected for result in results), results
    if protected:
        assert subprocess.check_output(['cat', '/workspace/.env'], text=True) == 'CREDENTIAL_ORIGINAL'
    else:
        assert subprocess.check_output(['cat', '/workspace/.env'], text=True) == 'CREDENTIAL_BASH_WRITE'
    print('PASS protected credential files reject all four operations' if protected else
          'PASS unprotected credential files allow native and Bash reads and writes', flush=True)
finally:
    p.terminate()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
