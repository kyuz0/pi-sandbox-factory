# Web search and website access

Enable **Web access** in **New sandbox → Configuration**, or in an existing
sandbox’s **Settings → Configuration**. This installs
[pi-web-access](https://github.com/nicobailon/pi-web-access) and adds `web_search`
and `fetch_content` to Pi and Pendant.

**Search mode** starts with **Automatic fallback** and keyless Exa. Add OpenAI,
Brave, Tavily or a SearXNG server with **Add provider**. Exa accepts an optional
API key in its Edit dialog. Automatic mode uses pi-web-access's built-in provider
selection and fallback among your configured providers; adding a provider does
not set its priority. Choose **Only Exa**, **Only Brave**, etc. to restrict searches
to one provider, including requests where the agent names a provider explicitly.

Each row shows whether its key or server URL is configured. Providers missing
required settings are inactive. In an **Only…** mode, other providers stay saved
for later use. **Edit** lets you replace or explicitly remove a key; leaving the
key field empty keeps it. Changing a custom endpoint requires its own key.

Active search providers' endpoints are allowed automatically. Exa includes both
`mcp.exa.ai` for keyless search and `api.exa.ai` for keyed search. To let the agent read
websites directly, select **Network → Website categories** or add individual
`hostname:port` entries. You can change these later in **Settings → Network**
without recreating the development container.

For example, enable Exa and the **Python** category, then ask:

> Find Python’s documentation on list comprehensions and read the relevant page.

Search requests go to Exa. Reading `docs.python.org` goes directly to that host
through the sandbox gateway. Exa can also include text from other sites in its
search response. Hosted page-reader fallbacks are off.

Search and stored search results run without automatic review. Direct page reads
use `fetch_content`, which follows the selected approval mode. Search runs without
background page downloads or summary workflows; Pi uses `fetch_content` when it
needs the full page. Text supplied by the search service remains part of its response.

Restricted networking is the default. With no categories selected, direct access
uses only your individual host allowances and the search service endpoints.
Choosing unrestricted networking removes the category-based destination limits;
fetch approval remains a separate setting.

## Website categories

Developer groups come from
[V2Fly domain-list-community](https://github.com/v2fly/domain-list-community):
Python, npm, Rust, GitHub, Stack Exchange and Read the Docs. Broader categories
come from [UT1 Toulouse](https://dsi.ut-capitole.fr/blacklists/), through its
[public mirror](https://github.com/olbat/ut1-blacklists): news, financial
information, banking and library resources.

Selecting a source trusts its category membership and future updates. The manager
checks selected categories when starting a sandbox or applying network settings,
at most once a day. Updates apply automatically. If a source is unavailable, it
keeps the last available list and reports the failed refresh. A bundled list lets
a first installation work offline.

Categories grant HTTP and HTTPS access, including the listed domains’ subdomains
unless the source specifies an exact hostname. Category grants exclude private
and loopback addresses; explicit host-and-port rules support local model
servers and internal services.

Some groups include user-published content, and UT1’s coverage varies between
topics. Allowed hosts can receive uploads as well as serve downloads. HTTPS rules restrict the
connection’s hostname and port, not individual pages or what the site returns.

## Reuse your configuration

**Save as default web access** saves the current providers, search mode and API
keys for new sandboxes. It updates the same defaults used by the main Defaults
screen. Existing sandboxes keep their settings.

**Copy from sandbox…** loads another sandbox's web settings into the form.
**Include search API keys** is selected initially when the source is running.
A stopped sandbox can supply its settings; start it first if you want its keys.
In an existing target sandbox, leaving this unchecked keeps that target's keys
for matching providers and endpoints. In a new sandbox, it copies no keys.
Review the provider rows, then apply the settings normally.

Reusable keys are stored separately in
`~/.config/pi-sandbox-factory/web-access-keys.json` with owner-only permissions
(or under `XDG_CONFIG_HOME`). Each new sandbox receives its own copy. Keys are
matched to the provider and endpoint and are never included in `cockpit.json`,
profile packages or exported options. Removing a key and saving defaults again
removes it from the reusable configuration.

## Pi and Pendant settings

Both use the sandbox’s `~/.pi/agent/web-search.json`. The manager sets the chosen
providers, search mode, restricted-network proxy and direct page fetching. It preserves manual
advanced settings across ordinary restarts, but changing managed search settings
replaces the generated configuration. Reload an open Pi/Pendant session after
changing it. See the extension’s [configuration reference](https://github.com/nicobailon/pi-web-access#configuration)
for additional providers. Add their endpoints in **Settings → Network**.

Each sandbox keeps its API keys in its private home. Saving reusable defaults
also stores a private copy on the workstation; keys never appear in command arguments. The coding agent runs as the same user and can read them.
For CLI use, enter a configured provider’s key at a masked prompt:

```sh
pi-sandbox-factory web-key my-project --provider brave
```

Use `--key-stdin` to pipe a key from a secret manager.

Sending an empty value removes that service’s saved key. Environment variables
supported by pi-web-access may override file settings for an allowed provider.
OpenAI supports an optional Responses endpoint URL and search model; SearXNG
requires its server URL. The OpenAI search model is selected independently of
Pi’s coding model.

The optional **Browser · Betterwright** feature handles interactive navigation.
Its requests follow the same network policy. Pi’s instructions explain the
search/read distinction and how to report a blocked destination.

## CLI configuration

Pass an options file during creation or as `options` in an `update` settings file:

```json
{
  "web_access": {"enabled": true, "mode": "auto", "providers": {"exa": {}, "brave": {}}},
  "website_groups": ["dev-python", "dev-npmjs"]
}
```

Save Brave’s key with the command above to activate it. Existing single-provider
settings retain **Only…** mode when updated. Use **Actions → Update sources and
recreate…** before copying keys from a sandbox created with an older version.

Category IDs are `dev-python`, `dev-npmjs`, `dev-rust`, `dev-github`,
`dev-stackexchange`, `dev-readthedocs`, `ut1-press`, `ut1-financial`, `ut1-bank`
and `ut1-liste_bu`. For an existing sandbox, retain your manual rules in a file
and select categories with:

```sh
pi-sandbox-factory network my-project --allowlist hosts.txt \
  --website-groups dev-python ut1-press
```

An empty `--website-groups` removes all category grants. Omitting the flag preserves
the selection. Search-service destinations are managed separately from category selections.
