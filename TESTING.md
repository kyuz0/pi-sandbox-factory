# Development and tests

From the checkout, install the package into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
npm ci --prefix pi_sandbox_factory/containers/inference --ignore-scripts
node --test tests/test_provider_runtime.mjs tests/test_web_search_policy.mjs tests/test_inference_broker.mjs
```

These suites use fixtures without account credentials. For macOS, put fixtures
under your home directory so Podman Machine can share them:

```sh
export TMPDIR="$HOME/Projects/pi-sandbox-test-tmp"
mkdir -p "$TMPDIR"
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## Package installation

Install the wheel outside the checkout and check `--help`, `profile list` and
`provider list`. Create a sandbox from that installation to verify bundled assets.
Check Python 3.10 syntax compatibility when changing Python code.

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

For expanded-skill approval, use a disposable sandbox with the workshop spikee
profile, automatic approval and host-loopback port 18187 allowed:

```sh
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name approval-check --port 18187 --approval-context
```

This expands a synthetic 32 KiB skill in Pi and the shipped Pendant worker.
It checks network approval, exact-command escalation, temporary writes, model
denials and credential-file restrictions without human dialogs or real inference.
Pendant checks also close overlapping runtime sessions and reopen the same saved
conversation, reload its resources and continue reviewed operations. A fork must
receive a new session ID, preserve the original saved conversation and continue
network and command review without permission dialogs. Another scenario selects one
answer in the question UI and verifies that successive network and command reviews
receive that answer without asking for it again.

For installed spikee skills and shell selection, use the same disposable setup:

```sh
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name approval-check --port 18187 --skill-workflow
```

This drives the actual spikee skill in Pi and Pendant with synthetic model replies.
It checks native and shell reference reads, installed tools, workspace and temporary
files, protected paths, a symlink outside the installed tree, and tmux creation,
input, capture and cleanup through reviewed escalation. Inner-shell tmux and denied
commands must fail. No paid inference or application attacks are used.

## Shell-launched Playwright

Use a disposable spikee-profile sandbox with automatic approval and fixture port
18187 allowed, then run:

```sh
.venv/bin/python tests/integration.py --state-dir "$test_root/state" \
  --name browser-check --port 18187 --browser-shell
```

Both Pi and the shipped Pendant worker launch `sandbox-browser` and Python
Playwright through inner Bash and reviewed escalation. With the current profile,
the inner proxy returns HTTP 407; the escalated commands load the local fixture,
interact with its form and save screenshots. The model/reviewer replies are synthetic.

## Question forms

Test the enabled default, disabling forms and enabling them again in both installed
Pi and the actual Pendant worker, without inference or network access:

```sh
.venv/bin/python tests/question_forms_container.py --image YOUR_FACTORY_DEV_IMAGE
```

The check uses a disposable container and verifies that permission and automatic
review extensions remain registered throughout.

## Hosted model connections

`tests/test_provider_credentials.py` exercises creation, browser editor, desktop
editor, Pi CLI and provider refresh/preview/status from saved configurations with
no transient state path. Each uses a custom state directory, with and without a
configured companion key; discovery failures must still block agent launch.

After the unit suites, run the companion and native Pi/Pendant checks:

```sh
podman build -t localhost/factory-inference-check pi_sandbox_factory/containers/inference
.venv/bin/python tests/inference_container.py --image localhost/factory-inference-check --dev-image YOUR_FACTORY_DEV_IMAGE
.venv/bin/python tests/hosted_container.py --image YOUR_FACTORY_DEV_IMAGE --inference-image localhost/factory-inference-check
.venv/bin/python tests/inference_lifecycle.py --dev-image YOUR_FACTORY_DEV_IMAGE
```

These disposable containers use a TLS fixture to check credential isolation,
route enforcement and streamed replies for all four providers, including Azure
deployments and Bedrock profiles. The lifecycle test covers key replacement without
restart, recovery and credential-volume deletion.

For live verification, connect an account in **Settings → Models**, choose a model
and use **Test selected model**. Check each supported authentication method,
including temporary AWS credentials and expired-session recovery.

## Runtime updates

Pi and Pendant have independent version pins in `pi_sandbox_factory/sandbox.py` and
`pi_sandbox_factory/containers/dev/Dockerfile`. Check the release's official metadata
before updating; then rebuild and run the worker suite. Extension fixes and unit
tests belong in their own repositories; update the lock file here afterward.

