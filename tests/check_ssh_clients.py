"""Run inside the disposable SSH client: real Pi/Pendant with synthetic model replies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import subprocess
import threading

reviews, contexts = [], []
alias = json.loads(Path('/etc/sandbox-ssh/targets.json').read_text())[0]['alias']


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages = data['messages']
        text = json.dumps(messages)
        reviewing = any(m.get('role') in ('system', 'developer') and str(m.get('content', '')).startswith(
            ('Review one proposed coding-agent action.', 'You are a fail-closed permission reviewer.')) for m in messages)
        delta = {'role': 'assistant'}
        finish = 'stop'
        if reviewing:
            assert 'sandbox-ssh-status' in text, 'Wrong command sent to reviewer'
            reviews.append(True)
            delta['content'] = json.dumps({'outcome': 'allow', 'risk_level': 'low', 'user_authorization': 'high',
                                          'rationale': 'Synthetic managed SSH status check.'})
        else:
            assert 'Managed SSH destinations' in text and alias in text, text[:1000]
            assert 'use bash_escalate directly' in text and 'sandbox-ssh-status' in text
            contexts.append(True)
            outputs = [m for m in messages if m.get('role') == 'tool']
            if len(outputs) == 2:
                assert 'Fixture Author <fixture@example.test>' in json.dumps(outputs[-1]), 'Commit identity missing in inner Bash'
                delta['content'] = 'SSH_STATUS_DONE'
            elif outputs:
                delta['tool_calls'] = [{'index': 0, 'id': 'git-identity-check', 'type': 'function',
                    'function': {'name': 'bash', 'arguments': json.dumps({'command':
                        'mkdir -p /workspace/git-identity-fixture && cd /workspace/git-identity-fixture && '
                        'git init -q && git -c core.hooksPath=/dev/null -c commit.gpgsign=false commit --allow-empty -qm fixture && '
                        'git log -1 --format="%an <%ae>"'})}}]
                finish = 'tool_calls'
            else:
                delta['tool_calls'] = [{'index': 0, 'id': 'ssh-status-check', 'type': 'function',
                    'function': {'name': 'bash_escalate', 'arguments': json.dumps({
                        'command': 'sandbox-ssh-status', 'justification': 'Check managed SSH key availability without reading keys.'})}}]
                finish = 'tool_calls'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for change, stop in ((delta, None), ({}, finish)):
            event = {'id': 'ssh-fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fixture-model',
                     'choices': [{'index': 0, 'delta': change, 'finish_reason': stop}]}
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
models = Path('/home/node/.pi/agent/models.json')
saved = models.read_text()
models.write_text(json.dumps({'providers': {'fixture': {'baseUrl': f'http://127.0.0.1:{server.server_port}/v1',
    'api': 'openai-completions', 'apiKey': 'synthetic-placeholder',
    'models': [{'id': 'fixture-model', 'contextWindow': 32000, 'maxTokens': 4096}]}}}))
process = None
try:
    process = subprocess.Popen(['pi', '--mode', 'rpc', '--provider', 'fixture', '--model', 'fixture-model',
                                '--no-session', '--approve'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    lines = queue.Queue()
    def read_stdout():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=read_stdout, daemon=True).start()
    process.stdin.write(json.dumps({'type': 'prompt', 'message': 'RUN_MANAGED_SSH_STATUS'}) + '\n')
    process.stdin.flush()
    events = []
    while True:
        line = lines.get(timeout=180)
        assert line is not None, 'Pi exited before the check completed'
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        assert not (event.get('type') == 'extension_ui_request' and event.get('method') in ('select', 'confirm', 'input'))
        if event.get('type') == 'agent_settled':
            break
    results = [e for e in events if e.get('type') == 'tool_execution_end']
    assert len(results) == 2 and results[0]['toolName'] == 'bash_escalate' and results[1]['toolName'] == 'bash', results
    assert not results[0].get('isError') and 'key_loaded' in json.dumps(results[0]), results
    assert not results[1].get('isError') and 'Fixture Author <fixture@example.test>' in json.dumps(results[1]), results
    assert len(reviews) == 1 and len(contexts) == 3, (reviews, contexts)
    print('PASS actual Pi: managed SSH context and reviewed status with SSH_AUTH_SOCK empty', flush=True)
    process.terminate()
    process.wait(timeout=15)
    process = None
    subprocess.run(['node', '/tmp/check-ssh-pendant.cjs', '--ssh'], check=True, timeout=240)
    assert len(reviews) == 2 and len(contexts) == 6, (reviews, contexts)
finally:
    if process:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    models.write_text(saved)
    server.shutdown()
