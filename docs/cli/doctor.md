# CLI: bpg doctor

```yaml
doc_metadata:
  topic: cli_doctor
  version: 1
  summary: Validate specs and emit machine-actionable diagnostics for repair.
```

## Summary
`bpg doctor` checks parse + validation + compile behavior and reports structured errors.

## When to use
Use while authoring specs, in CI, and before plan/apply.

## Core idea
Doctor is the primary self-healing entrypoint for AI-assisted spec development.

## Example
```bash
uv run bpg doctor process.bpg.yaml --json
uv run bpg suggest-fix process.bpg.yaml --json
```

```json
{
  "ok": false,
  "errors": [
    {
      "error_code": "E_TYPES_REQUIRED",
      "path": "$.types",
      "message": "Process must declare at least one type definition"
    }
  ]
}
```

## Common mistakes
- Relying on human-only output and skipping `--json` in automated flows.
- Attempting broad rewrites before applying targeted fixes.

## Related pages
- [Error Codes](../reference/error_codes.md)
- [Repair Strategies](../ai/repair_strategies.md)
- [Debug Validation Errors Guide](../guides/debug_validation_errors.md)
