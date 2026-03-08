from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from bpg.dashboard.server import DashboardConfig, create_server
from bpg.state.store import StateStore


def _write_process(tmp_path: Path) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: dash-proc
  version: 1.0.0
types:
  TriggerIn:
    title: string
    severity: enum(low,high)
node_types:
  ingest@v1:
    in: TriggerIn
    out: TriggerIn
    provider: core.passthrough
    version: v1
    config_schema: {}
nodes:
  ingest:
    type: ingest@v1
    config: {}
trigger: ingest
edges: []
"""
    )
    return process_file


def _get_json(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(base_url: str, path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_slack_interaction(
    base_url: str,
    payload: dict,
    *,
    signing_secret: str,
    tamper_signature: bool = False,
) -> tuple[int, dict]:
    body = urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    timestamp = str(int(time.time()))
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if tamper_signature:
        signature = "v0=deadbeef"
    req = urllib.request.Request(
        f"{base_url}/api/slack/interactions",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_dashboard_server_serves_process_graph_and_trigger(tmp_path: Path):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        process = _get_json(base_url, "/api/process")
        assert process["name"] == "dash-proc"
        assert process["trigger"] == "ingest"
        assert "title" in process["trigger_schema"]["fields"]

        graph = _get_json(base_url, "/api/graph")
        assert "<svg" in graph["html"]

        runs_before = _get_json(base_url, "/api/runs?limit=10")
        assert runs_before["runs"] == []

        trigger = _post_json(
            base_url,
            "/api/trigger",
            {"title": "Broken login", "severity": "high"},
        )
        run_id = trigger["run_id"]
        assert run_id

        run = _get_json(base_url, f"/api/runs/{run_id}")
        assert run["process_name"] == "dash-proc"

        events = _get_json(base_url, f"/api/runs/{run_id}/events?tail=100")
        assert events["run_id"] == run_id
        assert isinstance(events["events"], list)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_index_page_loads(tmp_path: Path):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"{base_url}/") as resp:
            html = resp.read().decode("utf-8")
        assert "BPG Dashboard" in html
        assert "Trigger Input" in html
        assert "Inbox" in html
        assert "Event Log" in html
        assert "join('\\n')" in html
        assert ".run-item.is-selected" in html
        assert "waiting_human" in html
        assert "e.g. 1,2,3 or 1-3" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_trigger_returns_json_error_on_runtime_failure(tmp_path: Path, monkeypatch):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    def _boom(self, payload):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("bpg.runtime.engine.Engine.trigger", _boom)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.dumps({"title": "x", "severity": "low"}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/trigger",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req):
                pass
            assert False, "expected HTTP 500 from /api/trigger"
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            body = json.loads(exc.read().decode("utf-8"))
            assert "Trigger failed: boom" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_trigger_succeeds_with_fresh_bind_mount_state_dir(tmp_path: Path):
    """Dashboard trigger must not raise when state dir has no subdirectories yet.

    Reproduces the Docker bind-mount scenario: ./state is created with .gitkeep
    only, then mounted as /app/.bpg-state.  The trigger request must succeed
    without FileNotFoundError on the processes/ subdirectory.
    """
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    state_dir.mkdir()
    (state_dir / ".gitkeep").write_text("")  # Mimic bundle's state/.gitkeep

    assert not (state_dir / "processes").exists()

    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        trigger = _post_json(base_url, "/api/trigger", {"title": "Bug", "severity": "high"})
        assert "run_id" in trigger
        assert trigger["run_id"]

        # State subdirectories must now exist
        assert (state_dir / "processes").is_dir()
        assert (state_dir / "runs").is_dir()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_artifacts_list_and_download(tmp_path: Path):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    store = StateStore(state_dir)
    store.create_run("run-1", "dash-proc", {"title": "x", "severity": "low"})
    store.update_run("run-1", {"status": "completed"})
    store.save_run_artifact(
        "run-1",
        name="result",
        payload={"ok": True},
        format="json",
    )

    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        artifacts = _get_json(base_url, "/api/runs/run-1/artifacts")
        assert artifacts["run_id"] == "run-1"
        assert len(artifacts["artifacts"]) == 1
        item = artifacts["artifacts"][0]
        assert item["name"] == "result"
        assert item["artifact_path"].endswith("result.json")
        assert item["download_url"] == "/api/runs/run-1/artifacts/result/download"

        with urllib.request.urlopen(f"{base_url}{item['download_url']}") as resp:
            body = resp.read().decode("utf-8")
            assert '"ok": true' in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_inbox_waiting_and_respond(tmp_path: Path, monkeypatch):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    store = StateStore(state_dir)
    store.create_run("run-1", "dash-proc", {"title": "x", "severity": "low"})
    store.save_pending_interaction(
        "ik-1",
        {
            "run_id": "run-1",
            "process_name": "dash-proc",
            "node_name": "approval",
            "provider_id": "dashboard.form",
            "input": {"approved": False, "reason": ""},
        },
    )

    stepped: list[str] = []

    def _step(self, run_id):  # noqa: ANN001
        stepped.append(run_id)

    monkeypatch.setattr("bpg.runtime.engine.Engine.step", _step)

    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        inbox = _get_json(base_url, "/api/inbox?limit=10")
        assert len(inbox["interactions"]) == 1
        assert inbox["interactions"][0]["run_id"] == "run-1"
        assert inbox["interactions"][0]["status"] == "pending"

        waiting = _get_json(base_url, "/api/runs/run-1/waiting")
        assert waiting["run_id"] == "run-1"
        assert waiting["waiting"][0]["idempotency_key"] == "ik-1"

        out = _post_json(base_url, "/api/interactions/ik-1/respond", {"approved": True, "reason": "ok"})
        assert out["idempotency_key"] == "ik-1"
        assert out["response"]["approved"] is True
        assert stepped == ["run-1"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_slack_interactions_callback_resumes_run(tmp_path: Path, monkeypatch):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    store = StateStore(state_dir)
    store.create_run("run-1", "dash-proc", {"title": "x", "severity": "low"})
    store.save_pending_interaction(
        "ik-1",
        {
            "run_id": "run-1",
            "process_name": "dash-proc",
            "node_name": "approval",
            "provider_id": "slack.interactive",
            "input": {"title": "Approve incident"},
        },
    )
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")

    stepped: list[str] = []

    def _step(self, run_id):  # noqa: ANN001
        stepped.append(run_id)

    monkeypatch.setattr("bpg.runtime.engine.Engine.step", _step)

    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_slack_interaction(
            base_url,
            {
                "type": "block_actions",
                "user": {"id": "U123"},
                "actions": [{"action_id": "bpg__ik-1__approve"}],
            },
            signing_secret="test-secret",
        )
        assert status == 200
        assert body["ok"] is True
        assert body["response"]["approved"] is True
        assert body["response"]["slack_user_id"] == "U123"
        assert stepped == ["run-1"]

        saved = store.load_interaction_response("ik-1")
        assert saved is not None
        assert saved["approved"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_dashboard_html_contains_src_check_in_edge_logic():
    """applyGraphState must check srcStatus (not just tgtStatus) for edge green highlight."""
    from bpg.dashboard.server import _dashboard_html
    html = _dashboard_html()
    assert "srcStatus === 'completed'" in html


def test_dashboard_html_contains_selected_node_state():
    """applyGraphState must track selectedNodeName and apply highlight on click."""
    from bpg.dashboard.server import _dashboard_html
    html = _dashboard_html()
    assert 'selectedNodeName' in html
    assert 'selected-node' in html


def test_dashboard_slack_interactions_rejects_invalid_signature(tmp_path: Path, monkeypatch):
    process_file = _write_process(tmp_path)
    state_dir = tmp_path / ".bpg-state"
    store = StateStore(state_dir)
    store.create_run("run-1", "dash-proc", {"title": "x", "severity": "low"})
    store.save_pending_interaction(
        "ik-1",
        {
            "run_id": "run-1",
            "process_name": "dash-proc",
            "node_name": "approval",
            "provider_id": "slack.interactive",
            "input": {"title": "Approve incident"},
        },
    )
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")

    config = DashboardConfig(
        state_dir=state_dir,
        process_name="dash-proc",
        process_file=process_file,
    )
    server = create_server(config=config, host="127.0.0.1", port=0)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_slack_interaction(
            base_url,
            {
                "type": "block_actions",
                "actions": [{"action_id": "bpg__ik-1__approve"}],
            },
            signing_secret="test-secret",
            tamper_signature=True,
        )
        assert status == 401
        assert "Invalid Slack signature" in body["error"]
        assert store.load_interaction_response("ik-1") is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
