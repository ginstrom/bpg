## Type System Reference

```yaml
doc_metadata:
  topic: type_system
  version: 1
  summary: BPG uses explicit named types and field-level contracts for graph safety.
```

## Summary
BPG type definitions are named mappings consumed by node contracts and validated at compile time.

## Primitive Types
- `string`: UTF-8 text.
- `number`: Floating point or integer.
- `bool`: `true` or `false`.
- `duration`: Time interval (e.g., `5s`, `2h`).
- `datetime`: ISO 8601 timestamp.
- `object`: Opaque dictionary (escape hatch for unstructured data).

## Complex Types
- `enum(A,B,C)`: Restricted set of string values.
- `list<T>`: Array of elements of type `T`.
- `T?`: Optional field (can be null or omitted).

## Example
```yaml
types:
  InputDoc:
    text: string
    tags: list<string>?
    priority: number

  Classification:
    label: enum(invoice,support,legal)
    confidence: number
    received_at: datetime
```

## Common mistakes
- Using overly generic `object` where strict fields are needed.
- Editing published type shapes without versioning discipline.

## Related pages
- [Process Schema](process_schema.md)
- [Node Schema](node_schema.md)
- [Versioning Concept](../concepts/versioning.md)
