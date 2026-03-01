from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _write_process_with_custom_provider(tmp_path: Path) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: custom-provider-proc
  version: 1.0.0
types:
  In:
    text: string
  Out:
    text: string
node_types:
  echo@v1:
    in: In
    out: Out
    provider: custom.echo
    version: v1
    config_schema: {}
nodes:
  step:
    type: echo@v1
    config: {}
trigger: step
edges: []
""",
        encoding="utf-8",
    )
    return process_file


def _write_custom_provider_module(tmp_path: Path) -> Path:
    module_path = tmp_path / "custom_provider_impl.py"
    module_path.write_text(
        """
from bpg.providers.base import Provider, ExecutionHandle, ExecutionStatus

class CustomEchoProvider(Provider):
    provider_id = "custom.echo"

    def invoke(self, input, config, context):
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": dict(input)},
        )

    def poll(self, handle):
        return ExecutionStatus.COMPLETED

    def await_result(self, handle, timeout=None):
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle):
        _ = handle
""",
        encoding="utf-8",
    )
    return module_path


def test_plan_accepts_custom_provider_from_explicit_registry_file(tmp_path: Path, monkeypatch):
    process_file = _write_process_with_custom_provider(tmp_path)
    module_path = _write_custom_provider_module(tmp_path)
    registry_file = tmp_path / "bpg.providers.yaml"
    registry_file.write_text(
        f"providers:\n  custom.echo: {module_path.stem}:CustomEchoProvider\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    result = runner.invoke(
        app,
        ["plan", str(process_file), "--providers-file", str(registry_file)],
    )
    assert result.exit_code == 0


def test_plan_accepts_custom_provider_from_default_registry_file(tmp_path: Path, monkeypatch):
    process_file = _write_process_with_custom_provider(tmp_path)
    module_path = _write_custom_provider_module(tmp_path)
    registry_file = tmp_path / "bpg.providers.yaml"
    registry_file.write_text(
        f"providers:\n  custom.echo: {module_path.stem}:CustomEchoProvider\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["plan", str(process_file)])
    assert result.exit_code == 0
