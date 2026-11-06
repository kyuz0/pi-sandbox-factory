# Slack

Enable **Communications → Slack** when creating a sandbox, or open
**Settings → Communications** to add it later. **Configure…** accepts a bot token
and an optional user token for search. Save the form to install the extension
and apply the configuration. Updating only the tokens preserves running sessions.

Pi and Pendant use the same Slack configuration. Ask Pi to list channels, read a
conversation, find messages or send a reply. The extension also downloads files
and can edit or delete messages sent by its bot. It runs tools when Pi requests
them; incoming messages do not start agent tasks.

## Connect your workspace

1. [Create a Slack app](https://api.slack.com/apps) **From scratch** and choose
   your Slack workspace.
2. In **OAuth & Permissions**, add the bot scopes for the features you need:

   | Feature | Bot scopes |
   |---|---|
   | Public channel list and history | `channels:read`, `channels:history` |
   | Private channel list and history | `groups:read`, `groups:history` |
   | Direct-message history | `im:history` |
   | Download attachments | `files:read` |
   | Send, edit and delete the bot's messages | `chat:write` |

3. For message search, add **User Token Scope → `search:read`**.
4. Choose **Install to Workspace** and authorize the app. Your Slack administrator
   may need to approve it. Reinstall after changing scopes.
5. Copy the **Bot User OAuth Token** (`xoxb-…`) into **Configure… → Bot token**.
   If using search, copy the **User OAuth Token** (`xoxp-…`) into the second field.
6. In Slack, invite the bot to the channels you want it to read. Ask Pi to list
   its channels, then read one by name or channel ID.

Search uses the user token's access, which can be broader than the bot's channel
membership. [Slack's search API](https://docs.slack.dev/reference/methods/search.messages/)
and [message permissions](https://docs.slack.dev/reference/scopes/chat.write/)
describe these scopes.

## Credentials and access

Tokens stay in the sandbox's private home. They are not included in saved defaults,
configuration copies or project files, and are not exported to shell tools.
The inner command sandbox and file-tool rules protect their storage. Disabling
the inner sandbox allows ordinary container processes to read that home.

Leave a token field empty to retain its saved value. **Remove saved token** clears
it. Disabling Slack removes its tools and automatic network destinations while
preserving credentials for later use. To revoke access, remove the tokens in the
form and revoke them in Slack.

Slack tools follow the sandbox's selected approval mode. Automatic approval can
permit a send without a human dialog; choose **Agent → Ask me** if you want to
approve each Slack operation yourself. Omitting `chat:write` makes the Slack app
read-only regardless of approval mode.

Enabling Slack allows HTTPS to `slack.com` and `files.slack.com`. Links to other
websites use your normal network rules. These hosts are accessible to all processes in the sandbox. View the service destinations under
**Settings → Network**.

From a terminal, configure a running sandbox with masked prompts:

```sh
pi-sandbox-factory communication-key NAME
pi-sandbox-factory communication-key NAME --status
```

The integration uses [@dreki-gg/pi-slack](https://github.com/jalbarrang/pi-slack),
pinned to a [fork with private credential-file support](https://github.com/kyuz0/pi-slack).
