# Browser editor prototype

Run Pendant in a browser with the editor server and its Node extensions inside
the sandbox. This avoids attaching a host VS Code process to the workspace.
The prototype is CLI-only; the normal VS Code and Pi CLI workflows are unchanged.

Requires Linux x86_64 and rootless Podman. The first launch downloads a pinned,
checksum-verified code-server release (226 MiB). It uses the existing development
container and gateway, with no additional container.

## Try it

Install the prototype separately from your usual installation:

```sh
git clone --branch codex/browser-editor-prototype \
  https://github.com/kyuz0/pi-sandbox-factory.git pi-browser-editor
cd pi-browser-editor
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p ~/pi-browser-test
.venv/bin/pi-sandbox-factory --state-dir ~/.local/state/pi-browser-editor \
  create browser-test \
  --workspace ~/pi-browser-test --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
.venv/bin/pi-sandbox-factory --state-dir ~/.local/state/pi-browser-editor \
  browser-editor browser-test
```

These commands use separate prototype state. Manage this sandbox through the
branch installation; do not attach it through your regular VS Code launcher.

Start your model server on port 8000 before opening Pendant. Other ports and
providers use the [usual model configuration](usage.md).

1. Open the printed URL in a separate browser profile and enter the printed
   password. Keep the launcher terminal open.
2. The selected workspace opens trusted. The editor starts in dark mode;
   Pendant belongs in the secondary sidebar on the right. Select its tab if needed.
3. In Pendant, select your model and ask: “Create a small HTML page in this folder
   with a button that counts clicks.” Confirm that the files appear in Explorer
   and in `~/pi-browser-test` on the host.
4. Use **Terminal → New Terminal**. Run `pwd`; it should show `/workspace`.
   Configured additional folders are available under `/mnt/<name>`.
5. Press Ctrl+C in the launcher terminal. The browser editor and its terminals
   stop, including active Pendant runs and scheduled prompts; the sandbox stays running. Run the `browser-editor` command again
   and sign in at the new URL. Open Pendant and resume the saved conversation.

Each launch creates a new browser origin and password. The launcher trusts
`/workspace` and its subfolders at that address automatically. Editor settings and
Pi conversations remain in the sandbox's private home. Your chosen theme and sidebar arrangement are preserved.
A sandbox opened this way is marked for browser use: the Factory refuses desktop
VS Code attachment afterward. Use a separate sandbox for the desktop editor so
extensions left in container state cannot regain the desktop client API bridge.
A running desktop VS Code server also prevents browser-editor startup.

To stop the test sandbox:

```sh
.venv/bin/pi-sandbox-factory --state-dir ~/.local/state/pi-browser-editor down browser-test
```

To remove its containers and private state, keeping your project files:

```sh
.venv/bin/pi-sandbox-factory --state-dir ~/.local/state/pi-browser-editor delete browser-test
```

## Access boundaries

The editor backend, Pendant and its tools can access the selected workspace,
additional mounts and container home. Container mounts enforce read-only folders.
Do not mount a directory containing secrets that extensions should not read.

Browser extensions run in the browser's web worker environment. They have no
unrestricted host filesystem or local terminal. Explicit browser file grants,
clipboard permissions and uploads can expose data; use a separate browser profile
and grant only what you intend to share. The launcher binds to loopback and checks
Host and Origin; code-server authenticates HTTP and WebSocket sessions. Other
local users can reach the listener, so keep its password private.

The container network policy applies to backend traffic. Browser-side requests use
the host browser's network, including browser-side extension gallery requests, so this is **not a browser network allowlist**. Container
isolation also depends on the host kernel and runtime; this prototype does not
claim protection against a container or browser escape.

[Developer checks](../TESTING.md#browser-editor-prototype) cover Pendant, hostile
extension probes, login protection and session cleanup.

## References

- [VS Code execution location and client resources](https://code.visualstudio.com/api/advanced-topics/remote-extensions#execution-location-and-access-to-client-resources)
- [code-server architecture and differences](https://coder.com/docs/code-server/FAQ)
- [Browser filesystem access](https://developer.mozilla.org/en-US/docs/Web/API/File_System_API)
