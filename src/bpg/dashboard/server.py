from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.compiler.visualizer import generate_html
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore


@dataclass(frozen=True)
class DashboardConfig:
    state_dir: Path
    process_name: str
    process_file: Path


def _field_kind(type_expr: str) -> dict[str, Any]:
    raw = str(type_expr).strip()
    if raw.startswith("enum(") and raw.endswith(")"):
        values = [v.strip() for v in raw[5:-1].split(",") if v.strip()]
        return {"kind": "enum", "values": values}
    if raw.startswith("list<") and raw.endswith(">"):
        return {"kind": "list", "item": raw[5:-1]}
    if raw in {"string", "number", "integer", "bool", "object"}:
        return {"kind": raw}
    if raw.endswith("?"):
        base = raw[:-1]
        inner = _field_kind(base)
        inner["optional"] = True
        return inner
    return {"kind": "string"}


def _load_process(config: DashboardConfig):
    store = StateStore(config.state_dir)
    process = store.load_process(config.process_name)
    if process is not None:
        return process
    if config.process_file.exists():
        process = parse_process_file(config.process_file)
        validate_process(process)
        return process
    return None


def _trigger_schema(process) -> dict[str, Any]:
    trigger_node = process.nodes.get(process.trigger)
    if trigger_node is None:
        return {"trigger": process.trigger, "fields": {}}
    node_type = process.node_types.get(trigger_node.node_type)
    if node_type is None:
        return {"trigger": process.trigger, "fields": {}}
    input_type_name = node_type.input_type
    type_def = process.types.get(input_type_name)
    fields: dict[str, Any] = {}
    if type_def is not None:
        for field_name, field_type in type_def.items():
            field_spec = _field_kind(field_type)
            field_spec.setdefault("optional", str(field_type).endswith("?"))
            fields[field_name] = field_spec
    return {
        "trigger": process.trigger,
        "input_type": input_type_name,
        "fields": fields,
    }


