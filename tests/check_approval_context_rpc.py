"""Synthetic expanded-skill approval through the shipped Pi RPC client."""
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
    p.stdin.write(json.dumps({'id':'expanded-skill','type':'prompt','message':'/skill:approval-context RUN_APPROVAL_CONTEXT'})+'\n');p.stdin.flush()
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
    assert len(results)==7, json.dumps(events)
    assert all(not results[i].get('isError') for i in (0,2,3,4)), json.dumps(results)
    assert all(results[i].get('isError') for i in (1,5,6)), json.dumps(results)
    assert 'Use sandboxed bash' in json.dumps(results[1])
    assert 'SYNTHETIC_PRIVATE_VALUE' not in json.dumps(events)
    print('PASS actual Pi: expanded skill, external read, reviewed file-tool restriction and reviewed temporary write, network review, escalation, model denial and secret denial; no dialogs',flush=True)
finally:
    p.terminate()
    try:p.wait(timeout=15)
    except subprocess.TimeoutExpired:p.kill();p.wait()
