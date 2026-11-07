# Providers

A provider connects Pi to a model service and configures the models it can use.
You choose providers independently of the profile, so the same working environment
can use local models or a hosted service. The built-in `local` provider discovers
models on selected host ports using Pi Local Model Manager.

Provider packages can also include a Pi extension to refresh the model list during
a conversation.

## Hosted services

For OpenRouter, Together, Azure/Foundry and AWS Bedrock, use **Settings → Models →
Connect provider…**, or **Model services and providers** during creation. Factory
keeps their keys in a separate inference container and configures Pi/Pendant for you.
See [hosted model setup](hosted-models.md) for deployment names and model selection.

For another service, a provider package can declare its API routes and keep the
same credential isolation. The adapter discovers models through a local proxy.
Pendant's **Sign in → Custom** also supports manual endpoints, but credentials
entered there live in the development container, and the endpoint must be allowed
under **Settings → Network**.

## Install and select

```sh
pi-sandbox-factory provider add company git@git.example.com:team/company-models.git
pi-sandbox-factory provider list
pi-sandbox-factory provider show company
```

For a provider in a shared plugin repository, add `--subdir FOLDER` when
installing. Updates retain the selected folder and ref. The TUI's **Packages**
screen exposes the same setting.

In **Configuration → Model services and providers**, enable the package and fill in
its non-secret settings. Any declared development-container destinations are added to the form’s
allowlist. Inference routes use the separate companion. Apply rebuilds the sandbox; it preserves the workspace and private home.
Then use **Settings → Models** to check, preview, refresh or enter a credential.

For the CLI, put settings in a JSON file:

```json
{"local":{},"company":{"model":"your-model-id"}}
```

```sh
pi-sandbox-factory create project --workspace /absolute/path/to/project \
  --providers-file providers.json --local-model-ports 8000 \
  --allow-domain local-model.internal:8000 --start
pi-sandbox-factory configure project --provider company --key
pi-sandbox-factory configure project --provider company --preview
pi-sandbox-factory configure project --provider company --status
```

`--key` prompts without echo. `--key-stdin` accepts a key from a credential tool.
With an `inference` declaration, keys pass over stdin into the companion and never
reach the adapter. Without it, the adapter receives the key and owns its storage
inside the development container.

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
- Optional `network`: fixed `host:port` destinations for the development container.
- Optional `inference`: an HTTPS origin, API base path, authentication and allowed operations.
- Optional `extensions` and `skills`: paths relative to the package.
- Optional `git_source` and `git_ref`: another repository exported into `source/`.

The entry exports:

```js
export async function run({action, agentDir, settings, secret, endpoint}) {
  return {state: 'ready', message: 'Configured the requested model.'};
}
```

`action` is `status`, `preview` or `refresh`. Text defaults are merged with saved
settings. For isolated inference, `endpoint` is the local proxy URL and `secret` is a harmless
placeholder on every call. Use them for discovery and saved Pi model configuration.
Other adapters receive `secret` only during credential entry. Return one of
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

## Declare an isolated API

The [example provider](../examples/provider/provider.json) declares:

```json
"inference": {
  "origin": "https://models.example.com",
  "basePath": "/v1",
  "auth": {"type": "bearer"},
  "operations": [
    {"method": "GET", "path": "/v1/models"},
    {"method": "POST", "path": "/v1/chat/completions"}
  ]
}
```

Replace the origin with your service. Paths are exact; declare required query values
as `"query": {"model_type": ["ALL_TEXT"]}`. Header authentication uses
`{"type":"header","header":"api-key"}` or `x-api-key`. The base path tells the
adapter where the API begins; it does not grant additional routes. Factory checks
all routes before starting or replacing the companion.

An in-session extension must reuse the saved proxy endpoint and placeholder.
Credential replacement belongs in Factory's **Settings → Models → Configure
credentials**, not an agent-side key prompt. The runnable example preserves unrelated
models and checks the service catalogue before saving.
