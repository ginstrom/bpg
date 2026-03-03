# BPG Wrapper Examples

These examples demonstrate node wrappers that run in dry-run mode, locally, and in Docker packages.

## 1) Parse -> Sum -> Email

- Process: `examples/wrappers/parse-sum-email/process.bpg.yaml`
- Input: `examples/wrappers/parse-sum-email/input.yaml`

Local (no package):

```bash
uv run bpg apply examples/wrappers/parse-sum-email/process.bpg.yaml
uv run bpg run sample-parse-sum-email --input examples/wrappers/parse-sum-email/input.yaml
uv run bpg status --process sample-parse-sum-email
```

Package + Docker:

```bash
uv run bpg package examples/wrappers/parse-sum-email/process.bpg.yaml --output-dir .bpg/package/sample-parse-sum-email --force
uv run bpg up examples/wrappers/parse-sum-email/process.bpg.yaml --local-dir .bpg/local/sample-parse-sum-email --force
uv run bpg logs --local-dir .bpg/local/sample-parse-sum-email
uv run bpg down --local-dir .bpg/local/sample-parse-sum-email
```

## 2) Web Search -> Email

- Process: `examples/wrappers/search-email/process.bpg.yaml`
- Input: `examples/wrappers/search-email/input.yaml`

Local (no package):

```bash
uv run bpg apply examples/wrappers/search-email/process.bpg.yaml
uv run bpg run sample-search-email --input examples/wrappers/search-email/input.yaml
uv run bpg status --process sample-search-email
```

Package + Docker:

```bash
uv run bpg package examples/wrappers/search-email/process.bpg.yaml --output-dir .bpg/package/sample-search-email --force
uv run bpg up examples/wrappers/search-email/process.bpg.yaml --local-dir .bpg/local/sample-search-email --force
uv run bpg logs --local-dir .bpg/local/sample-search-email
uv run bpg down --local-dir .bpg/local/sample-search-email
```

## Notes

- Trigger nodes are pass-through in this runtime, so each sample uses an explicit `ingest` trigger node and then routes into the first executable wrapper node.
- Both examples set `dry_run: true` in node config for `tool.web_search` and `notify.email`.
- You can switch to live integrations by changing `dry_run: false` and providing required env vars.
