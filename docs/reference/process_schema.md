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
    "modules": {"type": "object"},
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
    "observability": {
      "type": "object",
      "properties": {
        "tracing": {
          "type": "object",
          "properties": {
            "enabled": {"type": "boolean"},
            "exporter": {"type": "string", "enum": ["otlp", "none"]},
            "endpoint": {"type": "string"},
            "protocol": {"type": "string", "enum": ["grpc", "http", "http/protobuf", "protobuf"]},
            "sample": {"type": "string", "enum": ["always", "never"]},
            "emit_input": {"type": "boolean"},
            "emit_output": {"type": "boolean"},
            "service_name": {"type": "string"}
          },
          "additionalProperties": false
        },
        "audit": {
          "type": "object",
          "properties": {
            "enabled": {"type": "boolean"},
            "sink": {"type": "string", "enum": ["postgres"]},
            "dsn": {"type": "string"},
            "dsn_env": {"type": "string"},
            "failure_policy": {"type": "string", "enum": ["fail_run", "warn", "disabled"]},
            "retention": {"type": "string"},
            "payload_retention": {"type": "string", "enum": ["hash_only", "redacted", "full"]},
            "redaction_policy_id": {"type": "string"},
            "redacted_field_paths": {"type": "array", "items": {"type": "string"}},
            "duplicate_strategy": {"type": "string", "enum": ["reject", "ignore"]},
            "tags": {"type": "object", "additionalProperties": {"type": "string"}}
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    },
    "policy": {"type": "object"}
  },
  "additionalProperties": false
}
```

## Observability Semantics
- `observability.tracing` configures best-effort OpenTelemetry export. Raw input/output attributes remain disabled unless `emit_input` or `emit_output` is explicitly true.
- `observability.audit.enabled: true` configures durable audit capture when paired with a supported sink and a `dsn` or populated `dsn_env`.
- `failure_policy: fail_run` propagates audit sink failures to runtime execution; `warn` logs the failure and continues; `disabled` prevents durable audit sink registration.
- `payload_retention: redacted` is the default for enabled audit capture. `hash_only` stores only audit metadata and the original payload hash. `full` stores the original payload and must be explicitly configured.
- `redacted_field_paths` are dot paths within the event payload. Common sensitive keys such as `password`, `secret`, `token`, and `api_key` are redacted by the default policy.
- Audit `tags`, `redaction_policy_id`, and redacted field paths are copied onto canonical events before durable audit storage.

## Artifact semantics
- Artifacts are materialized at run completion.
- Default location is `.bpg-state/runs/<run_id>/artifacts/`.
- `path` supports templating with `{{run_id}}`, `{{process_name}}`, `{{artifact_name}}`.

## Common mistakes
- Omitting `types` entirely (fails with `E_TYPES_REQUIRED`).
- Using an import registry file as a runnable process.

## Related pages
- [Audit ledger operations](../operations/audit-ledger.md)
- [Tracing operations](../operations/tracing.md)
- [Node Schema](node_schema.md)
- [Edge Schema](edge_schema.md)
- [Error Codes](error_codes.md)
