"""Postgres-backed tamper-evident audit ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

from bpg.audit.policy import (
    AuditFailurePolicy,
    AuditPayloadRetention,
    AuditPolicyConfig,
    AuditSinkFailure,
    DuplicateStrategy,
    apply_audit_policy,
    audit_payload_for_event,
)
from bpg.runtime.events import BpgEvent, canonical_json, sha256_json

AUDIT_SCHEMA_SQL = """
create table if not exists audit_events (
  sequence_id bigserial primary key,
  chain_scope text not null,
  chain_id text not null,
  event_id text not null unique,
  event_type text not null,
  occurred_at timestamptz not null,
  inserted_at timestamptz not null default now(),

  run_id text not null,
  process_name text not null,
  process_version text,
  process_hash text,
  node_id text,
  node_type text,

  actor_id text,
  actor_type text,
  policy_id text,
  correlation_id text,
  external_ref text,

  trace_id text,
  span_id text,

  payload jsonb not null,
  payload_sha256 text not null,
  previous_hash text,
  event_hash text not null
);

create index if not exists audit_events_chain_idx
  on audit_events (chain_scope, chain_id, sequence_id);

create index if not exists audit_events_run_idx
  on audit_events (run_id, sequence_id);

create or replace function bpg_prevent_audit_events_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_events is append-only and cannot be updated or deleted';
end;
$$;

drop trigger if exists audit_events_no_update on audit_events;
create trigger audit_events_no_update
before update on audit_events
for each row execute function bpg_prevent_audit_events_mutation();

drop trigger if exists audit_events_no_delete on audit_events;
create trigger audit_events_no_delete
before delete on audit_events
for each row execute function bpg_prevent_audit_events_mutation();

create table if not exists audit_chain_checkpoints (
  checkpoint_id bigserial primary key,
  created_at timestamptz not null default now(),
  scope text not null,
  last_sequence_id bigint not null,
  chain_head_hash text not null,
  anchored_ref text,
  signature text
);

create index if not exists audit_chain_checkpoints_scope_idx
  on audit_chain_checkpoints (scope, checkpoint_id);

create or replace function bpg_prevent_audit_chain_checkpoints_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_chain_checkpoints is append-only and cannot be updated or deleted';
end;
$$;

drop trigger if exists audit_chain_checkpoints_no_update on audit_chain_checkpoints;
create trigger audit_chain_checkpoints_no_update
before update on audit_chain_checkpoints
for each row execute function bpg_prevent_audit_chain_checkpoints_mutation();

