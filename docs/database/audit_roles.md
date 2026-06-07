# Audit Ledger Database Roles

Recommended production posture:

- Migration owner: owns `audit_events`, can run schema migrations, and is not used by the runtime.
- Runtime audit writer: can `insert` and `select` from `audit_events`; should not have `update` or `delete`.
- Auditor reader: can `select` from `audit_events` and checkpoint tables only.

The `audit_events` table also installs update/delete prevention triggers. Role permissions and triggers are both intentional: permissions reduce accidental mutation capability, and triggers fail mutation attempts even for roles that retain broader table privileges.
