# Hosted models

During creation, open **Model services and providers → Connect provider…**.
For an existing sandbox, use **Settings → Models → Connect provider…**.
Save the connection, choose a model, then select **Use as default**. During creation,
model selection opens after the container starts. **Continue** then opens your
selected editor.

| Provider | What to enter | Model selection |
| --- | --- | --- |
| OpenRouter | API key | Refresh loads Pi’s catalogue and applies OpenRouter’s account model list. |
| Together | API key | Choose a catalogue model available to your account. |
| Azure / Foundry | API key and inference endpoint | Select the underlying model, then enter your Azure deployment name. Both native Azure Responses and Foundry Chat Completions models are supported. |
| AWS Bedrock | Region and bearer token, or AWS access key and secret; session token for temporary credentials | Select the exact model/profile ID from the catalogue. For an account-specific inference profile, select its underlying model and enter the profile ID or ARN. |

Pi’s catalogue supplies context limits, output limits, image support and reasoning
settings. For Azure deployments and Bedrock inference profiles, select the underlying
model so these settings match it. Bedrock profile ARNs must use the configured AWS
region. For models absent from the catalogue, use Pendant’s custom-provider form
or Pi’s `models.json`; see [custom providers](providers.md#hosted-services).

**Test selected model** sends a short prompt to check the connection and selected
model before you use it in a chat.

## Credential isolation

Factory stores these credentials in a separate inference container. Pi, Pendant
and browser-editor extensions receive a local API endpoint and a placeholder token.
The companion adds the real key, or signs AWS requests, before sending them to the
configured service.

Factory adds `pi.dev` to the sandbox’s network rules for model metadata. Provider
API requests go through the companion, so you do not need to add their hosts to the
sandbox allowlist. See [architecture](architecture.md#inference-credentials) for the
route and authentication controls.

Code inside the sandbox can use the configured models and consume account quota.
Use provider-side budgets and account permissions to limit that access. Keys entered
manually in Pendant, Pi or workspace files remain readable inside the sandbox; use
Factory's connection form for isolated credentials.

Replacing a key keeps both containers running. Changing endpoints or routes restarts
the inference companion. Reopen Pi/Pendant after changing models or endpoints; an
existing chat retains its selected model.

Use **Connection…** to replace a key or expired AWS session. Leave credential fields
empty to retain saved values; supply all temporary AWS credential fields together.
Changing an Azure origin or AWS region requires credentials again. **Remove** deletes the saved
connection credentials from the companion while retaining model definitions.

Installed provider plugins, including company-specific discovery, remain under
**Settings → Models → Installed provider plugins**. Their setup contract is documented
in [Providers](providers.md).
