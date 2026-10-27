# Tests

Run from the repository root after installing the TUI requirements. The discovery tests also require Node.js.

```sh
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/discovery/*.test.mjs
```

The suites cover launcher ownership and lifecycle, configuration, network updates and rollback, TUI navigation, and model discovery. Model responses are fixtures.

For integration tests, create a disposable running Podman sandbox with host-local port 8000 enabled. Port 8000 must be free on the host:

```sh
python tests/integration.py --state-dir /path/to/test-state --name test-name
```

This starts a fixture server, checks tools and isolation, exercises Pi/Pendant, and restores the model configuration. Use only disposable workspaces and sandbox state. It does not run an inference model.
