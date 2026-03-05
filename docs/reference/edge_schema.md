# Edge Schema Reference

```yaml
doc_metadata:
  topic: edge_schema
  version: 1
  summary: Edges define source, destination, optional condition, and explicit field mappings.
```

## Summary
An edge declares directed flow from one node to another with `with` mapping and optional `when` expression.

## When to use
Use for every data dependency between nodes.

## Core idea
Downstream required inputs must be satisfied explicitly by edge mappings.

## Example
```yaml
edges:
  - from: extract
    to: write_db
    when: extract.out.confidence >= 0.8
    with:
      customer_id: extract.out.customer_id
      payload: extract.out.payload
    timeout: 30s
    on_failure:
      action: route
      to: alert_operator
```

## Edge Properties
- `from`: Source node name.
- `to`: Target node name.
- `when`: Boolean condition expression.
- `with`: Data mapping from source to target.
- `timeout`: Per-edge timeout override.
- `on_failure`: Failure routing configuration.
  - `action`: `route`, `notify`, or `fail`.
  - `to`: Target node for `route` action.
  - `node`: Notification node for `notify` action.

## Common mistakes
- Missing required target fields in `with`.
- Referencing unknown node or output field paths.

## Related pages
- [Error Codes](error_codes.md)
- [Edges Concept](../concepts/edges.md)
- [Debug Validation Errors Guide](../guides/debug_validation_errors.md)
