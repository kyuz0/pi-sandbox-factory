"""Tiny TLS/SSE inference fixture; no model, credentials, or external service needed."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import time


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer fixture-key':
            self.send_error(401)
            return
        model = {'id': 'fixture-model', 'max_tokens': 32000, 'supports_images': False}
        if self.path in ('/v1/models?model_type=ALL_TEXT', '/api/v1/models?model_type=ALL_TEXT'):
            response = {'data': [{'id': model['id']}]}
        elif self.path in ('/v1/models/details', '/api/v1/models/details'):
            response = [model]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
        expected = Path('/fixture/expected-profile.txt')
        messages = request.get('messages', [])
        content = '\n'.join(strings(messages))
        reviewing = any(
            m.get('role') in ('system', 'developer') and any(
                text.startswith(('Review one proposed coding-agent action.',
                                 'You are a fail-closed permission reviewer.'))
                for text in strings(m.get('content'))) for m in messages)
        if not reviewing and 'RUN_SECURITY_' in content:
            names = {t['function']['name'] for t in request.get('tools', [])}
            if ('subagent' in names) != json.loads(Path('/fixture/expected-subagents.json').read_text()):
                self.send_error(400, 'Subagent tool availability does not match the explicit launcher choice')
                return
        if not reviewing and expected.exists() and expected.read_text().strip() not in content:
            self.send_error(400, 'Profile instructions missing from model request')
            return
        if (self.path != '/v1/chat/completions' or request['model'] != 'fixture-model'
                or self.headers.get('Authorization') != 'Bearer fixture-key'):
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        delta = {'role': 'assistant', 'content': 'SANDBOX_INFERENCE_OK'}
        finish = 'stop'
        if reviewing and Path('/fixture/feature-mode.json').exists():
            assert json.loads(Path('/fixture/feature-mode.json').read_text())['approval'] == 'automatic', 'Unexpected model review in manual/off mode'
        if reviewing:
            with Path('/fixture/reviews.jsonl').open('a') as audit:
                audit.write(json.dumps({'question': 'RUN_QUESTION_' in content}) + '\n')
            # Ordinary Bash must succeed even when a reviewer would deny it.
            outcome = 'deny' if ('DENY_BY_FIXTURE' in content or 'ALLOW_EXECUTED' in content) else 'defer' if 'DEFER_BY_FIXTURE' in content else 'allow'
            delta['content'] = json.dumps({'outcome': outcome, 'risk_level': 'medium',
                                          'user_authorization': 'high', 'rationale': 'Synthetic integration review: ' + outcome})
        elif 'RUN_QUESTION_' in content:
            outputs = [m for m in messages if m.get('role') == 'tool']
            if outputs:
                delta['content'] = 'QUESTION_DONE'
            else:
                params = {'questions': [{'header': 'Output', 'question': 'Which output format?',
                    'options': [{'label': 'CSV', 'description': 'A spreadsheet table'},
                                {'label': 'JSON', 'description': 'Structured records'}]}]}
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'question-call',
                    'type': 'function', 'function': {'name': 'ask_user_question', 'arguments': json.dumps(params)}}]}
                finish = 'tool_calls'
        elif 'RUN_VIEWER_' in content:
            names = {t['function']['name'] for t in request.get('tools', [])}
            assert {'browser', 'browser_viewer', 'ask_user_question'} <= names
            assert 'PROJECT_VIEWER_GUIDANCE' in content, 'Project guidance missing'
            assert 'When user interaction is needed' in content, 'Viewer tool guidance missing from system prompt'
            outputs = [m for m in messages if m.get('role') == 'tool']
            marker = 'VIEWER_ONE' if 'RUN_VIEWER_ONE' in content else 'VIEWER_TWO'
            if len(outputs) == 0:
                name = 'browser'
                params = {'code': "await page.setContent('<title>" + marker + "</title><h1>" + marker + "</h1><input aria-label=Name><button>Continue</button>'); state.marker='" + marker + "'; return await page.title()"}
            elif len(outputs) == 1:
                name, params = 'browser_viewer', {}
            elif len(outputs) == 2:
                name = 'ask_user_question'
                params = {'questions': [{'header': 'Browser', 'question': 'Open the live browser: ' + str(outputs[-1]['content']),
                                        'options': [{'label':'Done','description':'Continue in the same browser'}, {'label':'Cancel','description':'Stop this interaction'}]}]}
            elif len(outputs) == 3:
                name = 'browser'
                params = {'code': 'return {marker:state.marker,title:await page.title()};'}
            else:
                name = None
                delta['content'] = 'VIEWER_DONE'
            if name:
                delta = {'role':'assistant','tool_calls':[{'index':0,'id':'viewer-' + str(len(outputs)),
                         'type':'function','function':{'name':name,'arguments':json.dumps(params)}}]}
                finish = 'tool_calls'
        elif 'RUN_BROWSER_' in content:
            names = {t['function']['name'] for t in request.get('tools', [])}
            assert 'browser' in names, 'Betterwright tool is not loaded'
            outputs = [m for m in messages if m.get('role') == 'tool']
            deny = 'RUN_BROWSER_DENY' in content
            code = ["throw Error('DENY_BY_FIXTURE_EXECUTED')"] if deny else [
                "await page.setContent('<title>Pi browser fixture</title><button>Press</button>'); await page.getByRole('button',{name:'Press',exact:true}).click(); state.marker='BROWSER_STATE_OK'; return await page.title()",
                "return {marker:state.marker, screenshot:await screenshot({kind:'debug',name:'rpc-browser-check'})}",
                "await page.goto('https://example.com'); return await page.title()",
            ]
            if len(outputs) < len(code):
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'browser-' + str(len(outputs)),
                         'type': 'function', 'function': {'name': 'browser', 'arguments': json.dumps({'code': code[len(outputs)]})}}]}
                finish = 'tool_calls'
            else:
                delta['content'] = 'BROWSER_DONE'
        elif 'RUN_FEATURE_' in content:
            outputs = [m for m in messages if m.get('role') == 'tool']
            if outputs:
                delta['content'] = 'FEATURE_DONE'
            else:
                boundary = 'RUN_FEATURE_BOUNDARY' in content
                command = ('test -r /home/node/.pi/agent/models.json && printf FEATURE_BOUNDARY_OK' if boundary
                           else "python3 -c 'from pathlib import Path; import os; print(\"FEATURE_BASH_OK\"); print(\"FEATURE_HOME_READABLE\" if os.access(Path.home()/\".pi\"/\"agent\"/\"models.json\", os.R_OK) else \"FEATURE_HOME_HIDDEN\")'")
                args = {'command': command}
                if boundary:
                    args['justification'] = 'Synthetic capability-mode boundary test.'
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'feature-call', 'type': 'function',
                         'function': {'name': 'bash_escalate' if boundary else 'bash', 'arguments': json.dumps(args)}}]}
                finish = 'tool_calls'
        elif 'RUN_WEBSEC_MCP_' in content:
            outputs = [m for m in messages if m.get('role') == 'tool']
            call = None
            if not outputs:
                call = ('tool_search', {'query': 'get_proxy_http_history_summary'})
            elif len(outputs) == 1:
                call = ('mcp__burp__get_proxy_http_history_summary', {
                    'marker': 'DENY_BY_FIXTURE' if 'RUN_WEBSEC_MCP_DENY' in content else 'ALLOW_BY_FIXTURE'})
            if call:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'websec-' + str(len(outputs)),
                         'type': 'function', 'function': {'name': call[0], 'arguments': json.dumps(call[1])}}]}
                finish = 'tool_calls'
            else:
                delta['content'] = 'WEBSEC_REVIEW_DONE'
        elif 'RUN_AUTOMATION_' in content:
            names = {t['function']['name'] for t in request.get('tools', [])}
            outputs = [m for m in messages if m.get('role') == 'tool']
            user_content = '\n'.join(strings([m.get('content') for m in messages if m.get('role') == 'user']))
            assistant_content = '\n'.join(strings([m.get('content') for m in messages if m.get('role') == 'assistant']))
            call = None
            if 'RUN_AUTOMATION_GOAL' in content:
                if not outputs:
                    call = ('create_goal', {'objective': 'RUN_AUTOMATION_GOAL: verify sandboxed Bash then complete this synthetic goal.', 'token_budget': 10000, 'auto_continue': True, 'skip_auditor': True, 'verification_contract': 'Sandboxed Bash must return AUTOMATION_GOAL_BASH_OK.'})
                elif 'AUTOMATION_GOAL_FIRST_TURN' not in assistant_content:
                    delta['content'] = 'AUTOMATION_GOAL_FIRST_TURN'
                elif len(outputs) == 1:
                    call = ('bash', {'command': 'printf AUTOMATION_GOAL_BASH_OK'})
                elif len(outputs) == 2:
                    call = ('update_goal', {'status': 'complete'})
                else:
                    delta['content'] = 'AUTOMATION_GOAL_DONE'
            elif 'RUN_AUTOMATION_REJECT' in content:
                if not outputs:
                    call = ('schedule_prompt', {'action': 'add', 'type': 'once', 'schedule': '+1s',
                                                'prompt': 'DENY_BY_FIXTURE', 'name': 'automation-rejected'})
                else:
                    delta['content'] = 'AUTOMATION_REJECT_DONE'
            elif 'AUTOMATION_TIMER_FIRE' in user_content:
                bash_outputs = [m for m in outputs if m.get('name') in ('bash', 'bash_escalate')]
                # Some provider clients omit the tool name; tool calls still have
                # stable IDs, so use IDs to identify the three scheduled actions.
                bash_outputs = [m for m in outputs if 'automation-bash-' in m.get('tool_call_id', '')] or bash_outputs
                commands = [
                    "python3 -c 'from pathlib import Path; import os; assert not os.access(Path.home()/\".pi\"/\"agent\"/\"models.json\", os.R_OK); print(\"AUTOMATION_SCHEDULE_BASH_OK\")'",
                    'printf DEFER_BY_FIXTURE',
                    'printf DENY_BY_FIXTURE > automation-denied.txt',
                ]
                if len(bash_outputs) < len(commands):
                    step = len(bash_outputs)
                    arguments = {'command': commands[step]}
                    if step:
                        arguments['justification'] = 'Synthetic scheduled escalation approval check.'
                    call = ('bash_escalate' if step else 'bash', arguments)
                else:
                    delta['content'] = 'AUTOMATION_SCHEDULE_DONE'
            elif not outputs:
                schedule_schema = next(t['function']['parameters'] for t in request['tools'] if t['function']['name'] == 'schedule_prompt')
                assert not {'model', 'extensions', 'skills', 'notify'} & schedule_schema['properties'].keys()
                assert ('create_goal' in names) == ('PENDANT_WORKER_FIXTURE' in user_content)
                assert ('subagent' in names) == json.loads(Path('/fixture/expected-subagents.json').read_text())
                call = ('schedule_prompt', {'action': 'add', 'type': 'once', 'schedule': '+2s',
                                            'prompt': 'AUTOMATION_TIMER_FIRE: verify the existing command sandbox and approvals.',
                                            'name': ('pendant-' if 'PENDANT_WORKER_FIXTURE' in user_content else '') +
                                                    'automation-' + ('busy' if 'RUN_AUTOMATION_BUSY' in content else 'idle')})
            else:
                if 'RUN_AUTOMATION_BUSY' in content:
                    time.sleep(3)  # Timer must fire while this parent turn is still streaming.
                delta['content'] = 'AUTOMATION_SCHEDULE_CREATED'
            if call:
                name, arguments = call
                call_id = ('automation-bash-' if name in ('bash', 'bash_escalate') else 'automation-call-') + str(len(outputs))
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': call_id,
                         'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                finish = 'tool_calls'
        elif 'CHECK_NESTED_CAPABILITIES' in content and 'RUN_SECURITY_' not in content:
            outputs = [m for m in messages if m.get('role') == 'tool']
            if not outputs:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'nested-child-call',
                         'type': 'function', 'function': {'name': 'subagent', 'arguments': json.dumps({
                             'agent': 'assistant', 'task': 'CHECK_CHILD_CAPABILITIES', 'async': False,
                             'options': {'acceptance': {'level': 'none', 'reason': 'Synthetic security protocol test.'}}})}}]}
                finish = 'tool_calls'
            else:
                text = '\n'.join(strings(outputs))
                delta['content'] = 'SUBAGENT_FIXTURE_OK' if 'SUBAGENT_FIXTURE_OK' in text else 'NESTED_CHILD_FAILED: ' + text
        elif 'CHECK_CHILD_CAPABILITIES' in content and 'RUN_SECURITY_' not in content:
            names = {t['function']['name'] for t in request.get('tools', [])}
            required = {'bash', 'bash_escalate', 'read', 'write', 'edit'}
            outputs = [m for m in messages if m.get('role') == 'tool']
            step = len(outputs)
            calls = [
                ('bash', {'command': "python3 -c 'from pathlib import Path; import os; assert not os.access(Path.home()/\".pi\"/\"agent\"/\"models.json\", os.R_OK); print(\"CHILD_BASH_OK\")'"}),
                ('bash_escalate', {'command': 'test -r /home/node/.pi/agent/models.json && printf CHILD_ESCALATE_OK',
                                  'justification': 'Verify reviewed access inside the same devcontainer as the parent.'}),
                ('bash_escalate', {'command': 'printf DENY_BY_FIXTURE > child-denied-fixture.txt', 'justification': 'Synthetic child escalation denial check.'}),
            ]
            if 'CHECK_FORWARDED_QUESTION' in content:
                # Background children forward permission-system dialogs. Use a
                # read outside the workspace; ordinary Bash no longer asks.
                calls[2:2] = [
                    ('read', {'path': '/tmp/DEFER_BY_FIXTURE.txt'}),
                    ('bash', {'command': 'printf DEFER_BY_FIXTURE > child-defer-fixture.txt'}),
                ]
            if not required <= names:
                delta['content'] = 'CHILD_MISSING_TOOLS: ' + ','.join(sorted(required - names))
            elif step < len(calls):
                name, arguments = calls[step]
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'child-call-' + str(step),
                         'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                finish = 'tool_calls'
            else:
                text = '\n'.join(strings(outputs))
                delta['content'] = ('SUBAGENT_FIXTURE_OK' if 'CHILD_BASH_OK' in text and
                                    'CHILD_ESCALATE_OK' in text and ('denied' in text.lower() or 'blocked' in text.lower())
                                    else 'CHILD_EXECUTION_FAILED: ' + text)
        elif 'RUN_SECURITY_' in content and not any(m.get('role') == 'tool' for m in messages):
            scenario = next(x for x in ('SUBAGENT_ASYNC_DEFER', 'SUBAGENT_ASYNC', 'SUBAGENT_NESTED',
                                       'SUBAGENT_EXTERNAL', 'SUBAGENT', 'ALLOW', 'DENY', 'DEFER', 'ESCALATE')
                            if 'RUN_SECURITY_' + x in content)
            command = {'ALLOW': 'printf ALLOW_EXECUTED',
                       'DENY': 'printf DENY_BY_FIXTURE > denied-fixture.txt',
                       'DEFER': 'printf DEFER_BY_FIXTURE',
                       'ESCALATE': 'printf ESCALATE_EXECUTED'}.get(scenario, '')
            arguments = {'command': command}
            if scenario in ('ESCALATE', 'DENY', 'DEFER'):
                arguments['justification'] = 'Synthetic check of exact reviewed outer-container execution.'
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'security-fixture-call',
                     'type': 'function', 'function': {'name': 'bash_escalate' if scenario in ('ESCALATE', 'DENY', 'DEFER') else 'bash',
                                                    'arguments': json.dumps(arguments)}}]}
            if scenario.startswith('SUBAGENT'):
                delta['tool_calls'][0]['function'] = {'name': 'subagent', 'arguments': json.dumps({
                    'agent': 'assistant',
                    'task': ('CHECK_NESTED_CAPABILITIES' if scenario == 'SUBAGENT_NESTED' else
                             'CHECK_CHILD_CAPABILITIES CHECK_FORWARDED_QUESTION' if scenario == 'SUBAGENT_ASYNC_DEFER' else
                             'CHECK_CHILD_CAPABILITIES'),
                    'async': scenario.startswith('SUBAGENT_ASYNC'), 'model': 'fixture/fixture-model',
                    'options': {'acceptance': {'level': 'none', 'reason': 'Synthetic security protocol test.'}}})}
            if scenario == 'SUBAGENT_EXTERNAL':
                delta['tool_calls'][0]['function'] = {'name': 'subagent', 'arguments': json.dumps({
                    'agent': 'external-fixture', 'task': 'Synthetic external-runner rejection test.', 'async': True})}
            finish = 'tool_calls'
        for delta, finish in ((delta, None), ({}, finish)):
            event = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                     'model': 'fixture-model',
                     'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.flush()
        self.wfile.write(b'data: [DONE]\n\n')


class Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


server = Server(('::', 18443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/cert.pem', '/fixture/key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