drop trigger if exists audit_chain_checkpoints_no_delete on audit_chain_checkpoints;
create trigger audit_chain_checkpoints_no_delete
before delete on audit_chain_checkpoints
for each row execute function bpg_prevent_audit_chain_checkpoints_mutation();
""".strip()


class DuplicateAuditEventError(RuntimeError):
    """Raised when a duplicate audit event is inserted with reject semantics."""


@dataclass(frozen=True)
class PostgresAuditConfig(AuditPolicyConfig):
    """Configuration for the Postgres audit sink."""

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> "PostgresAuditConfig":
        """Build audit config from a root, observability, or audit-only mapping."""
        policy = AuditPolicyConfig.from_mapping(config)
        return cls(
            enabled=policy.enabled,
            sink=policy.sink,
            dsn=policy.dsn,
            dsn_env=policy.dsn_env,
            failure_policy=policy.failure_policy,
            retention=policy.retention,
            payload_retention=policy.payload_retention,
            redaction_policy_id=policy.redaction_policy_id,
            redacted_field_paths=policy.redacted_field_paths,
            duplicate_strategy=policy.duplicate_strategy,
            tags=policy.tags,
        )


@dataclass(frozen=True)
class AuditRecord:
    """One projected audit ledger row."""

    sequence_id: int
    chain_scope: str
    chain_id: str
    event_id: str
    event_type: str
    occurred_at: str
    run_id: str
    process_name: str
    process_version: str | None
    process_hash: str | None
    node_id: str | None
    node_type: str | None
    actor_id: str | None
    actor_type: str | None
    policy_id: str | None
    correlation_id: str | None
    external_ref: str | None
    trace_id: str | None
    span_id: str | None
    payload: dict[str, Any]
    payload_sha256: str
    previous_hash: str | None
    event_hash: str

    def to_insert_row(self) -> dict[str, Any]:
        """Return columns used by the audit_events insert."""
        return {
            "sequence_id": self.sequence_id,
            "chain_scope": self.chain_scope,
            "chain_id": self.chain_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "run_id": self.run_id,
            "process_name": self.process_name,
            "process_version": self.process_version,
            "process_hash": self.process_hash,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "policy_id": self.policy_id,
            "correlation_id": self.correlation_id,
            "external_ref": self.external_ref,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "payload": self.payload,
            "payload_sha256": self.payload_sha256,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class AuditChainCheckpoint:
    """One checkpoint over the current audit chain head."""

    checkpoint_id: int | None
    created_at: str | None
    scope: str
    last_sequence_id: int
    chain_head_hash: str
    anchored_ref: str | None = None
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible checkpoint representation."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
            "scope": self.scope,
            "last_sequence_id": self.last_sequence_id,
            "chain_head_hash": self.chain_head_hash,
            "anchored_ref": self.anchored_ref,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class AnchorResult:
    """Result returned by an audit checkpoint anchoring provider."""

    anchored_ref: str | None = None
    metadata: dict[str, Any] | None = None


class CheckpointAnchorProvider:
    """Interface for persisting checkpoint evidence outside the audit table."""

    def anchor(self, checkpoint: AuditChainCheckpoint) -> AnchorResult:  # pragma: no cover - interface
        raise NotImplementedError


class NoopCheckpointAnchorProvider(CheckpointAnchorProvider):
    """Explicitly configured provider for deployments without external anchoring."""

    def anchor(self, checkpoint: AuditChainCheckpoint) -> AnchorResult:  # noqa: ARG002
        return AnchorResult()


class LocalFileCheckpointAnchorProvider(CheckpointAnchorProvider):
    """Write checkpoint material to a local directory as a minimal anchor."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)

    def anchor(self, checkpoint: AuditChainCheckpoint) -> AnchorResult:
        self._directory.mkdir(parents=True, exist_ok=True)
        material = checkpoint_material(checkpoint)
        digest = sha256_json(material)
        path = self._directory / f"audit-checkpoint-{digest}.json"
        path.write_text(canonical_json(checkpoint.to_dict()) + "\n", encoding="utf-8")
        return AnchorResult(anchored_ref=str(path), metadata={"sha256": digest})


@dataclass(frozen=True)
class AuditChainVerification:
    """Result of recomputing an audit hash chain."""

    ok: bool
    checked: int
    chain_scope: str | None = None
    chain_id: str | None = None
    first_mismatch_sequence_id: int | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    message: str = ""
    checkpoint_id: int | None = None
    anchor_verified: bool | None = None
    anchor_message: str | None = None


def is_audit_worthy_event(event: BpgEvent) -> bool:  # noqa: ARG001
    """Return whether a canonical event should be stored in the audit ledger."""
    return True


def _payload_for_audit(event: BpgEvent, audit_config: AuditPolicyConfig | None) -> dict[str, Any]:
    if audit_config is None:
        return dict(event.payload or {})
    return audit_payload_for_event(event, audit_config)


def _timestamp_for_hash(value: str) -> str:
    """Match Python's stable datetime string used after Postgres fetches."""
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return str(datetime.fromisoformat(normalized))
    except ValueError:
        return value


def compute_audit_event_hash(record: Mapping[str, Any]) -> str:
    """Compute the tamper-evident hash for an audit row."""
    fields = {
        "previous_hash": record.get("previous_hash"),
        "chain_scope": record.get("chain_scope"),
        "chain_id": record.get("chain_id"),
        "sequence_id": record.get("sequence_id"),
        "event_id": record.get("event_id"),
        "event_type": record.get("event_type"),
        "occurred_at": record.get("occurred_at"),
        "run_id": record.get("run_id"),
        "process_name": record.get("process_name"),
        "process_version": record.get("process_version"),
        "process_hash": record.get("process_hash"),
        "node_id": record.get("node_id"),
        "node_type": record.get("node_type"),
        "actor_id": record.get("actor_id"),
        "policy_id": record.get("policy_id"),
        "correlation_id": record.get("correlation_id"),
        "external_ref": record.get("external_ref"),
        "trace_id": record.get("trace_id"),
        "span_id": record.get("span_id"),
        "payload_sha256": record.get("payload_sha256"),
    }
    return sha256_json(fields)


