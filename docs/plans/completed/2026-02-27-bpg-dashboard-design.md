# BPG Dashboard Design

Date: 2026-02-27
Status: Approved
Owner: CLI/Runtime/UI

## 1. Summary
Add an integrated BPG web dashboard that can run in local runtime and packaged Docker runtime via `--dashboard`.

The dashboard provides:
- Process graph visualization (reusing the existing `visualize` rendering).
- Process/run event log timeline from persisted state (`events.jsonl`).
- Trigger/input form when the trigger input type requires fields.
- Run list and run details with per-node statuses and outputs.

## 2. Goals
- Make process state explorable without reading YAML/JSONL files manually.
- Keep one deployment story across local and package modes.
- Reuse existing graph visualizer artifacts.
- Support ad-hoc triggering with typed input from UI.

## 3. Non-Goals
- Multi-tenant auth/SSO in MVP.
- Real-time websocket streaming in MVP.
- Editing process definitions from dashboard.

## 4. User Experience
Dashboard route serves a single-page app with four panels:
1. Graph Panel
- Displays generated process graph (from existing visualize generator).
- Overlays per-node run status color and badges.
- Clicking a node opens latest node record details.

2. Run/Event Panel
- Run selector (`latest`, or pick run id).
- Run metadata: status, started/completed time, output.
- Event log tail with status transitions and errors.

3. Trigger Panel
- Auto-generates form from trigger input type schema.
- Supports primitive fields (`string`, `number`, `bool`, `enum`, lists).
- Submits payload to trigger a new run.

4. Diagnostics Panel
- Render API/backend errors, validation issues, missing state warnings.

## 5. CLI and Runtime Contract
### 5.1 New CLI behavior
- `bpg up <process_file> --dashboard`
  - Includes dashboard service in local compose bundle.
  - Starts dashboard alongside bpg runtime and inferred services.

- `bpg package <process_file> --dashboard`
  - Emits dashboard service in package compose artifacts.

### 5.2 New flags
- `--dashboard` (bool): include dashboard service.
- `--dashboard-port` (int, default `8080`): host port binding for dashboard service.

### 5.3 Runtime spec extension
Extend runtime spec to include dashboard options:
- `dashboard_enabled: bool`
- `dashboard_port: int`

## 6. Composition and Packaging
### 6.1 Compose service
When dashboard enabled, render a `dashboard` service:
- Image: same project runtime image initially (phase 1), command starts dashboard ASGI app.
- Environment:
  - `BPG_STATE_DIR=/app/.bpg-state`
  - `BPG_PROCESS_NAME=<process>`
  - `DASHBOARD_PORT=<port>`
- Volumes:
  - `./state:/app/.bpg-state`
  - `./process.bpg.yaml:/app/process.bpg.yaml:ro`
- Ports:
  - `<dashboard_port>:<dashboard_port>`

### 6.2 Packaging metadata
Include dashboard fields in metadata:
- `dashboard_enabled`
- `dashboard_port`

## 7. Backend API Design
Create dashboard backend module (FastAPI) with read-only state + trigger endpoint.

Endpoints:
- `GET /api/process`
  - Returns deployed process metadata and trigger type schema.

- `GET /api/graph`
  - Returns graph HTML string (from existing visualizer output) and graph metadata.

- `GET /api/runs?limit=50`
  - Returns latest runs for process.

- `GET /api/runs/{run_id}`
  - Returns run record.

- `GET /api/runs/{run_id}/nodes`
  - Returns node record map.

- `GET /api/runs/{run_id}/events?tail=500`
  - Returns ordered event entries.

- `POST /api/trigger`
  - Body: trigger input payload.
  - Validates payload against trigger input type.
  - Starts run using `Engine(...).trigger(payload)`.
  - Returns `run_id`.

## 8. Graph Reuse Strategy
Reuse `compiler.visualizer.generate_html(ir)`.

Implementation note:
- Create helper that extracts SVG/body content or embeds full graph HTML in iframe.
- Preferred MVP: iframe embed to avoid reimplementing rendering/parsing.

## 9. Trigger Form Strategy
- Resolve trigger node from deployed process.
- Resolve input type fields from process `types`.
- Render fields dynamically on frontend.
- Submit JSON payload to `/api/trigger`.
- Show validation errors returned by backend.

## 10. Event Log Presentation
Data source: `runs/<run_id>/events.jsonl` and `nodes/*.yaml`.

Display requirements:
- Chronological entries with status and node name.
- Error emphasis for failed events.
- Link event entries to node details.

## 11. Failure Semantics
- If process not deployed: dashboard shows actionable message and command hint (`bpg apply`).
- If run missing: API returns 404, UI keeps previous run selected with warning.
- If trigger payload invalid: API returns 422 with field-level messages.
- If state files unreadable: API returns 500 with concise operational error.

## 12. Security and Ops
- MVP bind to localhost by default.
- No auth in MVP (local/dev use).
- Avoid shelling out from dashboard backend except deterministic graph generation path.

## 13. Testing Strategy
Unit tests:
- API serialization for process/runs/events/nodes.
- Trigger payload validation and trigger submission behavior.
- Graph endpoint emits expected document structure.

CLI tests:
- `bpg up --dashboard` writes compose with dashboard service.
- `bpg package --dashboard` writes package with dashboard service and metadata.

Integration tests:
- Local dashboard starts and serves health endpoint.
- Triggering via API creates new run and event entries.

## 14. Delivery Phases
Phase 1 (MVP):
- CLI flags + runtime spec + compose support.
- Dashboard backend API + static frontend shell.
- Graph iframe + run/event list + trigger form submit.

Phase 2:
- Live auto-refresh improvements.
- Node detail drawer and richer metrics.
- Optional websocket updates.
