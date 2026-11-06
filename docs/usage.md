# Usage

Pi and Pendant in a container, with a Textual manager and a dedicated VS Code window. Each sandbox has its own workspace selection, private home, model configuration and editor state.

Requirements: Linux, Python 3.10+, rootless Podman or Docker, and desktop VS Code with `code` on PATH. Host-loopback model access currently requires rootless Podman. Build steps download application dependencies; model servers and model files are managed separately.

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/vscode-pi-sandbox
```

Select **New sandbox**, choose a name and workspace, review settings, then create the sandbox. The base profile includes Pi, Pendant with built-in goals, and document tools. Install additional profiles through **Packages**, or select a custom profile folder.

Use **Open in VS Code** for the selected sandbox, **Settings** for its configuration and **Actions** for start/stop, Pi, shell, logs, rebuild and deletion. Press **D** on the home screen to configure defaults for new sandboxes.

Deleting a sandbox removes its containers, private home and editor state while preserving the workspace. Closing the manager or editor leaves containers running.

## Local models

You can start your inference server before or after creating the sandbox. During creation or in Settings, enable host-local models and enter its ports, such as `8000` or `8000-8002`. The launcher adds those exact destinations to the restricted gateway policy. The development container keeps its isolated network; only the gateway maps `local-model.internal` to host loopback.

The manager initializes the model catalogue before opening VS Code. If the server is offline, the editor still opens with **Model not connected**. Start the server, then choose **Settings → Models → Refresh** or run `vscode-pi-sandbox configure NAME`.

For later model changes within an open Pi or Pendant session:

```text
/local-models preview
/local-models refresh
/model
```

New model entries use a 32,768-token output allowance, capped by the active context and any advertised server output limit. Thinking uses part of this allowance. A saved `maxTokens` value in the sandbox’s private `local-pi-models.json` overrides the default. Refresh the catalogue after changing these settings.

[Pi Local Model Manager](https://github.com/kyuz0/pi-local-model-manager) provides discovery and thinking controls. Preview shows proposed changes; refresh writes them and updates Pi's model list.

Other remote destinations may be added explicitly in Settings. Disabling host-local access removes its generated allowlist entries. Model credentials belong in private configuration, not source files or images.

## CLI and storage

```sh
vscode-pi-sandbox create example --workspace /absolute/path/to/project \
  --engine podman --memory 8g --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
vscode-pi-sandbox open example
vscode-pi-sandbox down example
vscode-pi-sandbox up example
vscode-pi-sandbox delete example
```

CLI `delete` is an explicit destructive command; the TUI adds a confirmation dialog.

Saved state defaults to `~/.local/state/vscode-pi-sandbox`. Use `--state-dir PATH` before the command for an independent inventory. TUI defaults live in `~/.config/vscode-pi-sandbox/cockpit.json` (or under `XDG_CONFIG_HOME`). Workspaces are user-selected folders outside source/state. Container names and ownership labels are specific to this application.

### Package download presets

In Settings → Network, check **pip · Python packages from PyPI** and apply the settings. This adds `pypi.org:443` (package index) and `files.pythonhosted.org:443` (downloads) to the restricted allowlist. Unchecking removes those two entries; other destinations remain unchanged. The checkbox also reflects manual edits. New sandboxes do not enable it automatically.

For JavaScript packages, check **npm · JavaScript packages**. This adds `registry.npmjs.org:443`, the [default npm registry](https://docs.npmjs.com/cli/v11/using-npm/registry/). Node.js and npm are already installed in the development image. The preset also covers Yarn or pnpm when configured to use this registry. Packages with install scripts that fetch binaries elsewhere need those destinations added separately.

Common presets are **pip** for Python packages, **npm** for JavaScript packages, and **GitHub** for repositories and release downloads. They can be combined, work in new-sandbox configuration and Settings → Network, and stay synchronized with manual allowlist edits. Enable only the services the project needs; new sandboxes leave these presets unchecked.

This covers packages and build dependencies hosted on PyPI. Git URLs, private indexes and packages that download additional assets from other sites need explicit destinations of their own. See the [PyPI index API](https://docs.pypi.org/api/index-api/) for how the index links to package downloads.

To update an existing restricted sandbox, select it and choose **Settings → Network**. Edit destinations or check the pip preset, then **Apply network**. Only the gateway restarts; development processes, terminals and files remain in place. Active network requests may need to reconnect. A stopped gateway stays stopped and uses the new rules at its next start. Use **Settings → Configuration** for network mode or host model port changes.

CLI equivalent: `vscode-pi-sandbox network NAME --allowlist /path/to/allowlist.txt`.

The **GitHub** preset allows HTTPS repository and release access. For SSH hosts or authenticated Git access with an isolated key, see [SSH and GitHub](ssh.md). [Advisors](advisors.md) covers Codex, Antigravity and Claude setup.

### Network diagnostics

Development containers include `curl`, `ping`, `ip`, `ss` and `getent`.
Restricted mode forwards allowed HTTP/HTTPS destinations through the gateway;
external ICMP (`ping`) and direct DNS queries remain blocked. Use `curl` against
an allowed endpoint to check connectivity in that mode.
