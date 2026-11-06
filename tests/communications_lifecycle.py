"""Check Slack settings changes in a disposable sandbox; no account is used."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state-dir',required=True,type=Path)
parser.add_argument('--name',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
config=json.loads((args.state_dir/args.name/'config.json').read_text())
assert config['options']['communications']['slack'], 'Enable Slack in this disposable sandbox first'
engine=config['engine']; container='pi-sandbox-factory-'+args.name
cli=[sys.executable,'-m','pi_sandbox_factory','--state-dir',str(args.state_dir)]
def call(command, **kwargs): return subprocess.run(command,text=True,check=True,**kwargs)
def read(command): return subprocess.check_output(command,text=True)
def identity(): return read([engine,'inspect','--format','{{.Id}}',container]).strip()
original=identity()
call(cli+['communication-key',args.name,'--keys-stdin'],input=json.dumps({'botToken':'xoxb-lifecycle-fixture'}))
assert identity()==original, 'Token-only update recreated the container'
# Simulate a previous npm registration. Bootstrap must retain only its managed copy.
call([engine,'exec',container,'python3','-c',
      "import json;from pathlib import Path;p=Path('/home/node/.pi/agent/settings.json');s=json.loads(p.read_text());s.setdefault('packages',[]).append('npm:@dreki-gg/pi-slack@0.5.1');p.write_text(json.dumps(s))"])
with tempfile.TemporaryDirectory() as temp:
    settings=Path(temp)/'settings.json'
    def apply(value):
        settings.write_text(json.dumps({'options':value}))
        call(cli+['update',args.name,'--settings-file',str(settings)])
    try:
        disabled=json.loads(json.dumps(config['options']));disabled['communications']['slack']=False
        apply(disabled)
        current=json.loads(read([engine,'exec',container,'cat','/home/node/.pi/agent/settings.json']))
        assert not any('pi-slack' in str(p) for p in current.get('packages',[]))
        assert not any('/opt/pi-communications/' in str(p) for p in current.get('extensions',[]))
        call([engine,'exec','-i',container,'node','-','--communications-disabled'],input=(root/'tests/check_pendant_worker.cjs').read_text())
        assert json.loads(read(cli+['communication-key',args.name,'--status']))['botToken']
        assert 'slack.com' not in (args.state_dir/args.name/'squid.conf').read_text()
    finally:
        apply(config['options'])
assert json.loads(read(cli+['communication-key',args.name,'--status']))['botToken']
print('PASS Slack token updates preserve the container; disable/re-enable preserves credentials and removes duplicate registration')