def checkpoint_material(checkpoint: AuditChainCheckpoint | Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable checkpoint fields used for signatures and anchors."""
    if isinstance(checkpoint, AuditChainCheckpoint):
        scope = checkpoint.scope
        last_sequence_id = checkpoint.last_sequence_id
        chain_head_hash = checkpoint.chain_head_hash
    else:
        scope = checkpoint["scope"]
        last_sequence_id = checkpoint["last_sequence_id"]
        chain_head_hash = checkpoint["chain_head_hash"]
    return {
        "scope": scope,
        "last_sequence_id": last_sequence_id,
        "chain_head_hash": chain_head_hash,
    }


def sign_checkpoint(
    checkpoint: AuditChainCheckpoint | Mapping[str, Any],
    *,
    signing_key: str | bytes | None,
) -> str | None:
    """Return an HMAC-SHA256 checkpoint signature when a signing key is set."""
    if not signing_key:
        return None
    key = signing_key.encode("utf-8") if isinstance(signing_key, str) else signing_key
    digest = hmac.new(key, canonical_json(checkpoint_material(checkpoint)).encode("utf-8"), "sha256")
    return f"hmac-sha256:{digest.hexdigest()}"


def verify_checkpoint_signature(
    checkpoint: AuditChainCheckpoint | Mapping[str, Any],
    *,
    signing_key: str | bytes | None,
) -> bool:
    """Verify an HMAC checkpoint signature."""
    expected = sign_checkpoint(checkpoint, signing_key=signing_key)
    if expected is None:
        return True
    actual = checkpoint.signature if isinstance(checkpoint, AuditChainCheckpoint) else checkpoint.get("signature")
    return hmac.compare_digest(str(actual or ""), expected)


def build_audit_record(
    event: BpgEvent,
    *,
    sequence_id: int,
    previous_hash: str | None,
    chain_scope: str = "run",
    chain_id: str | None = None,
    audit_config: AuditPolicyConfig | None = None,
) -> AuditRecord:
    """Project a canonical BPG event into an audit ledger row."""
    event = apply_audit_policy(event, audit_config) if audit_config is not None else event
    payload = _payload_for_audit(event, audit_config)
    payload_sha256 = sha256_json(payload)
    row: dict[str, Any] = {
        "sequence_id": sequence_id,
        "chain_scope": chain_scope,
        "chain_id": chain_id or event.run_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": _timestamp_for_hash(event.occurred_at),
        "run_id": event.run_id,
        "process_name": event.process_name,
        "process_version": event.process_version,
        "process_hash": event.process_hash,
        "node_id": event.node_id,
        "node_type": event.node_type,
        "actor_id": event.actor_id,
        "actor_type": event.actor_type,
        "policy_id": event.policy_id,
        "correlation_id": event.correlation_id,
        "external_ref": event.external_ref,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "payload": payload,
        "payload_sha256": payload_sha256,
        "previous_hash": previous_hash,
    }
    row["event_hash"] = compute_audit_event_hash(row)
    return AuditRecord(**row)


def _row_to_mapping(row: Mapping[str, Any] | AuditRecord) -> dict[str, Any]:
    if isinstance(row, AuditRecord):
        return row.to_insert_row()
    return dict(row)


def verify_audit_chain(
    rows: Iterable[Mapping[str, Any] | AuditRecord],
    *,
    checkpoint: AuditChainCheckpoint | Mapping[str, Any] | None = None,
    require_anchor: bool = False,
    signing_key: str | bytes | None = None,
) -> AuditChainVerification:
    """Recompute a run-scoped audit chain and report the first mismatch."""
    ordered_rows = sorted((_row_to_mapping(row) for row in rows), key=lambda row: row["sequence_id"])
    if not ordered_rows:
        return AuditChainVerification(ok=True, checked=0, message="no audit rows")

    chain_scope = str(ordered_rows[0]["chain_scope"])
    chain_id = str(ordered_rows[0]["chain_id"])
    previous_hash: str | None = None
    start_sequence_id: int | None = None
    checkpoint_id: int | None = None
    if checkpoint is not None:
        checkpoint_id = (
            checkpoint.checkpoint_id
            if isinstance(checkpoint, AuditChainCheckpoint)
            else checkpoint.get("checkpoint_id")
        )
        if not verify_checkpoint_signature(checkpoint, signing_key=signing_key):
            return AuditChainVerification(
                ok=False,
                checked=0,
                chain_scope=chain_scope,
                chain_id=chain_id,
                message="checkpoint signature mismatch",
                checkpoint_id=checkpoint_id,
            )
        anchored_ref = (
            checkpoint.anchored_ref
            if isinstance(checkpoint, AuditChainCheckpoint)
            else checkpoint.get("anchored_ref")
        )
        if require_anchor and not anchored_ref:
            return AuditChainVerification(
                ok=False,
                checked=0,
                chain_scope=chain_scope,
                chain_id=chain_id,
                message="checkpoint anchor missing",
                checkpoint_id=checkpoint_id,
                anchor_verified=False,
                anchor_message="missing external anchor",
            )
        previous_hash = (
            checkpoint.chain_head_hash
            if isinstance(checkpoint, AuditChainCheckpoint)
            else checkpoint["chain_head_hash"]
        )
        start_sequence_id = (
            checkpoint.last_sequence_id
            if isinstance(checkpoint, AuditChainCheckpoint)
            else checkpoint["last_sequence_id"]
        )
        ordered_rows = [row for row in ordered_rows if row["sequence_id"] > start_sequence_id]
        if not ordered_rows:
            return AuditChainVerification(
                ok=True,
                checked=0,
                chain_scope=chain_scope,
                chain_id=chain_id,
                message="audit chain verified from checkpoint",
                checkpoint_id=checkpoint_id,
                anchor_verified=bool(anchored_ref),
                anchor_message="anchor present" if anchored_ref else "missing external anchor",
            )

    for index, row in enumerate(ordered_rows, start=1):
        if row["chain_scope"] != chain_scope or row["chain_id"] != chain_id:
            return AuditChainVerification(
                ok=False,
                checked=index - 1,
                chain_scope=chain_scope,
                chain_id=chain_id,
                first_mismatch_sequence_id=row["sequence_id"],
                message="chain contains rows from multiple scopes or IDs",
                checkpoint_id=checkpoint_id,
            )
        if row.get("previous_hash") != previous_hash:
            return AuditChainVerification(
                ok=False,
                checked=index - 1,
                chain_scope=chain_scope,
                chain_id=chain_id,
                first_mismatch_sequence_id=row["sequence_id"],
                expected_hash=previous_hash,
                actual_hash=row.get("previous_hash"),
                message="previous_hash does not match prior event_hash",
                checkpoint_id=checkpoint_id,
            )

        payload_sha256 = sha256_json(row.get("payload") or {})
        if row.get("payload_sha256") != payload_sha256:
            return AuditChainVerification(
                ok=False,
                checked=index - 1,
                chain_scope=chain_scope,
                chain_id=chain_id,
                first_mismatch_sequence_id=row["sequence_id"],
                expected_hash=payload_sha256,
                actual_hash=row.get("payload_sha256"),
                message="payload_sha256 mismatch",
                checkpoint_id=checkpoint_id,
            )

        expected_hash = compute_audit_event_hash(row)
        if row.get("event_hash") != expected_hash:
            return AuditChainVerification(
                ok=False,
                checked=index - 1,
                chain_scope=chain_scope,
                chain_id=chain_id,
                first_mismatch_sequence_id=row["sequence_id"],
                expected_hash=expected_hash,
                actual_hash=row.get("event_hash"),
                message="event_hash mismatch",
                checkpoint_id=checkpoint_id,
            )
        previous_hash = row["event_hash"]

    return AuditChainVerification(
        ok=True,
        checked=len(ordered_rows),
        chain_scope=chain_scope,
        chain_id=chain_id,
        message="audit chain verified from checkpoint" if start_sequence_id is not None else "audit chain verified",
        checkpoint_id=checkpoint_id,
        anchor_verified=None if checkpoint is None else bool(
            checkpoint.anchored_ref if isinstance(checkpoint, AuditChainCheckpoint) else checkpoint.get("anchored_ref")
        ),
        anchor_message=None
        if checkpoint is None
        else (
            "anchor present"
            if (checkpoint.anchored_ref if isinstance(checkpoint, AuditChainCheckpoint) else checkpoint.get("anchored_ref"))
            else "missing external anchor"
        ),
    )


def checkpoint_to_event(
    checkpoint: AuditChainCheckpoint,
    *,
    event_id: str | None = None,
) -> BpgEvent:
    """Represent a checkpoint as a canonical runtime event."""
    return BpgEvent(
        event_id=event_id or f"audit-checkpoint-{checkpoint.checkpoint_id or checkpoint.last_sequence_id}",
        event_type="audit_checkpointed",
        run_id="__audit_checkpoint__",
        process_name="bpg.audit",
        process_version="v1",
        process_hash="audit-ledger",
        engine_backend="audit",
        payload={
            "checkpoint_id": checkpoint.checkpoint_id,
            "scope": checkpoint.scope,
            "last_sequence_id": checkpoint.last_sequence_id,
            "chain_head_hash": checkpoint.chain_head_hash,
            "anchored_ref": checkpoint.anchored_ref,
            "signature": checkpoint.signature,
        },
        payload_sha256=sha256_json(checkpoint.to_dict()),
    )


class PostgresAuditEventSink:
    """Write canonical BPG events to a Postgres hash-chained audit ledger."""

    def __init__(
        self,
        *,
        dsn: str,
        duplicate_strategy: DuplicateStrategy = "reject",
        failure_policy: AuditFailurePolicy = "warn",
        retention: str | None = None,
        payload_retention: AuditPayloadRetention = "redacted",
        redaction_policy_id: str = "default",
        redacted_field_paths: Iterable[str] = (),
        tags: Mapping[str, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dsn = dsn
        self._audit_config = AuditPolicyConfig(
            enabled=True,
            dsn=dsn,
            failure_policy=failure_policy,
            retention=retention,
            payload_retention=payload_retention,
            redaction_policy_id=redaction_policy_id,
            redacted_field_paths=tuple(redacted_field_paths),
            duplicate_strategy=duplicate_strategy,
            tags=dict(tags or {}),
        )
        self._logger = logger or logging.getLogger("bpg.audit")

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | PostgresAuditConfig | None,
    ) -> "PostgresAuditEventSink | None":
        audit_config = (
            config if isinstance(config, PostgresAuditConfig) else PostgresAuditConfig.from_mapping(config)
        )
        if not audit_config.enabled:
            return None
        if not audit_config.dsn:
            dsn_hint = f" or populated dsn_env={audit_config.dsn_env}" if audit_config.dsn_env else ""
            raise ValueError(f"Postgres audit sink requires a dsn{dsn_hint}")
        return cls(
            dsn=audit_config.dsn,
            duplicate_strategy=audit_config.duplicate_strategy,
            failure_policy=audit_config.failure_policy,
            retention=audit_config.retention,
            payload_retention=audit_config.payload_retention,
            redaction_policy_id=audit_config.redaction_policy_id,
            redacted_field_paths=audit_config.redacted_field_paths,
            tags=audit_config.tags,
        )

    def emit(self, event: BpgEvent) -> BpgEvent | None:
        if not is_audit_worthy_event(event):
            return None
        audited_event = apply_audit_policy(event, self._audit_config)
        try:
            self.insert_event(audited_event)
        except Exception as exc:  # noqa: BLE001
            if self._audit_config.failure_policy == "fail_run":
                raise AuditSinkFailure(f"Postgres audit event insert failed: {exc}") from exc
            self._logger.warning("Postgres audit event insert failed: %s", exc)
        return audited_event

    def setup_schema(self) -> None:
        """Create the audit ledger schema and immutability controls."""
        with self._connect() as conn:
            conn.execute(AUDIT_SCHEMA_SQL)
            conn.commit()

    def insert_event(self, event: BpgEvent) -> AuditRecord | None:
        """Insert one event, serialized by run-scoped advisory locks."""
        if not is_audit_worthy_event(event):
            return None

        try:
            from psycopg.errors import UniqueViolation
            from psycopg.types.json import Jsonb
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("psycopg is required for Postgres audit support") from exc

        with self._connect() as conn:
            try:
                with conn.transaction():
                    chain_scope = "run"
                    chain_id = event.run_id
                    conn.execute(
                        "select pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                        (chain_scope, chain_id),
                    )
                    sequence_row = conn.execute(
                        "select nextval(pg_get_serial_sequence('audit_events', 'sequence_id'))"
                    ).fetchone()
                    sequence_id = sequence_row["nextval"]
                    previous_hash = conn.execute(
                        """
                        select event_hash
                        from audit_events
                        where chain_scope = %s and chain_id = %s
                        order by sequence_id desc
                        limit 1
                        """,
                        (chain_scope, chain_id),
                    ).fetchone()
                    record = build_audit_record(
                        event,
                        sequence_id=sequence_id,
                        previous_hash=previous_hash["event_hash"] if previous_hash else None,
                        chain_scope=chain_scope,
                        chain_id=chain_id,
                        audit_config=self._audit_config,
                    )
                    row = record.to_insert_row()
                    conn.execute(
                        """
                        insert into audit_events (
                          sequence_id, chain_scope, chain_id, event_id, event_type, occurred_at,
                          run_id, process_name, process_version, process_hash, node_id, node_type,
                          actor_id, actor_type, policy_id, correlation_id, external_ref,
                          trace_id, span_id, payload, payload_sha256, previous_hash, event_hash
                        )
                        values (
                          %(sequence_id)s, %(chain_scope)s, %(chain_id)s, %(event_id)s, %(event_type)s,
                          %(occurred_at)s, %(run_id)s, %(process_name)s, %(process_version)s,
                          %(process_hash)s, %(node_id)s, %(node_type)s, %(actor_id)s, %(actor_type)s,
                          %(policy_id)s, %(correlation_id)s, %(external_ref)s, %(trace_id)s,
                          %(span_id)s, %(payload)s, %(payload_sha256)s, %(previous_hash)s, %(event_hash)s
                        )
                        """,
                        {**row, "payload": Jsonb(row["payload"], dumps=canonical_json)},
                    )
                    return record
            except UniqueViolation as exc:
                conn.rollback()
                if self._audit_config.duplicate_strategy == "ignore":
                    return None
                raise DuplicateAuditEventError(f"duplicate audit event_id: {event.event_id}") from exc

    def create_checkpoint(
        self,
        *,
        scope: str = "global",
        run_id: str | None = None,
        anchor_provider: CheckpointAnchorProvider | None = None,
        signing_key: str | bytes | None = None,
        emit_event: bool = True,
    ) -> AuditChainCheckpoint:
        """Create a checkpoint over the latest global or run-specific chain head."""
        anchor_provider = anchor_provider or NoopCheckpointAnchorProvider()
        with self._connect() as conn:
            with conn.transaction():
                checkpoint = self._build_checkpoint(conn, scope=scope, run_id=run_id)
                signature = sign_checkpoint(checkpoint, signing_key=signing_key)
                checkpoint = AuditChainCheckpoint(
                    checkpoint_id=None,
                    created_at=None,
                    scope=checkpoint.scope,
                    last_sequence_id=checkpoint.last_sequence_id,
                    chain_head_hash=checkpoint.chain_head_hash,
                    signature=signature,
                )
                anchor = anchor_provider.anchor(checkpoint)
                row = conn.execute(
                    """
                    insert into audit_chain_checkpoints (
                      scope, last_sequence_id, chain_head_hash, anchored_ref, signature
                    )
                    values (%s, %s, %s, %s, %s)
                    returning checkpoint_id, created_at, scope, last_sequence_id,
                              chain_head_hash, anchored_ref, signature
                    """,
                    (
                        checkpoint.scope,
                        checkpoint.last_sequence_id,
                        checkpoint.chain_head_hash,
                        anchor.anchored_ref,
                        checkpoint.signature,
                    ),
                ).fetchone()
                saved = self._row_to_checkpoint(row)
            conn.commit()
        if emit_event:
            self.insert_event(checkpoint_to_event(saved))
        return saved

    def fetch_checkpoints(self, *, scope: str | None = None) -> list[AuditChainCheckpoint]:
        """Fetch checkpoints ordered by checkpoint id."""
        where = "where scope = %s" if scope is not None else ""
        params = (scope,) if scope is not None else ()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select checkpoint_id, created_at, scope, last_sequence_id,
                       chain_head_hash, anchored_ref, signature
                from audit_chain_checkpoints
                {where}
                order by checkpoint_id
                """,
                params,
            ).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    def latest_checkpoint(self, *, scope: str) -> AuditChainCheckpoint | None:
        """Fetch the latest checkpoint for a scope."""
        with self._connect() as conn:
            row = conn.execute(
                """
                select checkpoint_id, created_at, scope, last_sequence_id,
                       chain_head_hash, anchored_ref, signature
                from audit_chain_checkpoints
                where scope = %s
                order by checkpoint_id desc
                limit 1
                """,
                (scope,),
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def fetch_run_records(self, run_id: str) -> list[dict[str, Any]]:
        """Fetch ordered audit rows for one run."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  sequence_id, chain_scope, chain_id, event_id, event_type,
                  occurred_at, run_id, process_name,
                  process_version, process_hash, node_id, node_type, actor_id,
                  actor_type, policy_id, correlation_id, external_ref, trace_id,
                  span_id, payload, payload_sha256, previous_hash, event_hash
                from audit_events
                where chain_scope = 'run' and chain_id = %s
                order by sequence_id
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_run(
        self,
        run_id: str,
        *,
        checkpoint: AuditChainCheckpoint | Mapping[str, Any] | None = None,
        require_anchor: bool = False,
        signing_key: str | bytes | None = None,
    ) -> AuditChainVerification:
        """Verify the stored chain for one run."""
        return verify_audit_chain(
            self.fetch_run_records(run_id),
            checkpoint=checkpoint,
            require_anchor=require_anchor,
            signing_key=signing_key,
        )

    def verify_from_latest_checkpoint(
        self,
        run_id: str,
        *,
        require_anchor: bool = False,
        signing_key: str | bytes | None = None,
    ) -> AuditChainVerification:
        """Verify one run from its latest checkpoint if present."""
        checkpoint = self.latest_checkpoint(scope=f"run:{run_id}")
        return self.verify_run(
            run_id,
            checkpoint=checkpoint,
            require_anchor=require_anchor,
            signing_key=signing_key,
        )

    def _build_checkpoint(self, conn: Any, *, scope: str, run_id: str | None) -> AuditChainCheckpoint:
        if run_id is not None:
            row = conn.execute(
                """
                select sequence_id, event_hash
                from audit_events
                where chain_scope = 'run' and chain_id = %s
                order by sequence_id desc
                limit 1
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"cannot checkpoint empty run audit chain: {run_id}")
            return AuditChainCheckpoint(
                checkpoint_id=None,
                created_at=None,
                scope=f"run:{run_id}",
                last_sequence_id=row["sequence_id"],
                chain_head_hash=row["event_hash"],
            )

        if scope != "global":
            raise ValueError("custom checkpoint scopes must provide run_id")
        rows = conn.execute(
            """
            select distinct on (chain_scope, chain_id)
                   chain_scope, chain_id, sequence_id, event_hash
            from audit_events
            order by chain_scope, chain_id, sequence_id desc
            """
        ).fetchall()
        if not rows:
            raise ValueError("cannot checkpoint empty audit ledger")
        heads = [
            {
                "chain_scope": row["chain_scope"],
                "chain_id": row["chain_id"],
                "sequence_id": row["sequence_id"],
                "event_hash": row["event_hash"],
            }
            for row in rows
        ]
        return AuditChainCheckpoint(
            checkpoint_id=None,
            created_at=None,
            scope="global",
            last_sequence_id=max(row["sequence_id"] for row in rows),
            chain_head_hash=sha256_json(heads),
        )

    def _row_to_checkpoint(self, row: Mapping[str, Any]) -> AuditChainCheckpoint:
        return AuditChainCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            created_at=str(row["created_at"]) if row.get("created_at") is not None else None,
            scope=row["scope"],
            last_sequence_id=row["last_sequence_id"],
            chain_head_hash=row["chain_head_hash"],
            anchored_ref=row.get("anchored_ref"),
            signature=row.get("signature"),
        )

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._dsn, row_factory=dict_row)
