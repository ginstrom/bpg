"""Telemetry field convention stability tests."""

from __future__ import annotations

from bpg_sdk.telemetry import TelemetryFields, build_span_attributes, build_log_record


class TestTelemetryFieldNames:
    def test_core_fields_use_bpg_prefix(self):
        assert TelemetryFields.WORKFLOW_ID.startswith("bpg.")
        assert TelemetryFields.NODE_ID.startswith("bpg.")
        assert TelemetryFields.ACTOR_ID.startswith("bpg.")
        assert TelemetryFields.POLICY_ID.startswith("bpg.")
        assert TelemetryFields.CORRELATION_ID.startswith("bpg.")
        assert TelemetryFields.EXTERNAL_REF.startswith("bpg.")
        assert TelemetryFields.RUN_ID.startswith("bpg.")
        assert TelemetryFields.PROCESS_NAME.startswith("bpg.")

    def test_span_names_defined(self):
        assert TelemetryFields.SPAN_WORKFLOW_RUN
        assert TelemetryFields.SPAN_NODE_EXECUTE
        assert TelemetryFields.SPAN_APPROVAL_WAIT

    def test_metric_names_defined(self):
        assert TelemetryFields.METRIC_APPROVAL_DURATION
        assert TelemetryFields.METRIC_NODE_DURATION
        assert TelemetryFields.METRIC_POLICY_DECISIONS

    def test_audit_event_type_field_defined(self):
        assert TelemetryFields.AUDIT_EVENT_TYPE.startswith("bpg.")

    def test_field_names_are_stable_strings(self):
        # Validate exact values so renames are a deliberate breaking change
        assert TelemetryFields.WORKFLOW_ID == "bpg.workflow_id"
        assert TelemetryFields.NODE_ID == "bpg.node_id"
        assert TelemetryFields.ACTOR_ID == "bpg.actor_id"
        assert TelemetryFields.POLICY_ID == "bpg.policy_id"
        assert TelemetryFields.CORRELATION_ID == "bpg.correlation_id"
        assert TelemetryFields.EXTERNAL_REF == "bpg.external_ref"
        assert TelemetryFields.RUN_ID == "bpg.run_id"
        assert TelemetryFields.PROCESS_NAME == "bpg.process_name"


class TestBuildSpanAttributes:
    def test_returns_dict_with_bpg_keys(self):
        attrs = build_span_attributes(
            workflow_id="wf-1",
            node_id="send_email",
        )
        assert attrs[TelemetryFields.WORKFLOW_ID] == "wf-1"
        assert attrs[TelemetryFields.NODE_ID] == "send_email"

    def test_optional_fields_omitted_when_none(self):
        attrs = build_span_attributes(workflow_id="wf-1", node_id="n1")
        assert TelemetryFields.ACTOR_ID not in attrs
        assert TelemetryFields.CORRELATION_ID not in attrs

    def test_optional_fields_included_when_provided(self):
        attrs = build_span_attributes(
            workflow_id="wf-1",
            node_id="n1",
            actor_id="alice",
            policy_id="require-approval",
            correlation_id="corr-001",
            external_ref="jira:PROJ-1",
            run_id="run-abc",
            process_name="invoice_flow",
        )
        assert attrs[TelemetryFields.ACTOR_ID] == "alice"
        assert attrs[TelemetryFields.POLICY_ID] == "require-approval"
        assert attrs[TelemetryFields.CORRELATION_ID] == "corr-001"
        assert attrs[TelemetryFields.EXTERNAL_REF] == "jira:PROJ-1"
        assert attrs[TelemetryFields.RUN_ID] == "run-abc"
        assert attrs[TelemetryFields.PROCESS_NAME] == "invoice_flow"


class TestBuildLogRecord:
    def test_log_record_includes_required_fields(self):
        record = build_log_record(
            event_type="node_started",
            workflow_id="wf-2",
            node_id="fetch_data",
        )
        assert record[TelemetryFields.WORKFLOW_ID] == "wf-2"
        assert record[TelemetryFields.NODE_ID] == "fetch_data"
        assert record["event_type"] == "node_started"

    def test_log_record_has_timestamp(self):
        record = build_log_record(
            event_type="node_completed",
            workflow_id="wf-3",
            node_id="n1",
        )
        assert "timestamp" in record
        assert record["timestamp"] is not None

    def test_log_record_audit_event_type_field(self):
        record = build_log_record(
            event_type="approval_requested",
            workflow_id="wf-4",
            node_id="approve",
        )
        assert record[TelemetryFields.AUDIT_EVENT_TYPE] == "approval_requested"

    def test_log_record_extra_payload(self):
        record = build_log_record(
            event_type="policy_blocked",
            workflow_id="wf-5",
            node_id="delete",
            extra={"risk_level": "high", "policy_id": "gdpr-guard"},
        )
        assert record["risk_level"] == "high"
        assert record["policy_id"] == "gdpr-guard"
