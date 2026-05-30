"""Audit event schema completeness and sink behavior tests."""

from __future__ import annotations

import pytest

from bpg_sdk.audit import AuditEvent, AuditEventType, AuditSink, ListAuditSink


class TestAuditEventType:
    def test_approval_event_types_present(self):
        assert AuditEventType.APPROVAL_REQUESTED
        assert AuditEventType.APPROVED
        assert AuditEventType.REJECTED
        assert AuditEventType.ESCALATED
        assert AuditEventType.TIMED_OUT

    def test_policy_event_types_present(self):
        assert AuditEventType.POLICY_CHECKED
        assert AuditEventType.POLICY_BLOCKED

    def test_node_event_types_present(self):
        assert AuditEventType.NODE_STARTED
        assert AuditEventType.NODE_COMPLETED
        assert AuditEventType.NODE_FAILED


class TestAuditEventSchema:
    def test_required_fields(self):
        event = AuditEvent(
            event_type=AuditEventType.APPROVED,
            workflow_id="wf-1",
            node_id="send_invoice",
        )
        assert event.event_type == AuditEventType.APPROVED
        assert event.workflow_id == "wf-1"
        assert event.node_id == "send_invoice"

    def test_timestamp_auto_populated(self):
        event = AuditEvent(
            event_type=AuditEventType.APPROVED,
            workflow_id="wf-1",
            node_id="send_invoice",
        )
        assert event.timestamp is not None
        assert "T" in event.timestamp  # ISO 8601

    def test_optional_fields_default_none(self):
        event = AuditEvent(
            event_type=AuditEventType.NODE_STARTED,
            workflow_id="wf-2",
            node_id="fetch_data",
        )
        assert event.actor_id is None
        assert event.policy_id is None
        assert event.correlation_id is None
        assert event.external_ref is None
        assert event.reason is None

    def test_optional_fields_populated(self):
        event = AuditEvent(
            event_type=AuditEventType.APPROVED,
            workflow_id="wf-3",
            node_id="deploy",
            actor_id="alice@example.com",
            policy_id="require-approval",
            correlation_id="corr-abc",
            external_ref="jira:PROJ-123",
            reason="Reviewed and approved",
        )
        assert event.actor_id == "alice@example.com"
        assert event.policy_id == "require-approval"
        assert event.correlation_id == "corr-abc"
        assert event.external_ref == "jira:PROJ-123"
        assert event.reason == "Reviewed and approved"

    def test_payload_defaults_empty_dict(self):
        event = AuditEvent(
            event_type=AuditEventType.NODE_FAILED,
            workflow_id="wf-4",
            node_id="send_email",
        )
        assert event.payload == {}

    def test_payload_populated(self):
        event = AuditEvent(
            event_type=AuditEventType.POLICY_BLOCKED,
            workflow_id="wf-5",
            node_id="delete_records",
            payload={"reason": "requires_2fa", "risk_level": "high"},
        )
        assert event.payload["risk_level"] == "high"

    def test_is_immutable(self):
        event = AuditEvent(
            event_type=AuditEventType.APPROVED,
            workflow_id="wf-6",
            node_id="approve",
        )
        with pytest.raises(Exception):
            event.actor_id = "modified"  # type: ignore[misc]

    def test_explicit_timestamp_accepted(self):
        event = AuditEvent(
            event_type=AuditEventType.REJECTED,
            workflow_id="wf-7",
            node_id="reject",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert event.timestamp == "2026-01-01T00:00:00+00:00"


class TestListAuditSink:
    def test_starts_empty(self):
        sink = ListAuditSink()
        assert sink.events == []

    def test_emit_accumulates_events(self):
        sink = ListAuditSink()
        sink.emit(AuditEvent(
            event_type=AuditEventType.APPROVAL_REQUESTED,
            workflow_id="wf-1",
            node_id="n1",
        ))
        sink.emit(AuditEvent(
            event_type=AuditEventType.APPROVED,
            workflow_id="wf-1",
            node_id="n1",
            actor_id="alice",
        ))
        assert len(sink.events) == 2

    def test_by_type_filters(self):
        sink = ListAuditSink()
        sink.emit(AuditEvent(event_type=AuditEventType.APPROVED, workflow_id="w", node_id="n"))
        sink.emit(AuditEvent(event_type=AuditEventType.REJECTED, workflow_id="w", node_id="n"))
        sink.emit(AuditEvent(event_type=AuditEventType.APPROVED, workflow_id="w", node_id="n2"))
        approved = sink.by_type(AuditEventType.APPROVED)
        assert len(approved) == 2

    def test_for_node_filters(self):
        sink = ListAuditSink()
        sink.emit(AuditEvent(event_type=AuditEventType.NODE_STARTED, workflow_id="w", node_id="n1"))
        sink.emit(AuditEvent(event_type=AuditEventType.NODE_STARTED, workflow_id="w", node_id="n2"))
        sink.emit(AuditEvent(event_type=AuditEventType.NODE_COMPLETED, workflow_id="w", node_id="n1"))
        n1_events = sink.for_node("n1")
        assert len(n1_events) == 2

    def test_is_audit_sink_subclass(self):
        sink = ListAuditSink()
        assert isinstance(sink, AuditSink)


class TestAuditEventCompleteness:
    """Verify that approval audit records carry all required operational fields."""

    def test_approval_request_event_completeness(self):
        event = AuditEvent(
            event_type=AuditEventType.APPROVAL_REQUESTED,
            workflow_id="wf-order-42",
            node_id="approve_order",
            correlation_id="order-42",
            actor_id=None,
            payload={"amount": 5000},
        )
        assert event.workflow_id == "wf-order-42"
        assert event.node_id == "approve_order"
        assert event.correlation_id == "order-42"
        assert event.payload["amount"] == 5000

    def test_rejection_event_carries_reason(self):
        event = AuditEvent(
            event_type=AuditEventType.REJECTED,
            workflow_id="wf-1",
            node_id="n1",
            actor_id="manager@example.com",
            reason="Budget cap exceeded",
        )
        assert event.reason == "Budget cap exceeded"
        assert event.actor_id == "manager@example.com"

    def test_policy_blocked_event_records_policy_id(self):
        event = AuditEvent(
            event_type=AuditEventType.POLICY_BLOCKED,
            workflow_id="wf-1",
            node_id="delete_customer_data",
            policy_id="gdpr-delete-guard",
            reason="Requires DPO approval",
        )
        assert event.policy_id == "gdpr-delete-guard"
