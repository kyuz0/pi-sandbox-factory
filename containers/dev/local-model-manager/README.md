# Pi local model manager

Independent Pi extension for discovering local inference servers and refreshing `models.json`.

This package is installed by the container image. In Pi, run `/local-models preview`, `/local-models refresh`, then `/model`.

Configure host-local ports in the sandbox manager's Settings. The launcher writes `local-model.internal` and those ports to `local-pi-models.json` in the private agent directory, preserving other preferences. Its gateway permits only the configured ports. `/local-models status` reports the active configuration. Changing scan ranges directly in Pi does not broaden the gateway policy.

Thinking defaults follow the detected engine and served model family. Qwen3.8 exposes off/low/medium/xhigh; classic Qwen3 on llama.cpp exposes off/high (on). DwarfStar DeepSeek V4 exposes off/high/max (max requires at least 393,216 context); V4.1 exposes off/low/medium/high/max using named request values. Gufo DeepSeek V4 exposes off/low/high/max. Preview shows the chosen profile and assumptions. Existing custom thinking settings survive refresh; unknown combinations need explicit configuration. Accepted effort names may share the same underlying model behavior.

After updating this package, run `/reload`, `/local-models preview`, and `/local-models refresh`. Select the model, then use Pi's `/thinking` to choose its level. The output allowance still includes thinking tokens.

For an alias or custom engine, add an exact override to `local-pi-models.json`:

```json
{
  "thinkingOverrides": [
    { "endpoint": "http://localhost:8000", "model": "my-model-alias", "profile": "dwarfstar-deepseek41" }
  ]
}
```

Profiles: `dwarfstar-qwen`, `gufo-qwen`, `llama-qwen`, `llama-thinking-toggle`, `dwarfstar-deepseek-v4`, `dwarfstar-deepseek41`, `gufo-deepseek-v4`, `openai-effort`, and `disabled`. An optional `thinkingLevelMap` supplies a custom map; omitted levels become unsupported. Use `disabled` to keep a particular model off-only. Overrides apply only to the exact endpoint/model pair.
