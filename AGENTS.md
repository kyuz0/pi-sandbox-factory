# Agent guide

VS Code Pi Sandbox manages Pi/Pendant containers with a Python CLI and Textual UI.
Read `README.md` and `TESTING.md`. For package work, use `docs/profiles.md`,
`docs/providers.md` and the runnable `examples/`.

## Code map

Implementation and shipped assets live in `vscode_pi_sandbox/`:

- `sandbox.py`: lifecycle, ownership, immutable snapshots and image identities.
- `sandbox_tui.py`: terminal forms; `sandbox_options.py`: shared validation.
- `registry.py`: Git/local packages, revisions and installation.
- `model_providers.py` and `providers/`: provider image layer and container runner.
- `sandbox_advisors.py`, `sandbox_ssh.py`: credential companions.
- `containers/`: images, bootstrap and extension pins; `profiles/base/`: generic profile.

The root `sandbox.py` is a checkout convenience wrapper. The installed command
is `vscode-pi-sandbox`; `python -m vscode_pi_sandbox` is equivalent.

## Design

Profiles provide tools, skills and instructions. Providers configure models.
Neither requires a new launcher branch for a particular company or use case.
Keep private providers and specialist profiles outside this application. A plugin
repository can contain several packages, each installed with `--subdir`.

Git authentication happens on the host. Provider credentials stay in private
container state. Profiles and adapters are trusted executable packages; the
registry is not a security sandbox. Saved sandboxes use snapshots, not mutable
registry directories. Failed updates must preserve the running environment.

Keep the inner command sandbox, outer container, gateway and credential companions
separate. Approval never grants host access. Automatic approval returns failures
to Pi without a human dialog; assisted mode enables human fallback.
`ask_user_question` goes directly to the user without reviewer authorization.

Preserve workspace files, ownership checks and private home state. Model discovery
must work before a Pi session exists and allow opening the editor while offline.
Keep the UI usable at 80×24. Test actual shipped Pendant workers for bootstrap or
extension changes, not just mocked APIs. Never restart a user's sandbox to test.

## Changes and docs

Run the relevant suites in `TESTING.md`. Extension implementation and unit tests
belong in the extension repository; this project pins and integrates them.
Update pins in `vscode_pi_sandbox/containers/dev/extensions.lock.json` or the
security directory’s `sources.json`.
Pi and Pendant have separate version pins; Pendant embeds its own Pi.

Write short, direct documentation explaining supported behavior and actual setup.
Keep private names, credentials, conversation history and investigation logs out of
this public project. Add an example or test when it explains a contract better
than another paragraph.
