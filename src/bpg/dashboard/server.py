from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.compiler.visualizer import generate_html
from bpg.providers.slack_interactive import SlackInteractiveProvider
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore, StateStoreError


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


def _interaction_for_dashboard(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault("provider_id", "unknown")
    payload.setdefault("node_name", "")
    payload.setdefault("run_id", "")
    payload.setdefault("process_name", "")
    payload.setdefault("status", "pending")
    return payload


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
    .events { max-height: 26vh; overflow: auto; font-size: 12px; white-space: pre-wrap; background: #0b1020; color: #e5e7eb; padding: 8px; border-radius: 6px; }
    .runs { width: 100%; }
    .run-item { padding: 6px 8px; border-bottom: 1px dashed #e5e7eb; font-size: 12px; border-radius: 6px; cursor: pointer; }
    .run-item:hover { background: #f3f4f6; }
    .run-item.is-selected { background: #dbeafe; border-bottom-color: #93c5fd; }
    .run-item:last-child { border-bottom: none; }
    .form-row { display: grid; gap: 4px; margin-bottom: 8px; }
    label { font-size: 12px; color: #374151; }
    input, textarea, select { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; }
    button { padding: 8px 10px; background: #111827; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
    .inbox-form { margin-top: 8px; border-top: 1px solid #e5e7eb; padding-top: 8px; }
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
        <div class=\"body\"><div id=\"runs\" class=\"runs\"></div></div>
      </div>
      <div class=\"panel\">
        <h3>Inbox</h3>
        <div class=\"body\"><div id=\"inbox\" class=\"runs\"></div></div>
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
        <h3>Node Detail</h3>
        <div class=\"body\"><div id=\"nodeDetail\" class=\"events\" style=\"max-height:20vh;font-size:11px;\"></div></div>
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
const waiting_human = 'waiting_human';
const state = { process: null, runs: [], selectedRun: null, artifacts: [], inbox: [], waiting: [], nodeRecords: {}, selectedNodeName: null };

async function getJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`);
  return await res.json();
}

function inferKind(value) {
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
  return 'string';
}

async function respondInteraction(idempotencyKey, payload) {
  const res = await fetch(`/api/interactions/${encodeURIComponent(idempotencyKey)}/respond`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || `HTTP ${res.status}`);
  return out;
}

function applyGraphState(nodeStatusMap, waitingNodeNames, nodeRecords) {
  const frame = document.getElementById('graphFrame');
  const doc = frame.contentDocument;
  if (!doc) return;
  const waitingSet = new Set(waitingNodeNames || []);
  const texts = Array.from(doc.querySelectorAll('text'));
  for (const text of texts) {
    const nodeName = (text.textContent || '').trim();
    if (!nodeName) continue;
    const status = waitingSet.has(nodeName) ? waiting_human : (nodeStatusMap[nodeName] || '');
    let color = '#111827';
    if (status === waiting_human) color = '#d97706';
    else if (status === 'running') color = '#1d4ed8';
    else if (status === 'completed') color = '#047857';
    else if (status === 'failed') color = '#b91c1c';
    else if (status === 'skipped') color = '#6b7280';
    text.style.fill = color;
    text.style.fontWeight = status === waiting_human ? '700' : '500';
  }
  const paths = Array.from(doc.querySelectorAll('path[data-src]'));
  for (const path of paths) {
    const src = path.dataset.src;
    const tgt = path.dataset.tgt;
    const srcStatus = nodeStatusMap[src] || '';
    const tgtStatus = nodeStatusMap[tgt] || '';
    if (!srcStatus && !tgtStatus) continue;
    const taken = srcStatus === 'completed' && (tgtStatus === 'completed' || tgtStatus === 'running');
    const notTaken = srcStatus === 'skipped' || tgtStatus === 'skipped';
    if (notTaken && !taken) {
      path.setAttribute('stroke', '#d1d5db');
      path.setAttribute('stroke-dasharray', '4 3');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('marker-end', 'url(#ar)');
    } else if (taken) {
      path.setAttribute('stroke', '#059669');
      path.setAttribute('stroke-width', '2.5');
      path.removeAttribute('stroke-dasharray');
      path.setAttribute('marker-end', 'url(#ar-green)');
    }
  }
  const rects = Array.from(doc.querySelectorAll(\"rect[id^='node-']\"));
  for (const rect of rects) {
    const nodeName = rect.id.slice(5);
    rect.style.cursor = 'pointer';
    rect.classList.toggle('selected-node', nodeName === state.selectedNodeName);
    if (nodeName === state.selectedNodeName) {
      rect.setAttribute('stroke', '#3b82f6');
      rect.setAttribute('stroke-width', '3');
    } else if (rect.getAttribute('stroke') === '#3b82f6') {
      const isTrigger = state.process && nodeName === state.process.trigger;
      rect.setAttribute('stroke', isTrigger ? '#0ea5e9' : '#cbd5e1');
      rect.setAttribute('stroke-width', isTrigger ? '2' : '1');
    }
    rect.onclick = () => {
      state.selectedNodeName = nodeName;
      const nodeStatusMap = {};
      for (const [n, rec] of Object.entries(state.nodeRecords)) {
        nodeStatusMap[n] = rec.status || '';
      }
      const waitingNodeNames = state.waiting.map((i) => i.node_name).filter(Boolean);
      applyGraphState(nodeStatusMap, waitingNodeNames, state.nodeRecords);
      showNodeDetail(nodeName, state.nodeRecords);
    };
  }
}

function showNodeDetail(nodeName, nodeRecords) {
  const panel = document.getElementById('nodeDetail');
  if (!panel) return;
  const rec = (nodeRecords || {})[nodeName];
  if (!rec) { panel.textContent = `No record for ${nodeName}`; return; }
  const lines = [`Node: ${nodeName}`, `Status: ${rec.status || '\u2014'}`];
  if (rec.input) lines.push('', 'Input:', JSON.stringify(rec.input, null, 2));
  if (rec.output) lines.push('', 'Output:', JSON.stringify(rec.output, null, 2));
  panel.textContent = lines.join('\\n');
}

function renderRuns() {
  const root = document.getElementById('runs');
  root.innerHTML = '';
  for (const run of state.runs) {
    const el = document.createElement('div');
    el.className = 'run-item' + (state.selectedRun === run.run_id ? ' is-selected' : '');
    el.innerHTML = `<strong>${run.run_id}</strong><br/>status=${run.status} started=${run.started_at || ''}`;
    el.onclick = () => { state.selectedRun = run.run_id; renderRuns(); refreshSelectedRun(); };
    root.appendChild(el);
  }
}

function renderInbox() {
  const root = document.getElementById('inbox');
  root.innerHTML = '';
  const rows = state.inbox || [];
  if (!rows.length) { root.textContent = 'No pending interactions'; return; }

  for (const item of rows) {
    const el = document.createElement('div');
    el.className = 'run-item';
    const provider = item.provider_id || 'unknown';
    let decisionHtml = '';
    if (item.status === 'responded' && item.response && typeof item.response === 'object') {
      const resp = item.response;
      const decision = resp.decision;
      const approved = resp.approved;
      if (decision === 'deny' || approved === false) {
        decisionHtml = ' <span style=\"color:#b91c1c;font-weight:700\">\u2717 denied</span>';
      } else if (decision === 'approve' || approved === true) {
        decisionHtml = ' <span style=\"color:#047857;font-weight:700\">\u2713 approved</span>';
      } else {
        const pairs = Object.entries(resp).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ');
        decisionHtml = ` <span style=\"font-size:10px;color:#6b7280\">${pairs}</span>`;
      }
    }
    el.innerHTML = `<strong>${item.run_id}</strong><br/>${item.node_name} (${provider}) status=${item.status}${decisionHtml}`;
    el.onclick = () => { state.selectedRun = item.run_id; renderRuns(); refreshSelectedRun(); };

    if (provider === 'dashboard.form' && item.status === 'pending') {
      const form = document.createElement('form');
      form.className = 'inbox-form';
      const payload = item.input || {};
      const entries = Object.entries(payload);
      const hasDecision = entries.some(([name]) => name === 'decision');
      const hasApproved = entries.some(([name]) => name === 'approved');
      const looksLikeApprovalNode = String(item.node_name || '').toLowerCase().includes('approval');
      if (!hasDecision && !hasApproved && looksLikeApprovalNode) {
        entries.push(['decision', 'deny']);
      }
      if (!entries.length) entries.push(['approved', false], ['reason', '']);
      const hasDecisionControl = entries.some(([name]) => name === 'decision' || name === 'approved');
      for (const [name, current] of entries) {
        const kind = inferKind(current);
        let input;
        if (hasDecisionControl && name === 'decision') {
          input = document.createElement('input');
          input.type = 'hidden';
          input.value = String(current || 'deny') === 'approve' ? 'approve' : 'deny';
          input.dataset.kind = 'string';
          input.name = name;
          form.appendChild(input);
          continue;
        } else if (hasDecisionControl && name === 'approved' && kind === 'bool') {
          input = document.createElement('input');
          input.type = 'hidden';
          input.value = String(Boolean(current));
          input.dataset.kind = 'bool';
          input.name = name;
          form.appendChild(input);
          continue;
        }
        const row = document.createElement('div');
        row.className = 'form-row';
        const label = document.createElement('label');
        label.textContent = name;
        row.appendChild(label);
        if (kind === 'bool') {
          input = document.createElement('select');
          input.innerHTML = '<option value=\"true\">true</option><option value=\"false\">false</option>';
          input.value = String(Boolean(current));
          input.dataset.kind = 'bool';
        } else {
          input = document.createElement('input');
          input.type = kind === 'number' || kind === 'integer' ? 'number' : 'text';
          input.value = String(current ?? '');
          input.dataset.kind = kind;
        }
        input.name = name;
        row.appendChild(input);
        form.appendChild(row);
      }
      if (hasDecisionControl) {
        const actions = document.createElement('div');
        actions.className = 'form-row';
        const approveBtn = document.createElement('button');
        approveBtn.type = 'button';
        approveBtn.textContent = 'Approve';
        approveBtn.onclick = () => {
          const decision = form.elements['decision'];
          const approved = form.elements['approved'];
          if (decision) decision.value = 'approve';
          if (approved) approved.value = 'true';
          form.requestSubmit();
        };
        const denyBtn = document.createElement('button');
        denyBtn.type = 'button';
        denyBtn.textContent = 'Deny';
        denyBtn.onclick = () => {
          const decision = form.elements['decision'];
          const approved = form.elements['approved'];
          if (decision) decision.value = 'deny';
          if (approved) approved.value = 'false';
          form.requestSubmit();
        };
        actions.appendChild(approveBtn);
        actions.appendChild(denyBtn);
        form.appendChild(actions);
      } else {
        const btn = document.createElement('button');
        btn.type = 'submit';
        btn.textContent = 'Submit Response';
        form.appendChild(btn);
      }
      form.onsubmit = async (ev) => {
        ev.preventDefault();
        document.getElementById('error').textContent = '';
        const out = {};
        for (const field of Array.from(form.elements)) {
          if (!field.name) continue;
          if (field.dataset.kind === 'bool') out[field.name] = field.value === 'true';
          else if (field.dataset.kind === 'integer') out[field.name] = Math.trunc(Number(field.value || 0));
          else if (field.dataset.kind === 'number') out[field.name] = Number(field.value || 0);
          else out[field.name] = field.value;
        }
        try {
          await respondInteraction(item.idempotency_key, out);
          await refreshRuns();
          await refreshInbox();
          await refreshSelectedRun();
        } catch (err) {
          document.getElementById('error').textContent = String(err);
        }
      };
      el.appendChild(form);
    }
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
    el.innerHTML = `<strong>${artifact.name || 'artifact'}</strong> (${artifact.format || ''})<br/>${location}<br/><a href=\"${download}\" target=\"_blank\" rel=\"noopener\">Download</a>`;
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

async function refreshInbox() {
  const payload = await getJson('/api/inbox?limit=50');
  state.inbox = payload.interactions || [];
  renderInbox();
}

async function refreshSelectedRun() {
  await refreshEvents();
  await refreshArtifacts();
  if (!state.selectedRun) return;
  const [nodesPayload, waitingPayload] = await Promise.all([
    getJson(`/api/runs/${state.selectedRun}/nodes`),
    getJson(`/api/runs/${state.selectedRun}/waiting`),
  ]);
  state.nodeRecords = nodesPayload.nodes || {};
  const nodeStatusMap = {};
  for (const [nodeName, rec] of Object.entries(state.nodeRecords)) {
    nodeStatusMap[nodeName] = rec.status || '';
  }
  state.waiting = waitingPayload.waiting || [];
  const waitingNodeNames = state.waiting.map((i) => i.node_name).filter(Boolean);
  applyGraphState(nodeStatusMap, waitingNodeNames, state.nodeRecords);
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
      input.innerHTML = '<option value=\"\">(unset)</option><option value=\"true\">true</option><option value=\"false\">false</option>';
    } else if (spec.kind === 'enum') {
      input = document.createElement('select');
      input.innerHTML = ['<option value=\"\">(select)</option>', ...spec.values.map((v) => `<option value=\"${v}\">${v}</option>`)].join('');
    } else {
      input = document.createElement('input');
      input.type = spec.kind === 'number' || spec.kind === 'integer' ? 'number' : 'text';
      if (spec.kind === 'list') input.placeholder = spec.item === 'number' || spec.item === 'integer' ? 'e.g. 1,2,3 or 1-3' : 'comma or space separated values';
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
      const res = await fetch('/api/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || `HTTP ${res.status}`);
      document.getElementById('info').textContent = `Triggered run ${out.run_id}`;
      await refreshRuns();
      await refreshInbox();
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
  await refreshSelectedRun();
}

async function bootstrap() {
  try {
    state.process = await getJson('/api/process');
    renderTriggerForm();
    const graph = await getJson('/api/graph');
    const frame = document.getElementById('graphFrame');
    frame.srcdoc = graph.html;
    frame.addEventListener('load', () => refreshSelectedRun().catch(() => {}));
    await refreshRuns();
    await refreshInbox();
    setInterval(() => refreshRuns().catch(() => {}), 2000);
    setInterval(() => refreshInbox().catch(() => {}), 2000);
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

    def _verify_slack_signature(self, raw_body: bytes) -> tuple[bool, str]:
        secret = os.getenv("SLACK_SIGNING_SECRET", "")
        if not secret:
            return False, "SLACK_SIGNING_SECRET is not configured"

        timestamp = self.headers.get("X-Slack-Request-Timestamp", "")
        signature = self.headers.get("X-Slack-Signature", "")
        if not timestamp or not signature:
            return False, "Missing Slack signature headers"
        try:
            request_ts = int(timestamp)
        except ValueError:
            return False, "Invalid Slack timestamp header"
        if abs(int(time.time()) - request_ts) > 300:
            return False, "Slack timestamp outside allowed window"

        basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
        expected = "v0=" + hmac.new(
            secret.encode("utf-8"),
            basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False, "Invalid Slack signature"
        return True, ""

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

        if path == "/api/inbox":
            limit = int((query.get("limit") or ["50"])[0])
            store = StateStore(self.config.state_dir)
            interactions = store.list_interactions(
                process_name=self.config.process_name,
                limit=max(1, limit),
            )
            self._send_json(
                200,
                {"interactions": [_interaction_for_dashboard(item) for item in interactions]},
            )
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
                if len(parts) == 4 and parts[3] == "waiting":
                    interactions = store.list_interactions(
                        process_name=self.config.process_name,
                        run_id=run_id,
                        limit=200,
                    )
                    waiting = [
                        _interaction_for_dashboard(item)
                        for item in interactions
                        if item.get("status") == "pending"
                    ]
                    self._send_json(200, {"run_id": run_id, "waiting": waiting})
                    return
                if len(parts) == 4 and parts[3] == "artifacts":
                    try:
                        artifacts = store.list_run_artifacts(run_id)
                    except StateStoreError:
                        self._send_json(404, {"error": f"Run '{run_id}' not found"})
                        return
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
                    try:
                        artifacts = store.list_run_artifacts(run_id)
                    except StateStoreError:
                        self._send_json(404, {"error": f"Run '{run_id}' not found"})
                        return
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
        if parsed.path == "/api/slack/interactions":
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b""
            ok, reason = self._verify_slack_signature(raw)
            if not ok:
                self._send_json(401, {"error": reason})
                return

            form = parse_qs(raw.decode("utf-8"))
            payload_raw = (form.get("payload") or [""])[0]
            if not payload_raw:
                self._send_json(400, {"error": "Missing Slack payload form field"})
                return
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid Slack payload JSON"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Slack payload must be a JSON object"})
                return

            actions = payload.get("actions")
            if not isinstance(actions, list) or not actions:
                self._send_json(400, {"error": "Slack payload missing actions"})
                return
            action = actions[0] if isinstance(actions[0], dict) else {}
            action_id = action.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                self._send_json(400, {"error": "Slack action is missing action_id"})
                return

            try:
                idempotency_key, action_label = SlackInteractiveProvider.parse_action(action_id)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return

            store = StateStore(self.config.state_dir)
            pending = store.load_pending_interaction(idempotency_key)
            if pending is None:
                self._send_json(404, {"error": f"Interaction '{idempotency_key}' not found"})
                return

            run_id = pending.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                self._send_json(400, {"error": "Interaction has no run_id"})
                return

            output = SlackInteractiveProvider.action_to_output(action_label)
            user = payload.get("user")
            if isinstance(user, dict):
                user_id = user.get("id")
                if isinstance(user_id, str) and user_id:
                    output["slack_user_id"] = user_id

            store.save_interaction_response(idempotency_key, output)

            process = self._process_or_404()
            if process is None:
                return
            try:
                Engine(process=process, state_store=store).step(run_id)
            except Exception as exc:  # pragma: no cover - defensive API boundary
                self._send_json(500, {"error": f"Resume failed: {exc}"})
                return

            self._send_json(
                200,
                {
                    "ok": True,
                    "idempotency_key": idempotency_key,
                    "run_id": run_id,
                    "response": output,
                },
            )
            return

        if parsed.path.startswith("/api/interactions/") and parsed.path.endswith("/respond"):
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) != 4:
                self._send_json(404, {"error": "Not found"})
                return
            idempotency_key = unquote(parts[2])

            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON body"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Interaction response must be a JSON object"})
                return

            store = StateStore(self.config.state_dir)
            pending = store.load_pending_interaction(idempotency_key)
            if pending is None:
                self._send_json(404, {"error": f"Interaction '{idempotency_key}' not found"})
                return

            run_id = pending.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                self._send_json(400, {"error": "Interaction has no run_id"})
                return

            store.save_interaction_response(idempotency_key, payload)

            run = store.load_run(run_id)
            if run is None:
                self._send_json(404, {"error": f"Run '{run_id}' not found"})
                return

            process = self._process_or_404()
            if process is None:
                return
            try:
                Engine(process=process, state_store=store).step(run_id)
            except Exception as exc:  # pragma: no cover - defensive API boundary
                self._send_json(500, {"error": f"Resume failed: {exc}"})
                return

            self._send_json(
                200,
                {
                    "idempotency_key": idempotency_key,
                    "run_id": run_id,
                    "response": payload,
                    "status": "responded",
                },
            )
            return

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
