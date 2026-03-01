# BPG End-to-End (E2E) Test Design

This document outlines the strategy and test cases for verifying the BPG lifecycle: **Plan -> Apply -> Run -> Update -> Re-apply**.

## 1. Objectives
- Verify that a new process can be deployed from scratch.
- Ensure `plan` accurately reflects changes (add/modify/remove).
- Validate that `apply` correctly persists state and versioning.
- Confirm that in-flight runs respect idempotency during updates.
- Enforce immutability and breaking change rules (§11).

## 2. Test Environment
- **Runner**: `pytest`
- **State Store**: Temporary directory (`tmp_path`) for each test to ensure isolation.
- **Provider Mocks**: Use the `mock` provider to simulate external effects (Slack, GitLab) without side effects.

## 3. Core Test Scenarios

### Scenario A: Green-Field Deployment
1. **Initialize**: Create a minimal `process.bpg.yaml` (1 trigger, 1 mock node).
2. **Plan**: Run `bpg plan`. Verify output shows `+ node "trigger"` and `+ node "worker"`.
3. **Apply**: Run `bpg apply`.
4. **Verify**:
   - `.bpg-state/processes/test-process.yaml` exists.
   - Version is `1`.

### Scenario B: Incremental Non-Breaking Update
1. **Setup**: Start with Scenario A deployed.
2. **Modify**: Update the `config` of "worker" (e.g., change a timeout or a mock value).
3. **Plan**: Verify output shows `~ node "worker"` with the specific config diff.
4. **Apply**: Run `bpg apply`.
5. **Verify**: Version increments to `2`.

### Scenario C: Idempotency & In-flight Resumption
1. **Setup**: Deploy a process with `intake -> step1 -> step2`.
2. **Execute**: Run until `step2` fails with a transient error.
3. **Modify**: Update the process metadata (non-breaking change).
4. **Apply**: Deploy the update.
5. **Resume**: Call `engine.step(run_id)` after fixing the external error.
6. **Verify**: `step1` is NOT re-called (verified via provider call counts).

### Scenario D: Breaking Change Enforcement (§11)
1. **Setup**: Deploy a process with a defined type `User`.
2. **Violate Type Immutability**: Modify a field in the `User` type.
3. **Verify**: System raises `ImmutabilityError`.

### Scenario E: Graph Edge Updates
1. **Setup**: Deploy `A -> B`.
2. **Modify**: Change the `when` condition on the edge.
3. **Verify**: New runs respect the updated condition.

## 4. Implementation
- Test code is located in `tests/e2e/test_lifecycle.py`.
- Execution: `make test-e2e`.
