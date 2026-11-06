"""User-installed, immutable profile and provider packages. No host plugin execution."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from urllib.parse import urlsplit

NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
KINDS = {"profile": "profile.json", "provider": "provider.json"}


def root():
    return Path(
        os.environ.get(
            "SANDBOX_REGISTRY_DIR",
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "vscode-pi-sandbox/packages",
        )
    )


def source_url(value):
    if isinstance(value, str) and Path(value).expanduser().is_dir():
        return str(Path(value).expanduser().resolve())
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Enter a Git HTTPS/SSH URL or an existing local folder")
    parsed = urlsplit(value)
    if (
        parsed.scheme in ("https", "ssh")
        and parsed.hostname
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        if parsed.scheme == "https" and parsed.username:
            raise ValueError("Use host Git authentication, not credentials in a URL")
        return value
    if re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+", value):
        return value
    raise ValueError("Use Git HTTPS/SSH or a local folder; custom Git transports are not supported")


def safe_tree(path):
    for f in path.rglob("*"):
        if ".git" in f.relative_to(path).parts:
            continue
        if f.is_symlink() or not (f.is_file() or f.is_dir()):
            raise ValueError("Package files must be regular files: " + str(f))


def manifest(kind, path):
    if kind not in KINDS:
        raise ValueError("Choose profile or provider")
    data = json.loads((Path(path) / KINDS[kind]).read_text())
    if not NAME.fullmatch(data.get("name", "")) or data.get("version", 1) != 1:
        raise ValueError("Package needs a valid name and interface version 1")
    required = ("Dockerfile", "profile.md") if kind == "profile" else (data.get("entry", ""),)
    for filename in required:
        file = Path(filename)
        if (
            not filename
            or file.is_absolute()
            or ".." in file.parts
            or not (Path(path) / file).is_file()
        ):
            raise ValueError("Missing or unsafe package entry: " + filename)
    if kind == "provider":
        settings = data.get("settings", {})
        if not isinstance(settings, dict) or any(
            not isinstance(spec, dict) for spec in settings.values()
        ):
            raise ValueError("Provider settings must be objects")
        if sum(spec.get("type") == "secret" for spec in settings.values()) > 1:
            raise ValueError("Declare one credential field per provider")
        from .sandbox import parse_rules

        network = data.get("network", [])
        if not isinstance(network, list) or any(not isinstance(rule, str) for rule in network):
            raise ValueError("Provider network must be a list of host:port destinations")
        parse_rules("\n".join(network))
        for field, spec in data.get("settings", {}).items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", field) or spec.get("type") not in (
                "text",
                "secret",
            ):
                raise ValueError("Provider settings must declare text or secret fields")
        for key in ("extensions", "skills"):
            if not isinstance(data.get(key, []), list) or any(
                not isinstance(entry, str) or not entry for entry in data.get(key, [])
            ):
                raise ValueError("Provider resources must be lists of relative paths")
            for entry in data.get(key, []):
                f = Path(entry)
                if (
                    f.is_absolute()
                    and Path(path).resolve()
                    != (Path(__file__).parent / "providers/local").resolve()
                ) or ".." in f.parts:
                    raise ValueError("Provider resources must be relative package paths")
                if (
                    not f.is_absolute()
                    and not data.get("git_source")
                    and not (Path(path) / f).exists()
                ):
                    raise ValueError("Provider resource does not exist: " + entry)
    return data


def git(*args, capture=False):
    return subprocess.run(
        ["git", *map(str, args)],
        check=True,
        text=True,
        env=dict(
            os.environ,
            GIT_TERMINAL_PROMPT="0",
            GIT_SSH_COMMAND=os.environ.get(
                "GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=20"
            ),
        ),
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def package_directory(root, subdir):
    relative = Path(subdir or ".")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Package subdirectory must stay inside the source repository")
    selected = root / relative
    if not selected.is_dir():
        raise ValueError("Package subdirectory does not exist: " + str(relative))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Package subdirectory must not follow symlinks")
    return selected


def export(source, dest, ref=None, *, subdir="."):
    source = source_url(source)
    local = Path(source)
    if local.is_dir() and not (local / ".git").exists():
        if ref:
            raise ValueError("A revision requires a Git repository")
        selected = package_directory(local, subdir)
        safe_tree(selected)
        shutil.copytree(
            selected, dest, ignore=shutil.ignore_patterns("__pycache__", ".env", ".env.*", ".venv")
        )
        return None
    if ref and (ref.startswith("-") or any(c.isspace() for c in ref)):
        raise ValueError("Invalid Git revision")
    with tempfile.TemporaryDirectory(prefix="sandbox-git-") as temp:
        checkout = Path(temp) / "checkout"
        git("clone", "--quiet", "--no-checkout", "--", source, checkout)
        # A non-default branch exists only under refs/remotes after cloning.
        revision_ref = ref or "HEAD"
        if ref and not ref.startswith("refs/"):
            remote = subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    "refs/remotes/origin/" + ref,
                ],
                check=False,
            )
            if remote.returncode == 0:
                revision_ref = "refs/remotes/origin/" + ref
        revision = git(
            "-C", checkout, "rev-parse", "--verify", revision_ref + "^{commit}", capture=True
        ).stdout.strip()
        git("-C", checkout, "checkout", "--quiet", "--detach", revision)
        git("-C", checkout, "submodule", "update", "--init", "--recursive")
        selected = package_directory(checkout, subdir)
        safe_tree(selected)
        shutil.copytree(selected, dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return revision


@contextmanager
def locked():
    base = root()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (base / "registry.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield base


def installed(kind):
    path = root() / "registry.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return data.get(kind, {})


def write_registry(base, data):
    temp = base / "registry.tmp"
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(base / "registry.json")


def add(kind, name, source, ref=None, *, subdir=".", replace=False):
    from .sandbox import tree_digest

    if kind not in KINDS or not NAME.fullmatch(name) or name in ("base", "local"):
        raise ValueError("Choose a valid package name; base and local are built in")
    source = source_url(source)
    relative = Path(subdir or ".")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Package subdirectory must stay inside the source repository")
    subdir = str(relative)
    with locked() as base:
        file = base / "registry.json"
        data = json.loads(file.read_text()) if file.exists() else {}
        if name in data.get(kind, {}) and not replace:
            raise ValueError("Package already registered; use update")
        with tempfile.TemporaryDirectory(prefix=".install-", dir=base) as temp:
            path = Path(temp) / "package"
            revision = export(source, path, ref, subdir=subdir)
            info = manifest(kind, path)
            dependencies = {}
            if info.get("git_source"):
                if (path / "source").exists():
                    raise ValueError("source/ is reserved for the package dependency")
                dependencies[info["git_source"]] = export(
                    info["git_source"], path / "source", info.get("git_ref")
                )
                info.pop("git_source")
                info.pop("git_ref", None)
                (path / KINDS[kind]).write_text(json.dumps(info, indent=2) + "\n")
            manifest(kind, path)
            # Registration aliases are independent from the package's own identity.
            digest = tree_digest(path)
            target = base / "sources" / digest
            target.parent.mkdir(exist_ok=True, mode=0o700)
            if not target.exists():
                shutil.move(path, target)
            record = {
                "name": name,
                "package_name": info["name"],
                "description": info.get("description", ""),
                "source": source,
                "subdir": subdir,
                "ref": ref,
                "commit": revision,
                "dependencies": dependencies,
                "digest": digest,
                "path": str(target),
            }
            data.setdefault(kind, {})[name] = record
            write_registry(base, data)
            return record


def update(kind, name):
    row = installed(kind).get(name)
    if not row:
        raise ValueError("Package is not registered: " + name)
    return add(
        kind, name, row["source"], row.get("ref"), subdir=row.get("subdir", "."), replace=True
    )


def remove(kind, name):
    with locked() as base:
        file = base / "registry.json"
        data = json.loads(file.read_text()) if file.exists() else {}
        if name not in data.get(kind, {}):
            raise ValueError("Package is not registered: " + name)
        del data[kind][name]
        write_registry(base, data)
        # Snapshots may still be used by saved sandboxes; removing registration is non-destructive.


def resolve(kind, name):
    from .sandbox import ROOT, tree_digest

    builtin = ROOT / ("profiles" if kind == "profile" else "providers") / name
    row = installed(kind).get(name)
    path = builtin if builtin.is_dir() else Path(row["path"]) if row else Path(name).expanduser()
    if not path.is_dir():
        raise ValueError("Unknown " + kind + ": " + name + ". Install it first or supply a folder.")
    if row and tree_digest(path) != row["digest"]:
        raise ValueError("Installed package was modified; reinstall it")
    manifest(kind, path)
    return path


def choices(kind):
    from .sandbox import ROOT

    folder = ROOT / ("profiles" if kind == "profile" else "providers")
    values = {
        p.name: manifest(kind, p).get("description", p.name) for p in folder.iterdir() if p.is_dir()
    }
    values.update({name: r["description"] for name, r in installed(kind).items()})
    return values
