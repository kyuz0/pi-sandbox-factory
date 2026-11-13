"""Run only in a disposable browser sandbox: real tool guards, synthetic model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import subprocess
import threading

secret = 'SYNTHETIC_PRIVATE_SESSION_GUARD_VALUE'
root = Path('/home/node/.local/state/pi-browser-sessions/session-guard')
root.mkdir(parents=True, exist_ok=True, mode=0o700)
target = root / 'cookies.txt'
target.write_text(secret + '\n'); target.chmod(0o600)
link = Path('/workspace/session-guard-link')
link.symlink_to(root, target_is_directory=True)
cases = [(name, arguments) for name, arguments in [
    ('read', {'path': str(target)}),
    ('read', {'path': '~/.local/state/pi-browser-sessions/session-guard/cookies.txt'}),
    ('read', {'path': '../home/node/.local/state/pi-browser-sessions/session-guard/cookies.txt'}),
    ('read', {'path': str(link / 'cookies.txt')}),
    ('grep', {'pattern': 'PRIVATE', 'path': str(root)}),
    ('find', {'pattern': '*', 'path': str(root)}),
    ('ls', {'path': str(root)}),
    ('write', {'path': str(target), 'content': 'CORRUPTED'}),
    ('edit', {'path': str(target), 'oldText': 'SYNTHETIC', 'newText': 'CORRUPTED'}),
    ('bash', {'command': 'cat ' + str(target)}),
    ('bash', {'command': 'cat ' + str(link / 'cookies.txt')}),
]]
reviews = []

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages = data['messages']
        assert secret not in json.dumps(messages), 'Private session leaked to the model'
        reviewing = any(m.get('role') in ('system', 'developer') and str(m.get('content', '')).startswith(
            ('Review one proposed coding-agent action.', 'You are a fail-closed permission reviewer.')) for m in messages)
        delta, finish = {'role': 'assistant'}, 'stop'
        if reviewing:
            reviews.append(True)
            delta['content'] = json.dumps({'outcome': 'deny', 'risk_level': 'high', 'user_authorization': 'low',
                'rationale': 'Do not expose private synthetic session files.'})
        else:
            outputs = [m for m in messages if m.get('role') == 'tool']
            if len(outputs) == len(cases): delta['content'] = 'SESSION_GUARDS_DONE'
            else:
                name, arguments = cases[len(outputs)]
                delta['tool_calls'] = [{'index': 0, 'id': 'guard-' + str(len(outputs)), 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(arguments)}}]
                finish = 'tool_calls'
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        for change, stop in ((delta, None), ({}, finish)):
            event = {'id': 'guard-fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fixture-model',
                'choices': [{'index': 0, 'delta': change, 'finish_reason': stop}]}
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
models = Path('/home/node/.pi/agent/models.json'); saved = models.read_text()
models.write_text(json.dumps({'providers': {'fixture': {'baseUrl': f'http://127.0.0.1:{server.server_port}/v1',
    'api': 'openai-completions', 'apiKey': 'synthetic-placeholder',
    'models': [{'id': 'fixture-model', 'contextWindow': 32000, 'maxTokens': 4096}]}}}))
try:
    for client in ('pi', 'pendant'):
        command = ['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model', '--no-session', '--approve', '--tools', 'read,bash,edit,write,grep,find,ls'] if client == 'pi' else ['node', '/tmp/session-worker-bridge.cjs', 'fixture', 'fixture-model', '--all-file-tools']
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        lines = queue.Queue()
        def read_stdout():
            for line in process.stdout: lines.put(line)
            lines.put(None)
        threading.Thread(target=read_stdout, daemon=True).start()
        try:
            process.stdin.write(json.dumps({'type': 'prompt', 'message': 'Exercise only the synthetic private-session guard fixture.'}) + '\n'); process.stdin.flush()
            events = []
            while True:
                line = lines.get(timeout=180)
                assert line is not None, 'Client ended before completing tool guard checks'
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                events.append(event)
                assert secret not in json.dumps(event), 'Session value leaked into tool output'
                assert not (event.get('type') == 'extension_ui_request' and event.get('method') in ('select','confirm','input')), 'Unexpected approval dialog'
                if event.get('type') == 'agent_settled': break
            results = [e for e in events if e.get('type') == 'tool_execution_end']
            assert len(results) == len(cases), (len(results), len(cases))
            for result, (name, arguments) in zip(results, cases):
                text = json.dumps(result).lower()
                assert result.get('toolName') == name
                assert any(word in text for word in ('denied', 'not permitted', 'permission', 'not allowed')), (name, arguments, result)
            assert target.read_text() == secret + '\n', 'Native edit/write altered the private session'
            print('PASS ' + client + ': ' + str(len(cases)) + ' native/inner-shell guard cases, no session values or dialogs', flush=True)
        finally:
            process.terminate()
            try: process.wait(timeout=30)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
finally:
    models.write_text(saved); server.shutdown(); link.unlink(missing_ok=True)
    target.unlink(missing_ok=True); root.rmdir()
