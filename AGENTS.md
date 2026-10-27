# Development

Keep documentation focused on installation, usage and supported behavior. Do not include private project names, local source paths, development conversations or unpublished provenance in code, tests, assets, documentation or commit messages.

Preserve sandbox ownership checks, persistent state and host workspaces. Network changes must keep the gateway policy and model discovery configuration consistent. Model discovery must not require a running Pi session or prevent the editor from opening when the model server is offline.

Keep the terminal interface compact: Open in VS Code, Settings and Actions for the selected sandbox; New sandbox is separate. Keep maintenance and deletion in Actions, with confirmation for deletion. Preserve the gold theme and small-terminal layout.

Run the relevant Python and Node test suites. Use disposable resources for container tests; never treat fixture replies as live model results.
