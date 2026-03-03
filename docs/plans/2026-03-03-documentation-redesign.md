# BPG Documentation Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign BPG documentation to an AI-first architecture that is machine-usable and human-friendly.

**Architecture:** Introduce a new documentation information architecture under `docs/` with predictable page templates, structured metadata, and explicit system-model explanations. Keep existing historical plan docs in place and shift primary navigation to the new AI-first docs and README entrypoint.

**Tech Stack:** Markdown, existing BPG CLI semantics, repository docs conventions.

---

### Task 1: Define IA and canonical page template

**Files:**
- Create: `docs/overview.md`
- Create: `docs/quickstart.md`

**Step 1:** Capture AI-first messaging and top-level narrative in `overview.md`.

**Step 2:** Create quickstart using real CLI commands (`init`, `doctor`, `plan`, `apply`, `run`, `replay`).

**Step 3:** Add `doc_metadata` block and canonical sections to both pages.

**Step 4:** Commit this IA anchor.

### Task 2: Add Concepts and Guides

**Files:**
- Create: `docs/concepts/process.md`
- Create: `docs/concepts/nodes.md`
- Create: `docs/concepts/edges.md`
- Create: `docs/concepts/execution.md`
- Create: `docs/concepts/human_steps.md`
- Create: `docs/concepts/versioning.md`
- Create: `docs/guides/build_process.md`
- Create: `docs/guides/add_ai_step.md`
- Create: `docs/guides/add_human_review.md`
- Create: `docs/guides/modify_process.md`
- Create: `docs/guides/debug_validation_errors.md`
- Create: `docs/guides/testing_processes.md`

**Step 1:** Build each page with identical section headings.

**Step 2:** Add YAML examples with explicit node/edge mappings.

**Step 3:** Ensure guides reinforce validation-driven loop and deterministic model.

### Task 3: Add Reference and CLI docs

**Files:**
- Create: `docs/reference/process_schema.md`
- Create: `docs/reference/node_schema.md`
- Create: `docs/reference/edge_schema.md`
- Create: `docs/reference/type_system.md`
- Create: `docs/reference/provider_interface.md`
- Create: `docs/reference/error_codes.md`
- Create: `docs/cli/plan.md`
- Create: `docs/cli/apply.md`
- Create: `docs/cli/doctor.md`
- Create: `docs/cli/run.md`

**Step 1:** Document canonical schemas with JSON/YAML snippets.

**Step 2:** Align command pages with `src/bpg/cli.py` behavior and JSON output fields.

**Step 3:** Include actionable error/repair examples with patch payloads.

### Task 4: Add Patterns, Examples, and AI agent docs

**Files:**
- Create: `docs/patterns/approval_workflow.md`
- Create: `docs/patterns/retry_pattern.md`
- Create: `docs/patterns/validation_pattern.md`
- Create: `docs/patterns/parallel_processing.md`
- Create: `docs/patterns/ai_evaluation_pipeline.md`
- Create: `docs/examples/document_pipeline.md`
- Create: `docs/examples/insurance_claims.md`
- Create: `docs/examples/support_automation.md`
- Create: `docs/examples/compliance_review.md`
- Create: `docs/ai/how_agents_should_use_bpg.md`
- Create: `docs/ai/prompt_patterns.md`
- Create: `docs/ai/repair_strategies.md`

**Step 1:** Provide reusable patterns with explicit graph shapes.

**Step 2:** Add end-to-end examples that reflect realistic business systems.

**Step 3:** Add agent playbooks for generation, repair, and incremental edits.

### Task 5: Rewrite README as AI-first homepage

**Files:**
- Modify: `README.md`

**Step 1:** Replace opening narrative with AI-first value proposition.

**Step 2:** Add 30-second YAML example.

**Step 3:** Add docs map linking to the new structure.

**Step 4:** Preserve critical operational links (search example, install, dev setup).

### Task 6: Validate and finalize

**Files:**
- Modify: any docs with broken internal links or inconsistent terminology

**Step 1:** Run link/path sanity checks (`rg` over links + verify file existence).

**Step 2:** Confirm command names/options in docs match CLI.

**Step 3:** Commit all changes with a single message focused on docs redesign.
