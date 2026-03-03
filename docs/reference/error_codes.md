# Error Codes Reference

```yaml
doc_metadata:
  topic: error_codes
  version: 1
  summary: Compiler diagnostics include stable codes, paths, and suggested patch-style repairs.
```

## Summary
`bpg doctor` and `bpg plan --json-errors` return machine-readable diagnostics with `error_code`, `path`, `message`, and optional fix guidance.

## When to use
Use this page when building repair loops for agents and CI diagnostics.

## Core idea
Treat diagnostics as data. Parse and repair deterministically.

## Example
```json
{
  "error_code": "E_TYPES_REQUIRED",
  "path": "$.types",
  "message": "Process must declare at least one type definition",
  "fix": "Add a non-empty `types` section with at least one named type definition.",
  "example_patch": [
    {"op": "add", "path": "$.types", "value": {"RequiredType": {"ok": "bool"}}}
  ],
  "schema_excerpt": {"types": {"<TypeName>": {"field_name": "string"}}},
  "severity": "error"
}
```

## Common mistakes
- Treating `message` as free-form text only and ignoring `path` + `example_patch`.
- Building repair logic tied to wording instead of `error_code`.

## Related pages
- [Doctor CLI](../cli/doctor.md)
- [Debug Validation Errors Guide](../guides/debug_validation_errors.md)
- [Repair Strategies](../ai/repair_strategies.md)
