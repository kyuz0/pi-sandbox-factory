"""Fetch and verify the pinned security packages."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

root = Path(__file__).resolve().parent
spec = json.loads((root / "sources.json").read_text())["pi-packages"]
with urllib.request.urlopen(spec["url"], timeout=120) as response:
    blob = response.read()
if hashlib.sha256(blob).hexdigest() != spec["sha256"]:
    raise RuntimeError("Pi fork archive checksum mismatch")
with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
    for entry in archive.getmembers():
        parts = PurePosixPath(entry.name).parts[1:]
        if not parts or ".." in parts:
            continue
        relative = PurePosixPath(*parts)
        # Personal profiles and development repository state are not image inputs.
        if not (parts[0] == "packages" or str(relative) in (
            "package.json", "package-lock.json", "LICENSE",
            "scripts/prepare-container.py", "scripts/container-sources.json",
        )):
            continue
        if entry.isdir():
            continue
        if not entry.isfile():
            raise RuntimeError("Unexpected non-regular source: " + str(relative))
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.extractfile(entry).read())
        target.chmod(entry.mode & 0o755)
(root / "source-commit").write_text(spec["commit"] + "\n")
print("Fetched Pi security packages " + spec["commit"])
