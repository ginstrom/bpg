# BPG User Manual

## What BPG Does
BPG (Business Process Graph) lets you define typed workflow graphs in YAML, preview deployment changes (`plan`), package deployable artifacts (`package`), deploy them (`apply`), and execute them (`run`/`status`) with persisted state and run logs.

## Documentation Map
- Node authoring and built-ins: [nodes/README.md](nodes/README.md)
- Full system spec: [../docs/bpg-spec.md](../docs/bpg-spec.md)

## Prerequisites
- Python 3.12+
- `uv`

## Install As App (GitHub)
Install globally as a CLI app:

```bash
uv tool install "git+https://github.com/<org>/<repo>.git"
```

Alternative:

```bash
pipx install "git+https://github.com/<org>/<repo>.git"
```

## Setup
```bash
uv venv
source .venv/bin/activate
uv sync
```

## CLI Overview
```bash
uv run bpg --help
```

Available commands:
- `bpg visualize <process_file>`
- `bpg plan <process_file>`
- `bpg package [process_file] --output-dir <dir> [--force] [--dashboard] [--dashboard-port <port>]`
- `bpg up [process_file] [--local-dir <dir>] [--force] [--dashboard] [--dashboard-port <port>]`
- `bpg down [process_file] [--local-dir <dir>]`
- `bpg logs [--local-dir <dir>] [--service <name>]`
- `bpg apply <process_file>`
- `bpg run <process_name> [--input FILE]`
- `bpg status [run_id] [--process PROCESS_NAME]`

## Typical Workflow
1. Edit a process file (for example `process.bpg.yaml`).
2. Preview deployment changes (no writes to deployed process/run state):
```bash
uv run bpg plan process.bpg.yaml
```
3. Apply changes:
```bash
uv run bpg apply process.bpg.yaml
```
4. Trigger a run against deployed state:
```bash
uv run bpg run bug-triage-process --input input.yaml
```
5. Check status:
```bash
uv run bpg status
uv run bpg status <run_id>
```

## Command Details
- `plan`
  - Parses + validates process YAML.
  - Compiles IR and shows diff against deployed process record.
  - Does not execute nodes.
- `apply`
  - Re-validates and computes plan.
  - Performs drift check against saved process hash before writing.
  - Deploys/undeploys provider artifacts for changed nodes.
  - Persists process record with incremented version.
- `package`
  - If `process_file` is omitted, defaults to `process.bpg.yaml` then `process.bpg.yml` in current directory.
  - Validates and compiles process definition.
  - Infers internal services for docker compose (defaults to postgres ledger for package mode).
  - Generates artifact-only output in the requested directory:
    - `docker-compose.yml`
    - `.env.example`
    - `.env`
    - `process.bpg.yaml`
    - `README.md`
    - `package-metadata.json`
    - `Dockerfile` (default package mode)
    - `pyproject.toml` (default package mode)
    - `uv.lock` (default package mode)
    - `src/**/*.py` (default package mode)
  - Missing required env vars are warnings, not hard failures.
  - Unresolved required vars are emitted in `.env` as `KEY=__REQUIRED__`.
  - `--dashboard` includes a `dashboard` service and API/UI container in generated compose artifacts.
  - Default package mode is local-buildable (`docker compose up --build`) and does not require pulling a registry image.
  - `--image` (or `BPG_PACKAGE_IMAGE`) switches package mode to an explicit image reference.
- `up`
  - If `process_file` is omitted, defaults to `process.bpg.yaml` then `process.bpg.yml` in current directory.
  - Builds a local runtime bundle using the same inference model as `package` with local defaults.
  - Builds local image `bpg-local:dev` from the current repository before `docker compose up -d`.
  - Starts services via `docker compose up -d`.
  - Fails hard if required vars are unresolved.
  - `--dashboard` prints a local dashboard URL (default `http://localhost:8080`).
