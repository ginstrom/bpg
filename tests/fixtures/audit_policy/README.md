# Audit policy fixtures

These process specs validate `observability.audit` parsing and doctor checks.

`enabled.bpg.yaml` declares durable audit capture. Runtime backends build the
Postgres audit sink from `process.observability` during `bpg run`; set
`BPG_AUDIT_DATABASE_URL` (or an inline `dsn`) for live capture.

Use `bpg doctor tests/fixtures/audit_policy/enabled.bpg.yaml` to validate the
fixture locally.
