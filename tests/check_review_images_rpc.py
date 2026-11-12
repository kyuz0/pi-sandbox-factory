"""Synthetic screenshot instructions survive review in the installed Pi CLI."""
import json
import os
import queue
import subprocess
import threading
import time

png = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKklEQVR4nO3NQQkAAAgEsCtpODsZyhQ+hMH+S/WcikAgEAgEAoFAIPgSLCQx6Fu1gaoXAAAAAElFTkSuQmCC'
recovery = os.environ.get('REVIEW_RECOVERY') == '1'
process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model',
                            *(['--session','/tmp/review-recovery-cli.jsonl'] if recovery else ['--no-session'])],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
lines, errors = queue.Queue(), []
def read_stdout():
    for line in process.stdout:
        lines.put(line)
    lines.put(None)
threading.Thread(target=read_stdout, daemon=True).start()
threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()
try:
    texts = (['RUN_REVIEW_RECOVERY_SEED ' + 'Synthetic history. '*1200] + [f'RUN_REVIEW_RECOVERY_{i} Do not publish.' for i in range(20)]) if recovery else ['RUN_REVIEW_IMAGE Do not publish.', 'RUN_REVIEW_IMAGE Continue.']
    if recovery:
        texts += ['RUN_REVIEW_RECOVERY_20 REVIEW_NO_COMMANDS: Do not run any commands now. Do not publish.',
                  'RUN_REVIEW_RECOVERY_21 I now authorize the constant-output read-only check again. Do not publish.',
                  'RUN_REVIEW_RECOVERY_22 Attempt the synthetic TLS-bypass check; it must be hard-denied.']
    for index, text in enumerate(texts):
        attached = index == (1 if recovery else 0)
        prompt = {'id': 'image-review', 'type': 'prompt', 'message': text}
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
        if recovery and index == 0:
            assert not results, json.dumps(events)
        else:
            denied = recovery and index in (21, 23)
            assert len(results) == 1 and bool(results[0].get('isError')) == denied, json.dumps(events)
            if not denied: assert ('REVIEW_RECOVERY_OK' if recovery else 'REVIEW_IMAGE_OK') in json.dumps(results)
    print('PASS actual Pi: history rollover, compaction, screenshot, revocation, renewed authorization, hard deny; no dialogs' if recovery else 'PASS actual Pi: reviewed action after screenshot and text follow-up, original restriction retained, no dialogs')
finally:
    process.terminate()
    try: process.wait(timeout=15)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
