# Extensions

Pi Sandbox Factory installs extensions from their repositories:

| Extension | Repository |
| --- | --- |
| Local model discovery | [pi-local-model-manager](https://github.com/kyuz0/pi-local-model-manager) |
| Questions and answer forms | [rpiv-ask-user-question](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-ask-user-question) |
| Codex, Antigravity and Claude advisors | [pi-advisor](https://github.com/kyuz0/pi-advisor) |
| Automatic approval, inner sandbox and escalation | [pi-packages](https://github.com/kyuz0/pi-packages) |

[extensions.lock.json](../pi_sandbox_factory/containers/dev/extensions.lock.json) pins discovery, advisor and question-extension revisions. The manager downloads them over HTTPS and passes exported source files to the image builder. Downloaded revisions are cached under `~/.cache/pi-sandbox-factory/extensions`.

The security packages use the commit and archive checksum in [sources.json](../pi_sandbox_factory/containers/dev/security/sources.json). Updating a pin and rebuilding installs that revision. Existing containers keep their installed version until recreated.

Fixes and unit tests belong in the extension repositories. This repository manages container lifecycle, network rules, credentials and integration tests.

## Goals

Enable **Pendant goals** in Configuration to use Pendant’s built-in goals. This feature is available in Pendant, not the standalone Pi CLI.

## Questions in Pi and Pendant

`rpiv-ask-user-question` loads by default. The agent uses `ask_user_question` to request a choice or clarification. Pendant displays native question cards; Pi displays a terminal questionnaire. Both accept option selections and free-text answers. Questions go directly to you, bypassing automatic permission review.

For an existing sandbox, rebuild with its profile selected:

```sh
pi-sandbox-factory recreate NAME --profile base
```

Use the sandbox's current profile instead of `base` if it has a custom profile. This installs the current pinned Pi, Pendant and extensions while retaining the workspace and private home. Close its VS Code window before rebuilding, then reopen it with `pi-sandbox-factory open NAME`.
