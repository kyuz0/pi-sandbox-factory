# Development and tests

From the checkout, install the package into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_provider_runtime.mjs
```

The Python suite covers lifecycle, ownership, rollback, package revisions,
subfolder exports, provider selection and terminal interactions, including 80×24 layouts. Node tests
cover the adapter contract, preview, credential handling and refresh locking.
These tests use fixtures and no account credentials.

## Package installation

Build a wheel, install it in a separate environment, then run `pi-sandbox-factory --help`,
`profile list` and `provider list` from outside the checkout. Create a sandbox from
that installation to check that container files, profiles and provider modules are
included. Parse shipped Python files with Python 3.10 grammar when changing syntax.

```sh
.venv/bin/pip wheel --no-deps . -w dist
python3 -m venv /tmp/pi-sandbox-package-check
/tmp/pi-sandbox-package-check/bin/pip install dist/pi_sandbox_factory-*.whl
(cd /tmp && /tmp/pi-sandbox-package-check/bin/pi-sandbox-factory profile list)
```

## Container and Pendant integration

Use a disposable workspace and an unused port. This fixture serves synthetic
replies; it does not evaluate a real inference model.

```sh
test_root=$(mktemp -d /tmp/pi-sandbox-check.XXXXXX)
mkdir "$test_root/workspace"
.venv/bin/pi-sandbox-factory --state-dir "$test_root/state" create pendant-check \
  --workspace "$test_root/workspace" --local-model-ports 18081 \
  --allow-domain local-model.internal:18081 --start
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name pendant-check --port 18081 --pendant-questions-only
.venv/bin/pi-sandbox-factory --state-dir "$test_root/state" delete pendant-check
```

This checks container boundaries, installed document tools, actual Pendant worker
startup, shared configuration, shell tools, and question choices, free text and
cancellation. Questions must not invoke the reviewer. A desktop smoke check is
still needed for VS Code keyboard behavior and visual layout.

For the wider security and scheduling scenarios, create a separate sandbox with
`--options-file` containing `{"approval":"assisted"}` and omit
`--pendant-questions-only`. Those scenarios intentionally exercise human fallback.
The automatic mode is covered by `tests/test_approval_modes.py` and the security
extension's own suite.

For provider changes, install `examples/profile` as `reporting` and
`examples/provider` as `company`. Create a disposable reporting sandbox with local
discovery on 18082, company endpoint `http://local-model.internal:18084/v1`, model
`fixture-model`, and both destinations allowed. Run:

```sh
.venv/bin/python tests/provider_container.py --name YOUR_TEST_SANDBOX
```

This replaces the disposable catalogue with fixtures. It checks authentication,
preview without writes, two provider catalogues, and the registered profile skill.

## Runtime updates

Pi and Pendant have independent version pins in `pi_sandbox_factory/sandbox.py` and
`pi_sandbox_factory/containers/dev/Dockerfile`. Check the release's official metadata
before updating; then rebuild and run the worker suite. Extension fixes and unit
tests belong in their own repositories; update the lock file here afterward.

Advisor or SSH changes need their unit suites and companion tests.
Run
`.venv/bin/python tests/advisor_container.py --dev-image IMAGE` after installing the
package. It checks isolated launchers and credential volumes without real login.
Actual account login and authorized SSH access are separate checks.

Use disposable state throughout. Never restart a user's sandbox or copy credentials
for testing. Record commands and results; distinguish fixtures from live services.

## Browser viewer

Create the disposable sandbox above with `--browser`. Put this synthetic project
override in its workspace before testing:

```sh
mkdir -p "$test_root/workspace/.pi"
printf '%s\n' 'PROJECT_VIEWER_GUIDANCE' > "$test_root/workspace/.pi/APPEND_SYSTEM.md"
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name pendant-check --port 18081 --browser-viewer
.venv/bin/python tests/browser_lifecycle.py --state-dir "$test_root/state" \
  --name pendant-check
```

The first command checks the installed Pi CLI and Pendant worker, tool guidance
with the project override, question handoff, retained state, two simultaneous
browser sessions and their authenticated tab lists. Replies come from a synthetic
model. The second stops and restarts this disposable sandbox: it checks repeated
opens, rejected URLs and origins, shutdown with an active WebSocket, viewer repair,
key rotation and stale descriptors after a container restart.

For the rendered check, ask the agent to open a synthetic form and show its browser.
Open the returned link, select the tab, type and click in the screencast, then tell
the agent to continue. Confirm the browser tool reads the change. Reopen the sandbox
from the launcher after stopping only its viewer; the new link must show the same
page state. Verify that ordinary application port forwarding still works in VS Code.
Delete the disposable sandbox when finished.

## Launcher updates

Unit tests mock GitHub and pipx. They cover stable-tag selection, offline startup,
confirmation, upgrade failure, relaunch and the update notice at 80×24 and 120×40.
Use an isolated `PIPX_HOME` and `PIPX_BIN_DIR` to check installation from GitHub and
`pipx upgrade pi-sandbox-factory` without changing your normal installation.
The GitHub workflow runs Python and provider tests, installs the built wheel,
then versions and tags successful pushes to `main` only when package code,
bundled assets or packaging configuration changes. Documentation, tests and
workflow changes alone do not create a release. Full container checks remain in
the disposable integration recipe above.

## Web access

`test_web_access.py` covers service selection, category expansion, automatic
refresh, offline fallback and gateway rule ordering. TUI tests cover creation,
editing, keys and category selection. The normal suite makes no search requests.

For a live check, create the disposable sandbox described above with an options
file containing `{"web_access":{"enabled":true},"website_groups":["dev-python"]}`.
Run `tests/integration.py` with `--web-access` instead of
`--pendant-questions-only`. It drives the installed Pi and Pendant with fixture
model replies, searches through keyless Exa, reads Python documentation and checks
that an unselected website is blocked. No personal account is needed. Other paid
services require their own credentials for live checks.

When changing category rules, verify an allowed domain, a misleading suffix such
as `python.org.example.net`, an unselected site, a redirect to an unselected site,
and a category hostname resolving to loopback. Existing explicit local-model
ports must still work. Category refresh must not restart the development container.
