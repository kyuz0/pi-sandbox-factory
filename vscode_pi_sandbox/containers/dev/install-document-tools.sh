#!/bin/sh
set -eu
# Optional pip arguments allow the same installation from an offline wheel bundle.
python3 -m pip install --no-cache-dir --target=/opt/document-tools/lib \
    -r /opt/document-tools/requirements.txt "$@"
# Keep distro Python intact; expose the /opt libraries to system Python and
# profile virtual environments created with --system-site-packages.
python3 - <<'PY'
from pathlib import Path
import sysconfig
packages = Path(sysconfig.get_path('purelib'))
packages.mkdir(parents=True, exist_ok=True)
(packages / 'sandbox-document-tools.pth').write_text('/opt/document-tools/lib\n')
for executable in Path('/opt/document-tools/lib/bin').glob('*'):
    link = Path('/usr/local/bin') / executable.name
    if executable.is_file() and not link.exists():
        link.symlink_to(executable)
PY
python3 -m pip check
