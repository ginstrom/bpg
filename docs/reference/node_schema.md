# Node Schema Reference

```yaml
doc_metadata:
  topic: node_schema
  version: 1
  summary: Node types define interfaces; nodes bind those interfaces to concrete config.
```

## Summary
`node_types` declare typed contracts and providers; `nodes` instantiate them.

## When to use
Use for provider integration design and enforcing stable in/out contracts.

## Core idea
The node type is the reusable contract. Node instances are deployment-time bindings.

## Example
```yaml
node_types:
  extract@v1:
    in: DocIn
    out: ExtractOut
    provider: mock
    version: v1
    config_schema:
      model: string?

nodes:
  extract:
    type: extract@v1
    config:
      model: sample
    retry:
      max_attempts: 3
      backoff: exponential
      initial_delay: 5s
    on_timeout:
      fallback_result: "default"
    stable_input_fields: ["user_id"]
    unstable_input_fields: ["timestamp"]
```

## Node Instance Properties
- `type`: Versioned node type reference (`name@version`).
- `config`: Concrete configuration values.
- `retry`: Optional retry policy.
- `on_timeout`: Optional fallback output for human nodes that time out.
- `stable_input_fields`: Fields used for idempotency calculation.
- `unstable_input_fields`: Fields excluded from idempotency calculation.

## Retry Policy
- `max_attempts`: Maximum invocation attempts (minimum 1).
- `backoff`: `linear`, `exponential`, or `constant`.
- `initial_delay`: e.g. `5s`.
- `max_delay`: e.g. `60s`.
- `retryable_errors`: List of error codes that trigger retry.

## Common mistakes
- Mismatching `type` references or versions.
- Treating `config_schema` as optional when providers require fields.

## Related pages
- [Provider Interface](provider_interface.md)
- [Type System](type_system.md)
- [Nodes Concept](../concepts/nodes.md)
