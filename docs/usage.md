# Usage

Run Pi through Pendant in the browser editor, in your terminal, or in host VS Code. Each sandbox has its own workspace selection, private home, model configuration and editor state.

Requirements: Python 3.10+ and rootless Podman. Use [WSL2 on Windows or Podman Machine on macOS](platforms.md). Linux also supports Docker with Pi CLI or host VS Code. The browser editor requires an amd64 or arm64 Podman container. Host VS Code needs `code` on PATH. Host-loopback model access requires rootless Podman. Build steps download application dependencies; model servers and model files are managed separately.

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

**Open in browser** is the default on supported hosts. The editor opens locally
without a password. During creation, expand **Editor** to choose Pi CLI or
VS Code on host; clear **Open selected editor after creation** to launch later.
Use **Settings → Editor** to change the launch choice, address, port or password.

**Open with…** opens another client without changing the default. Pi CLI runs in
the current terminal; exit Pi to return to the manager. You can use it alongside
the browser editor. Both share files and model settings, with separate conversations,
and start in the folder configured under **Settings → Folders**.

The browser editor continues running when the manager closes. **Actions → Stop
browser editor** stops it and its terminal/agent processes. Opening it again
reuses its address and saved conversations. Use a separate sandbox for host VS Code
after browser-editor use to preserve the extension isolation boundary.
[Browser editor setup and access](browser-editor.md).

Use **Settings** for configuration and **Actions** for start/stop, shell, logs,
rebuild and deletion. Press **D** on the home screen to configure defaults for
new sandboxes.

Deleting a sandbox removes its containers, private home and editor state while preserving the workspace. Closing the manager or editor leaves containers running.

## Additional skills

In **Skills and features**, enter a Git repository URL and the relative folder
containing the skill’s `SKILL.md`. Any supported HTTPS or SSH Git server works.
The form adds one skill per save. To add another, open **Settings → Configuration**
and enter its source; previously added skills remain listed and enabled. Adding
the same skill name again replaces that skill. Deselect an added skill to remove it.

Profiles can bundle several skills and can be installed from a local folder.
The individual additional-skill field currently accepts Git URLs only.

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

Factory includes [Pi Local Model Manager](https://github.com/kyuz0/pi-local-model-manager).
It discovers running inference servers, reads their context limits and image support,
and configures thinking controls for supported engines. Pi and Pendant share the
resulting model catalogue.

1. Start your inference server on the host.
2. During sandbox creation, or under **Settings → Configuration**, enable
   **Connect to models on this host (rootless Podman)**. Set **Host model ports**
   to the server’s ports, for example `8000`, `8000,8080` or `8000-8002`.
3. Create or update the sandbox, then choose a model in Pendant’s model picker
   or with `/model` in Pi CLI.

Factory allows the selected ports through the gateway and configures discovery
against `local-model.internal`. On Windows, the host is WSL; see
[platform setup](platforms.md) for Windows-hosted servers.

Discovery runs before the editor opens. If the server starts later or you load a
different model, choose **Settings → Models**, select **Local inference servers**,
then **Refresh**. From an open Pi or Pendant chat, use:

```text
/local-models preview
/local-models refresh
/model
```

`preview` shows the proposed catalogue changes; `refresh` applies them. From the
host terminal, `pi-sandbox-factory configure NAME --provider local` also refreshes
the catalogue; reopen Pi/Pendant afterward.

New model entries use a 32,768-token output allowance, capped by the active context
and any advertised server output limit. Thinking uses part of this allowance.
A saved `maxTokens` value in the sandbox’s private `local-pi-models.json` overrides
the default. Refresh after changing it.

## CLI and storage

```sh
pi-sandbox-factory create example --workspace /absolute/path/to/project \
  --engine podman --memory 8g --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
pi-sandbox-factory open example
pi-sandbox-factory pi example
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

If a link stops loading, use **Open in browser** in the launcher again, then ask
for a fresh link. This repairs the viewer without restarting the browser. Stopping
the sandbox ends its running browser sessions.

## Conversation recall

New sandboxes include [pi-compaction-recall](https://github.com/shttty/compaction-recall)
in **Lite** mode. Pi can search conversation history removed by compaction with
`history_grep` and retrieve a passage with `history_expand`.
Lite adds no automatic history hints.

Choose **Configuration → Skills and features → Conversation recall** when creating
or editing a sandbox. **Full** adds automatic hints and may reduce prefix-cache
reuse. **Off** disables recall. The selection applies to both Pi CLI and Pendant.
For CLI creation, use `"compaction_recall": "lite"`, `"full"` or `"off"` in the
JSON passed to `--options-file`.