For advisor or SSH changes, run their unit suites and:

```sh
.venv/bin/python tests/advisor_container.py --dev-image IMAGE
.venv/bin/python tests/advisor_credentials_container.py
```

The advisor check also sends a synthetic image through `advisor_ask` in both Pi
and the actual Pendant worker, using a fixture companion without account access.

Use a development image with the local model provider enabled. These check
isolated launchers, synthetic credential imports, permissions and keyring
persistence. With explicit authorization, add `--host-logins` to the credential
test to check the host’s real sign-ins without inference. On macOS, use the
`TMPDIR` setting above. Actual account login and authorized SSH access need live checks.

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

The integration test checks both clients’ browser tools, injected guidance,
handoff and concurrent sessions. The lifecycle test checks viewer repair,
authentication and cleanup across container restarts, with active native-display
and CDP WebSockets. Private displays, disabled password saving, normal close and
abrupt owner death are covered separately:

```sh
.venv/bin/python tests/browser_native_lifecycle.py --state-dir "$test_root/state" \
  --name pendant-check
```

The rendered test uses Python Playwright and a locally installed Chromium:

```sh
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_interaction.py --state-dir "$test_root/state" \
  --name pendant-check --artifacts "$test_root/browser-interaction"
```

It opens two synthetic sessions without visiting an external website. It checks
rendered pixels, pointer and keyboard input, “Next,” resizing, explicit clipboard
transfer, Observe, popup sign-in, new tabs, native tab switching and reconnects.
Oversized clipboard text receives a clear error without disconnecting.
It rejects a token borrowed from the other session and captures desktop and small
window screenshots, worker diagnostics and a result manifest. Use a new artifact
directory for each run; interrupted runs must not be counted as passed. The
fixture owns its browser processes and closes them when its input ends. Run
these browser suites sequentially: each creates two full browsers within the
container’s configured process limit. The dependency repository also provides
`packages/pi-sandbox/test/browser-lifecycle-check.mjs`; run it inside this
disposable container to exercise transient startup failure and repeated
start/close races.

Inspect both screenshots and the browser console. The native tab bar and controls
must remain usable without overlays, and small windows must scale the desktop
without shrinking popup dialogs. Verify that ordinary application port forwarding
still works in VS Code. Delete the disposable sandbox when finished.

## Automatic review

