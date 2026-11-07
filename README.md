# Pi Sandbox Factory

Pi Sandbox Factory runs Pi coding agents in development containers so you can
control which files, commands and network destinations they can access. Select a
project folder, choose your models and create a sandbox from the terminal UI.
Network access is restricted by default; commands needing broader permissions
go through approval and still run inside the container.

The default editor runs in your browser with Pendant, the Pi chat extension.
You can also use Pi CLI or host VS Code. Each sandbox keeps its own tools, model
settings and conversations.

![Pi Sandbox Factory terminal interface](docs/sandboxes.png)

## Install

You need Python 3.10+, Git, pipx and rootless Podman. On Windows, run inside WSL2;
on macOS, use Podman Machine. See [platform setup](docs/platforms.md).
Linux also supports Docker with Pi CLI or host VS Code. Host VS Code needs `code`
on your PATH; the launcher installs Dev Containers if needed.

```sh
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
pi-sandbox-factory
```

Open a new terminal if the command is not found. The first build downloads Pi,
Pendant and their dependencies.

## Create a sandbox

Choose **New sandbox**, select your project folder and configure a model:

- **Local server:** enable its port, usually `8000`. The included
  [Pi Local Model Manager](docs/usage.md#local-models) discovers the running model.
- **OpenRouter, Together, Azure/Foundry or AWS Bedrock:** open **Model services
  and providers → Connect provider…**. Factory keeps credentials outside Pi and
  editor extensions; see [hosted model setup](docs/hosted-models.md).

Choose **Create and start** to open the editor. Use **Settings** to change the
configuration and **Open with…** to launch Pi CLI. See [everyday use](docs/usage.md)
for additional folders, skills and CLI commands.

The manager offers **Upgrade now** when a new version is available. You can also
run `pipx upgrade pi-sandbox-factory`. Update existing sandbox images through
**Actions → Update sources and recreate…**.

## Profiles and providers

A **Profile** supplies tools, skills and agent instructions. A **Provider** connects
Pi to a model service and configures its models. Install either through **Packages**
from a Git repository or local folder, then select it in the sandbox configuration.
Packages contain executable code; install ones you trust.

```sh
pi-sandbox-factory profile add reporting /path/to/reporting-profile
pi-sandbox-factory provider add company git@git.example.com:team/plugins.git --subdir models
```

- [Create a profile](docs/profiles.md) or [provider](docs/providers.md).
- [Browser editor](docs/browser-editor.md), [web search](docs/web-access.md) and [Slack](docs/communications.md).
- [Isolation and architecture](docs/architecture.md), [approvals](docs/approvals.md), [SSH](docs/ssh.md) and [advisors](docs/advisors.md).
- [Development and tests](TESTING.md), [agent guide](AGENTS.md).
