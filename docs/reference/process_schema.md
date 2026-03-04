# Process Schema Reference

```yaml
doc_metadata:
  topic: process_schema
  version: 1
  summary: Canonical top-level schema for BPG process definitions.
```

## Summary
A process spec defines metadata, types, node types, nodes, trigger, edges, and optional output/policy/artifacts sections.

## When to use
Use this page when authoring or validating full process files and when building generator prompts.

## Core idea
Keep one canonical YAML shape. Avoid equivalent alternate representations.

## Example
```json
{
  "type": "object",
  "required": ["types", "node_types", "nodes", "trigger", "edges"],
  "properties": {
    "metadata": {"type": "object"},
    "imports": {"type": "array", "items": {"type": "string"}},
    "types": {"type": "object"},
    "node_types": {"type": "object"},
    "nodes": {"type": "object"},
    "trigger": {"type": "string"},
    "edges": {"type": "array"},
    "output": {"type": "string"},
    "artifacts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "from", "format"],
        "properties": {
          "name": {"type": "string"},
          "from": {"type": "string"},
          "format": {"type": "string", "enum": ["json", "jsonl", "csv"]},
          "path": {"type": "string"}
        },
        "additionalProperties": false
      }
    },
    "policy": {"type": "object"}
  },
  "additionalProperties": false
}
```

## Artifact semantics
- Artifacts are materialized at run completion.
- Default location is `.bpg-state/runs/<run_id>/artifacts/`.
- `path` supports templating with `{{run_id}}`, `{{process_name}}`, `{{artifact_name}}`.

## Common mistakes
- Omitting `types` entirely (fails with `E_TYPES_REQUIRED`).
- Using an import registry file as a runnable process.

## Related pages
- [Node Schema](node_schema.md)
- [Edge Schema](edge_schema.md)
- [Error Codes](error_codes.md)
