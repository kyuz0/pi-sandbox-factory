"""Check host imports after startup, including preserved SELinux labels when enabled."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def check_workspace_imports(engine, dev, proxy, workspace):
    workspace = Path(workspace)
    getenforce = shutil.which('getenforce')
    selinux = subprocess.check_output([getenforce], text=True).strip() if getenforce else 'Unavailable'
    enabled = selinux in ('Enforcing', 'Permissive')
    # These directories share a filesystem, so rename preserves the original
    # inode/label just as dragging a downloaded document into the workspace does.
    with tempfile.TemporaryDirectory(prefix='.import-source-', dir=workspace.parent) as source_tmp, \
            tempfile.TemporaryDirectory(prefix='.import-check-', dir=workspace) as target_tmp:
        source, target = Path(source_tmp), Path(target_tmp)
        nested = source / 'nested'
        nested.mkdir()
        original = nested / 'document.txt'
        original.write_text('HOST_IMPORT_OK')
        if enabled:
            subprocess.run(['chcon', '-R', '-t', 'user_home_t', str(nested)], check=True)
            original_label = os.getxattr(original, 'security.selinux')
            assert b':user_home_t:' in original_label
        nested.rename(target / 'moved')
        moved = target / 'moved/document.txt'
        shutil.copy2(moved, target / 'copied.txt')
        (target / 'new.txt').write_text('HOST_IMPORT_OK')
        if enabled:
            for path in (moved, target / 'copied.txt'):
                assert os.getxattr(path, 'security.selinux') == original_label
            metadata = json.loads(subprocess.check_output([engine, 'inspect', dev], text=True))[0]
            assert not metadata.get('ProcessLabel'), 'Development container still has SELinux label separation'
            if proxy:
                metadata = json.loads(subprocess.check_output([engine, 'inspect', proxy], text=True))[0]
                assert metadata.get('ProcessLabel'), 'Proxy lost SELinux confinement'
        container_dir = '/workspace/' + target.name
        script = ('from pathlib import Path; p=Path(' + repr(container_dir) + '); '
                  'assert all((p / f).read_text() == "HOST_IMPORT_OK" '
                  'for f in ("moved/document.txt", "copied.txt", "new.txt"))')
        subprocess.run([engine, 'exec', dev, 'python3', '-c', script], check=True)
        command = 'python3 -c ' + "'" + script.replace("'", "'\\''") + "'"
        # Exercise the same nested runner used by Pi's Bash tool as well as the
        # outer container; no model/provider or real documents are involved.
        runner = '''
import assert from 'node:assert/strict';
import {createJiti} from 'jiti';
const {runSandboxedCommand} = await createJiti(import.meta.url, {tryNative: false})
  .import('/opt/pi-security/packages/pi-sandbox/src/runner.ts');
let output = '';
const result = await runSandboxedCommand({
  command: COMMAND, cwd: DIRECTORY, onData: d => { output += d.toString(); },
  review: async () => 'deny', reviewDomain: async () => 'deny',
});
assert.equal(result.exitCode, 0, output);
'''.replace('COMMAND', json.dumps(command)).replace('DIRECTORY', json.dumps(container_dir))
        subprocess.run([engine, 'exec', '-i', '-w', '/opt/pi-security', dev,
                        'node', '--input-type=module'], input=runner, text=True, check=True)
        if enabled:
            assert os.getxattr(moved, 'security.selinux') == original_label
            assert subprocess.check_output([getenforce], text=True).strip() == selinux
    print(f'PASS new, moved and copied host files readable after startup in container and nested Bash '
          f'(host SELinux: {selinux}; host labels preserved)', flush=True)
