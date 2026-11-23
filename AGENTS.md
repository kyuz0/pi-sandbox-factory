# Migration launcher

This is a public compatibility repository for `kyuz0/ai-sandbox-factory`.
Keep it limited to installation, safe folder migration and command forwarding.
Preserve the `pi_sandbox_factory` module: already-running old managers relaunch
that module after `pipx upgrade pi-sandbox-factory`.

Never overwrite or merge an existing destination. Keep old paths as compatibility
links so snapshots and container mounts survive. Never rename custom state roots,
project folders, containers, volumes or credential-service identifiers. Show actual
errors and installer output; redact credentials without removing the failure reason.
Test rollback, repeated runs, redirected output, both installation methods, live
editor controls and the old manager's module relaunch before release.
