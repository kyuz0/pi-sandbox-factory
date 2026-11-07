"""Install selected model packages and run their adapters inside the development container."""

import json
from pathlib import Path
import shutil
import tempfile
from . import registry


def selections(config):
    return config.get("model_providers", [])


def prepare(values, state, *, saved=(), refresh=False):
    from . import sandbox

    if not isinstance(values, dict):
        raise ValueError("Providers must map names to settings")
    result = []
    for name, settings in values.items():
        previous = next((row for row in saved if row["name"] == name), None)
        use_saved = previous and (
            not refresh or (name != "local" and name not in registry.installed("provider"))
        )
        source = Path(previous["path"]) if use_saved else registry.resolve("provider", name)
        if use_saved and sandbox.tree_digest(source) != previous["digest"]:
            raise ValueError("Provider snapshot changed: " + name)
        info = previous["manifest"] if use_saved else registry.manifest("provider", source)
        if not isinstance(settings, dict) or set(settings) - set(info.get("settings", {})):
            raise ValueError("Unknown settings for provider " + name)
        for key, value in settings.items():
            if not isinstance(value, str) or info["settings"][key]["type"] == "secret":
                raise ValueError(
                    "Secrets must be entered through configure, not saved in sandbox settings"
                )
        snapshot = sandbox.snapshot_profile(
            {"name": name, "path": str(source), "digest": sandbox.tree_digest(source)}, state
        )
        result.append(dict(snapshot, settings=settings, manifest=info))
    return result


def required_rules(providers):
    from .sandbox_options import endpoint_rule

    rules = []
    for row in providers:
        info = row["manifest"]
        rules.extend(info.get("network", []))
        for key, spec in info.get("settings", {}).items():
            if spec.get("network"):
                value = row["settings"].get(key, spec.get("default", ""))
                if value:
                    rules.append(endpoint_rule(value))
    return rules


def validate_network(config, rules):
    from .sandbox import parse_rules

    if config.get("network") == "unrestricted":
        return
    missing = set(parse_rules("\n".join(required_rules(selections(config))))) - set(rules)
    if missing:
        raise ValueError(
            "Allow provider destinations first: "
            + ", ".join(f"{h}:{p}" for h, p in sorted(missing))
        )


def digest(config):
    import hashlib

    return hashlib.sha256(
        json.dumps(
            [(p["name"], p["digest"], p["settings"]) for p in selections(config)], sort_keys=True
        ).encode()
    ).hexdigest()[:12]


def build(config, base, target):
    from . import sandbox

    with tempfile.TemporaryDirectory(prefix="pi-model-providers-") as temp:
        path = Path(temp)
        descriptors = []
        resources = {"extensions": [], "skills": []}
        for row in selections(config):
            if sandbox.tree_digest(Path(row["path"])) != row["digest"]:
                raise ValueError("Provider snapshot changed: " + row["name"])
            folder = path / "providers" / row["name"]
            shutil.copytree(row["path"], folder)
            info = row["manifest"]
            inside = "/opt/sandbox/providers/" + row["name"]
            descriptors.append(
                dict(id=row["name"], directory=inside, settings=row["settings"], manifest=info)
            )
            for key in resources:
                for entry in info.get(key, []):
                    resource = entry if entry.startswith("/") else inside + "/" + entry
                    if key == "extensions":
                        loader = folder / f"loader-{len(resources[key])}.mjs"
                        loader.write_text(
                            "import install from "
                            + json.dumps(resource)
                            + ";\nimport {guard} from '/opt/sandbox/provider-lock.mjs';\nexport default pi => install(guard(pi));\n"
                        )
                        resource = inside + "/" + loader.name
                    resources[key].append(resource)
        (path / "providers").mkdir(exist_ok=True)
        (path / "providers.json").write_text(json.dumps(descriptors))
        (path / "provider-resources.json").write_text(json.dumps(resources))
        for file in ("provider-runner.mjs", "provider-lock.mjs"):
            shutil.copy(sandbox.ROOT / "providers" / file, path / file)
        (path / "Dockerfile").write_text(
            "ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nUSER root\nCOPY providers/ /opt/sandbox/providers/\nCOPY providers.json provider-resources.json provider-runner.mjs provider-lock.mjs /opt/sandbox/\nUSER node\n"
        )
        sandbox.run(
            [config["engine"], "build", "-t", target, "--build-arg", f"BASE_IMAGE={base}", path]
        )


def configure(config, action="refresh", provider=None, secret=None):
    from . import sandbox

    rows = selections(config)
    if provider:
        rows = [r for r in rows if r["name"] == provider]
    if not rows:
        raise ValueError("No matching provider is enabled")
    for row in rows:
        if row["name"] == "local" and not config.get("local_model_ports"):
            print("Local models: select host ports in Configuration first.")
            continue
        request = {"id": row["name"], "action": action}
        route = row["manifest"].get("inference")
        if route:
            if secret is not None:
                from . import inference
                inference.credentials(config, Path(config['state_path']), {
                    'id':row['name'], 'origin':route['origin'], 'auth':route['auth']['type'],
                    'credentials':{'key':secret}})
        elif secret is not None:
            request["secret"] = secret
        result = sandbox.run(
            [
                config["engine"],
                "exec",
                "-i",
                sandbox.names(config)[0],
                "node",
                "/opt/sandbox/provider-runner.mjs",
            ],
            input=json.dumps(request),
            capture=True,
            check=False,
            stderr=__import__("subprocess").PIPE,
        )
        if result.returncode:
            raise ValueError(
                "Provider operation failed: "
                + row["name"]
                + "; check the provider configuration"
            )
        response = json.loads(result.stdout)
        message = (
            row["name"]
            + ": "
            + response.get("state", "unknown")
            + " — "
            + response.get("message", "")
        )
        if response.get("state") == "error":
            raise ValueError(message)
        print(message)
