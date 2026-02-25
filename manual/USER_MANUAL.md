# BPG User Manual

## What BPG Does
BPG (Business Process Graph) lets you define business workflows as typed YAML graphs, preview changes, and deploy them with a `plan/apply` flow.

## Prerequisites
- Python 3.12+
- `uv` installed

## Setup
```bash
uv venv
source .venv/bin/activate
uv sync
```

## CLI Basics
Run all commands from the project root.

```bash
# Show command help
uv run bpg --help
```

## Typical Workflow
1. Edit your process definition file (example: `process.bpg.yaml`).
2. Validate and preview changes:
```bash
uv run bpg plan process.bpg.yaml
```
3. Apply changes:
```bash
uv run bpg apply process.bpg.yaml
```
4. Skip confirmation prompt (CI/non-interactive use):
```bash
uv run bpg apply process.bpg.yaml --auto-approve
```

## Commands
- `bpg plan <process_file>`: Parses + validates a process and shows the diff versus deployed state.
- `bpg apply <process_file>`: Deploys provider artifacts and persists process state.
- `bpg visualize <process_file>`: Generates graph HTML under `.bpg/viz` (or `--output-dir`).
- `bpg run <process_name>`: Placeholder; not implemented yet.
- `bpg status [run_id]`: Placeholder; not implemented yet.

## State and Output Locations
- Default state directory: `.bpg-state` (override with `--state-dir`).
- Visualization output: `.bpg/viz/<process_file_stem>.html`.

## Quick Examples
```bash
# Plan against a custom state directory
uv run bpg plan process.bpg.yaml --state-dir .bpg-state

# Generate visualization and open it
uv run bpg visualize process.bpg.yaml --open
```

## Troubleshooting
- Parse/validation errors: Fix schema, node/edge references, or type mismatches in the YAML.
- "No changes detected": The deployed state already matches your process file.
- Provider deploy issues: Re-run `plan`, verify node provider configs, then `apply` again.
