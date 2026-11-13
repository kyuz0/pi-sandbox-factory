# Usage

Run `pi-sandbox-factory` to open the manager. See [installation](../README.md#install)
and [platform setup](platforms.md) for prerequisites. `--version` prints the
installed version. Pipx installations can update from the manager; source checkouts
use Git and a package reinstall.

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

Use a separate sandbox for host VS Code after browser-editor use.
See [browser editor setup](browser-editor.md) for connection settings and access boundaries.

Use **Settings** for configuration and **Actions** for start/stop, shell, logs,
rebuild and deletion. Press **D** on the home screen to configure defaults for
new sandboxes.

Deleting a sandbox removes its containers, private home and editor state while preserving the workspace. Closing the manager or editor leaves containers running.

## Change approval and sandbox settings

For a sandbox you have already created:

1. Open `pi-sandbox-factory` on the host and select the sandbox.
2. Open **Settings → Configuration** and expand **Permissions and sandbox**.
3. Choose **Approval mode**, set **Use inner command sandbox**, and leave
   **Protect common credential files** enabled unless `.env`, private keys and
   similar workspace files may be shown to the agent.
4. Select **Apply and recreate**, then reopen Pi or Pendant and resume your saved chat.

Applying these settings stops running commands and tmux sessions. Workspace files,
private configuration and saved conversations are preserved. Finish active work
before applying the change.

These settings are managed by Factory; Pi has no slash command to switch them.
`/reload` does not apply a different Factory approval mode or enable/disable the
inner sandbox. When **Protect common credential files** is disabled, the agent
can read and write those files like other workspace files. Changing defaults on the manager's home screen affects future
sandboxes, not existing ones.

See [approval modes and shell behavior](approvals.md#configuration-and-updates).
The outer container and its network policy still apply when the inner sandbox is off.

## Additional skills

**Skills and features** also contains **Enable optional subagents**, alongside
question forms, conversation recall, browser tools, goals and scheduled prompts.

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
**Read-only** to allow changes to the host files. System folders,
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

During creation or in **Settings → Configuration**, enable **Connect to models on
this host** and enter the server ports, such as `8000` or `8000-8002`.
Factory uses [Pi Local Model Manager](https://github.com/kyuz0/pi-local-model-manager)
to discover models and configure their context, image and thinking support in
Pi and Pendant.

Choose a model in Pendant’s picker or with `/model`. After changing the running
model, use `/local-models refresh` or **Settings → Models → Refresh**.

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

Saved state lives in `~/.local/state/pi-sandbox-factory`. Pass `--state-dir PATH`
before the command for a separate inventory. TUI defaults live in
`~/.config/pi-sandbox-factory/cockpit.json` (or under `XDG_CONFIG_HOME`).

### Package downloads and website categories

In **Configuration → Network → Website categories**, select **Python** for PyPI,
**npm** for JavaScript packages, **GitHub** for repositories and release downloads,
or **Hugging Face** for models and datasets.
For Microsoft sign-in and MFA, select **Authentication → Microsoft Entra / Microsoft 365**.
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
[SSH and Git repositories](ssh.md).

### Included command-line tools

Alongside Git, SSH, Python and Node.js, development containers include:

- Downloads and networking: `curl`, `wget`, `ping`, `ip`, `ss`, `getent`, `dig`, `nslookup`, `nc`.
- Text and files: `jq`, `less`, `nano`, `vi`, `file`, `ripgrep`, `rsync` and the standard shell utilities.
- Archives: `tar`, `gzip`, `zip`, `unzip`, `bzip2`, `xz`.

Restricted mode forwards allowed HTTP/HTTPS destinations through the gateway;
external ICMP (`ping`) and direct DNS queries remain blocked. Use `curl` against
an allowed endpoint to check connectivity in that mode.

## See and interact with the agent’s browser

Enable **Browser** when creating the sandbox, then open it normally. Ask Pi or
Pendant to show its browser. Its local link opens the live browser window,
including the tab bar and popup windows. Type, click, navigate and switch tabs
normally. When you have finished, tell the agent to continue; it keeps the same
browser state.

Use **Observe** to stop sending mouse and keyboard input, **Paste text** or
**Copy text** for explicit clipboard transfers, and **Reconnect** after a dropped
connection. Small windows scale the desktop; larger windows resize it.
Manual sign-ins are not saved automatically.

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
