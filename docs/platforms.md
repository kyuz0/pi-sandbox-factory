# Host platforms

## Linux local models

Connecting to a model on the Linux host (including WSL) requires passt/pasta
`2024_08_21.1d6142f` or newer, or a distribution backport providing
`--map-host-loopback`. Factory checks the helper before starting the sandbox.
This requirement does not apply when local-model access is disabled and you use
OpenRouter or another hosted provider.

Check support with `pasta --help 2>&1 | grep -- --map-host-loopback`. On Ubuntu,
try `sudo apt update && sudo apt install --only-upgrade passt`. If the distribution
still supplies an older version, disable **Connect to models on this host** for
hosted-provider use, or install a supported passt package for local models.

[Upstream release](https://passt.top/passt/tag/?h=2024_08_21.1d6142f).

## Windows and macOS

The manager runs in WSL2 on Windows and natively on macOS with Podman Machine.
Both run the same Linux containers as the Linux installation.

## Windows

Use Windows 11 with virtualization enabled. For browser-enabled sandboxes, the
recommended setup is 24 GB RAM and at least 30 GB free on the drive holding Ubuntu.

In **PowerShell as Administrator**:

```powershell
wsl --install Ubuntu-26.04
wsl --update
```

Restart Windows if prompted. Open Ubuntu and create your Linux username and password.

In PowerShell, open `notepad "$env:USERPROFILE\.wslconfig"` and add:

```ini
[general]
instanceIdleTimeout=-1

[wsl2]
memory=12GB
```

This keeps background containers running after you close the terminal and gives
WSL 12 GB RAM. Merge these entries if the file already exists. Run `wsl --shutdown`
from PowerShell, then reopen Ubuntu. See [WSL settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

Inside **Ubuntu**:

```sh
sudo apt update
sudo apt install podman passt uidmap git pipx
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
mkdir -p ~/Projects
```

Reopen Ubuntu, then run `pi-sandbox-factory`. Choose **New sandbox**, a folder
under `~/Projects`, then **Create and start**. The editor opens in your Windows
browser. Pi CLI runs in the Ubuntu terminal. Update with
`pipx upgrade pi-sandbox-factory`.

Use Linux Podman inside Ubuntu; Docker Desktop and Windows Podman Machine are
not required. Projects under `~/Projects` have normal Linux permissions and file
watching. You can also select a Windows project through `/mnt/c/...` or paste a
`C:\...` path; use polling if a build tool needs to detect edits by Windows apps.

For OpenRouter, Azure, Bedrock or Together, use **Settings → Models**; see
[model setup](providers.md#hosted-services).

**Connect to models on this host** refers to WSL. Run the model there, or create
its SSH tunnel there, for example `ssh -N -L 8000:localhost:8000 MODEL_HOST`.
For a model running directly on Windows, Windows 11 mirrored networking lets WSL
reach Windows through localhost. Add `networkingMode=mirrored` to the existing
`[wsl2]` section in `%UserProfile%\.wslconfig`, then run `wsl --shutdown` from
PowerShell and reopen Ubuntu.

This restarts all WSL distributions. See [Microsoft’s WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking)
and [Ubuntu’s installation guide](https://ubuntu.com/wsl/docs/latest/howto/install-ubuntu-wsl2/).

## macOS

You need an Apple Silicon Mac with macOS 15 or newer, [Homebrew](https://docs.brew.sh/Installation),
Podman 5.6 or newer, Git and pipx. Homebrew installs Python with pipx. Safari works
with the browser editor; installing desktop VS Code is optional.

The commands below allocate four CPU cores and 8 GB RAM to Podman Machine.
Allow additional memory for models running on the Mac.

```sh
brew install podman pipx git
podman machine init --cpus 4 --memory 8192 --disk-size 60
podman machine start
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
mkdir -p ~/Projects
```

Open a new Terminal window and run `pi-sandbox-factory`. Choose **New sandbox**,
a project folder under `~/Projects`, then **Create and start**. The browser editor
opens automatically.

If a Podman Machine already exists, skip `machine init`. Use its rootless
connection. Keep workspaces, additional folders and sandbox state under your Mac
home directory, which the default machine shares. See [Podman installation](https://podman.io/docs/installation)
and [machine settings](https://docs.podman.io/en/stable/markdown/podman-machine-init.1.html).

If a build tool watches files edited by Mac applications, enable its polling
option. Changes are visible inside the container, but native file-watch events
may not cross the VM share. See [Node's file-watching caveats](https://nodejs.org/api/fs.html#availability).

After restarting your Mac, run `podman machine start` before opening the manager.
To update Factory, run `pipx upgrade pi-sandbox-factory`.

**Connect to models on this host** reaches model servers on the Mac. For
OpenRouter or a custom endpoint, follow [model setup](providers.md#hosted-services).
Apple Silicon runs native ARM64 containers, including the editor and Chromium.

## Browser access and advisors

On WSL and macOS, each editor gets a separate `sbx-….localhost` name and listens
on `127.0.0.1`. Keep this generated name in the browser address: it separates
sandbox cookies and is checked on every request. Linux retains its individual
`127.x.x.x` addresses. Passwords and HTTPS are configured in **Settings → Editor**.

Use **Settings → Advisors** to sign in inside an advisor container. Host sign-in
copies read the manager’s environment: WSL credentials on Windows, not Windows
application credentials. macOS Claude and Antigravity keychain imports are not
supported; use their sign-in buttons. Codex file-based sign-ins can be copied.
