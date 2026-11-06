# Profiles

A profile defines the tools and instructions inside a sandbox. Model providers
are chosen separately, so the same profile can use local or hosted models.

## Install and update

```sh
pi-sandbox-factory profile add reporting ./examples/profile
pi-sandbox-factory profile list
pi-sandbox-factory profile show reporting
pi-sandbox-factory create reports --profile reporting --workspace /absolute/path/to/reports \
  --local-model-ports 8000 --allow-domain local-model.internal:8000 --start
```

Replace the folder with a Git HTTPS or SSH URL to install from a repository.
For a repository containing several plugins, select the folder:

```sh
pi-sandbox-factory profile add reporting git@git.example.com:team/plugins.git --subdir reporting
```

Updates reuse that folder. Only its files become the package's build inputs.
The TUI's **Packages** screen has a matching plugin-subfolder field.
Use `--ref TAG_OR_COMMIT` to pin it. Local Git repositories install their committed
files; commit edits before updating. A plain folder installs its current files.

```sh
pi-sandbox-factory profile update reporting
pi-sandbox-factory recreate reports --profile reporting
```

Update fetches the selected branch or ref. Recreate builds the updated profile
before stopping the old containers, then preserves the workspace and private
home. Close the editor first. Updating a pinned commit keeps that commit.

`pi-sandbox-factory profile remove reporting` removes the registration. It does not delete
saved sandboxes or their snapshots. Existing sandboxes can still start and build.
**Packages** provides the same install, update and remove operations in the TUI.

## Write a profile

Copy [examples/profile](../examples/profile) into a new repository. It contains:

| File | Purpose |
| --- | --- |
| `profile.json` | `version: 1`, a lowercase `name`, and a short `description`. |
| `Dockerfile` | Extends `ARG BASE_IMAGE` / `FROM ${BASE_IMAGE}`; finishes as `USER node`. |
| `profile.md` | Instructions for the agent, copied to `/opt/sandbox/profile.md`. |
| `check.py` | Optional tool checks, copied to `/opt/sandbox/profile-check.py`. |
| `resources.json` | Skills, prompts and extensions registered with Pi. |

Install dependencies during the image build. Put profile resources under `/opt`
and copy `resources.json` to `/opt/sandbox/resources.json`, for example:

```json
{"skills":["/opt/reporting"],"prompts":[],"extensions":[]}
```

Skills are folders containing `SKILL.md`. Extensions are Pi extension files or
folders. Prompts are Pi prompt files or folders. They must exist in the built
image. Pi and Pendant read the same registrations. Replacing a profile removes
its old launcher-managed registrations while preserving user-added resources.

If the tools live in another repository, add `git_source` and optionally `git_ref`
to `profile.json`. Installation exports that repository and its submodules into
`source/`, with the dependency commit recorded in the registry. Reserve that directory
for the dependency; use `COPY source/ ...` in the Dockerfile. Git credentials and
`.git` directories are excluded from the image inputs.

Keep service-specific setup in the profile's README and agent instructions.
Use `pi-sandbox-factory exec NAME -- COMMAND ...` to configure a tool inside its sandbox;
add required destinations through **Settings → Network** first.

## Check it

Install the example, create a disposable sandbox and run:

```sh
pi-sandbox-factory check reports --allowed-url http://local-model.internal:8000/v1/models
```

The endpoint must be running and allowed. This checks the container boundaries,
common tools and your `check.py`. Open Pi/Pendant and confirm the skill loads.
Delete the disposable sandbox afterward; its workspace is retained.
