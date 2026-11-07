# Hosted models

During creation, open **Model services and providers → Connect provider…**.
For an existing sandbox, use **Settings → Models → Connect provider…**.
Save the connection, choose a model, then select **Use as default**. During creation,
model selection opens after the container starts. **Continue** opens your selected
editor if you enabled that option.

| Provider | What to enter | Model selection |
| --- | --- | --- |
| OpenRouter | API key | Refresh loads Pi’s catalogue and applies OpenRouter’s account model list. |
| Together | API key | Choose a catalogue model available to your account. |
| Azure / Foundry | API key and inference endpoint | Select the underlying model, then enter your Azure deployment name. Both native Azure Responses and Foundry Chat Completions models are supported. |
| AWS Bedrock | Region and bearer token, or AWS access key and secret; session token for temporary credentials | Select the exact model/profile ID from the catalogue. For an account-specific inference profile, select its underlying model and enter the profile ID or ARN. |

Pi supplies context limits, output limits, image support and reasoning capabilities.
An Azure deployment name or Bedrock profile ID does not describe those capabilities;
select the underlying model that actually serves it. An ARN must use the configured
AWS region. For a model absent from Pi’s catalogue, use Pendant’s custom-provider
configuration or Pi’s `models.json`, with the model publisher’s metadata.

**Test selected model** sends a short inference request, which the provider may
charge for. Saving a connection and refreshing the catalogue do not send inference
requests. A listed model still needs account access and any required deployment.

## Credential isolation

Factory stores these credentials in a separate inference container. Pi, Pendant
and browser-editor extensions receive a local API endpoint and a placeholder token.
The companion adds the real key, or signs AWS requests, before sending them to the
configured service. Its credential volume is not mounted in the development container.

Factory configures this connection automatically. The development container needs
`pi.dev` for public model metadata; provider API access goes through the companion.
Requests can use only the declared inference and model-listing routes. The companion
replaces authentication headers and refuses redirects.

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
connection credentials from the inference companion. It retains model definitions
and unrelated settings.

Installed provider plugins, including company-specific discovery, remain under
**Settings → Models → Installed provider plugins**. Their setup contract is documented
in [Providers](providers.md).
