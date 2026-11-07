# Development and tests

From the checkout, install the package into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_provider_runtime.mjs tests/test_web_search_policy.mjs
```

The Python suite covers lifecycle, ownership, rollback, package revisions,
subfolder exports, provider selection and terminal interactions, including 80×24 layouts. Node tests
cover the adapter contract, preview, credential handling and refresh locking.
Creation tests cover **Create from existing…**, optional search keys, independent
package snapshots after source deletion, and unchanged source settings.
Launcher tests cover Open with, terminal handoff and return, browser-editor defaults,
startup failure and the configured working folder. Editor tests cover password
generation, masked saved credentials, connection validation and settings changes
without container recreation.
These tests use fixtures and no account credentials. On macOS, place test fixtures
under your home directory: the default system temporary directory is intentionally
excluded from sandbox workspaces.

```sh
export TMPDIR="$HOME/Projects/pi-sandbox-test-tmp"
mkdir -p "$TMPDIR"
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Use `~/Projects` for container integration workspaces on macOS so Podman Machine
can share them.

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
test_root=$(mktemp -d "${TMPDIR:-/tmp}/pi-sandbox-check.XXXXXX")
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

For local discovery and profile resources, install `examples/profile` as `reporting`,
create a disposable reporting sandbox with local discovery on port 18082 and that
port allowed, then run `tests/provider_container.py --name NAME`.
It checks local discovery, preservation of unrelated models and the profile skill.

## Hosted model connections

The Python suite exercises provider forms at 80×24, 120×40 and 220×50, saved
configuration, credential transport, endpoint validation and routing rollback.
Run the broker and native-runtime checks:

```sh
npm ci --prefix pi_sandbox_factory/containers/inference --ignore-scripts
node --test tests/test_inference_broker.mjs tests/test_provider_runtime.mjs
podman build -t localhost/factory-inference-check pi_sandbox_factory/containers/inference
.venv/bin/python tests/inference_container.py --image localhost/factory-inference-check --dev-image YOUR_FACTORY_DEV_IMAGE
.venv/bin/python tests/hosted_container.py --image YOUR_FACTORY_DEV_IMAGE --inference-image localhost/factory-inference-check
.venv/bin/python tests/inference_lifecycle.py --dev-image YOUR_FACTORY_DEV_IMAGE
```

These create and remove disposable offline containers. They check private credential
storage, header replacement, fixed routes, redirects, cancellation, limits, restart
persistence, and native Pi/Pendant streamed replies for OpenRouter, Together, Azure
and Bedrock against a TLS fixture. Azure deployment mapping, Bedrock profile metadata
and the actual Pendant worker's default model are exercised too. The lifecycle check
uses the current development entrypoint and checks startup, key replacement without
restarting containers, stopped-service recovery and deletion of credential volumes.

For live verification, connect an account in **Settings → Models**, choose a model
and use **Test selected model**. Repeat with the supported authentication methods;
AWS IAM tests must include a session token when using temporary credentials. This
sends a small billable request. Fixture results do not establish account permissions
or real provider acceptance of a request.

## Runtime updates

Pi and Pendant have independent version pins in `pi_sandbox_factory/sandbox.py` and
`pi_sandbox_factory/containers/dev/Dockerfile`. Check the release's official metadata
before updating; then rebuild and run the worker suite. Extension fixes and unit
tests belong in their own repositories; update the lock file here afterward.

Advisor or SSH changes need their unit suites and companion tests.
Run
`.venv/bin/python tests/advisor_container.py --dev-image IMAGE` after installing the
package. Use an image with the local model provider enabled. It checks isolated launchers
and credential volumes without real login.
Actual account login and authorized SSH access are separate checks.

Run `python tests/advisor_credentials_container.py` to check synthetic credential
copies, file permissions, keyring persistence and companion mounts. With explicit
authorization, add `--host-logins` to copy the host’s Codex, Claude and Antigravity
sign-ins and check login/model status without inference. The script removes its
disposable containers and credential volumes afterwards. On macOS, set
`TMPDIR="$HOME/Projects/pi-sandbox-test-tmp"` as above so the fixture state is
inside the VM share. The synthetic check reads Codex and Claude fixture files
through the real importer, checks the macOS Keychain recovery message, and tests
Antigravity's container keyring separately. It does not establish that a real
provider accepts copied or renewed tokens.

Use disposable state throughout. Never restart a user's sandbox or copy real credentials
without explicit authorization. Record commands and results; distinguish fixtures from live services.

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

`test_web_access.py` covers provider migration, active endpoint selection, private
keys, reusable defaults, category expansion, automatic
refresh, offline fallback and gateway rule ordering. TUI tests cover creation,
editing, defaults, copying without keys, stopped sources and category selection. The normal suite makes no search requests.

For a live check, create the disposable sandbox described above with an options
file containing `{"web_access":{"enabled":true},"website_groups":["dev-python"]}`.
Run `tests/integration.py` with `--web-access` instead of
`--pendant-questions-only`. It drives the installed Pi and Pendant with fixture
model replies, searches through keyless Exa, reads Python documentation and checks
that an unselected website is blocked. It also checks that searches and stored
results skip review, automatic page retrieval through search is rejected, and each
explicit fetch produces one approval notice with its reason, including denials.
No personal account is needed. Other paid
services require their own credentials for live checks.

