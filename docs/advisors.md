# Advisors

Pi can ask Codex (OpenAI models) or Antigravity (Gemini models) for a second opinion. It sends the question and selected context, receives the reply unchanged, and carries out any suggested work using its own tools and permissions.

## Setup

1. During **New sandbox → Review sandbox**, expand **Advisors** and select Codex and/or Antigravity. For an existing sandbox, use **Settings → Advisors**, select the providers, then **Apply**. This builds the companion and restarts the development container; your workspace and private home are preserved.
2. After creation or setup finishes, select **Back to sandboxes**, then reopen **Settings → Advisors**. Sign-in buttons become available only after the advisor has been added; ticking its checkbox alone does not enable login. Codex uses device login: follow the URL in your browser. Antigravity opens its terminal interface in remote-login mode; complete the displayed browser/code flow yourself. The manager temporarily gives the terminal to the CLI, so credentials are not collected by the form or operation log.
3. Use **Check providers** to check Codex login or display Antigravity's model catalogue and quota. For Antigravity, enter an exact Gemini model ID, its quota group and matching effort, then **Apply** again. You can leave these blank for the initial login; advice requires a configured model.
4. Reopen Pi/Pendant to load the extension. Use `/advisor status`, then ask Pi to consult the advisor. `/advisor usage` shows separate usage; `/advisor cancel` stops an active request. `start` and `resume` retain a conversation reference for follow-up.

Set an optional per-session call limit under **Usage and network**.

The CLI can add providers during creation with `--advisor codex` and/or `--advisor agy`. Sign in afterwards:

```sh
python sandbox.py advisor-login NAME codex
python sandbox.py advisor-login NAME agy
python sandbox.py advisor-check NAME
```

Codex's [device login](https://developers.openai.com/codex/auth/) must be enabled for your account. Antigravity uses its documented [remote login flow and Linux Secret Service](https://antigravity.google/docs/install?tab=cli). The companion has its own keyring; it never mounts your desktop session bus.

## Where things run

```mermaid
flowchart LR
    USER[You in the terminal manager] -->|interactive login| CLI
    subgraph DEV[Development container]
        PI[Pi + Pendant] --> EXT[advisor_ask extension]
        PI --> TOOLS[Local file and shell tools]
    end
    EXT -->|question and selected context over Unix socket| RPC
    subgraph COMP[Advisor companion · no workspace mount]
        RPC[Bounded advisor service] --> CLI[Codex / Antigravity]
        CLI --> HOME[Private credentials and conversation state]
    end
    CLI -->|HTTP proxy over a separate socket| PROXY[Advisor gateway · exact destination allowlist]
    PROXY --> CLOUD[Selected cloud provider]
    RPC -->|reply, usage and conversation reference| EXT
```

The companion has no direct network. Its gateway has a separate allowlist: enabling advisors does not widen the development container's network policy. Provider hosts are supplied as defaults; add exact hosts and ports under **Usage and network** if your account's login route requires others.

Credentials stay in the advisor's private volume. The development container receives only the advisor socket. Provider tools are disabled; Pi carries out suggested work through its own tools and approval rules.

`advisor_ask` has a separate permission rule. Access to the socket permits consultations and consumes provider quota. The service accepts questions and selected context; it rejects arbitrary commands and configuration changes.

Login state survives stopping and rebuilding. Deleting the sandbox removes it. The host account that owns the containers retains access to their storage.
