# Pi Sandbox Factory has moved

**[AI Sandbox Factory](https://github.com/kyuz0/ai-sandbox-factory)** supports Pi,
Codex, Claude Code and Antigravity. Visit that repository for the application,
documentation and new releases.

This repository contains the migration launcher for existing installations.

```sh
pipx upgrade pi-sandbox-factory
pi-sandbox-factory
```

Press Enter when prompted. The launcher installs `ai-sandbox-factory` and moves
Factory's default settings, saved sandbox state, chat backups and cache to folders
named `ai-sandbox-factory`. Your project files and saved chats are kept.
Compatibility links at the old paths preserve existing snapshots and container mounts.
User-chosen workspace folders and `--state-dir` locations are not renamed.

After migration, start and update the application with:

```sh
ai-sandbox-factory
pipx upgrade ai-sandbox-factory
```

The old command forwards its arguments to the new application. If the application
is already installed, it is reused. For pip installations, the launcher installs
the new package in the same Python environment. For pipx, it creates the new
application's own environment. Uninstalling this launcher with
`pipx uninstall pi-sandbox-factory` does not uninstall the new application.

For unattended migration, run `pi-sandbox-factory --yes`. Without that flag, a
first launch without a terminal stops with instructions instead of waiting for input.
If both an old folder and its new destination exist, the launcher reports both
paths and changes neither. It never merges or overwrites existing data.

Windows users run Factory inside WSL2. Linux and macOS use their usual home
folder and any configured XDG locations.

## Development

Run `python -m unittest discover -s tests`. For the installer matrix, run
`python tests/integration.py --baseline OLD_CHECKOUT --application NEW_CHECKOUT --output /tmp/factory-migration-check`.
For Linux container preservation, run `python tests/container_migration.py --image LOCALLY_BUILT_FACTORY_IMAGE`.
Successful test installations are removed; logs and synthetic state remain in the output folder. Tests use temporary folders and
synthetic data. Socket tests need execution permissions that allow local sockets.
The application lives entirely in `kyuz0/ai-sandbox-factory`; keep feature code there.
