# CLI: bpg visualize

```yaml
doc_metadata:
  topic: cli_visualize
  version: 1
  summary: Generate an interactive HTML graph from a process definition.
```

## Summary
`bpg visualize` renders an interactive visualization of the process graph to aid understanding and debugging.

## When to use
Use while designing or reviewing complex processes to see dependencies, routing, and node interactions.

## Core idea
Visualizing the graph helps human developers and AI agents verify that their mental model matches the actual BPG definition.

## Example
```bash
# Basic visualization
uv run bpg visualize process.bpg.yaml

# Open the visualization in the default browser
uv run bpg visualize process.bpg.yaml --open

# Write to a specific directory
uv run bpg visualize process.bpg.yaml --output-dir .bpg/viz/
```

## Options
- `--output-dir`: Where to save the generated HTML (default: `.bpg/viz/`).
- `--open`: Automatically open the generated HTML in the default browser.
- `--providers-file`: Path to the provider registry to use for metadata in the graph.

## Related pages
- [Process Concept](../concepts/process.md)
- [Quickstart](../quickstart.md)
