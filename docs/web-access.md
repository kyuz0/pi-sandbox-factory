# Web search and website access

Enable **Web access** in **New sandbox → Configuration**, or in an existing
sandbox’s **Settings → Configuration**. This installs
[pi-web-access](https://github.com/nicobailon/pi-web-access) and adds `web_search`
and `fetch_content` to Pi and Pendant. Exa works without an API key. You can also
choose keyed Exa, OpenAI, Brave, Tavily or your own SearXNG server. Enter a key in
the same form when needed; a blank field keeps an existing key.

The search service’s endpoints are allowed automatically. Exa uses `mcp.exa.ai`
without a key and `api.exa.ai` with a key; both are included. To let the agent read
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

## Pi and Pendant settings

Both use the sandbox’s `~/.pi/agent/web-search.json`. The manager sets the chosen
service, restricted-network proxy and direct page fetching. It preserves manual
advanced settings across ordinary restarts, but changing managed search settings
replaces the generated configuration. Reload an open Pi/Pendant session after
changing it. See the extension’s [configuration reference](https://github.com/nicobailon/pi-web-access#configuration)
for additional providers. Add their endpoints in **Settings → Network**.

API keys are stored in the sandbox’s private home, not launcher defaults or
command arguments. The coding agent runs as the same user and can read them.
For CLI use, enter the selected service’s key at a masked prompt:

```sh
pi-sandbox-factory web-key my-project
```

Use `--key-stdin` to pipe a key from a secret manager.

Sending an empty value removes that service’s saved key. Environment variables
supported by pi-web-access can also supply keys and may override file settings.
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
  "web_access": {"enabled": true, "service": "exa"},
  "website_groups": ["dev-python", "dev-npmjs"]
}
```

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
