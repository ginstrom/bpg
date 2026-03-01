# Node Authoring Spec

This document defines how to create and use nodes in BPG process files.

## 1. Node Model

A runnable node is defined by two layers:

1. `node_types.<name@version>`: reusable contract + provider binding.
2. `nodes.<instance_name>`: concrete instance with config/retry/timeouts.

Minimal shape:

```yaml
types:
  Input:
    text: string
  Output:
    ok: bool

node_types:
  parse@v1:
    in: Input
    out: Output
    provider: mock
    version: v1
    config_schema: {}

nodes:
  parse_step:
    type: parse@v1
    config: {}

trigger: parse_step
edges: []
```

## 2. `node_types` Contract

Each node type must define:

- `in`: input type name
- `out`: output type name
- `provider`: provider ID (for example `text.parse_numbers`)
- `version`: version string (must match `name@version` suffix)
- `config_schema`: config keys and field types for node instances

Optional fields:

- `description`
- `timeout_default`

Rules enforced by validator:

- referenced `in`/`out` types must exist
- provider ID must be registered
- `name@version` key and `version` field must match

## 3. `nodes` Instance Contract

Each node instance must define:

- `type`: a `node_types` key (for example `parse@v1`)
- `config`: object matching `config_schema`

Optional fields:

- `description`
- `retry`
- `stable_input_fields`
- `unstable_input_fields`
- `on_timeout` (required for human nodes, see below)

## 4. Edge Input Mapping Requirements

For every edge:

- `from` and `to` nodes must exist
- `with` mappings must type-check against target node input type
- all required fields in target input must be satisfied by incoming mappings

Expression validation:

- `when` must be syntactically valid
- field refs in mappings/expressions must reference valid node inputs/outputs

## 5. Trigger and Graph Rules

- `trigger` must exist in `nodes`
- trigger node cannot have incoming edges
- process graph must be acyclic

## 6. Human Node Rules

For providers `slack.interactive` and `dashboard.form`:

- `node.config.timeout` must be present
- `node.on_timeout.out` must conform to the node output type

## 7. Provider Packaging and Env Inference

During `bpg up` / `bpg package`, required env vars and services are inferred from:

1. provider `packaging_requirements(config)`
2. `${ENV_VAR}` and `${ENV_VAR:?}` references in node config

Behavior:

- `bpg up`: unresolved required vars are hard errors
- `bpg package`: unresolved required vars are warnings (artifact can still be shipped)

## 8. Runtime Semantics for Node Authors

Provider interface:

- `invoke(input, config, context) -> handle`
- `poll(handle) -> status`
- `await_result(handle, timeout) -> output`
- `cancel(handle) -> None`

Idempotency:

- every invocation gets a deterministic key from run ID + node name + input payload
- providers should forward this key to external systems where possible

Retry and timeout:

- node `retry` policy controls retry attempts/backoff
- edge timeout can override node timeout
- `on_timeout.out` lets a node emit fallback output instead of failing

## 9. Dry-Run / Local / Docker Guidance

Recommended node design:

- support dry-run behavior for external side effects
- keep output shape identical between dry-run and live mode
- fail with typed `ProviderError` codes for retry logic

Execution modes:

- local dev: `bpg up` builds local image and runs compose locally
- package artifact: `bpg package` produces a runnable compose bundle for target machines

## 10. Checklist for New Nodes

- define input/output `types`
- define `node_types` contract with `provider` and `config_schema`
- instantiate under `nodes`
- wire edges with complete required input mappings
- validate with `bpg plan`
- exercise with dry-run and live mode where applicable
