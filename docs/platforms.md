# Windows and macOS

The manager runs in WSL2 on Windows and natively on macOS with Podman Machine.
Both run the same Linux containers as the Linux installation. Apple Silicon has
been tested on an M1 with macOS 27 and Podman 6.1.4: container creation, Pi/Pendant,
browser tools, editor authentication, network isolation and folder permissions.
Windows hardware validation is pending. See [platform checks](../TESTING.md#platform-checks).

## Windows

Install Ubuntu 26.04 in WSL2 from PowerShell:

```powershell
wsl --install Ubuntu-26.04
```

Then, inside Ubuntu:

```sh
sudo apt update
sudo apt install podman passt uidmap git pipx
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
mkdir -p ~/Projects
pi-sandbox-factory
```

Open a new Ubuntu terminal if the command is not found. Keep projects under
`~/Projects` for Linux filesystem permissions and performance. You can select
individual Windows project folders through `/mnt/c/...`, or paste a `C:\...` path.
Their mount permissions are checked before launch. Changes made by Windows apps
may not trigger Linux file watchers; keep projects in WSL when using watch builds.
Install and run Linux Podman inside this distribution; a separate Windows Podman
Machine is not needed. The browser editor opens in your Windows browser. Pi CLI
runs in the WSL terminal.

**Connect to models on this host** refers to WSL. Run the model there, or create
its SSH tunnel there, for example `ssh -N -L 8000:localhost:8000 MODEL_HOST`.
For a model running directly on Windows, Windows 11 mirrored networking lets WSL
reach Windows through localhost. Add this to `%UserProfile%\.wslconfig`, then run
`wsl --shutdown` from PowerShell and reopen Ubuntu:

```ini
[wsl2]
networkingMode=mirrored
```

This restarts all WSL distributions. The manager does not change Windows networking
or firewall settings. See [Microsoft’s WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking)
and [Ubuntu’s installation guide](https://ubuntu.com/wsl/docs/latest/howto/install-ubuntu-wsl2/).

## macOS

You need an Apple Silicon Mac with macOS 15 or newer, [Homebrew](https://docs.brew.sh/Installation),
Podman 5.6 or newer, Git and pipx. Homebrew installs Python with pipx. Safari works
with the browser editor; installing desktop VS Code is optional.

The tested setup uses a 16 GB M1 Mac with four CPU cores and 8 GB RAM assigned to
Podman Machine. This allocation is for the development containers; local model
inference needs additional memory.

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
opens automatically. Pi and Pendant are installed inside the container.

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
OpenRouter or a custom endpoint, follow [model setup](providers.md#openrouter-and-other-built-in-services).
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
