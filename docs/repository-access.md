# Repository permissions

Factory’s [SSH companion](ssh.md) keeps private keys outside the development
container. The sandbox can still use an unlocked key to authenticate. Its remote
permissions determine which repositories and branches it can change.

## Read-only access

Use a separate deploy key for the repository:

1. Generate the key on your host, outside the workspace:
   `ssh-keygen -t ed25519 -f ~/.ssh/pi-project-readonly`.
2. Add the `.pub` file under **Settings → Deploy keys** on GitHub, or
   **Settings → Repository → Deploy keys** on GitLab. Leave write access disabled.
3. Configure the destination and import the private key through
   **Settings → SSH**, following the [SSH setup](ssh.md#ssh-setup).
4. Clone through its alias, for example:
   `git clone git@github-project:OWNER/REPOSITORY.git`.

The agent can edit files, create local branches and commit locally. The server
rejects pushes. Factory currently holds one imported key per sandbox; GitHub
requires a different deploy key for each repository.

[GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) ·
[GitLab deploy keys](https://docs.gitlab.com/user/project/deploy_keys/)

## Allowing contributions

Use a dedicated automation identity with access only to the intended repository.
Protect branches on the server; an instruction in `AGENTS.md` or a Git hook inside
the workspace can be changed by the agent.

For a policy that permits pushes only to `pi-*` branches:

| Service | Server configuration |
| --- | --- |
| GitHub | An active branch ruleset targeting all branches except `pi-*`, restricting creation, updates and deletion. Grant bypass only to the human maintainers who need it, never the automation identity. Add rules preventing force pushes and deletion on `pi-*`, and restrict creation, updates and deletion of all tags. |
| GitLab | Protect `*` against pushes and merges by the automation identity. Add a `pi-*` rule permitting that identity to push, while retaining human-only merges and disabling force pushes. Protect tags separately. Audit overlapping rules: GitLab usually applies the most permissive match. |

A personal SSH key inherits your permissions, including any bypass rights.
A write-enabled deploy key is not a replacement for this policy. Test the
identity against a disposable repository before granting it production access.

GitHub rulesets cover public repositories on Free, and private repositories on
Pro, Team or Enterprise Cloud. GitLab protected branches are available on all
tiers; selecting individual users or groups can require a paid tier.

[GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) ·
[GitLab protection rules](https://docs.gitlab.com/user/project/repository/branches/protection_rules/)

## Pull requests and API credentials

SSH authenticates Git operations. Creating a GitHub pull request through its API
requires separate API authentication. Factory does not currently provide a
repository API credential companion. Signing into `gh` or placing a token in the
sandbox makes that credential accessible to its processes.

For a credential companion, GitHub Apps provide selected-repository access and
short-lived installation tokens. GitLab project access tokens provide a project
identity with chosen roles and scopes. Neither credential type alone expresses
“push only `pi-*` and open requests, but never merge”. That requires server rules
and restrictions on the API operations exposed to the sandbox.

[GitHub installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation) ·
[GitLab project tokens](https://docs.gitlab.com/user/project/settings/project_access_tokens/)

## CI permissions

A permitted push or pull request can start CI before anything is merged.
Even unchanged workflow files may execute an agent-modified test or build script.
Keep privileged jobs and secrets behind maintainer approval, or disable automation
for the repository used by the agent. On GitLab, a protected `pi-*` branch can
make protected variables available to its branch pipelines; marking a variable
protected does not by itself exclude agent branches.

Forks can separate contribution code from upstream privileges. Check the repository’s
fork workflow policy: GitHub `pull_request_target` jobs can access base-repository
secrets, and GitLab maintainers can run fork pipelines in the parent project.
Do not run unreviewed contribution code in a privileged job.

[GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use) ·
[GitLab fork pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/)
