# Type System Reference

```yaml
doc_metadata:
  topic: type_system
  version: 1
  summary: BPG uses explicit named types and field-level contracts for graph safety.
```

## Summary
BPG type definitions are named mappings consumed by node contracts and validated at compile time.

## When to use
Use while designing node boundaries and edge mappings.

## Core idea
Strong typing turns ambiguous runtime failures into early actionable diagnostics.

## Example
```yaml
types:
  InputDoc:
    text: string
    locale: string?

  Classification:
    label: enum(invoice,support,legal)
    confidence: number
```

## Common mistakes
- Using overly generic `object` where strict fields are needed.
- Editing published type shapes without versioning discipline.

## Related pages
- [Process Schema](process_schema.md)
- [Node Schema](node_schema.md)
- [Versioning Concept](../concepts/versioning.md)
