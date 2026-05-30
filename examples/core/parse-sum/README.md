# parse-sum

Parse numbers from a text string and sum them.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Packages: `bpg-nodes-core`

## Setup

```bash
uv sync
```

## Validate and compile

```bash
# Validate the v2 process spec
uv run bpg validate process.v2.bpg.yaml

# Compile to execution plan
uv run bpg compile process.v2.bpg.yaml

# List discovered node packages
uv run bpg node list
```

## Process spec

The `process.v2.bpg.yaml` spec uses `schema_version: 2` and references nodes
from the `bpg-nodes-core` package by entry-point identity:

| Node   | Package ref                     | Node ID           |
|--------|---------------------------------|-------------------|
| ingest | `bpg.nodes.core@v1`             | `passthrough`     |
| parse  | `bpg.nodes.core@v1`             | `text.parse_numbers` |
| sum    | `bpg.nodes.core@v1`             | `math.sum_numbers` |

## Worker

Start a local Temporal worker (requires a running Temporal server):

```bash
# Preview worker configuration
uv run bpg worker start --dry-run

# Start Temporal dev server (separate terminal)
temporal server start-dev

# Start the BPG worker
uv run bpg worker start
```
