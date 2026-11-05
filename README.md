# VS Code Pi Sandbox

Run Pi and Pendant in independent development containers, managed from a terminal.
Each sandbox works on a folder you choose and keeps its own models, sessions and
editor state. Profiles add tools and skills; model providers configure the models
Pi can use. Local model discovery is included by default.

## Install

You need Linux, Python 3.10+, Git, rootless Podman and desktop VS Code with `code`
on your PATH. The launcher installs the Dev Containers extension if needed.
Docker also works, but forwarding a host-loopback model requires rootless Podman.

The distribution and command are both named `vscode-pi-sandbox`. This version
has not been published to PyPI. Install from this checkout:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/vscode-pi-sandbox
```

A built wheel can be installed with `pipx install ./vscode_pi_sandbox-*.whl`.
The first sandbox build downloads Pi, Pendant and their dependencies.

Choose **New sandbox**, select your project folder and enable the port used by
your model server, usually `8000`. Create it, then choose **Open in VS Code**.
Start the model server separately. If it starts later, use **Settings → Models →
Refresh**. [CLI and everyday use](docs/usage.md).

## Add your own environment

Use **Packages** or install a profile from a Git URL:

```sh
vscode-pi-sandbox profile add reporting git@git.example.com:team/reporting.git
vscode-pi-sandbox provider add company git@git.example.com:team/company-models.git
```

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
