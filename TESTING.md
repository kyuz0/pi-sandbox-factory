# Tests and runtime updates

Run from this repository root with the TUI requirements installed:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

These cover lifecycle/ownership, configuration, rollback, TUI navigation, advisor creation, extension installation and model initialization. They use fixtures, not account credentials or inference models.

## Pendant updates and questions

Check the official [Open VSX metadata](https://open-vsx.org/api/cdervis/vscode-pi/latest) and the release's linked changelog. Update `PENDANT_VERSION` in both `sandbox.py` and `containers/dev/Dockerfile`. Pendant embeds its own Pi version; verify it with the worker test, separately from the standalone CLI pin.

Build an isolated sandbox on an unused host port:

```sh
test_root=$(mktemp -d /tmp/sandbox-check.XXXXXX)
mkdir "$test_root/workspace"
python3 sandbox.py --state-dir "$test_root/state" create pendant-check \
  --workspace "$test_root/workspace" --profile base --engine podman \
  --local-model-ports 18081 --allow-domain local-model.internal:18081 --start
python3 tests/integration.py --state-dir "$test_root/state" \
  --name pendant-check --port 18081 --pendant-questions-only
podman exec -i local-ai-sandbox-pendant-check node --experimental-transform-types - \
  < tests/check_approval_config.mjs
python3 sandbox.py --state-dir "$test_root/state" delete pendant-check
```

The fixture server exercises the shipped Pendant worker's startup, shared configuration, extension loading, question choices, free text and cancellation. It asserts one question dialog and no reviewer call for each question. The container check also covers installed tools and isolation. This verifies worker behavior; VS Code's visual layout and keyboard shortcuts need a desktop smoke check.

For the full legacy security/scheduling integration scenarios, create a separate disposable sandbox with `--options-file` pointing to `{"approval":"assisted"}` and omit `--pendant-questions-only`. Those scenarios intentionally exercise human fallback. The default automatic mode's no-dialog behavior is tested in the security extension suite and `tests/test_approval_modes.py`.

## Extension and companion changes

- Source fixes and unit tests belong in the extension repository: [model manager](https://github.com/kyuz0/pi-local-model-manager), [advisor](https://github.com/kyuz0/pi-advisor) (`npm test`), or [security packages](https://github.com/kyuz0/pi-packages) (`npm run check && npm test`).
- Publish the runtime change, update `containers/dev/extensions.lock.json` or the security commit/archive checksum in `containers/dev/security/sources.json`, then rebuild a disposable sandbox. Documentation-only extension changes do not need a consumer pin update.
- Run `python3 tests/advisor_container.py --dev-image YOUR_BUILT_DEVELOPMENT_IMAGE` for companion changes. It checks the Pendant worker, CLI launchers, socket, credential-volume separation, Secret Service persistence and cleanup without real login.
- SSH unit tests cover destinations, host keys, ownership and key mounts. `tests/check_pendant_worker.cjs --ssh-live` additionally needs an explicitly assigned host, unlocked companion and authorized live model.

Use disposable state and workspaces for integration tests. Never restart a user's active sandbox for testing or copy their credentials. Existing installations receive new image pins through **Actions → Update sources and recreate…**, followed by reopening the editor; workspace and private home persist.
