from pathlib import Path

from bpg.compiler.parser import parse_process_file
from bpg.packaging.inference import build_package_metadata, infer_package_spec


def _write_process(tmp_path: Path, content: str) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(content)
    return process_file


def test_infer_services_includes_postgres_by_default_for_package_mode(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(
        process,
        process_file.read_text(),
        env={"SLACK_BOT_TOKEN": "", "GITLAB_TOKEN": ""},
    )
    assert "postgres" in spec.services


def test_infer_services_excludes_postgres_for_sqlite_file_ledger(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
policy:
  audit:
    tags:
      ledger_backend: sqlite-file
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(process, process_file.read_text(), env={})
    assert "postgres" not in spec.services


def test_infer_unresolved_required_var_marked_required(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema:
      api_key: string
nodes:
  n1:
    type: n@v1
    config:
      api_key: ${API_KEY}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(
        process,
        process_file.read_text(),
        env={"SLACK_BOT_TOKEN": "", "GITLAB_TOKEN": ""},
    )
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["API_KEY"].required is True
    assert by_name["API_KEY"].value is None


def test_provider_requirements_add_required_env_for_slack_and_gitlab(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  In:
    title: string
  ApprovalDecision:
    approved: bool
    reason: string?
  IssueResult:
    ticket_id: string
    url: string
node_types:
  approve@v1:
    in: In
    out: ApprovalDecision
    provider: slack.interactive
    version: v1
    config_schema:
      channel: string
      buttons: list<string>
  gitlab@v1:
    in: In
    out: IssueResult
    provider: http.gitlab
    version: v1
    config_schema:
      project_id: string
nodes:
  approval:
    type: approve@v1
    config:
      channel: "#ops"
      buttons: [Approve, Reject]
  issue:
    type: gitlab@v1
    config:
      project_id: "myorg/backend"
trigger: approval
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(
        process,
        process_file.read_text(),
        env={"SLACK_BOT_TOKEN": "", "GITLAB_TOKEN": ""},
    )
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["SLACK_BOT_TOKEN"].required is True
    assert not by_name["SLACK_BOT_TOKEN"].value
    assert by_name["GITLAB_TOKEN"].required is True
    assert not by_name["GITLAB_TOKEN"].value


def test_provider_requirements_add_env_for_web_search_and_email(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p2
  version: 1.0.0
types:
  SearchIn:
    query: string
  SearchOut:
    results: list<object>
  EmailIn:
    to: string
    subject: string
    body: string
  EmailOut:
    sent: bool
node_types:
  search@v1:
    in: SearchIn
    out: SearchOut
    provider: tool.web_search
    version: v1
    config_schema:
      endpoint: string
  email@v1:
    in: EmailIn
    out: EmailOut
    provider: notify.email
    version: v1
    config_schema:
      from: string
nodes:
  search:
    type: search@v1
    config:
      endpoint: https://search.local
  email:
    type: email@v1
    config:
      from: robot@example.com
trigger: search
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(process, process_file.read_text(), env={})
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["WEB_SEARCH_API_KEY"].required is True
    assert by_name["SMTP_HOST"].required is True
    assert by_name["SMTP_FROM"].required is False


def test_provider_requirements_for_dry_run_nodes_are_optional(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p3
  version: 1.0.0
types:
  SearchIn:
    query: string
  SearchOut:
    results: list<object>
  EmailIn:
    to: string
    subject: string
    body: string
  EmailOut:
    sent: bool
node_types:
  search@v1:
    in: SearchIn
    out: SearchOut
    provider: tool.web_search
    version: v1
    config_schema:
      dry_run: bool
  email@v1:
    in: EmailIn
    out: EmailOut
    provider: notify.email
    version: v1
    config_schema:
      dry_run: bool
      from: string
nodes:
  search:
    type: search@v1
    config:
      dry_run: true
  email:
    type: email@v1
    config:
      dry_run: true
      from: robot@example.com
trigger: search
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(process, process_file.read_text(), env={})
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["WEB_SEARCH_API_KEY"].required is False
    assert by_name["SMTP_HOST"].required is False
    assert by_name["SMTP_FROM"].required is False


def test_provider_requirements_add_env_for_ai_llm_anthropic(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p5
  version: 1.0.0
types:
  In:
    text: string
  Out:
    risk: string
node_types:
  extract@v1:
    in: In
    out: Out
    provider: ai.llm
    version: v1
    config_schema:
      model: string
nodes:
  extract:
    type: extract@v1
    config:
      vendor: anthropic
      model: claude-3-5-sonnet-latest
trigger: extract
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(process, process_file.read_text(), env={})
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["ANTHROPIC_API_KEY"].required is True


def test_provider_requirements_add_env_for_ai_openai_google_ollama(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p6
  version: 1.0.0
types:
  In:
    text: string
  Out:
    risk: string
node_types:
  openai@v1:
    in: In
    out: Out
    provider: ai.openai
    version: v1
    config_schema:
      model: string
  google@v1:
    in: In
    out: Out
    provider: ai.google
    version: v1
    config_schema:
      model: string
  ollama@v1:
    in: In
    out: Out
    provider: ai.ollama
    version: v1
    config_schema:
      model: string
nodes:
  openai:
    type: openai@v1
    config:
      model: gpt-4.1-mini
  google:
    type: google@v1
    config:
      model: gemini-1.5-flash
  ollama:
    type: ollama@v1
    config:
      model: llama3.1
trigger: openai
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = infer_package_spec(process, process_file.read_text(), env={})
    by_name = {v.name: v for v in spec.env_vars}
    assert by_name["OPENAI_API_KEY"].required is True
    assert by_name["GOOGLE_API_KEY"].required is True
    assert "OLLAMA_API_KEY" not in by_name


def test_metadata_contains_dashboard_fields(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p4
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    from bpg.packaging.inference import build_runtime_spec

    spec = build_runtime_spec(
        process,
        process_file.read_text(),
        mode="package",
        dashboard=True,
        dashboard_port=9090,
    )
    metadata = build_package_metadata(spec)
    assert metadata["dashboard_enabled"] is True
    assert metadata["dashboard_port"] == 9090
    assert metadata["runtime_image"] == "bpg-package:local"
