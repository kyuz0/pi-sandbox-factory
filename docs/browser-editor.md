# Browser editor

The browser editor runs Pendant and its Node extensions inside the sandbox.
It is the default with rootless Podman on Linux, Windows through WSL2, and macOS
through Podman Machine. Pi CLI and host VS Code remain available through **Open with…**.
It supports amd64 and arm64 containers; see [platform setup](platforms.md).

## Open a sandbox

Run `pi-sandbox-factory`, choose **New sandbox**, select your project folder and
model connection, then **Create and start**. The browser opens automatically unless
you clear **Open selected editor after creation**. The first launch downloads a
pinned code-server release for the container’s architecture into the existing development container.

The selected workspace opens trusted, in dark mode, with Pendant in the right
secondary sidebar. Select your model and start a conversation.
Files in `/workspace` are your project files; additional mounts appear under `/mnt`.

Closing the tab or manager leaves the editor running. **Open in browser** returns
to it. **Actions → Stop browser editor** stops the editor and its terminals,
active Pendant runs and scheduled prompts. Pi CLI sessions remain independent.
Stopping the sandbox stops both clients.

## Connection settings

During creation, expand **Editor → Browser connection**. For a saved sandbox,
use **Settings → Editor → Browser connection**.

- **Listen address:** empty chooses a separate local-only address for each sandbox.
  Enter a specific IP address and enable a password to use a custom address.
- **Port:** empty chooses an available port and remembers it. Enter a port to fix it.
- **Require a password:** off by default. Enter a password or choose **Generate**;
  **Show password** lets you copy it. Only its hash is saved.

Changing settings stops a running editor. Use **Open** to launch it again.
Creating from another sandbox copies the editor choice; connection addresses and
passwords start fresh.

To connect from another computer, enter the host's interface IP, enable a password
and supply an HTTPS certificate and private key. These fields appear when the
address is non-local. The certificate must be trusted by the connecting browser
and cover that IP. Pendant's webviews require a secure browser context. The key
stays on the host and must have permissions `0600`; encrypted keys are unsupported.

## Choose a client

**Settings → Editor** changes the default client. **Open with…** selects a client
for one launch. Use Pi CLI alongside either editor.

A sandbox used in the browser cannot subsequently attach to host VS Code: that
would give its installed extensions a bridge back to the host client. Create a
separate sandbox for host VS Code. A running desktop VS Code server also prevents
browser-editor startup.

## Command line

```sh
pi-sandbox-factory open NAME
pi-sandbox-factory open NAME --editor pi
pi-sandbox-factory open NAME --editor desktop
pi-sandbox-factory browser-editor NAME --background
pi-sandbox-factory browser-editor NAME --stop
```

`open` uses the saved client. The `browser-editor` command without `--background`
runs in the foreground; Ctrl+C stops it. `--no-open` prints the address without
opening a tab.

## Access boundaries

The editor backend, Pendant and its tools can access the selected workspace,
additional mounts and container home. Container mounts enforce read-only folders.
Do not mount a directory containing secrets that extensions should not read.

Browser extensions run in the browser's web worker environment. They have no
unrestricted host filesystem or local terminal. Explicit browser file grants,
clipboard permissions and uploads can expose data; use a separate browser profile
and grant only what you intend to share. The launcher checks Host and Origin on
HTTP and WebSocket requests. Local access is passwordless by default; enable a password on a shared computer. With a password
enabled, code-server authenticates both HTTP and WebSocket sessions.

The container network policy controls backend traffic. Browser-side requests,
including extension gallery requests, use the host browser's network.

[Developer checks](../TESTING.md#browser-editor) cover Pendant, hostile
extension probes, login protection and session cleanup.

## References

- [VS Code execution location and client resources](https://code.visualstudio.com/api/advanced-topics/remote-extensions#execution-location-and-access-to-client-resources)
- [code-server architecture and differences](https://coder.com/docs/code-server/FAQ)
- [Browser filesystem access](https://developer.mozilla.org/en-US/docs/Web/API/File_System_API)
