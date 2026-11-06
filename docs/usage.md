# Usage

Pi and Pendant in a container, with a Textual manager and a dedicated VS Code window. Each sandbox has its own workspace selection, private home, model configuration and editor state.

Requirements: Linux, Python 3.10+, rootless Podman or Docker, and desktop VS Code with `code` on PATH. Host-loopback model access currently requires rootless Podman. Build steps download application dependencies; model servers and model files are managed separately.

Install and update with [pipx](../README.md#install). Run `pi-sandbox-factory`
to open the manager. The version appears beside the title; `--version` prints it
from the terminal. Update checks run in the background and stay quiet when GitHub
is unreachable. The upgrade button is available for pipx installations; source
checkouts use their usual Git and package-install workflow.

Select **New sandbox**, choose a name and workspace, review settings, then create the sandbox. The base profile includes Pi, Pendant with built-in goals, and document tools. Install additional profiles through **Packages**, or select a custom profile folder.

**Create from existing…**, beside **New sandbox**, lets you reuse a saved setup.
Choose the source, enter a new name and workspace, then review its profile, model
providers, network rules, features and advisor settings before creating. Added
skills are included; you can deselect them in **Skills and features**.

Select **Include search API keys** to copy those keys from a running source.
Model and advisor logins, SSH credentials, browser sessions and conversations
start fresh. Environment files and Pi seed directories must be selected again.
The new sandbox keeps independent copies of its packages.

Use **Open in VS Code** for the selected sandbox, **Settings** for its configuration and **Actions** for start/stop, Pi, shell, logs, rebuild and deletion. Press **D** on the home screen to configure defaults for new sandboxes.

Deleting a sandbox removes its containers, private home and editor state while preserving the workspace. Closing the manager or editor leaves containers running.

## Workspace and additional folders

The project you select is available at `/workspace`. In **Folders**, you can
choose a starting subfolder, such as `apps/api`, for Pi and VS Code. Leave `.`
to open the whole project. The rest of `/workspace` remains accessible.

Use **Add folder…** to share another host directory. It appears at
`/mnt/<folder-name>`, with a name you can edit. Folders start read-only; clear
**Read-only** to allow changes to the host files. The form shows both paths and
the access mode before you save. Choose specific data folders; system folders,
private sandbox state and overlapping mounts are rejected.

For an existing sandbox, open **Settings → Folders**. Changing mounts recreates
the container and interrupts running processes; its private home and host files
are retained. Changing only the starting folder takes effect the next time you
open Pi or VS Code. Removing a folder disconnects it without deleting its files.
**Create from existing…** includes the extra folders for review and resets the
starting folder to the new workspace root.

Pi and Pendant receive the container paths and access modes through managed
context in their private `~/.pi/agent/AGENTS.md`. Project instructions remain in
place. Read-only access is enforced by the container, including for approved
commands; writable folders also receive the inner sandbox’s usual protections
for configuration and secret files.

For CLI creation, use `--working-directory apps/api` and optionally
`--folders-file folders.json`:

```json
[
  {"source": "/home/user/Documents/reference", "name": "reference", "read_only": true},
  {"source": "/home/user/Documents/reports", "name": "reports", "read_only": false}
]
```

To edit these later, pass an object containing `working_directory` and/or
`extra_folders` to `pi-sandbox-factory update NAME --settings-file settings.json`.
Additional folders require Docker Engine 25+ when using Docker.
Separately mounted filesystems nested inside an added host folder are excluded;
add each filesystem as its own folder if needed.

## Local models

You can start your inference server before or after creating the sandbox. During creation or in Settings, enable host-local models and enter its ports, such as `8000` or `8000-8002`. The launcher adds those exact destinations to the restricted gateway policy. The development container keeps its isolated network; only the gateway maps `local-model.internal` to host loopback.

The manager initializes the model catalogue before opening VS Code. If the server is offline, the editor still opens with **Model not connected**. Start the server, then choose **Settings → Models → Refresh** or run `pi-sandbox-factory configure NAME`.

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
pi-sandbox-factory create example --workspace /absolute/path/to/project \
  --engine podman --memory 8g --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
pi-sandbox-factory open example
pi-sandbox-factory down example
pi-sandbox-factory up example
pi-sandbox-factory delete example
```

CLI `delete` is an explicit destructive command; the TUI adds a confirmation dialog.

Saved state defaults to `~/.local/state/pi-sandbox-factory`. Use `--state-dir PATH` before the command for an independent inventory. TUI defaults live in `~/.config/pi-sandbox-factory/cockpit.json` (or under `XDG_CONFIG_HOME`). Workspaces are user-selected folders outside source/state. Container names and ownership labels are specific to this application.

### Package downloads and website categories

In **Configuration → Network → Website categories**, select **Python** for PyPI,
**npm** for JavaScript packages or **GitHub** for repositories and release downloads.
For an existing sandbox, use **Settings → Network → Website categories**.
[Web access](web-access.md) describes the category sources and automatic updates.

Node.js and npm are already installed. Yarn and pnpm can use the same npm registry.
Packages whose install scripts fetch binaries elsewhere may need additional
`hostname:port` entries, as may private registries.

Choose **Apply network** to update an existing sandbox. The gateway restarts;
active requests may need to reconnect. Use **Settings → Configuration** for
network mode or host model port changes.

CLI equivalent:

```sh
pi-sandbox-factory network NAME --allowlist /path/to/allowlist.txt \
  --website-groups dev-python dev-npmjs dev-github
```

For SSH hosts or authenticated Git access with an isolated key, see
[SSH and GitHub](ssh.md).

### Included command-line tools

Alongside Git, SSH, Python and Node.js, development containers include:

- Downloads and networking: `curl`, `wget`, `ping`, `ip`, `ss`, `getent`, `dig`, `nslookup`, `nc`.
- Text and files: `jq`, `less`, `nano`, `vi`, `file`, `ripgrep`, `rsync` and the standard shell utilities.
- Archives: `tar`, `gzip`, `zip`, `unzip`, `bzip2`, `xz`.

Existing sandboxes receive image changes through **Actions → Update sources and recreate…**.

Restricted mode forwards allowed HTTP/HTTPS destinations through the gateway;
external ICMP (`ping`) and direct DNS queries remain blocked. Use `curl` against
an allowed endpoint to check connectivity in that mode.

## See and interact with the agent’s browser

Enable **Browser** when creating the sandbox, then open it normally. Ask Pi or
Pendant to show its browser. It returns a local link to the current session’s tab
list. Select a tab to open its live DevTools screencast; use **Toggle screencast**
in the top-left toolbar if the page is hidden. You can type, click and navigate.
When you have finished, tell the agent to continue. It keeps the same tabs and state.

The viewer starts automatically and stops with the container. It listens only on
host loopback and requires a session-specific link. Keep that link private: it
allows browser control and appears in the conversation. Website traffic still
passes through the sandbox’s configured network policy.

If a link stops loading, use **Open in VS Code** in the launcher again, then ask
for a fresh link. This repairs the viewer without restarting the browser. Stopping
the sandbox ends its running browser sessions.
