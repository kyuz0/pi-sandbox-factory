"""Synthetic screenshot instructions survive review in the installed Pi CLI."""
import json
import queue
import subprocess
import threading
import time

png = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKklEQVR4nO3NQQkAAAgEsCtpODsZyhQ+hMH+S/WcikAgEAgEAoFAIPgSLCQx6Fu1gaoXAAAAAElFTkSuQmCC'
process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model', '--no-session'],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
lines, errors = queue.Queue(), []
def read_stdout():
    for line in process.stdout:
        lines.put(line)
    lines.put(None)
threading.Thread(target=read_stdout, daemon=True).start()
threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()
try:
    for attached in (True, False):
        prompt = {'id': 'image-review', 'type': 'prompt', 'message': 'RUN_REVIEW_IMAGE Do not publish.' if attached else 'RUN_REVIEW_IMAGE Continue.'}
        if attached:
            prompt['images'] = [{'type': 'image', 'mimeType': 'image/png', 'data': png}]
        process.stdin.write(json.dumps(prompt) + '\n'); process.stdin.flush()
        events = []
        deadline = time.monotonic() + 180
        while True:
            line = lines.get(timeout=max(1, deadline - time.monotonic()))
            assert line is not None, ''.join(errors)
            try: event = json.loads(line)
            except json.JSONDecodeError: continue
            events.append(event)
            assert not (event.get('type') == 'extension_ui_request' and event.get('method') in ('select', 'confirm'))
            if event.get('type') == 'agent_settled': break
        results = [e for e in events if e.get('type') == 'tool_execution_end']
        assert len(results) == 1 and not results[0].get('isError'), json.dumps(events)
        assert 'REVIEW_IMAGE_OK' in json.dumps(results)
    print('PASS actual Pi: reviewed action after screenshot and text follow-up, original restriction retained, no dialogs')
finally:
    process.terminate()
    try: process.wait(timeout=15)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
