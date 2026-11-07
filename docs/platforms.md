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

Install [Homebrew](https://brew.sh/) if needed, then:

```sh
brew install podman pipx git
podman machine init --cpus 4 --memory 8192
podman machine start
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
pi-sandbox-factory
```

Use Podman 5.6 or newer with a current machine image. Skip initialization if you
already have a machine; select its rootless connection. Keep workspaces, extra
folders and sandbox state under your macOS home, which Podman shares by default.
The manager checks folder visibility, write access and read-only enforcement
before starting the sandbox. It never changes the ownership of your project files.
See [Podman installation](https://podman.io/docs/installation) and
[machine volumes](https://docs.podman.io/en/stable/markdown/podman-machine-init.1.html).

Host-local models run on your Mac; the gateway reaches them through Podman’s
host networking service. Apple Silicon uses native ARM64 containers and code-server.
Agent browsing uses Debian Chromium on ARM64 and BetterChromium on amd64, through
the same Pi browser tools and network gateway.

## Browser access and advisors

On WSL and macOS, each editor gets a separate `sbx-….localhost` name and listens
on `127.0.0.1`. Keep this generated name in the browser address: it separates
sandbox cookies and is checked on every request. Linux retains its individual
`127.x.x.x` addresses. Passwords and HTTPS are configured in **Settings → Editor**.

Use **Settings → Advisors** to sign in inside an advisor container. Host sign-in
copies read the manager’s environment: WSL credentials on Windows, not Windows
application credentials. macOS Claude and Antigravity keychain imports are not
supported; use their sign-in buttons. Codex file-based sign-ins can be copied.
