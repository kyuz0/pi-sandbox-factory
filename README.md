# Pi Sandbox Factory

Pi Sandbox Factory helps you use the Pi coding agent on your projects inside a
development container. You choose a project folder, create a sandbox from the
terminal interface, then open it in VS Code. The sandbox comes with Pi and
Pendant, the VS Code extension that lets you chat with Pi while you work.

Each sandbox has its own tools, model settings and conversation history. Your
project files stay in the folder you selected. Local model discovery is included,
and you can add other model connections or customize the development tools as
your needs change.

![Pi Sandbox Factory terminal interface](docs/sandboxes.png)

## Install

You need Linux, Python 3.10+, Git, rootless Podman and desktop VS Code with `code`
on your PATH. The launcher installs the Dev Containers extension if needed.
Docker also works, but forwarding a host-loopback model requires rootless Podman.

Install pipx with your distribution's package manager, then:

```sh
pipx ensurepath
pipx install git+https://github.com/kyuz0/pi-sandbox-factory.git
pi-sandbox-factory
```

Open a new terminal after `pipx ensurepath` if the command is not found.
The first sandbox build downloads Pi, Pendant and their dependencies.

The manager checks GitHub for updates in the background. **Upgrade now** runs
`pipx upgrade pi-sandbox-factory` after confirmation and restarts the manager.
You can run the same command in your terminal. Existing sandboxes receive image
updates through **Actions → Update sources and recreate…**.

Choose **New sandbox**, select your project folder and enable the port used by
your model server, usually `8000`. Create it, then choose **Open in VS Code**.
Start the model server separately. If it starts later, use **Settings → Models →
Refresh**. [CLI and everyday use](docs/usage.md).

## Add your own environment

A profile defines the tools and skills installed in a sandbox. A model provider
connects Pi to a model service and configures the available models. You can install
both from separate repositories, so a team can share its setup.

Use **Packages** or install a profile from a Git URL:

```sh
pi-sandbox-factory profile add reporting git@git.example.com:team/reporting.git
pi-sandbox-factory provider add company git@git.example.com:team/company-models.git
```

For repositories containing several plugins, add `--subdir FOLDER` to select one.
The same folder is used by subsequent updates.

Select the profile during creation. Choose providers in **Configuration** and
enter credentials through **Settings → Models**. Git authentication uses your
host account; it is not copied into the sandbox.

A profile or provider contains executable code. Install packages you trust.
Profiles do not grant network access: allowed destinations remain explicit.
Existing sandboxes retain their saved package versions until you update them.

- [Create a profile](docs/profiles.md), with a runnable reporting example.
- [Create a model provider](docs/providers.md), including the adapter contract.
- [Isolation and architecture](docs/architecture.md), [approvals](docs/approvals.md), [SSH](docs/ssh.md), [advisors](docs/advisors.md).
- [Development and tests](TESTING.md), [agent guide](AGENTS.md).
