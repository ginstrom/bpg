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

## Error Code Categories

### Core Codes
- `E_PARSE`: Structural YAML parsing or BPG schema violation.
- `E_VALIDATION`: Semantic validation failure (default).
- `E_TYPES_REQUIRED`: Process missing mandatory `types` section.
- `E_UNKNOWN`: Unhandled internal exception caught at CLI boundary.

### Expression Codes (`when` conditions)
- `E_EXPR_EMPTY`: Expression is empty or contains only whitespace.
- `E_EXPR_TOKEN_UNEXPECTED_CHAR`: Invalid character in expression.
- `E_EXPR_EXPECTED_TOKEN`: Parser expected a specific token kind (e.g. `)`).
- `E_EXPR_UNEXPECTED_TOKEN`: Parser encountered a token in an invalid position.
- `E_EXPR_UNEXPECTED_END`: Expression ended prematurely (e.g. trailing `&&`).
- `E_EXPR_UNKNOWN_FUNCTION`: Reference to a function not in the allowed list (`is_null`, `is_present`).

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
