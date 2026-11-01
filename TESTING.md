# Tests

Run from the repository root after installing the TUI requirements.

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

The suites cover launcher ownership and lifecycle, configuration, network updates and rollback, TUI navigation, extension installation and model initialization. Model responses are fixtures.

SSH checks cover destination validation, trusted host keys, companion ownership, client mounts, GitHub presets and TUI settings. The optional `--ssh-live` mode in `tests/check_pendant_worker.cjs` uses a running model to request an approved read-only SSH command; it requires a configured destination and unlocked companion.

For integration tests, create a disposable running Podman sandbox with host-local port 8000 enabled. Port 8000 must be free on the host:

```sh
python tests/integration.py --state-dir /path/to/test-state --name test-name
```

This starts a fixture server, checks tools and isolation, exercises Pi/Pendant, and restores the model configuration. Use only disposable workspaces and sandbox state. It does not run an inference model.

Extension unit tests run in [pi-local-model-manager](https://github.com/kyuz0/pi-local-model-manager) and [pi-advisor](https://github.com/kyuz0/pi-advisor) with `npm test`.

Disposable Podman integration check (builds the advisor image; no real credentials or inference):

```sh
python3 tests/advisor_container.py --dev-image YOUR_BUILT_DEVELOPMENT_IMAGE
```

This checks the actual Pendant worker, both isolated CLI launchers, the shared socket, credential-volume separation, Secret Service persistence and cleanup. It needs no model server and does not use port 8000.
