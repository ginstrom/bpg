# bpg-sdk

Authoring SDK for installable BPG node packages.

Current surface:

- `@node(...)` for simple function-backed nodes
- `Node` base class for advanced node implementations
- `NodeManifest` as the canonical framework metadata contract
- `discover_nodes()` for `bpg.nodes` entry-point discovery
- helper registration shims for Temporal and LangGraph integration