def _process_summary(process_name: str, process) -> dict[str, Any]:
    metadata = process.metadata
    return {
        "name": process_name,
        "version": metadata.version if metadata else None,
        "description": metadata.description if metadata else None,
        "trigger": process.trigger,
        "trigger_schema": _trigger_schema(process),
    }


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>BPG Dashboard</title>
  <style>
    body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #f6f7f9; color: #111827; }
    header { padding: 12px 16px; background: #111827; color: #fff; font-weight: 700; }
    .layout { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; padding: 12px; }
    .panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
    .panel h3 { margin: 0; padding: 10px 12px; font-size: 14px; border-bottom: 1px solid #e5e7eb; background: #f9fafb; }
    .panel .body { padding: 10px 12px; }
    iframe { width: 100%; height: 70vh; border: 0; }
    .stack { display: grid; gap: 12px; }
    .events { max-height: 32vh; overflow: auto; font-size: 12px; white-space: pre-wrap; background: #0b1020; color: #e5e7eb; padding: 8px; border-radius: 6px; }
    .runs { width: 100%; }
    .run-item { padding: 6px 8px; border-bottom: 1px dashed #e5e7eb; font-size: 12px; border-radius: 6px; cursor: pointer; }
    .run-item:hover { background: #f3f4f6; }
    .run-item.is-selected { background: #dbeafe; border-bottom-color: #93c5fd; }
    .run-item:last-child { border-bottom: none; }
    .form-row { display: grid; gap: 4px; margin-bottom: 8px; }
    label { font-size: 12px; color: #374151; }
    input, textarea, select { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; }
    button { padding: 8px 10px; background: #111827; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
    #error { color: #b91c1c; font-size: 12px; }
    #info { color: #065f46; font-size: 12px; }
  </style>
</head>
<body>
  <header>BPG Dashboard</header>
  <div class=\"layout\">
    <section class=\"panel\">
      <h3>Process Graph</h3>
      <div class=\"body\"><iframe id=\"graphFrame\" title=\"BPG graph\"></iframe></div>
    </section>
    <section class=\"stack\">
      <div class=\"panel\">
        <h3>Runs</h3>
        <div class=\"body\">
          <div id=\"runs\" class=\"runs\"></div>
        </div>
      </div>
      <div class=\"panel\">
        <h3>Event Log</h3>
        <div class=\"body\"><div id=\"events\" class=\"events\"></div></div>
      </div>
      <div class=\"panel\">
        <h3>Artifacts</h3>
        <div class=\"body\"><div id=\"artifacts\" class=\"runs\"></div></div>
      </div>
      <div class=\"panel\">
        <h3>Trigger Input</h3>
        <div class=\"body\">
          <form id=\"triggerForm\"></form>
          <div id=\"error\"></div>
          <div id=\"info\"></div>
        </div>
      </div>
    </section>
  </div>
<script>
const state = { process: null, runs: [], selectedRun: null, artifacts: [] };

async function getJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
  return await res.json();
}

function renderRuns() {
  const root = document.getElementById('runs');
  root.innerHTML = '';
  for (const run of state.runs) {
    const el = document.createElement('div');
    el.className = 'run-item' + (state.selectedRun === run.run_id ? ' is-selected' : '');
    el.innerHTML = `<strong>${run.run_id}</strong><br/>status=${run.status} started=${run.started_at || ''}`;
    el.onclick = () => { state.selectedRun = run.run_id; renderRuns(); refreshEvents(); refreshArtifacts(); };
    root.appendChild(el);
  }
}

async function refreshEvents() {
  const root = document.getElementById('events');
  if (!state.selectedRun) { root.textContent = 'No run selected'; return; }
  try {
    const payload = await getJson(`/api/runs/${state.selectedRun}/events?tail=500`);
    root.textContent = payload.events.map((e) => JSON.stringify(e)).join('\\n');
  } catch (err) {
    root.textContent = String(err);
  }
}

function renderArtifacts() {
  const root = document.getElementById('artifacts');
  root.innerHTML = '';
  if (!state.selectedRun) { root.textContent = 'No run selected'; return; }
  if (!state.artifacts.length) { root.textContent = 'No artifacts for this run'; return; }
  for (const artifact of state.artifacts) {
    const el = document.createElement('div');
    el.className = 'run-item';
    const location = artifact.artifact_path || artifact.path || '';
    const download = artifact.download_url || '#';
    el.innerHTML = `<strong>${artifact.name || 'artifact'}</strong> (${artifact.format || ''})<br/>${location}<br/><a href="${download}" target="_blank" rel="noopener">Download</a>`;
    root.appendChild(el);
  }
}

async function refreshArtifacts() {
  const root = document.getElementById('artifacts');
  if (!state.selectedRun) { root.textContent = 'No run selected'; return; }
  try {
    const payload = await getJson(`/api/runs/${state.selectedRun}/artifacts`);
    state.artifacts = payload.artifacts || [];
    renderArtifacts();
  } catch (err) {
    root.textContent = String(err);
  }
}

function renderTriggerForm() {
  const form = document.getElementById('triggerForm');
  form.innerHTML = '';
  const schema = (state.process || {}).trigger_schema || { fields: {} };
  const parseListInput = (raw, itemKind) => {
    const text = String(raw || '').trim();
    if (!text) return [];
    const normalized = text.replace(/,/g, ' ').trim();
    const tokens = normalized.split(/\\s+/).filter(Boolean);
    const out = [];
    for (const token of tokens) {
      const rangeMatch = token.match(/^(-?\\d+)-(-?\\d+)$/);
      if (rangeMatch && (itemKind === 'number' || itemKind === 'integer')) {
        let start = Number(rangeMatch[1]);
        let end = Number(rangeMatch[2]);
        if (!Number.isFinite(start) || !Number.isFinite(end)) throw new Error(`Invalid range '${token}'`);
        const step = start <= end ? 1 : -1;
        for (let n = start; step > 0 ? n <= end : n >= end; n += step) out.push(n);
        continue;
      }
      if (itemKind === 'number' || itemKind === 'integer') {
        const num = Number(token);
        if (!Number.isFinite(num)) throw new Error(`Expected numeric list item, got '${token}'`);
        out.push(itemKind === 'integer' ? Math.trunc(num) : num);
      } else if (itemKind === 'bool') {
        if (token !== 'true' && token !== 'false') throw new Error(`Expected bool list item, got '${token}'`);
        out.push(token === 'true');
      } else {
        out.push(token);
      }
    }
    return out;
  };
  for (const [name, spec] of Object.entries(schema.fields || {})) {
    const row = document.createElement('div');
    row.className = 'form-row';
    const label = document.createElement('label');
    label.textContent = `${name}${spec.optional ? ' (optional)' : ''}`;
    row.appendChild(label);

    let input;
    if (spec.kind === 'bool') {
      input = document.createElement('select');
      input.innerHTML = '<option value="">(unset)</option><option value="true">true</option><option value="false">false</option>';
    } else if (spec.kind === 'enum') {
      input = document.createElement('select');
      input.innerHTML = ['<option value="">(select)</option>', ...spec.values.map((v) => `<option value="${v}">${v}</option>`)].join('');
    } else {
      input = document.createElement('input');
      input.type = spec.kind === 'number' || spec.kind === 'integer' ? 'number' : 'text';
      if (spec.kind === 'list') {
        input.placeholder = spec.item === 'number' || spec.item === 'integer'
          ? 'e.g. 1,2,3 or 1-3'
          : 'comma or space separated values';
      }
    }
    input.name = name;
    row.appendChild(input);
    form.appendChild(row);
  }
  const btn = document.createElement('button');
  btn.type = 'submit';
  btn.textContent = 'Trigger Run';
  form.appendChild(btn);

  form.onsubmit = async (ev) => {
    ev.preventDefault();
    document.getElementById('error').textContent = '';
    document.getElementById('info').textContent = '';
    const payload = {};
    const schema = (state.process || {}).trigger_schema || { fields: {} };
    for (const [name, spec] of Object.entries(schema.fields || {})) {
      const value = form.elements[name].value;
      if (value === '') continue;
      if (spec.kind === 'number') payload[name] = Number(value);
      else if (spec.kind === 'integer') payload[name] = Math.trunc(Number(value));
      else if (spec.kind === 'bool') payload[name] = value === 'true';
      else if (spec.kind === 'list') payload[name] = parseListInput(value, spec.item || 'string');
      else payload[name] = value;
    }
    try {
      const res = await fetch('/api/trigger', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || `HTTP ${res.status}`);
      document.getElementById('info').textContent = `Triggered run ${out.run_id}`;
      await refreshRuns();
    } catch (err) {
      document.getElementById('error').textContent = String(err);
    }
  };
}

async function refreshRuns() {
  const payload = await getJson('/api/runs?limit=20');
  state.runs = payload.runs || [];
  renderRuns();
  if (!state.selectedRun && state.runs.length > 0) state.selectedRun = state.runs[0].run_id;
  await refreshEvents();
  await refreshArtifacts();
}

async function bootstrap() {
  try {
    const process = await getJson('/api/process');
    state.process = process;
    renderTriggerForm();
    const graph = await getJson('/api/graph');
    document.getElementById('graphFrame').srcdoc = graph.html;
    await refreshRuns();
    setInterval(refreshRuns, 2000);
  } catch (err) {
    document.getElementById('error').textContent = String(err);
  }
}
bootstrap();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    config: DashboardConfig

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, status: int, *, body: bytes, filename: str, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _process_or_404(self):
        process = _load_process(self.config)
        if process is None:
            self._send_json(404, {"error": f"Process '{self.config.process_name}' not found"})
            return None
        return process

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in {"/", "/index.html"}:
            self._send_html(200, _dashboard_html())
            return

        if path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        if path == "/api/process":
            process = self._process_or_404()
            if process is None:
                return
            self._send_json(200, _process_summary(self.config.process_name, process))
            return

        if path == "/api/graph":
            process = self._process_or_404()
            if process is None:
                return
            ir = compile_process(process)
            html = generate_html(ir)
            self._send_json(200, {"html": html})
            return

        if path == "/api/runs":
            limit = int((query.get("limit") or ["50"])[0])
            store = StateStore(self.config.state_dir)
            runs = store.list_runs(process_name=self.config.process_name)[: max(1, limit)]
            self._send_json(200, {"runs": runs})
            return

        if path.startswith("/api/runs/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3:
                run_id = parts[2]
                store = StateStore(self.config.state_dir)
                if len(parts) == 3:
                    run = store.load_run(run_id)
                    if run is None:
                        self._send_json(404, {"error": f"Run '{run_id}' not found"})
                        return
                    self._send_json(200, run)
                    return
                if len(parts) == 4 and parts[3] == "events":
                    tail = int((query.get("tail") or ["500"])[0])
                    events = store.load_execution_log(run_id)
                    if tail > 0:
                        events = events[-tail:]
                    self._send_json(200, {"run_id": run_id, "events": events})
                    return
                if len(parts) == 4 and parts[3] == "nodes":
                    nodes = store.list_node_records(run_id)
                    self._send_json(200, {"run_id": run_id, "nodes": nodes})
                    return
                if len(parts) == 4 and parts[3] == "artifacts":
                    artifacts = store.list_run_artifacts(run_id)
                    for item in artifacts:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if isinstance(name, str) and name:
                            item["download_url"] = f"/api/runs/{run_id}/artifacts/{name}/download"
                        item["artifact_path"] = item.get("path")
                    self._send_json(200, {"run_id": run_id, "artifacts": artifacts})
                    return
                if len(parts) == 6 and parts[3] == "artifacts" and parts[5] == "download":
                    artifact_name = unquote(parts[4])
                    artifacts = store.list_run_artifacts(run_id)
                    selected: dict[str, Any] | None = None
                    for item in artifacts:
                        if not isinstance(item, dict):
                            continue
                        if item.get("name") == artifact_name:
                            selected = item
                            break
                    if selected is None:
                        self._send_json(404, {"error": f"Artifact '{artifact_name}' not found"})
                        return
                    raw_path = selected.get("path")
                    if not isinstance(raw_path, str) or not raw_path:
                        self._send_json(404, {"error": f"Artifact '{artifact_name}' has no path"})
                        return
                    artifact_path = Path(raw_path)
                    run_dir = (self.config.state_dir / "runs" / run_id).resolve()
                    resolved = artifact_path.resolve()
                    if run_dir not in resolved.parents:
                        self._send_json(403, {"error": "Artifact path is outside run directory"})
                        return
                    if not resolved.exists() or not resolved.is_file():
                        self._send_json(404, {"error": f"Artifact file not found: {resolved}"})
                        return
                    body = resolved.read_bytes()
                    self._send_file(200, body=body, filename=resolved.name)
                    return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/trigger":
            self._send_json(404, {"error": "Not found"})
            return

        process = self._process_or_404()
        if process is None:
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Trigger payload must be a JSON object"})
            return

        store = StateStore(self.config.state_dir)
        try:
            run_id = Engine(process=process, state_store=store).trigger(payload)
        except Exception as exc:  # pragma: no cover - defensive API boundary
            self._send_json(500, {"error": f"Trigger failed: {exc}"})
            return
        self._send_json(200, {"run_id": run_id})

    def log_message(self, fmt, *args):  # noqa: A003
        _ = fmt, args


def create_server(config: DashboardConfig, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    class _ConfiguredDashboardHandler(DashboardHandler):
        pass

    _ConfiguredDashboardHandler.config = config
    return ThreadingHTTPServer((host, port), _ConfiguredDashboardHandler)


def run_dashboard_server() -> None:
    state_dir = Path(os.getenv("BPG_STATE_DIR", ".bpg-state"))
    process_name = os.getenv("BPG_PROCESS_NAME", "default")
    process_file = Path(os.getenv("BPG_PROCESS_FILE", "process.bpg.yaml"))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))

    config = DashboardConfig(
        state_dir=state_dir,
        process_name=process_name,
        process_file=process_file,
    )
    server = create_server(config=config, host=host, port=port)
    browser_host = "localhost" if host in {"0.0.0.0", "::"} else host
    print(f"BPG dashboard listening on http://{browser_host}:{port} (bind={host})")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard_server()
