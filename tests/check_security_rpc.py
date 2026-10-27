"""Real Pi/permission/reviewer RPC flow with the local synthetic model."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import sys

external = Path('/home/node/.pi/agent/agents/external-fixture.md')
external.parent.mkdir(parents=True, exist_ok=True)
external.write_text('''---
name: external-fixture
description: Synthetic unsupported-runner fixture
runner:
  type: external-cli
  command: python3
  args: ["-c", "from pathlib import Path; Path('/workspace/external-ran-fixture.txt').touch()"]
  promptDelivery: stdin
async: true
---
Synthetic test only.
''')

Path('/tmp/DEFER_BY_FIXTURE.txt').write_text('Synthetic external-directory permission fixture.')

scenarios = ['ALLOW', 'DENY', 'DEFER', 'ESCALATE']
websec = '--websec' in sys.argv
if websec:
    scenarios = ['WEBSEC_ALLOW', 'WEBSEC_DENY']
elif os.environ.get('SANDBOX_SUBAGENTS') == '1':
    scenarios += ['SUBAGENT', 'SUBAGENT_ASYNC', 'SUBAGENT_NESTED',
                  'SUBAGENT_EXTERNAL', 'SUBAGENT_ASYNC_DEFER']
for scenario in scenarios:
    process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = queue.Queue()
    errors = []
    def stdout_reader():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    def stderr_reader():
        errors.extend(process.stderr.readlines())
    threading.Thread(target=stdout_reader, daemon=True).start()
    threading.Thread(target=stderr_reader, daemon=True).start()
    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    events = []
    dialogs = 0
    expects_dialog = scenario in ('DEFER', 'SUBAGENT_ASYNC_DEFER')
    def handle_event(event):
        global dialogs
        events.append(event)
        if event.get('type') == 'extension_ui_request' and event.get('method') in ('select', 'confirm'):
            dialogs += 1
            assert expects_dialog, ('Unexpected human dialog', scenario, event)
            if event['method'] == 'confirm':
                send({'type': 'extension_ui_response', 'id': event['id'], 'confirmed': True})
            else:
                options = event['options']
                choice = next((x for x in options if x == 'Yes'), None)
                if choice is None:
                    choice = next(x for x in options if ('allow' in x.lower() or 'yes' in x.lower()) and 'session' not in x.lower() and 'always' not in x.lower())
                send({'type': 'extension_ui_response', 'id': event['id'], 'value': choice})
    try:
        message = 'RUN_WEBSEC_MCP_' + scenario.removeprefix('WEBSEC_') if websec else 'RUN_SECURITY_' + scenario
        send({'id': 'test', 'type': 'prompt', 'message': message})
        deadline = time.monotonic() + 300
        while True:
            line = lines.get(timeout=max(1, deadline - time.monotonic()))
            assert line is not None, ''.join(errors)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            handle_event(event)
            if event.get('type') == 'agent_settled':
                break
        results = [e for e in events if e.get('type') == 'tool_execution_end']
        assert results, (scenario, events, errors)
        result = json.dumps(results)
        if scenario.startswith('SUBAGENT_ASYNC'):
            details = results[0]['result']['details']
            status_file = Path(details['asyncDir']) / 'status.json'
            # Keep the parent RPC session alive for permission forwarding.
            while time.monotonic() < deadline:
                if status_file.exists():
                    status = json.loads(status_file.read_text())
                    if status.get('state') in ('complete', 'failed', 'partial', 'paused', 'stopped', 'rejected'):
                        break
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                assert line is not None, ''.join(errors)
                try:
                    handle_event(json.loads(line))
                except json.JSONDecodeError:
                    continue
            else:
                raise AssertionError(('Background child did not finish', status_file.read_text(), errors))
            result = json.dumps(status)
            assert status['state'] == 'complete', result
        if websec:
            calls = [e for e in results if e.get('toolName') == 'mcp__burp__get_proxy_http_history_summary']
            assert len(calls) == 1, result
            if scenario == 'WEBSEC_ALLOW':
                assert 'WEBSEC_MCP_OK' in json.dumps(calls) and not calls[0].get('isError'), result
            else:
                assert calls[0].get('isError') and 'WEBSEC_MCP_OK' not in json.dumps(calls), result
                assert 'denied' in result.lower() or 'blocked' in result.lower(), result
        elif scenario == 'DENY':
            assert not Path('denied-fixture.txt').exists(), 'Denied command executed'
            assert 'denied' in result.lower() or 'blocked' in result.lower(), result
        elif scenario == 'SUBAGENT_EXTERNAL':
            assert not Path('external-ran-fixture.txt').exists(), 'Unsupported runner bypassed required policy'
            assert any(e.get('isError') for e in results), result
            assert 'requires child extensions' in result, result
        else:
            marker = ('SUBAGENT_FIXTURE_OK' if scenario.startswith('SUBAGENT') else
                      {'ALLOW': 'ALLOW_EXECUTED', 'DEFER': 'DEFER_BY_FIXTURE', 'ESCALATE': 'ESCALATE_EXECUTED'}[scenario])
            assert marker in result, result
            assert not any(e.get('isError') for e in results), result
        if scenario.startswith('SUBAGENT'):
            assert not Path('child-denied-fixture.txt').exists(), 'Denied child command executed'
        if scenario == 'SUBAGENT_ASYNC_DEFER':
            assert Path('child-defer-fixture.txt').read_text() == 'DEFER_BY_FIXTURE'
        assert dialogs > 0 if expects_dialog else dialogs == 0
        print('PASS real Pi RPC security flow: ' + scenario.lower(), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
