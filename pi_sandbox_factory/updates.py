"""Background GitHub release checks for the pipx installation."""
import json
from importlib import metadata
from pathlib import Path
import sys
import urllib.request

from packaging.version import InvalidVersion, Version

PACKAGE = 'pi-sandbox-factory'
TAGS_URL = 'https://api.github.com/repos/kyuz0/pi-sandbox-factory/tags?per_page=20'
UPGRADE_COMMAND = ('pipx', 'upgrade', PACKAGE)
RELAUNCH = 'relaunch-after-update'


def installed_version():
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return '0.0.0+source'


def pipx_install():
    return (Path(sys.prefix) / 'pipx_metadata.json').is_file()


def available_update(current=None):
    try:
        current = Version(current or installed_version())
        request = urllib.request.Request(TAGS_URL, headers={'User-Agent': PACKAGE})
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(262144))
        if not isinstance(payload, list):
            return None
        versions = []
        for tag in payload:
            if not isinstance(tag, dict):
                continue
            try:
                version = Version(str(tag.get('name', '')).removeprefix('v'))
            except InvalidVersion:
                continue
            if not version.is_prerelease and not version.is_devrelease:
                versions.append(version)
        latest = max(versions, default=current)
        return str(latest) if latest > current else None
    except (OSError, ValueError):
        return None
