#!/usr/bin/env python3
"""Check provider discovery against a local HTTP fixture in a disposable sandbox."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--name", required=True)
parser.add_argument("--port", type=int, default=18082)
parser.add_argument("--company-port", type=int, default=18084)
args = parser.parse_args()
container = "pi-sandbox-factory-" + args.name


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            value = {
                "data": [
                    {
                        "id": "fixture-model",
                        "context_length": 131072,
                        "architecture": {"input_modalities": ["text"]},
                    }
                ]
            }
        elif self.path == "/props":
            value = {
                "default_generation_settings": {"n_ctx": 131072},
                "modalities": {"vision": False},
            }
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())


server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
company_server = ThreadingHTTPServer(("127.0.0.1", args.company_port), Handler)
company_thread = threading.Thread(target=company_server.serve_forever, daemon=True)
company_thread.start()


def execute(*command, input=None):
    return subprocess.run(
        ["podman", "exec", "-i", container, *command],
        input=input,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def run(provider, action, **extra):
    return json.loads(
        execute(
            "node",
            "/opt/sandbox/provider-runner.mjs",
            input=json.dumps({"id": provider, "action": action, **extra}),
        )
    )


def models():
    return execute("cat", "/home/node/.pi/agent/models.json")


try:
    execute(
        "python3",
        "-c",
        'from pathlib import Path;Path(\'/home/node/.pi/agent/models.json\').write_text(\'{"providers":{"manual":{"models":[]}}}\')',
    )
    execute("rm", "-f", "/home/node/.pi/agent/models.json.local-lab-state.json")
    before = models()
    assert run("company", "refresh")["state"] == "needs-auth"
    assert run("company", "preview", secret="fixture-key")["state"] == "ready"
    assert models() == before, "Preview changed the catalogue"
    assert run("company", "refresh", secret="fixture-key")["state"] == "ready"
    result = run("local", "refresh")
    assert result["state"] == "ready", result
    config = json.loads(models())
    assert "manual" in config["providers"] and "company" in config["providers"]
    assert len(config["providers"]) == 3, config["providers"].keys()
    assert config["providers"]["company"]["models"][0]["id"] == "fixture-model"
    settings = json.loads(execute("cat", "/home/node/.pi/agent/settings.json"))
    assert "/opt/reporting" in settings["skills"]
    assert any("/providers/local/loader-" in path for path in settings["extensions"])
    print(
        "PASS real container: authentication, preview, local + company refresh, preserved catalogue and profile skill"
    )
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    company_server.shutdown()
    company_server.server_close()
    company_thread.join()
