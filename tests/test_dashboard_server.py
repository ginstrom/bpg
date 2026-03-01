from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from bpg.dashboard.server import DashboardConfig, create_server


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
        assert "Event Log" in html
        assert "join('\\n')" in html
        assert ".run-item.is-selected" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
