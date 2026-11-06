# Agent guide

Pi Sandbox Factory manages Pi/Pendant containers with a Python CLI and Textual UI.
Read `README.md` and `TESTING.md`. For package work, use `docs/profiles.md`,
`docs/providers.md` and the runnable `examples/`.

## Code map

Implementation and shipped assets live in `pi_sandbox_factory/`:

- `sandbox.py`: lifecycle, ownership, immutable snapshots and image identities.
- `sandbox_tui.py`: terminal forms; `sandbox_options.py`: shared validation.
- `web_access.py`: search modes, provider settings and reusable private keys; `network_groups.py`: trusted category updates and gateway rules.
- `updates.py`: GitHub tags, installed version and pipx upgrade detection.
- `browser_viewer.py`: authenticated loopback viewer and container-bound lifetime.
- `registry.py`: Git/local packages, revisions and installation.
- `model_providers.py` and `providers/`: provider image layer and container runner.
- `sandbox_advisors.py`, `sandbox_ssh.py`: credential companions.
- `containers/`: images, bootstrap and extension pins; `profiles/base/`: generic profile.

The root `sandbox.py` is a checkout convenience wrapper. The installed command
is `pi-sandbox-factory`; `python -m pi_sandbox_factory` is equivalent.

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

Search defaults and sandbox copies must keep credentials separate from options.
Match keys to both provider and endpoint; a copy without keys must not inherit
workstation defaults. Exercise fallback and Only-provider behavior in both clients.

Preserve workspace files, ownership checks and private home state. Model discovery
must work before a Pi session exists and allow opening the editor while offline.
Keep the UI usable at 80×24. Test actual shipped Pendant workers for bootstrap or
extension changes, not just mocked APIs. Never restart a user's sandbox to test.

## Changes and docs

Run the relevant suites in `TESTING.md`. Extension implementation and unit tests
belong in the extension repository; this project pins and integrates them.
Update pins in `pi_sandbox_factory/containers/dev/extensions.lock.json` or the
security directory’s `sources.json`.
Pi and Pendant have separate version pins; Pendant embeds its own Pi.

Write short, direct documentation explaining supported behavior and actual setup.
Keep private names, credentials, conversation history and investigation logs out of
this public project. Add an example or test when it explains a contract better
than another paragraph.

Release versions use UTC CalVer. After tests pass, the GitHub workflow versions
and tags pushes that change `pi_sandbox_factory/`, `pyproject.toml` or `MANIFEST.in`.
Documentation, tests and workflow changes alone do not create a release. Keep update checks off the UI thread;
upgrades require confirmation and must not recreate running sandboxes.
