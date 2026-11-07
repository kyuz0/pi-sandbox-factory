# Agent guide

Pi Sandbox Factory manages Pi/Pendant containers with a Python CLI and Textual UI.
Read `README.md` and `TESTING.md`. For package work, use `docs/profiles.md`,
`docs/providers.md` and the runnable `examples/`.

## Code map

Implementation and shipped assets live in `pi_sandbox_factory/`:

- `sandbox.py`: lifecycle, ownership, immutable snapshots and image identities.
- `folders.py` and `folders_ui.py`: validated host mounts, starting directory and shared folder controls.
- `sandbox_tui.py`: terminal forms; `sandbox_options.py`: shared validation.
- `communications.py` and `communications_ui.py`: optional channel tools and private credential configuration.
- `web_access.py`: search modes, provider settings and reusable private keys; `network_groups.py`: trusted category updates and gateway rules.
- `updates.py`: GitHub tags, installed version and pipx upgrade detection.
- `browser_editor.py` and `containers/editor/launch.py`: opt-in code-server, loopback relay and process supervision.
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
workstation defaults. Full configuration copies reuse package snapshots, with fresh
workspace selection and private state; never copy credential paths or seed homes.
Exercise fallback and Only-provider behavior in both clients.

Preserve workspace files, ownership checks and private home state. Model discovery
must work before a Pi session exists and allow opening the editor while offline.
Extra folders use `/mnt/<name>` and default to read-only. The starting directory
is relative to `/workspace` and applies at launch. Keep mount validation, inner
write roots, native tool permissions and agent context derived from the same
folder configuration. The managed global `AGENTS.md` block adds context without
replacing project instructions. Folder grants never become workstation defaults.
Keep the UI usable at 80×24. Test actual shipped Pendant workers for bootstrap or
extension changes, not just mocked APIs. Never restart a user's sandbox to test.

## Terminal layout and navigation

- Group each label, control and explanation in one `.setting`. Keep help directly
  below its control; put one blank row between groups, not inside them.
- Path inputs and Browse buttons share a three-row height. Put dependent options
  one row below, indented two columns. Use the shared checkbox from `tui_widgets.py`.
- Give inputs persistent labels; placeholders are examples, not labels. Use the
  same title style and left edge across screens, and limit forms to 112 columns.
- Align page Back/Cancel left and the primary action right, at the form edges.
  Group dialog actions on the right, Cancel before Save. Keep contextual actions
  beside their object. Use three-row page action buttons at 32 terminal rows or
  more; below that, use one row with two columns of inner padding.
  Dock page actions below scrollable
  fields, with three columns of side padding and a blank row above and below
  their contents. Reserve the status-bar row separately; it must not cover the
  bottom padding. Put after-save choices, such as opening the editor, beside the final
  action rather than between unrelated sections. Keep buttons visibly distinct
  from their section background; constrain dialogs and scroll their fields so errors cannot hide Save.
  Escape cancels dialogs without applying changes.
- Put common tasks in the visible Settings menu. A shortcut should open and focus
  the existing form, not duplicate its save logic. Keep optional setup collapsed
  and show its state in the heading. Disable fields whose controlling option is off.
- Review rendered screens at 80×24 and 120×40, including expanded sections, long
  paths, errors and keyboard focus. Check monochrome checkbox states too. Geometry
  tests complement visual inspection; neither replaces the other.

## Changes and docs

Run the relevant suites in `TESTING.md`. Extension implementation and unit tests
belong in the extension repository; this project pins and integrates them.
Update pins in `pi_sandbox_factory/containers/dev/extensions.lock.json` or the
security directory’s `sources.json`.
Pi and Pendant have separate version pins; Pendant embeds its own Pi.
Conversation recall defaults to Lite in both clients; keep its mode tied to the
saved sandbox options. Its dependency lock lives in `containers/dev/compaction-recall/`.

Write short, direct documentation explaining supported behavior and actual setup.
Keep private names, credentials, conversation history and investigation logs out of
this public project. Add an example or test when it explains a contract better
than another paragraph.

Release versions use UTC CalVer. After tests pass, the GitHub workflow versions
and tags pushes that change `pi_sandbox_factory/`, `pyproject.toml` or `MANIFEST.in`.
Documentation, tests and workflow changes alone do not create a release. Keep update checks off the UI thread;
upgrades require confirmation and must not recreate running sandboxes.
