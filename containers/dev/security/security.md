Automatic approval and nested execution are installed for every profile.
The reviewer uses the current Pi model and retains explicit denials. Use ordinary
bash for work inside the inner OS sandbox; ordinary commands run without
command-level model review. It allows workspace edits, protects
private home files, and reviews outbound destinations. If required access is
unavailable there, use bash_escalate with the exact command and justification.
That tool reviews one command before executing inside the outer devcontainer;
it cannot execute on the physical host or override the outer network policy.
A denial must not be worked around. A deferral requires the user's decision.

SANDBOX_NETWORK_MODE identifies the outer network: allowlist uses the supplied
HTTP_PROXY/HTTPS_PROXY gateway; unrestricted uses ordinary container networking.
The inner Bash sandbox still reviews network access in either mode. Use inherited
proxy settings inside sandboxed commands. Root-owned configuration lives under
/opt/pi-security/config. Configure the Pi model with /local-models refresh and /model
before asking the reviewer to approve commands.

Subagents are disabled by default. SANDBOX_SUBAGENTS=1 means the user explicitly
enabled delegation through the launcher. Otherwise work in the current agent;
do not start extra Pi processes as a substitute for disabled delegation.
When enabled, delegation uses standard pi-subagents, not pi-sandbox's bundled worker.
Use its assistant role for the parent's tools, skills and context, with the same
review and Bash sandbox policy. Background mode retains ambient extensions.
Specialist roles may declare narrower tools; select those only when that is the
intended task. No extra OS sandbox surrounds the entire Pi child process.

# Goals and scheduled prompts

Every profile includes `pi-goal` and the current-chat integration of
`pi-schedule-prompt`. Start goal mode only when explicitly requested, using
`/goal [--tokens 50k] <objective>` or `create_goal`. `/goal pause`, `/goal resume`,
`/goal status` and `/goal clear` manage it. Goals continue the current session;
they do not require subagents.

Use `schedule_prompt` for a requested future or recurring prompt. For example,
`action: "add", type: "once", schedule: "+5m", prompt: "Review the latest results"`.
Jobs inject a follow-up into the chat that created them, using its current model,
tools and approval rules. A busy agent receives the prompt as queued follow-up
work. Per-job models and independent background agents are unavailable.

`/schedule-prompt` lists this chat's jobs. Append `disable ID`, `enable ID`,
`remove ID` or `cleanup` to manage them. Jobs are saved in
`.pi/schedule-prompts.json`, bound to the originating session. Timers only run
while that Pi session is open; resume the same session to restore its schedules.
Missed one-shot jobs are disabled and recurring runs are not replayed. Never
promise delivery while Pi or the container is stopped. Unsupported unbound or
background-agent jobs are left inactive on disk.
