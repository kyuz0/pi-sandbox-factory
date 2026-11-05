## Optional Betterwright browser

Use the native `browser` tool for Playwright JavaScript, page interaction and
screenshots. Betterwright, Bun, BetterChromium, Linux libraries, fonts and FFmpeg
are already installed. Do not download a browser or start a separate agent.
Browser calls follow the selected Pi approval policy.
Ad-blocking rules are seeded from the image's build-time snapshot.

The browser is headless inside this devcontainer. Its local CDP connection is
private to the container and is not published on the host. The outer network
policy applies to browser traffic, including redirects and subresources. In
restricted mode, required website hostnames and ports must be allowed by the
launcher. Do not change the network policy to work around a denied destination.

Browser tabs and cookies persist across calls in this Pi session. Each Pi process
has a separate temporary browser profile, removed on normal session shutdown.
Headed display, host browser attachment and the credential vault are not enabled.
Downloads ask for approval; noninteractive approval fails closed. The standalone
Betterwright CLI uses its own launch settings; use the native Pi tools here so
network configuration and lifecycle are managed correctly.
