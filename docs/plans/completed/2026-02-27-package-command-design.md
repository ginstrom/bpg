# BPG `package` Command Design

Date: 2026-02-27
Status: Approved
Owner: CLI/Runtime

## 1. Summary
Add a new CLI command:

`bpg package <process-file> --output-dir <dir> [--force]`

The command is artifact-only. It compiles and validates a process definition, infers required runtime services, and emits a deterministic Docker Compose package for handoff and execution in another environment.

## 2. Goals
- Produce a portable, reviewable deployment artifact for a specific process config.
- Keep package generation deterministic and CI-friendly.
- Infer internal dependencies (Postgres, Redis, etc.) from process/runtime configuration.
- Emit both:
  - `.env.example` for commit/review.
  - `.env` for runnable defaults and environment handoff.

## 3. Non-Goals
- Running Docker during packaging.
- Provisioning external infrastructure.
- Managing secrets beyond template/value surfacing.

## 4. CLI Contract
`bpg package <process-file> --output-dir <dir> [--force]`

Behavior:
- Validates process (`parse` + `validate` + `compile`).
- Infers required internal services.
- Collects required environment variables.
- Writes package files to `output-dir`.
- Fails only on structural errors (invalid process, unsupported dependency, output collision without `--force`, filesystem errors).

Missing required env vars do not fail packaging. They produce warnings and placeholder values in `.env`.

## 5. Output Artifacts
The package directory contains:
- `docker-compose.yml`
- `.env.example`
- `.env`
- `process.bpg.yaml` (packaged process definition)
- `README.md`
- `package-metadata.json`

### 5.1 Determinism
- Stable key ordering in generated YAML/JSON.
- Normalized newlines.
- Deterministic service/env ordering.

## 6. Service Inference
Packaging builds a `PackageSpec` from compiled IR + runtime/storage/provider metadata.

Inference rules:
- Ledger/storage backend drives DB inclusion:
  - sqlite-memory/sqlite-file: no DB service required.
  - postgres: include `postgres` service.
- Provider capability metadata may declare service dependencies (e.g. `redis`).
- Unsupported inferred dependency fails with clear error.

## 7. Env/Secrets Handling
### 7.1 `.env.example`
- Includes all required and optional keys.
- Contains comments describing source/usage where available.

### 7.2 `.env`
- Resolved values are emitted directly.
- Unresolved required values are emitted as:
  - `KEY=__REQUIRED__`
- Optional unresolved values may be commented.

### 7.3 Warning UX
At completion, print summary warnings:
- Count of unresolved required vars.
- Per-variable usage context (service/provider/backend).

Packaging still returns exit code `0` when these are the only issues.

## 8. Readiness Signaling
`package-metadata.json` includes:
- `process_name`
- `process_hash`
- `generated_at`
- `ready_to_run` (boolean)
- `unresolved_required_vars` (array)
- `services` (inferred internal services)

`README.md` includes:
- Run instructions (`docker compose up`)
- Required pre-run checklist derived from unresolved vars
- Notes on inferred services and storage backend

## 9. Failure Semantics
Non-zero exit on:
- Parse/validation/compiler errors.
- Unsupported inferred service dependency.
- Existing output dir without `--force`.
- Artifact rendering/write failure.

Zero exit on:
- Successful package generation, even with unresolved required vars.

## 10. Architecture Sketch
Proposed internal modules:
- `bpg.packaging.spec`:
  - Build `PackageSpec` from process/IR/config.
- `bpg.packaging.inference`:
  - Resolve service dependencies and env requirements.
- `bpg.packaging.render`:
  - Render compose/env/readme/metadata deterministically.
- `bpg.packaging.writer`:
  - Validate destination, write files, enforce `--force` behavior.

CLI entry point remains `src/bpg/cli.py` with a new `@app.command()`.

## 11. Testing Strategy
Unit tests:
- Service inference for sqlite/postgres and provider-dependent services.
- `.env` placeholder rendering (`__REQUIRED__`).
- Deterministic render ordering.
- Error cases for unsupported dependency and output collision.

CLI tests:
- `bpg package` success path with warnings.
- `bpg package` hard failures on invalid process.
- `--force` overwrite behavior.

E2E (optional next phase):
- Generate package and verify expected artifact set.

## 12. Open Items (For Implementation Plan)
- Exact process/runtime config location for ledger backend selection.
- Capability API for providers to expose runtime dependencies/env requirements.
- Whether to include a generated app service Dockerfile or reference existing image/tag.

