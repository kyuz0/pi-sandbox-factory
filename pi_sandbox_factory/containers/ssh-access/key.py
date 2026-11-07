"""Manage the companion's single key without exporting private material."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def generate(directory=Path('/private')):
    key = directory / 'id_key'
    if key.exists() or key.is_symlink():
        raise ValueError('A key already exists. Use Show public key, or create another sandbox for a separate key.')
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='.key-', dir=directory) as temporary:
        new = Path(temporary) / 'id_key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C',
                        'pi-sandbox-factory', '-f', str(new)], check=True, capture_output=True)
        # Refuse replacement even if another manager generated/imported a key meanwhile.
        try:
            os.link(new, key)
        except FileExistsError:
            raise ValueError('A key already exists; it was not replaced.') from None


def public_key():
    result = subprocess.run(['ssh-add', '-L'], capture_output=True, text=True)
    rows = result.stdout.strip().splitlines()
    if result.returncode or len(rows) != 1:
        raise ValueError('Unlock the existing key first, then choose Show public key.')
    return rows[0]


def main():
    try:
        if sys.argv[1:] == ['generate']:
            generate()
            subprocess.run(['python3', '/opt/ssh-access/unlock.py'], check=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.argv[1:] != ['show']:
            raise ValueError('Choose generate or show')
        print(public_key())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, subprocess.SubprocessError):
        print('Could not prepare the key. Use Unlock existing key and retry.', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
