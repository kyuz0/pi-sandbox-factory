# Extensions

Local AI Sandboxes installs extensions from their repositories:

| Extension | Repository |
| --- | --- |
| Local model discovery | [pi-local-model-manager](https://github.com/kyuz0/pi-local-model-manager) |
| Codex and Antigravity advisors | [pi-advisor](https://github.com/kyuz0/pi-advisor) |
| Automatic approval, inner sandbox and escalation | [pi-packages](https://github.com/kyuz0/pi-packages) |

[extensions.lock.json](../containers/dev/extensions.lock.json) pins discovery and advisor revisions. The manager downloads them over HTTPS and passes exported source files to the image builder. Downloaded revisions are cached under `~/.cache/local-ai-sandboxes/extensions`.

The security packages use the commit and archive checksum in [sources.json](../containers/dev/security/sources.json). Updating a pin and rebuilding installs that revision. Existing containers keep their installed version until recreated.

Fixes and unit tests belong in the extension repositories. This repository manages container lifecycle, network rules, credentials and integration tests.
