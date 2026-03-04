# AI Provider Split Migration Notes (2026-03-04)

- New provider IDs: `ai.anthropic`, `ai.openai`, `ai.google`, `ai.ollama`.
- Legacy `ai.llm` remains available as a compatibility alias to `ai.anthropic`.
- Existing `ai.llm` process definitions continue working without changes.
- For new process definitions, prefer vendor-specific provider IDs and remove `vendor` from node config.
