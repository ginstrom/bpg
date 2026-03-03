# Quickstart

```yaml
doc_metadata:
  topic: quickstart
  version: 1
  summary: Build, validate, deploy, run, and replay a BPG process in minutes.
```

## Summary
This quickstart walks through the core loop: scaffold from intent, validate, plan/apply, run, and inspect replay state.

## When to use
Use this when you are starting a new process or testing BPG’s AI-first development workflow.

## Core idea
The shortest reliable loop is:

generate -> validate -> repair -> deploy -> run -> replay.

## Example
```bash
uv run bpg init --from-intent "triage incoming support requests" --output process.bpg.yaml --todos-out todos.json
uv run bpg doctor process.bpg.yaml --json
uv run bpg suggest-fix process.bpg.yaml --json
uv run bpg fmt process.bpg.yaml --check
uv run bpg plan process.bpg.yaml --json --explain
uv run bpg apply process.bpg.yaml --auto-approve
uv run bpg run triage-incoming-support-requests --input input.json --engine local
uv run bpg replay <run-id> --json
```

## Common mistakes
- Skipping `doctor` and debugging at runtime first.
- Applying changes without checking `plan --explain` warnings.
- Assuming engine choice changes process semantics.

## Related pages
- [Build Process Guide](guides/build_process.md)
- [Debug Validation Errors](guides/debug_validation_errors.md)
- [Doctor CLI Reference](cli/doctor.md)
