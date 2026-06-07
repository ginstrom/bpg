# CLI: bpg marketplace

```yaml
doc_metadata:
  topic: cli_marketplace
  version: 1
  summary: Export, validate, and sync node manifests to the bpg-marketplace registry.
```

## Summary

`bpg marketplace` commands help node authors publish installable packages to the
[bpg-marketplace](https://github.com/ginstrom/bpg-marketplace) registry. Commands
discover installed nodes via the `bpg.nodes` entry-point group and map each
`NodeManifest` to a marketplace artifact.

## When to use

- **export** — generate local artifact JSON before a release.
- **validate** — check artifacts against the framework schema and domain rules.
- **sync** — write registry entries into a local clone of
  [bpg-marketplace](https://github.com/ginstrom/bpg-marketplace).

## export

Export installed node manifests as marketplace-ready artifacts.

```bash
# Write artifacts to a directory
uv run bpg marketplace export --output-dir marketplace-artifacts

# Validate without writing files
uv run bpg marketplace export --dry-run
```

Artifacts are written to `nodes/<package_id>/<node_id>.json` under the output
directory.

## validate

Validate artifact JSON files in a directory.

```bash
uv run bpg marketplace validate marketplace-artifacts
```

Exits with an error if any file fails schema or domain validation (duplicate node
IDs, version mismatches, invalid install specs).

## sync

Sync installed node manifests to the
[bpg-marketplace](https://github.com/ginstrom/bpg-marketplace) registry format.

```bash
# Default: writes to ../bpg-marketplace/registry/nodes/
uv run bpg marketplace sync

# Custom marketplace clone path
uv run bpg marketplace sync --marketplace-dir /path/to/bpg-marketplace

# Preview entries without writing
uv run bpg marketplace sync --dry-run
```

### Options

| Flag | Default | Description |
| --- | --- | --- |
| `--marketplace-dir` / `-m` | `../bpg-marketplace` | Path to the [bpg-marketplace](https://github.com/ginstrom/bpg-marketplace) repository root |
| `--source-repo` | `https://github.com/ginstrom/bpg` | Source repository URL for first-party packages |
| `--trust-level` | `blessed` | Trust level (`community`, `verified`, `blessed`) |
| `--rebuild-index` / `--no-rebuild-index` | rebuild | Rebuild marketplace indexes after writing |
| `--dry-run` | off | Print entries without writing files |

After syncing, commit and push changes in the marketplace repository.

## Related pages

- [Marketplace overview](../marketplace/index.md)
- [Release and Versioning](../reference/release_versioning.md)
- [Package Ownership](../reference/package_ownership.md)
