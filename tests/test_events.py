from bpg.runtime.events import EVENT_SCHEMA_VERSION, normalize_event, replay_state_from_events


def test_normalize_event_adds_schema_version_and_event_type():
    ev = normalize_event({"event": "node_failed", "node": "triage", "status": "failed"}, run_id="r1")
    assert ev["schema_version"] == EVENT_SCHEMA_VERSION
    assert ev["event_type"] == "node_failed"
    assert ev["run_id"] == "r1"
    assert "timestamp" in ev


def test_replay_state_from_events_reconstructs_statuses():
    events = [
        {"event_type": "run_started"},
        {"event_type": "node_scheduled", "node": "extract"},
        {"event_type": "node_completed", "node": "extract", "status": "completed"},
        {"event_type": "node_scheduled", "node": "review"},
        {"event_type": "node_completed", "node": "review", "status": "skipped"},
        {"event_type": "run_completed"},
    ]
    replayed = replay_state_from_events(events)
    assert replayed["run_status"] == "completed"
    assert replayed["node_statuses"]["extract"] == "completed"
    assert replayed["node_statuses"]["review"] == "skipped"
    assert replayed["event_counts"]["node_completed"] == 2
