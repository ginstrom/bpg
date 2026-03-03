# Search Weaviate Built-ins Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-class built-in nodes/providers for markdown ingestion and Weaviate hybrid retrieval, using a shared datastore contract across separate ingestion and retrieval processes.

**Architecture:** Keep ingestion and retrieval as separate process graphs. Introduce provider-backed built-in nodes for markdown listing/chunking, embedding, and Weaviate upsert/search. Enforce shared datastore targeting through a typed `store` identifier in node config and consistent provider/env resolution.

**Tech Stack:** Python 3.12, Typer CLI, Pydantic models, current provider registry/runtime engine, Docker Compose local/package paths, pytest.

---

### Task 1: Define Node/Provider Contracts

**Files:**
- Modify: `docs/bpg-spec.md`
- Modify: `manual/nodes/built-in-providers.md`
- Modify: `manual/nodes/node-authoring-spec.md`
- Create: `manual/nodes/search-pattern.md` (already added)

**Steps:**
1. Finalize IO schemas for:
   - `fs.markdown_list@v1`
   - `text.markdown_chunk@v1`
   - `embed.text@v1`
   - `weaviate.upsert@v1`
   - `weaviate.hybrid_search@v1`
2. Specify required config keys and defaults.
3. Define dry-run behavior for external effects.
4. Define expected failure modes and retry semantics.

**Verification:**
- `uv run pytest -q tests/system/test_spec_examples.py tests/system/test_manual_node_examples.py`

### Task 2: Add Provider Implementations

**Files:**
- Modify/Create: `src/bpg/providers/builtin.py`
- Modify: `src/bpg/providers/__init__.py`
- Modify: `src/bpg/providers/base.py` (if new shared helpers are needed)
- Test: `tests/test_providers.py`

**Steps:**
1. Add provider classes/handlers for markdown list/chunk/embed/weaviate upsert/search.
2. Register provider IDs in built-in provider registry.
3. Add dry-run branches for embed and Weaviate providers.
4. Add deterministic unit tests with mock fixtures.

**Verification:**
- `uv run pytest -q tests/test_providers.py`

### Task 3: Add Runtime Inference for Weaviate Service

**Files:**
- Modify: `src/bpg/runtime/spec.py`
- Modify: `src/bpg/runtime/inference.py`
- Modify: `src/bpg/packaging/render.py`
- Test: `tests/test_runtime_spec.py`
- Test: `tests/test_runtime_inference.py`
- Test: `tests/test_packaging_render.py`

**Steps:**
1. Infer Weaviate service when process uses `weaviate.*` providers.
2. Add required env variable handling for Weaviate endpoint/auth.
3. Ensure local `up` and `package` both include consistent compose wiring.
4. Keep package unresolved vars as warnings and local unresolved behavior aligned with current policy.

**Verification:**
- `uv run pytest -q tests/test_runtime_spec.py tests/test_runtime_inference.py tests/test_packaging_render.py`

### Task 4: Add Example Processes and Validation Coverage

**Files:**
- Create: `examples/search/search-resources.bpg.yaml` (already added)
- Create: `examples/search/ingest.bpg.yaml` (already added)
- Create: `examples/search/retrieve.bpg.yaml` (already added)
- Create: `tests/system/test_examples_search_yaml.py`

**Steps:**
1. Keep examples under `examples/search`.
2. Add a system test that parses these files and validates YAML structure.
3. Upgrade test to compile examples once providers are implemented.

**Verification:**
- `uv run pytest -q tests/system/test_examples_search_yaml.py`

### Task 5: End-to-End Weaviate Smoke

**Files:**
- Modify/Create: `tests/e2e/test_search_weaviate_smoke.py`
- Modify: `tests/E2E_DESIGN.md`

**Steps:**
1. Bring up a disposable Weaviate container.
2. Run ingest process over sample markdown docs.
3. Run retrieval process and assert expected hit(s).
4. Verify run logs/event records are captured.

**Verification:**
- `uv run pytest -q tests/e2e -k weaviate`

### Task 6: CLI and Docs Polish

**Files:**
- Modify: `manual/USER_MANUAL.md`
- Modify: `README.md`
- Modify: `manual/nodes/README.md`

**Steps:**
1. Document example paths and intended command sequence.
2. Clarify planned vs implemented status for providers/examples until release lands.
3. Add migration notes once provider IDs are live.

**Verification:**
- `uv run pytest -q tests/system/test_spec_examples.py tests/system/test_manual_node_examples.py`

---

## Open Questions

1. Which embedding backend should `embed.text` use by default?
2. Should `text.markdown_chunk` preserve heading hierarchy in metadata by default?
3. Should Weaviate schema/class creation be automatic or explicit?
4. Should retrieval include optional reranking in v1 or stay hybrid-only?
