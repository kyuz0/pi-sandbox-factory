# Usage

Pi and Pendant in a container, with a Textual manager and a dedicated VS Code window. Each sandbox has its own workspace selection, private home, model configuration and editor state.

Requirements: Linux, Python 3.9+, rootless Podman or Docker, and desktop VS Code with `code` on PATH. Host-loopback model access currently requires rootless Podman. Build steps download application dependencies; model servers and model files are managed separately.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-tui.txt
.venv/bin/python sandbox.py
```

The manager uses the yellow `cockpit-gold` theme. Select **New**, choose a name and workspace, review settings, then create the sandbox. The base profile includes Pi, Pendant, Goal and document tools. Custom profiles can be selected by folder.

Select a saved sandbox to start, stop, open VS Code, change settings, inspect logs, open Pi/a shell, preview/refresh models, rebuild or delete it. Start/Stop, Pi, shell, logs, rebuild and Delete are under **Actions**. Delete asks for confirmation. **Settings** groups Network, Models and Configuration; defaults for future sandboxes are available with **D** on the home screen. It removes that sandbox's containers, private home, sessions and editor state; it keeps the host workspace, seed configuration and shared images. Closing the manager or editor does not stop containers.

## Local models

You can start your inference server before or after creating the sandbox. During creation or in Settings, enable host-local models and enter its ports, such as `8000` or `8000-8002`. The launcher adds those exact destinations to the restricted gateway policy. The development container keeps its isolated network; only the gateway maps `local-model.internal` to host loopback.

After starting the containers, creation runs `pi-local-model-manager` directly with Node and writes any discovered models to the private catalogue before opening VS Code. No Pi session, selected model or Pendant command is required. The same initialization runs before later editor opens.

If no usable model is found, creation and editor opening still complete with **Model not connected**. Files, the shell and VS Code remain usable; model chat needs a connected server. Start the configured server (or correct its ports in Settings), then choose **Settings → Models → Refresh catalogue**. This action runs outside Pi/Pendant and works even with an empty catalogue. Reopen the editor or refresh its model list afterward. CLI: `python sandbox.py configure NAME`.

Invalid configuration or an actual tool failure remains an error; an unavailable model is not a failed sandbox.

For later model changes within an open Pi or Pendant session:

```text
/local-models preview
/local-models refresh
/model
```

New model entries use a 32,768-token output allowance, capped by the active context and any advertised server output limit. Thinking uses part of this allowance. A saved `maxTokens` value in the sandbox’s private `local-pi-models.json` overrides the default. After updating the sandbox image, refresh the catalogue; remove an explicit old limit if you want the new default.

The bundled `pi-local-model-manager` extension discovers server metadata and maintains the private model catalogue. It does not start inference servers, download weights or guess missing context/image capabilities. Preview is read-only. The manager's Refresh models writes the same configuration; existing Pi/Pendant sessions should also refresh before selecting the new model.

Other remote destinations may be added explicitly in Settings. Disabling host-local access removes its generated allowlist entries. Model credentials belong in private configuration, not source files or images.

## CLI and storage

```sh
python sandbox.py create example --workspace /absolute/path/to/project \
  --engine podman --memory 8g --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
python sandbox.py open example
python sandbox.py down example
python sandbox.py up example
python sandbox.py delete example
```

CLI `delete` is an explicit destructive command; the TUI adds a confirmation dialog.

Saved state defaults to `~/.local/state/local-ai-sandbox`. Use `--state-dir PATH` before the command for an independent inventory. TUI defaults live in `~/.config/local-ai-sandbox/cockpit.json` (or under `XDG_CONFIG_HOME`). Workspaces are user-selected folders outside source/state. Container names and ownership labels are specific to this application.

Choose each sandbox's name and workspace when creating it.

### pip network preset

In Settings → Network, check **pip · Python packages from PyPI** and apply the settings. This adds `pypi.org:443` (package index) and `files.pythonhosted.org:443` (downloads) to the restricted allowlist. Unchecking removes those two entries; other destinations remain unchanged. The checkbox also reflects manual edits. New sandboxes do not enable it automatically.

This covers packages and build dependencies hosted on PyPI. Git URLs, private indexes and packages that download additional assets from other sites need explicit destinations of their own. See the [PyPI index API](https://docs.pypi.org/api/index-api/) for how the index links to package downloads.

To update an existing restricted sandbox, select it and choose **Settings → Network**. Edit destinations or check the pip preset, then **Apply network**. Only the gateway restarts; development processes, terminals and files remain in place. Active network requests may need to reconnect. A stopped gateway stays stopped and uses the new rules at its next start. Use **Settings → Configuration** for network mode or host model port changes.

CLI equivalent: `python sandbox.py network NAME --allowlist /path/to/allowlist.txt`.