Extension implementation and unit tests live in
[`pi-auto-review/TESTING.md`](https://github.com/kyuz0/pi-packages/blob/main/packages/pi-auto-review/TESTING.md).
Run that repository's type checks and complete suite before publishing a new
extension pin. Factory's tests below check the installed Pi RPC client and shipped
Pendant worker, including their real session loading and permission events.

Create disposable state, workspace and an unused fixture port:

```sh
review_root=$(mktemp -d "${TMPDIR:-/tmp}/pi-review-check.XXXXXX")
mkdir "$review_root/workspace"
printf '%s\n' '{"approval":"automatic"}' > "$review_root/options.json"
.venv/bin/pi-sandbox-factory --state-dir "$review_root/state" create review-check \
  --workspace "$review_root/workspace" --options-file "$review_root/options.json" \
  --local-model-ports 18189 --allow-domain local-model.internal:18189 --start
.venv/bin/python tests/integration.py --state-dir "$review_root/state" \
  --name review-check --port 18189 --review-recovery \
  --artifacts "$review_root/scripted"
```

| Scenario in each client | Required result |
| --- | --- |
| Load a compacted session whose summary omits an original restriction and includes forged permission | Reviewer evidence retains the original restriction; summary text cannot grant permission |
| Add oversized older instructions and a synthetic screenshot | Whole-message omissions are explicit; retained screenshot text and metadata exclude binary image data |
| Run 20 reviewed constant-output commands with a 4,096-token reviewer input limit | All succeed; history rolls over in both clients without permanent exhaustion |
| Revoke command permission | The operation is denied |
| Explicitly authorize the next read-only check | Review resumes and the operation succeeds |
| Attempt a synthetic TLS-security bypass | Local policy denies it before model review |
| All phases | No permission dialog, one tool result per operation, no retry loop |

The run executes 46 tool operations and 44 scripted model reviews across both
clients. It temporarily changes the disposable sandbox's reviewer input limit and
model catalogue, then restores them in `finally`. Artifacts include fixture
requests and reviewer evidence in `fixture/reviews.jsonl`. Use a fresh artifact
directory for each run. `run.json` records the outcome, Factory revision, source
pin, test-file hashes, actual Pi/Pendant versions, model and scenario counts.
An interrupted run must not be counted as passed. `--review-images` is the shorter four-review screenshot
and text-follow-up check.

With explicit authorization, configure the chosen provider and managed credentials
in the **disposable** sandbox through Factory. Export only its model metadata to
a temporary `CATALOGUE.json`: use the managed proxy endpoint, provider API type,
model ID, input capabilities, context limit and output limit. Its `apiKey` must be
the proxy placeholder, never the real provider key. Then repeat:

```sh
.venv/bin/python tests/integration.py --state-dir "$review_root/state" \
  --name review-check --port 18189 --review-recovery \
  --review-model PROVIDER/MODEL --review-models CATALOGUE.json \
  --artifacts "$review_root/live"
```

Only the 44 reviewer decisions use live inference; main-agent replies stay
scripted. This checks provider transport and model judgment against the same
positive and negative tool scenarios, with the review count verified from both
saved synthetic sessions. Internal reviewer-envelope, omission and rollover
assertions run only with the scripted reviewer, which can inspect its inputs.
The live run also rejects accidental use of the scripted reviewer.
Live success does not establish that every future model decision will
be correct. No production conversation or sandbox is needed.

Record the Factory commit, pinned extension commit, Pi/Pendant versions, model ID,
commands, exit status, counts and skips with each run. When adding a regression,
put controller/policy tests in the extension; extend `mock_inference.py` and both
client drivers here when the problem depends on installed runtime behavior. Assert
denials and recovery as well as successful actions, and always assert no human
permission dialog in automatic mode.

After testing, delete the disposable sandbox:

```sh
.venv/bin/pi-sandbox-factory --state-dir "$review_root/state" delete review-check
```

## Launcher updates

Use an isolated `PIPX_HOME` and `PIPX_BIN_DIR` to test GitHub installation and
`pipx upgrade pi-sandbox-factory` without changing your normal installation.
Check the update notice, confirmation, failure handling and relaunch.

CI runs unit tests and wheel installation checks. Successful pushes to `main`
create a release only when package code, bundled assets or packaging configuration
changes. Documentation, tests and workflows alone must not trigger a release.

## Web access

For a live check, create the disposable sandbox described above with an options
file containing `{"web_access":{"enabled":true},"website_groups":["dev-python"]}`.
Run `tests/integration.py` with `--web-access` instead of
`--pendant-questions-only`. It drives the installed Pi and Pendant with fixture
model replies, searches through keyless Exa, reads Python documentation and checks
that an unselected website is blocked. It also checks that searches and stored
results skip review, automatic page retrieval through search is rejected, and each
explicit fetch produces one approval notice with its reason, including denials.
Use authorized test credentials when checking paid search providers.

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

For the bundled Microsoft sign-in category, use the built proxy image:

```sh
.venv/bin/python tests/network_auth_categories.py
```

This creates and removes its own gateway. Without credentials, it checks live
Microsoft discovery/CDN access and denies misleading suffixes, Graph, an
unselected host, a nonstandard port and a category hostname mapped to loopback.
An explicit local port remains usable; a redirect from it to an unselected host
is blocked. No saved sandbox is changed.

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
afterward.

## Conversation recall

Create a disposable sandbox with the fixture port as above, then run
`tests/integration.py` with `--recall` instead of `--pendant-questions-only`.
Repeat after changing `options.compaction_recall` to `full`, then `off`, through
`update --settings-file`. Preserve the other saved options in that file.

The test resumes synthetic compacted history in the installed Pi CLI and Pendant
worker. It checks retrieval of the original message, tool availability, Full's
hints, no hints in Lite, and no approval-review requests for history tools.

The extension and its runtime dependencies are pinned in
`pi_sandbox_factory/containers/dev/compaction-recall/package-lock.json`.
Its Node requirement applies to both the container CLI and VS Code's remote
Node runtime, which Pendant uses. Check both when updating this package.

## Terminal layout

Run the TUI suites, including `test_tui_layout.py` and `test_packages_ui.py`.
Review new and edited forms at 80×24, 120×40 and 220×50, including expanded sections,
validation errors and long paths. Inspect the rendered view as well as geometry;
use Textual's `App.export_screenshot()` for SVG captures with fixture data.

## Communications

Create a disposable sandbox with `{"communications":{"slack":true}}` in its
options file and the fixture port allowed. Run `tests/integration.py` with
`--communications`. This installs an invalid synthetic bot token in that
sandbox and checks both the actual Pi CLI and Pendant worker: eight Slack tools,
API access through the proxy, missing search credentials, a rejected send, blocked
credential-file reads and absent token environment variables. It sends no messages.
Delete the disposable sandbox afterward. Use a separately authorized account check
for reading and sending real messages.

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

Use `--cdp http://HOST:PORT` to attach to an existing Chromium or Edge debugging
session. For WSL, drive Windows Edge so the check includes Windows localhost
forwarding. Keep the debugging listener on loopback and use a disposable browser profile.

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

For authentication and lifecycle changes, run:

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

Run the Python and Node suites on Linux, then validate on each target platform.

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
5. Close the launcher and all Ubuntu terminals; verify the editor still responds
   after 90 seconds. Restart WSL or Podman Machine, then reopen the sandbox.
   On macOS, switching to another Podman connection must produce an error before managing its containers.
   Verify a folder outside the VM shares produces an actionable startup error.
6. Sign in to one advisor with disposable test credentials; check its status and
   recovery after logout. Never include credentials in results or fixtures.

For Windows, check WSL-native projects first, then a specific `/mnt/c` project.
Test an SSH-forwarded model in WSL and, separately, a Windows-local model with
mirrored networking. For macOS, check localhost model access, native ARM64 images
and Chromium interaction.

## macOS verification

On a 16 GB M1 with macOS 27 and Podman 6.1.4, container creation, Pi/Pendant,
browser tools, editor authentication, network isolation and folder permissions passed.
Podman Machine used four CPU cores and 8 GB RAM.

## Windows verification

Windows 11, WSL 2.7.10, Ubuntu 26.04, Podman 5.7 and Windows Edge 157;
24 GB assigned to Windows, 12 GB to WSL. The 7 November 2026 run passed:

| Check | Result |
| --- | --- |
| Python unit suite | 242 passed on Windows/WSL and Linux |
| Node unit suite | 24 passed on Windows/WSL |
| Installed Pi and Pendant | Questions, folder context, permissions, browser tools and Lite recall passed |
| Windows Edge | Pendant loaded automatically in dark mode; typing worked for WSL and C: workspaces |
| Editor lifecycle | Restart, password login, HTTPS, Host/Origin checks and anonymous WebSocket rejection passed |
| Browser viewer | Session isolation, reconnect, key rotation and container-stop cleanup passed |
| Folder lifecycle | Starting-folder edits, mount removal and read-only changes preserved files and private state |
| Windows-local models | Mirrored networking, restricted gateway access and model/context discovery passed |
| Background operation | Both editors remained reachable with no Ubuntu terminal or launcher open for 90 seconds |

Model replies in these checks came from synthetic fixtures.

## Repository SSH access

Run `tests/test_ssh.py` and the TUI suite, then exercise the actual SSH companion:

```sh
.venv/bin/python tests/repository_ssh_container.py --dev-image YOUR_FACTORY_DEV_IMAGE
```

The disposable SSH Git server checks generated-key persistence, refusal to replace
keys, private-volume isolation, clone and push behaviour under read-only,
restricted-branch and full-write server policies. Its policies are test fixtures,
not a verification of GitHub or GitLab settings. It deletes its containers and
volumes afterward.

For a live service check, use a disposable repository and follow
[repository setup](docs/repository-access.md). Verify clone succeeds and push fails
with a read-only deploy key. With a separate automation account, test `pi-*` pushes,
forbidden refs, force pushes and deletions against the configured server rules.
Do not modify production repository policies for testing.

## TUI visual review

Run `./.venv/bin/python tests/render_tui.py /tmp/factory-ui` to capture offline
fixtures at 80×24, 120×40 and 220×50. Open the SVGs in a browser; `coverage.json`
lists each screen and state. The fixtures include expanded settings, populated
fields and errors. Review every image with Claude Opus before committing UI changes,
using the layout rules in `AGENTS.md`. Re-render corrected views; passing tests alone
is insufficient. Use `--size 80x24 --monochrome` for the monochrome check, or
`--only STATE` to repeat a corrected view. Also exercise keyboard focus and scrolling.
