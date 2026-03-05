# CLI: bpg test

```yaml
doc_metadata:
  topic: cli_test
  version: 1
  summary: Run spec-level process tests with mocks and assertions.
```

## Summary
`bpg test` executes a suite of process-level tests against a `process.bpg.yaml` definition using fixture inputs and mocked node outputs.

## When to use
Use during development and CI to verify process routing, data mapping, and failure handling without executing actual provider work.

## Core idea
Spec tests confirm that the process logic (edges, conditions, mappings) is correct for a given set of node behaviors.

## Example
```bash
# Run tests from a spec test suite file
uv run bpg test tests/process_test_suite.yaml

# Run tests and emit JSON results (CI mode)
uv run bpg test tests/process_test_suite.yaml --json
```

## Options
- `suite_file`: Path to the YAML file defining the test cases.
- `--json`: Emit detailed results and per-case errors as JSON.

## Related pages
- [Testing Processes Guide](../guides/testing_processes.md)
- [CLI: bpg doctor](doctor.md)
