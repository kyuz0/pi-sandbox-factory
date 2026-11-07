## Optional Betterwright browser

Use the native `browser` tool for Playwright JavaScript, page interaction and
screenshots. Betterwright, Bun, Chromium, Linux libraries, fonts and FFmpeg
are already installed. Do not download a browser or start a separate agent.
Browser calls follow the selected Pi approval policy.
Ad-blocking rules are seeded from the image's build-time snapshot.

The browser is headless inside this devcontainer. Its local CDP connection is
private to the container. The launcher provides an authenticated loopback viewer for the user. The outer network
policy applies to browser traffic, including redirects and subresources. In
restricted mode, required website hostnames and ports must be allowed by the
launcher. Do not change the network policy to work around a denied destination.

Browser tabs and cookies persist across calls in this Pi session. Each Pi session
has a separate temporary browser profile, removed on normal session shutdown.
Headed display, host browser attachment and the credential vault are not enabled.
Downloads ask for approval; noninteractive approval fails closed. The standalone
Betterwright CLI uses its own launch settings; use the native Pi tools here so
network configuration and lifecycle are managed correctly.

When the user wants to see or interact with this browser, call `browser_viewer`
and share its link. The link opens the session's tab list; each tab opens the live
DevTools screencast. When a manual action is needed, include the link and the action
in `ask_user_question`, wait for the reply, then continue with the same browser tool.
Reload the tab list to see new tabs. Keep viewer links private: they grant control
of this browser and are recorded in the conversation. If a link stops loading,
reopen the sandbox from the launcher and request a fresh link.
