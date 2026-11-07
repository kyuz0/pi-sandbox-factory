# Repository access

Use **Settings → SSH and repositories**. Private keys stay in the SSH companion;
GitHub or GitLab controls what the key can do. Factory holds one key per sandbox.

## Read-only repository

1. Choose **Add repository…**, enter its HTTPS project URL and **Add destination**.
   This supports GitHub, GitLab.com and self-hosted GitLab.
2. Under **Host identity**, select a `known_hosts` file containing that server’s
   verified SSH host key. Choose **Apply**. This restarts the sandbox’s processes.
3. Reopen **SSH and repositories → SSH key** and choose **Generate repository key**.
   Choose **Copy public key**. Generation refuses to replace an existing key;
   use a separate sandbox if this one already holds your account key.
4. In GitHub, open the repository’s **Settings → Deploy keys → Add deploy key**.
   Paste the public key and leave **Allow write access** unchecked.
   In GitLab, use **Settings → Repository → Deploy keys → Add new key** and
   leave **Grant write permissions** unchecked. **Add repository… → Open deploy-key
   settings** opens the appropriate page.
5. In the sandbox, clone through the `repository` alias:

   ```sh
   git clone git@repository:OWNER/PROJECT.git
   ```

The agent can edit and commit locally; pushes are rejected by the server.
GitHub requires a different deploy key for each repository.

If you already have a repository key, use **Import and unlock** instead of
Generate. Keep the source key outside every folder mounted into the sandbox.
Use **Unlock existing key** after the eight-hour expiry; **Show public key**
retrieves the public half of the unlocked key.

For an unknown SSH host, verify its fingerprint against the provider’s published
fingerprints or with your server administrator, then connect from your host
terminal to record it in `known_hosts`. Factory never accepts an unknown key
for you. See [GitHub fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).

## Full SSH access

Configure destinations as above, then **Import and unlock** with your existing
account key. The sandbox gets that account’s Git permissions, including access to
other repositories on the configured server and any protection bypass rights.
For other SSH servers and custom ports, see [SSH setup](ssh.md#ssh-setup).

## Restrict contributions to `pi-*` branches

Use a separate automation account with write access only to the required
repository, then import that account’s SSH key. Configure these rules on the
server before granting the sandbox access. Factory does not verify the rules.

### GitHub

Open **Settings → Rules → Rulesets → New ruleset**. Set each ruleset to **Active**:

| Target | Rules |
| --- | --- |
| All branches, excluding `pi-*` | Restrict creations, updates and deletions. Give bypass only to the human maintainers who need to update these branches. |
| Branches matching `pi-*` | Restrict deletions and block force pushes. |
| All tags | Restrict creations, updates and deletions. Give bypass only to the human maintainers who need to publish tags. |

Never give the automation account a bypass role, team or direct grant. Check
organization rules too. These controls require Pro/Team/Enterprise for private
repositories; public repositories support them on Free.

### GitLab

Under **Settings → Repository → Branch rules**, protect `*`: allow pushes and
merges only by Maintainers. Add `pi-*` with **Allowed to push and merge** set to
Developers + Maintainers, **Allowed to merge** set to Maintainers, and force push
disabled. Give the automation account the Developer role. Protect tags matching
`*` with creation restricted to Maintainers.

GitLab applies the most permissive matching rule, so inspect overlapping branch
rules. Do not add a deploy key to a protected branch’s allowed-push list.

### Check and use

Test with a disposable repository first: push `pi-test`, then confirm that pushes
to `main`, new non-`pi-*` branches, tags, force pushes and branch deletion fail.
The sandbox can change any branch covered by the permitted pattern.

After pushing, ask Pi for a comparison link and PR description. Open the link in
your signed-in browser and create the request:

```text
https://github.com/OWNER/PROJECT/compare/main...pi-feature?expand=1
```

For GitLab, open **Code → Merge requests → New merge request** and select the
source and target branches. Factory does not provide an authenticated PR API to
the agent. Signing into `gh` inside the sandbox would expose that credential.

## CI access

A permitted push can run agent-modified code in CI, including changes to workflow
files and build scripts. For a repository dedicated to agent work, the simplest
setup is to disable Actions/CI until a maintainer reviews the change.

If CI must run, keep secret-bearing jobs behind maintainer approval and prevent
unreviewed code from reaching them. A read-only `GITHUB_TOKEN` does not protect
other secrets. On GitLab, protected `pi-*` branches can receive protected variables;
marking variables protected is insufficient here.

[GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) ·
[GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) ·
[GitLab branch rules](https://docs.gitlab.com/user/project/repository/branches/protection_rules/)
