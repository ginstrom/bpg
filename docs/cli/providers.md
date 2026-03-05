# CLI: bpg providers

```yaml
doc_metadata:
  topic: cli_providers
  version: 1
  summary: Discover and describe available BPG providers and their capabilities.
```

## Summary
The `bpg providers` command group provides access to the project's provider registry, detailing available execution components.

## When to use
Use during process design to discover available node types, their input/output schemas, and configuration requirements.

## Example
```bash
# List all registered providers
uv run bpg providers list

# List providers in machine-readable JSON
uv run bpg providers list --json

# Describe a specific provider (e.g. mock)
uv run bpg providers describe mock
```

## Subcommands

### `list`
Lists the identifiers of all registered providers.
- `--json`: Emit full registry metadata as JSON.

### `describe`
Prints detailed metadata for a single provider.
- `provider`: Provider ID to describe.
- `--json`: Emit full provider metadata payload.

## Related pages
- [Node Schema](../reference/node_schema.md)
- [Provider Interface Reference](../reference/provider_interface.md)
- [Built-in Providers](../manual/nodes/built-in-providers.md)
