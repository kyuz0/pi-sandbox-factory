"""Actual timer delivery through standalone Pi RPC."""
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


for scenario in ('SCHEDULE', 'BUSY', 'REJECT'):
    process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines, errors = queue.Queue(), []
    def read_stdout():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()
    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    events, dialogs = [], []
    deadline = time.monotonic() + 180
    def read_event():
        while time.monotonic() < deadline:
            line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            assert line is not None, (scenario, errors, events[-5:])
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            if event.get('type') == 'extension_ui_request' and event.get('method') in ('confirm', 'select'):
                assert scenario in ('SCHEDULE', 'BUSY'), (scenario, event)
                dialogs.append(event)
                if event['method'] == 'confirm':
                    send({'type': 'extension_ui_response', 'id': event['id'], 'confirmed': True})
                else:
                    choices = event['options']
                    choice = next((x for x in choices if x == 'Yes'), None)
                    if choice is None:
                        choice = next(x for x in choices if ('allow' in x.lower() or 'yes' in x.lower()) and
                                      'session' not in x.lower() and 'always' not in x.lower())
                    send({'type': 'extension_ui_response', 'id': event['id'], 'value': choice})
            return event
        raise AssertionError((scenario, 'RPC did not finish', errors, events[-10:]))
    try:
        marker = 'AUTOMATION_' + ('REJECT' if scenario == 'REJECT' else 'SCHEDULE') + '_DONE'
        send({'type': 'prompt', 'message': 'RUN_AUTOMATION_' + scenario})
        done = False
        while True:
            event = read_event()
            if marker in json.dumps(event):
                done = True
            if done and event.get('type') == 'agent_settled':
                break
        results = [e for e in events if e.get('type') == 'tool_execution_end']
        text = json.dumps(results)
        if scenario == 'REJECT':
            assert len(results) == 1 and results[0]['toolName'] == 'schedule_prompt', results
            assert results[0].get('isError') and ('denied' in text.lower() or 'blocked' in text.lower()), results
            store = Path('.pi/schedule-prompts.json')
            assert not any(j['name'] == 'automation-rejected' for j in json.loads(store.read_text())['jobs'])
        else:
            assert [e['toolName'] for e in results] == ['schedule_prompt', 'bash', 'bash_escalate', 'bash_escalate'], results
            assert 'AUTOMATION_SCHEDULE_BASH_OK' in text and 'DEFER_BY_FIXTURE' in text
            assert dialogs and results[-1].get('isError'), results
            assert not Path('automation-denied.txt').exists(), 'A denied scheduled command ran'
            send({'id': 'messages', 'type': 'get_messages'})
            while True:
                reply = read_event()
                if reply.get('id') == 'messages':
                    assert reply['success'], reply
                    messages = reply['data']['messages']
                    injected = [m for m in messages if m.get('role') == 'user' and 'AUTOMATION_TIMER_FIRE' in json.dumps(m.get('content'))]
                    assert len(injected) == 1, ('Timer must inject once in the original chat', messages)
                    break
            job = results[0]['result']['details']['jobs'][0]
            assert job['session'] and not job.get('model'), job
        print('PASS real Pi automation: ' + scenario.lower(), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
