# Model providers

A provider package configures Pi's shared model catalogue and may supply a Pi
extension for refreshing it within a conversation. It is independent of the tool
profile. The built-in `local` provider scans selected host ports using Pi Local
Model Manager.

## Install and select

```sh
pi-sandbox-factory provider add company git@git.example.com:team/company-models.git
pi-sandbox-factory provider list
pi-sandbox-factory provider show company
```

For a provider in a shared plugin repository, add `--subdir FOLDER` when
installing. Updates retain the selected folder and ref. The TUI's **Packages**
screen exposes the same setting.

In **Configuration → Additional model providers**, enable the package and fill in
its non-secret settings. Required destinations are shown and added to the form's
allowlist. Apply rebuilds the sandbox; it preserves the workspace and private home.
Then use **Settings → Models** to check, preview, refresh or enter a credential.

For the CLI, put settings in a JSON file:

```json
{"local":{},"company":{"endpoint":"https://models.example.com/v1","model":"your-model-id"}}
```

```sh
pi-sandbox-factory create project --workspace /absolute/path/to/project \
  --providers-file providers.json --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --allow-domain models.example.com:443 --start
pi-sandbox-factory configure project --provider company --key
pi-sandbox-factory configure project --provider company --preview
pi-sandbox-factory configure project --provider company --status
```

`--key` prompts without echo. `--key-stdin` accepts a key from a credential tool.
Keys pass over stdin into the container; they are not image build arguments or
launcher settings. The adapter owns credential storage in the private agent home.

Omit `local` to use only other sources; use `{}` to configure no providers. Already
saved model entries and credentials are preserved when a source is disabled.
Local discovery adopts model entries at the selected host ports. Give each
endpoint one provider package to avoid competing catalogue owners.

Reload an open Pi/Pendant session after a launcher refresh, or use the provider's
in-session refresh command.

`provider update NAME` fetches its registered source. **Actions → Update sources
and recreate…** applies installed package updates to an existing sandbox.
`recreate NAME --profile PROFILE` does the same from the CLI. Ordinary starts and
settings changes retain saved versions. Removing a registration leaves existing
sandboxes usable.

## Write an adapter

Copy [examples/provider](../examples/provider). Its manifest declares:

- `version: 1`, `name`, `description`, and a relative `entry` module.
- Optional `settings`: text fields, plus one secret field for the credential.
  Set `network: true` on a text field containing an HTTP(S) API endpoint.
- Optional `network`: fixed `host:port` destinations.
- Optional `extensions` and `skills`: paths relative to the package.
- Optional `git_source` and `git_ref`: another repository exported into `source/`.

The entry exports:

```js
export async function run({action, agentDir, settings, secret}) {
  return {state: 'ready', message: 'Configured the requested model.'};
}
```

`action` is `status`, `preview` or `refresh`. Text defaults are merged with saved
settings. `secret` is supplied only during credential entry. Return one of
`ready`, `offline`, `needs-auth` or `error`, with a useful message that contains no
credentials. Status should describe saved state; preview must not change it.
Refresh writes `${agentDir}/models.json` using Pi's model schema.

Preserve other providers and user customizations. Validate responses before
writing, retain the old catalogue on failure, and replace files atomically.
The runner serializes adapter calls and supplied extension commands using a shared
lock. Use those paths for catalogue changes; background writers must coordinate
with the same lock. Provider extensions load inside Pi/Pendant, never on the host.

The example configures one text-only model. Replace its explicit context/output
limits, input capabilities and API compatibility with your service's documented
values. A model name alone does not establish thinking or image support.

Run `node --test tests/test_provider_runtime.mjs` to exercise the example contract,
then test your adapter against a fixture service and in a disposable sandbox.
