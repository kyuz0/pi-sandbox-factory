## Optional Betterwright browser

Use the native `browser` tool for Playwright JavaScript, page interaction and
screenshots. Betterwright, Bun, Chromium, Linux libraries, fonts and FFmpeg
are already installed. Do not download a browser or start a separate agent.
Enabling browser support allows native `browser` calls without per-action approval.
The selected outer network policy and download controls still apply.
Ad-blocking rules are seeded from the image's build-time snapshot.

The browser is headless inside this devcontainer. Its local CDP connection is
private to the container. The launcher provides an authenticated loopback viewer for the user. The outer network
policy applies to browser traffic, including redirects and subresources. In
restricted mode, required website hostnames and ports must be allowed by the
launcher. Do not change the network policy to work around a denied destination.

Browser tabs and cookies persist across calls in this Pi session. Each Pi session
has a separate temporary browser profile, removed on normal session shutdown.
Headed display and host browser attachment are not enabled.
The credential vault is shared by browser sessions in this sandbox and stored at
`/home/node/.betterwright/vault` in its persistent private home. Use `credentials.list()`
for matching account metadata and `credentials.fill()` or `browser_login` to fill
the current site. These APIs do not return passwords. Do not read the vault files
or request credentials in chat. User-entered logins in the headless viewer are not
saved automatically under the default vault settings.
Downloads ask for approval; noninteractive approval fails closed. The standalone
Betterwright CLI uses its own launch settings; use the native Pi tools here so
network configuration and lifecycle are managed correctly.

When the user wants to see or interact with this browser, call `browser_viewer`
and share its link. The link opens the session's tab list; each tab opens the live
DevTools screencast. When a manual action is needed, include the link and the action
in `ask_user_question` if available, or ask in chat. Wait for the reply, then
continue with the same browser tool.
Reload the tab list to see new tabs. Keep viewer links private: they grant control
of this browser and are recorded in the conversation. If a link stops loading,
reopen the sandbox from the launcher and request a fresh link.
