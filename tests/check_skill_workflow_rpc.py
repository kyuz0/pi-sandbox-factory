"""Installed skill and shell workflow through the shipped Pi RPC client."""
import json
import queue
import subprocess
import threading
import time

p = subprocess.Popen(['pi','--mode','rpc','--provider','fixture','--model','fixture-model'],
                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
lines = queue.Queue()
errors = []
def read_lines():
    for line in p.stdout: lines.put(line)
    lines.put(None)
threading.Thread(target=read_lines,daemon=True).start()
threading.Thread(target=lambda: errors.extend(p.stderr.readlines()),daemon=True).start()
try:
    p.stdin.write(json.dumps({'id':'expanded-skill','type':'prompt','message':'/skill:spikee-pentesting RUN_SKILL_WORKFLOW'})+'\n');p.stdin.flush()
    events=[]
    deadline=time.monotonic()+300
    while True:
        line=lines.get(timeout=max(1,deadline-time.monotonic()))
        assert line is not None, ''.join(errors)
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        events.append(event)
        assert not (event.get('type')=='extension_ui_request' and event.get('method') in ('select','confirm')), 'Unexpected permission dialog'
        if event.get('type')=='agent_settled': break
    results=[e for e in events if e.get('type')=='tool_execution_end']
    cases=json.load(open('/tmp/skill-workflow-cases.json'))
    assert len(results)==len(cases), (len(results),len(cases),json.dumps(events))
    for case,result in zip(cases,results):
        assert bool(result.get('isError'))==case['error'], (case['name'],result)
        if case['contains']: assert case['contains'] in json.dumps(result), (case['name'],result)
        print('PASS Pi:',case['name'],flush=True)
    assert 'SYNTHETIC_PRIVATE_VALUE' not in json.dumps(events)
    assert 'PRIVATE_HOME' not in json.dumps(events)
    print('PASS actual Pi: all workflow cases; no permission dialogs',flush=True)

finally:
    p.terminate()
    try:p.wait(timeout=15)
    except subprocess.TimeoutExpired:p.kill();p.wait()
