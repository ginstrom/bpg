# System Integration Tests

```yaml
doc_metadata:
  topic: system_integration_tests
  version: 1
  summary: Run opt-in tests that call real external systems (Gemini, Slack, Email).
```

## Summary
System integration tests verify real provider behavior against production systems.
They are separate from deterministic unit/e2e tests and run only when explicitly enabled.

## Test type
- Directory: `tests/system_integration/`
- Marker: `@pytest.mark.system_integration`
- Make target: `make test-system-integration`

## Enable and run
```bash
export BPG_SYSTEM_INTEGRATION=1
make test-system-integration
```

Run one file:
```bash
export BPG_SYSTEM_INTEGRATION=1
. .venv/bin/activate && uv run pytest -q -m system_integration tests/system_integration/test_gemini_structured_extraction.py
```

## Environment variables
- Global gate:
  - `BPG_SYSTEM_INTEGRATION=1` required to run live tests.
- Provider credentials:
  - Gemini/Google: `GOOGLE_API_KEY`
  - Slack: `SLACK_BOT_TOKEN` (and `SLACK_SIGNING_SECRET` when needed by the scenario)
  - Email: `SMTP_HOST`, `SMTP_FROM`, optional `SMTP_USERNAME`, `SMTP_PASSWORD`

## Conventions
- Use synthetic test data (documents/messages) with deterministic assertions.
- Validate typed outputs (shape + key values), not just command success.
- Skip with a clear reason when required env vars are missing.
- Keep live tests isolated from default suites (`make test`, `make test-unit`, `make test-e2e`).

## Related pages
- [Testing Processes](./testing_processes.md)
- [Add AI Step Guide](./add_ai_step.md)
- [Built-in Provider Catalog](../../manual/nodes/built-in-providers.md)