- `down`
  - If `--local-dir` is set, uses that directory directly.
  - Otherwise, if `process_file` is provided (or default `process.bpg.yaml`/`process.bpg.yml` exists), it infers local runtime dir as `.bpg/local/<process_name>`.
  - If neither process file exists nor `--local-dir` is provided, falls back to legacy inference from `.bpg/local/default` (single-directory inference).
  - Stops local runtime services via `docker compose down`.
- `logs`
  - Streams local runtime logs via `docker compose logs --tail 200`.
- `run`
  - Loads deployed process by `metadata.name`.
  - Accepts YAML or JSON input via `--input`; defaults to `{}`.
  - Executes end-to-end and persists run/node/event records.
- `status`
  - No `run_id`: lists runs (optionally filtered by `--process`).
  - With `run_id`: prints run metadata and per-node record summaries.
- `visualize`
  - Generates HTML graph at `.bpg/viz/<process_file_stem>.html` (or `--output-dir`).

## Current Validation Rules (Implemented)
- `types` must be present and non-empty.
- `trigger` must exist and cannot have incoming edges.
- Node type/module versions must be valid; `name@version` keys must match `version`.
- Edge mappings are type-checked against target input schema.
- Required target input fields must be covered by the union of incoming edge mappings.
- `when` expressions are validated for syntax.
- Cycles are rejected.
- Human nodes (`slack.interactive`, `dashboard.form`) require:
  - `node.config.timeout`
  - `node.on_timeout.out` matching node output type

## Runtime Behavior (Implemented)
- Trigger semantics:
  - Only the declared `trigger` node is treated as entry pass-through.
- Incoming edge semantics:
  - All firing incoming edges are merged.
  - Conflicting values for the same mapped input field fail the node.
  - Per-edge `timeout` is supported; if multiple edges fire, the smallest timeout is used.
- Failure semantics (`edge.on_failure`):
  - `route`: route original input payload to `to` node.
  - `notify`: route payload to `node` with `__failure__` context.
  - `fail`: force run failure.
- Timeout semantics:
  - If `on_timeout.out` exists, node continues with synthetic output.
  - Without fallback output, node times out and may fail/escalate.
- Retry semantics:
  - Uses node `retry` policy (`max_attempts`, `backoff`, delays, retryable codes).
- Process output:
  - If `output` is configured, result is persisted on run record as `output`.

## Built-in Provider IDs
- `mock`
- `http.webhook`
- `core.passthrough`
- `agent.pipeline`
- `dashboard.form`
- `slack.interactive`
- `http.gitlab`
- `queue.kafka`
- `timer.delay`
- `flow.loop`
- `flow.fanout`
- `flow.await_all`
- `bpg.process_call`
- `text.parse_numbers`
- `math.sum_numbers`
- `tool.web_search`
- `notify.email`

`tool.web_search` and `notify.email` support dry-run mode via either:
- node config: `dry_run: true`
- env: `BPG_DRY_RUN=1` or `BPG_EXECUTION_MODE=dry-run`

## State Layout
Default state root is `.bpg-state` (override with `--state-dir`).

```text
.bpg-state/
  processes/
    <process-name>.yaml
  runs/
    <run-id>/
      run.yaml
      events.jsonl
      nodes/
        <node-name>.yaml
  interactions/
    <idempotency_key>/
      pending.yaml
      response.yaml
  exports/
    *.jsonl
```

Process records include deployment metadata and integrity pins/checksums (`process_version`, `node_type_pins`, `type_pins`, `type_checksums`, `node_type_checksums`, `ir_checksum`).  
Run records include process snapshot metadata (`process_hash`, `process_record_version`, `process_version`).

## Notes on Duration Format
Current code accepts duration literals in forms like `500ms`, `30s`, `5m`, `2h`, `1d`.

## Troubleshooting
- Parse/validation error:
  - Fix schema/type references, mappings, trigger placement, or human timeout config.
- `No changes detected`:
  - Deployed process already matches current definition.
- Apply drift/checksum error:
  - Re-run `plan`, then `apply`; do not apply stale plans.
- `Process '<name>' not found in state` on run:
  - Apply the process first and use `metadata.name` as `process_name`.