For provider fallback checks, also configure SearXNG with
`http://local-model.internal:PORT`, where PORT is the fixture port already allowed
for the test sandbox. Keep search mode `auto` and Exa configured. Run with
`--web-providers` instead of `--web-access`. The fixture returns a SearXNG error;
both installed clients must fall back to Exa. The next phase selects only SearXNG
and verifies that its failure stays a failure and an explicit Exa request is
rejected. The runner restores the search configuration afterward.

When changing category rules, verify an allowed domain, a misleading suffix such
as `python.org.example.net`, an unselected site, a redirect to an unselected site,
and a category hostname resolving to loopback. Existing explicit local-model
ports must still work. Category refresh must not restart the development container.

## Folder mounts and starting directory

Create a disposable workspace with an `app` subfolder and two separate host
folders. Mount them as `reference` (read-only) and `output` (writable), using
`--folders-file` as shown in [Usage](docs/usage.md#workspace-and-additional-folders).
Set `--working-directory app` and allow fixture model port 18085. Put
`REFERENCE_OK` in `reference/readme.txt`, `PROJECT_FOLDER_CONTEXT` in
`workspace/app/AGENTS.md`, and `PROJECT_FOLDER_OVERRIDE` in
`workspace/app/.pi/APPEND_SYSTEM.md`. Create `workspace/.pi` and a symlink
`output/private-link` pointing to `/home/node/.pi/agent/auth.json`.

```sh
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name folders-check --port 18085 --folders
.venv/bin/python tests/folders_lifecycle.py --state-dir "$test_root/state" \
  --name folders-check
```

The fixture checks the actual model-request context in Pi and Pendant, their cwd,
file tools, ordinary shell writes and read-only enforcement after escalation.
The lifecycle check changes and removes mounts, checks host ownership and SELinux
labels, and confirms that starting-folder edits preserve the running container.
It leaves the disposable sandbox with only `output`, mounted read-only. Delete it
afterward. `test_folders.py` covers path validation, permissions, copies and folder
controls at 80×24; it needs no container or account.

## Conversation recall

Create a disposable sandbox with the fixture port as above, then run
`tests/integration.py` with `--recall` instead of `--pendant-questions-only`.
Repeat after changing `options.compaction_recall` to `full`, then `off`, through
`update --settings-file`. Preserve the other saved options in that file.

The test resumes synthetic compacted history in the installed Pi CLI and Pendant
worker. It checks retrieval of the original message, tool availability, Full's
hints, no hints in Lite, and no approval-review requests for history tools.
Lite is the creation default. The Python suite also covers saved selection,
disabling the extension and keyboard operation at 80×24.

The extension and its runtime dependencies are pinned in
`pi_sandbox_factory/containers/dev/compaction-recall/package-lock.json`.
Its Node requirement applies to both the container CLI and VS Code's remote
Node runtime, which Pendant uses. Check both when updating this package.

## Terminal layout

`test_tui_layout.py` checks path-control alignment, dependent-option spacing,
visible actions, Escape cancellation, direct web-access navigation, conditional
fields and the selected editor launch. `test_packages_ui.py` checks installation,
item-specific updates, removal confirmation, list refresh and action placement.
Run these with the other TUI tests.
Review new and edited forms at 80×24 and 120×40, including expanded sections,
validation errors and long paths. Inspect the rendered view as well as geometry;
use Textual's `App.export_screenshot()` for SVG captures with fixture data.

## Communications

`test_communications.py` checks token storage, copies and network rules;
`test_communications_ui.py` checks the accordion and masked credential dialog at
80×24 and 120×40, including errors and Escape cancellation.

Create a disposable sandbox with `{"communications":{"slack":true}}` in its
options file and the fixture port allowed. Run `tests/integration.py` with
`--communications`. This installs an invalid synthetic bot token in that
sandbox and checks both the actual Pi CLI and Pendant worker: eight Slack tools,
API access through the proxy, missing search credentials, a rejected send, blocked
credential-file reads and absent token environment variables. It uses an
invalid token for the Slack API check and sends no messages. Delete the disposable
sandbox afterward. Reading a real workspace and sending messages require a
separate authorized account check.

The Slack extension's unit tests live in its pinned repository.

Run `tests/communications_lifecycle.py --state-dir PATH --name NAME` against the
same disposable sandbox to check token-only updates without recreation, removal
of a duplicate npm registration, disabled tools in Pendant, network-rule removal,
and credentials surviving disable/re-enable.

## Browser editor

Follow [the browser editor guide](docs/browser-editor.md) for the real-model smoke
check. Confirm dark mode, Explorer on the left, Pendant in the right secondary
sidebar with its composer loaded **without clicking the Pendant tab**, a shell
tool writing a workspace file, and conversation persistence after
restarting the editor. Use **Actions → Stop browser editor** and verify that its
terminal processes also exit. Stopping the container must close the loopback listener. Neither action
should stop unrelated sandboxes or Pi CLI sessions.

On a fresh launch and after restarting, `/workspace` must open
without a trust prompt or Restricted Mode. Check that Manage Workspace Trust says
“You trust this folder”. Opening `/tmp` instead must still request trust.

For an automated startup check, install Playwright in your test environment and
run `playwright install chromium`. Start a fresh disposable browser editor, then:

```sh
python tests/browser_editor_startup.py 'PRINTED_URL/?folder=/workspace' --screenshot /tmp/pendant-startup.png
```

The check waits for the actual Pendant composer without selecting its tab. Inspect
the screenshot for dark mode and right-side placement. Also check a fresh host
VS Code profile when changing extension startup behavior.

For synthetic host-file probes, create a disposable sandbox without desktop VS Code:

```sh
check_root="${TMPDIR:-/tmp}/pi-browser-boundary-check"
.venv/bin/python tests/browser_editor_check.py prepare --root "$check_root"
.venv/bin/pi-sandbox-factory --state-dir "$check_root/state" create browser-check \
  --workspace "$check_root/workspace" --folders-file "$check_root/folders.json" \
  --allow-domain local-model.internal:8000 --start
.venv/bin/pi-sandbox-factory --state-dir "$check_root/state" browser-editor browser-check
```

Leave the launcher running. In another terminal at this checkout:

```sh
.venv/bin/python tests/browser_editor_check.py install \
  --root "$check_root" --container pi-sandbox-factory-browser-check
```

Open the printed URL and reload the page.
Both probe extensions write JSON results into the workspace. Then run:

```sh
.venv/bin/python tests/browser_editor_check.py verify --root "$check_root"
```

The probes exercise container Node APIs and a browser-only extension worker against
fake `.env` and SSH-key files outside the mounts. They also check workspace writes,
read-only mount enforcement and absence of the host-terminal command. Never replace
the fake files with real secrets or grant the browser access to the host-private folder.

The unit suite checks relay headers, origin rejection, fixed container commands,
stream forwarding, archive integrity and the desktop/browser session lock.
For authentication and lifecycle changes, run against the disposable sandbox:

```sh
.venv/bin/python tests/browser_editor_lifecycle.py --state-dir "$check_root/state" --name browser-check
```

It checks passwordless startup, reopening, address reuse, password login,
anonymous WebSocket rejection, foreign origins, HTTPS cookies and occupied ports.
It restores the saved editor settings and leaves the editor stopped.

In the TUI, check **Editor** during creation and **Settings → Editor** afterward.
Generate a password, save, open the browser and sign in. Close the manager and
confirm the editor remains usable. Reopen through **Open**; use **Open with… → Pi
CLI** alongside it. Confirm that selecting Pi CLI during creation opens it in the
terminal and returns to the manager when Pi exits. For remote HTTPS, use a
certificate trusted by the connecting browser and verify Pendant loads there too.

Delete the disposable sandbox after stopping the launcher:

```sh
.venv/bin/pi-sandbox-factory --state-dir "$check_root/state" delete browser-check
```


## Platform checks

Run the Python and Node suites on Linux before publishing platform changes.
`test_host_platform.py` checks platform selection, WSL paths, private-folder
rejection, Podman connection/version validation and architecture selection with
fixtures. It does not establish that Windows or macOS works on real hardware.

On Windows 11 with WSL2 Ubuntu 26.04, and on an Apple Silicon Mac with rootless
Podman Machine, install from [platform setup](docs/platforms.md) and check:

1. Create a default sandbox from the TUI. Open the browser editor; confirm dark
   mode, trusted workspace, Pendant on the right and a responding fixture/local model.
   Reopen it, stop the editor, restart it and confirm its URL stays stable.
2. Open a second sandbox. Confirm its hostname differs and its login cookie is
   not sent to the first. Check WebSocket connection and clipboard in the target
   browser. Confirm the editor’s file upload/download commands are disabled. Open
   Pi CLI alongside the editor.
3. Use a workspace subfolder and two extra folders: read-only and writable. Check
   host-to-container and container-to-host changes and unchanged host ownership.
   On macOS, check polling for host edits; native file-watch events may not cross
   the VM share. Attempt writes to the read-only mount from the outer container.
4. Run the browser and model fixture recipes above. An allowed endpoint must work;
   an unselected destination and a redirect to it must fail. Open the browser
   viewer, interact with the synthetic form and read that state through Pi.
5. Restart WSL or Podman Machine, then reopen the sandbox. On macOS, switching to
   another Podman connection must produce an error before managing its containers.
   Verify a folder outside the VM shares produces an actionable startup error.
6. Sign in to one advisor with disposable test credentials; check its status and
   recovery after logout. Never include credentials in results or fixtures.

For Windows, check WSL-native projects first, then a specific `/mnt/c` project.
Test an SSH-forwarded model in WSL and, separately, a Windows-local model with
mirrored networking. For macOS, check localhost model access, native ARM64 images
and Chromium interaction. A Windows cloud VM needs nested virtualization for WSL2;
use a Mac with hardware virtualization available for Podman Machine.
