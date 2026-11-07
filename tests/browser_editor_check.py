"""Synthetic file-boundary probes for a disposable browser-editor sandbox."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import zipfile


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    for folder in ('workspace', 'reference', 'host-private'):
        (root / folder).mkdir()
    for name in ('.env', 'id_ed25519'):
        (root / 'host-private' / name).write_text('SYNTHETIC_HOST_SECRET\n')
    (root / 'reference/reference.txt').write_text('Mounted reference file.\n')
    (root / 'workspace/browser-editor-probe.json').write_text(json.dumps({
        'hostFiles': [str(root / 'host-private' / name) for name in ('.env', 'id_ed25519')],
        'hostMarker': str(root / 'host-private/terminal-write'),
    }))
    (root / 'folders.json').write_text(json.dumps([{'source': str(root / 'reference'), 'name': 'reference', 'read_only': True}]))


def install(container):
    from pi_sandbox_factory.browser_editor import INSTALL
    for name in ('browser_editor_probe', 'browser_editor_web_probe'):
        folder = Path(__file__).parent / name
        meta = json.loads((folder / 'package.json').read_text())
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('[Content_Types].xml', '''<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="json" ContentType="application/json"/>
<Default Extension="cjs" ContentType="application/javascript"/>
<Default Extension="vsixmanifest" ContentType="text/xml"/></Types>''')
            archive.writestr('extension.vsixmanifest', f'''<?xml version="1.0"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
<Metadata><Identity Language="en-US" Id="{meta['name']}" Version="{meta['version']}" Publisher="sandbox-tests"/>
<DisplayName>Browser Editor Probe</DisplayName><Description xml:space="preserve">Synthetic isolation checks</Description></Metadata>
<Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation><Dependencies/>
<Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets></PackageManifest>''')
            for file in folder.iterdir():
                archive.write(file, 'extension/' + file.name)
        subprocess.run(['podman', 'exec', '-i', '--user', 'node', container, 'python3', '-c',
                        'import sys;open("/tmp/browser-probe.vsix","wb").write(sys.stdin.buffer.read())'],
                       input=data.getvalue(), check=True)
        subprocess.run(['podman', 'exec', '--user', 'node', container, INSTALL + '/bin/code-server',
                        '--config', '/home/node/.local/share/pi-browser-editor/config.yaml',
                        '--extensions-dir', '/home/node/.local/share/pi-browser-editor/extensions',
                        '--install-extension', '/tmp/browser-probe.vsix', '--force'], check=True)
    print('Reload the browser editor, trust the disposable workspace, then run verify.')


def verify(root):
    remote = json.loads((root / 'workspace/browser-editor-probe-results.json').read_text())
    web = json.loads((root / 'workspace/browser-editor-web-probe-results.json').read_text())
    assert web['uiKind'] == 2 and not web['hasNodeProcess']
    for report in (remote, web):
        probes = {key: value for key, value in report.items() if '/host-private/' in key}
        assert probes, 'Expected host-file probes'
        assert all(not value['ok'] for value in probes.values()), probes
    assert remote['workspace-write']['ok'] and remote['readonly-read']['ok']
    assert not remote['readonly-write']['ok']
    assert not (root / 'reference/must-not-exist').exists()
    assert not (root / 'host-private/terminal-write').exists()
    assert not remote['localTerminalCommandPresent']
    print('PASS Node and browser-worker host-file probes, workspace access and read-only mount')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'install', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--container')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.action == 'prepare':
        prepare(root)
    elif args.action == 'install':
        if not args.container:
            parser.error('install requires --container (disposable container name)')
        install(args.container)
    else:
        verify(root)
