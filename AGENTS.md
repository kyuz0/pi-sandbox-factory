# Agent guide

## Purpose and starting points

Local AI Sandboxes manages independent Pi/Pendant development containers through a Textual TUI and CLI. Read `README.md`, `docs/architecture.md` and `TESTING.md`; consult `docs/approvals.md`, `docs/advisors.md` or `docs/ssh.md` for those features.

## Where to change things

- `sandbox.py`: lifecycle, ownership, profile snapshots, image identity and Pi/Pendant version pins.
- `sandbox_tui.py`: forms and operations; `sandbox_options.py`: shared option validation and permission generation.
- `containers/dev/`: image, bootstrap and installed extension configuration. `containers/proxy/` and the network helpers in `sandbox.py`: gateway rules.
- `sandbox_advisors.py` and `sandbox_ssh.py`: isolated companions; credentials stay outside the development container.
- `containers/dev/extensions.lock.json`: model manager, advisor and question-tool sources. `containers/dev/security/sources.json`: security extension archive pin/checksum. See `docs/extensions.md` for repository links.

## Design constraints

The workspace is a host bind mount; private home/session state lives in separate volumes. The inner command sandbox, outer container, network gateway and credential companions are separate boundaries. An approval never grants host access. Automatic approval returns failures to Pi without a human dialog; assisted mode explicitly enables that fallback. `ask_user_question` asks the user directly and requires no reviewer call. Advisors can be selected at creation (`--advisor codex` / `--advisor agy`) or added later through Settings. Login becomes available only after creation or Apply has added that provider to the sandbox.

## Test and update

Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` from this root. For Pi/Pendant, bootstrap or permission changes, follow the disposable-container commands in `TESTING.md`; verify the actual shipped Pendant worker as well as the CLI. Fixture tests do not establish live-model quality or desktop keyboard behavior.

To update Pendant, check the official Open VSX metadata/changelog, change `PENDANT_VERSION` in `sandbox.py` and `containers/dev/Dockerfile`, build and run the worker test. Pendant embeds its own Pi; the standalone CLI pin is independent. Change both only when intended and tested. Fix extensions in their own repositories, publish their commits, then update the appropriate lock/checksum here. Existing containers need **Actions → Update sources and recreate…** and a reopened editor; never restart an active user sandbox just to test an update.

## Development rules

Keep documentation focused on installation, usage and supported behavior. Do not include private project names, local source paths, development conversations or unpublished provenance in code, tests, assets, documentation or commit messages.

Preserve sandbox ownership checks, persistent state and host workspaces. Network changes must keep the gateway policy and model discovery configuration consistent. Model discovery must not require a running Pi session or prevent the editor from opening when the model server is offline.

Keep the terminal interface compact: Open in VS Code, Settings and Actions for the selected sandbox; New sandbox is separate. Keep maintenance and deletion in Actions, with confirmation for deletion. Preserve the gold theme and small-terminal layout.

Run the relevant Python and Node test suites. Use disposable resources for container tests; never treat fixture replies as live model results.

Pi extension implementations belong in their own repositories. This project loads pinned revisions and supplies container configuration; do not vendor, copy or patch extension source here. Keep extension unit tests with their source repositories and container integration tests here.

Use direct public-facing documentation. Omit repository visibility notes, development history, private paths and obvious commentary.
