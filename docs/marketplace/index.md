# BPG Marketplace

```yaml
doc_metadata:
  topic: marketplace
  version: 1
  summary: Node package registry, publishing workflow, and first-party packages.
```

## Summary

The [bpg-marketplace](https://github.com/ginstrom/bpg-marketplace) repository is the
public registry for installable BPG node packages. It indexes node manifests published
from this framework and from third-party authors.

Runtime audit capture and tracing are framework concerns. Marketplace packages are
optional extensions — install them when you need additional node types or post-run
compliance helpers.

## First-party packages

These packages ship from the BPG workspace and are synced to the marketplace registry
with `trust.level: blessed`:

| Package | Package ID | Nodes |
| --- | --- | --- |
| `bpg-nodes-core` | `bpg.nodes.core@v1` | 12 |
| `bpg-nodes-ai` | `bpg.nodes.ai@v1` | 5 |
| `bpg-nodes-human` | `bpg.nodes.human@v1` | 2 |
| `bpg-nodes-search` | `bpg.nodes.search@v1` | 4 |
| `bpg-nodes-comm` | `bpg.nodes.comm@v1` | 5 |
| `bpg-nodes-audit` | `bpg.nodes.audit@v1` | 6 |

Install a package in your project:

```bash
uv add bpg-nodes-core
```

Browse the full registry at [ginstrom/bpg-marketplace](https://github.com/ginstrom/bpg-marketplace).

## Publishing workflow

Node authors export manifests from installed packages, validate them, and sync entries
to the marketplace repository.

```bash
# Export artifacts from installed bpg.nodes entry points
uv run bpg marketplace export --output-dir marketplace-artifacts

# Validate exported JSON before publishing
uv run bpg marketplace validate marketplace-artifacts

# Write registry entries to a local clone of bpg-marketplace
git clone https://github.com/ginstrom/bpg-marketplace.git ../bpg-marketplace
uv run bpg marketplace sync --marketplace-dir ../bpg-marketplace
```

The `sync` command writes per-package JSON entries under
`registry/nodes/` in the [bpg-marketplace](https://github.com/ginstrom/bpg-marketplace)
repo and optionally rebuilds the generated index. See [CLI: marketplace](../cli/marketplace.md)
for all options.

After syncing, commit and push changes in the marketplace repository to publish.

## Optional audit helpers

The `bpg-nodes-audit` package provides post-run compliance and reporting nodes. These
read from the runtime Postgres audit ledger and must not replace mandatory runtime
capture. See [Audit Helper Nodes](audit-helper-nodes.md).

## Related pages

- [CLI: marketplace](../cli/marketplace.md)
- [Release and Versioning](../reference/release_versioning.md)
- [Package Ownership](../reference/package_ownership.md)
- [Audit Helper Nodes](audit-helper-nodes.md)
- [Traceability and Auditability Design](../design/traceability-and-auditability.md)
