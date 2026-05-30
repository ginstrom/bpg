"""Framework-first BPG CLI.

Commands:
    node list       List installed node packages discovered via entry points.
    node describe   Show metadata for a specific installed node.
    validate        Validate a v2 process spec file.
    compile         Compile a v2 process spec to an execution plan.
    worker start    Print Temporal worker startup configuration (--dry-run).
    marketplace     Artifact generation, validation, and sync sub-commands.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from bpg_sdk.discovery import DiscoveryError, discover_nodes

app = typer.Typer(
    name="bpg",
    help="Business Process Graph — declarative workflow automation.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

node_app = typer.Typer(help="Node package discovery and inspection.", no_args_is_help=True)
app.add_typer(node_app, name="node")

worker_app = typer.Typer(help="Temporal worker management.", no_args_is_help=True)
app.add_typer(worker_app, name="worker")

marketplace_app = typer.Typer(help="Marketplace artifact generation and validation.", no_args_is_help=True)
app.add_typer(marketplace_app, name="marketplace")

console = Console()
err_console = Console(stderr=True, style="bold red")


def main() -> None:
    app()


# ---------------------------------------------------------------------------
# node list
# ---------------------------------------------------------------------------


@node_app.command("list")
def node_list(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """List installed node packages discovered via bpg.nodes entry points."""
    try:
        catalog = discover_nodes()
    except DiscoveryError as exc:
        err_console.print(f"Discovery error: {exc}")
        raise typer.Exit(1)

    nodes = [
        {
            "package_id": node.manifest.package,
            "node_id": node.manifest.node_id,
            "capabilities": list(node.manifest.capabilities),
        }
        for node in catalog.values()
    ]

    if as_json:
        typer.echo(_json.dumps({"nodes": nodes}, indent=2))
        return

    if not nodes:
        console.print("[yellow]No installed node packages found.[/yellow]")
        return

    packages: dict[str, list[str]] = {}
    for n in nodes:
        packages.setdefault(n["package_id"], []).append(n["node_id"])

    for pkg_id, node_ids in sorted(packages.items()):
        console.print(f"[bold]{pkg_id}[/bold]")
        for nid in sorted(node_ids):
            console.print(f"  {nid}")


# ---------------------------------------------------------------------------
# node describe
# ---------------------------------------------------------------------------


@node_app.command("describe")
def node_describe(
    package_id: Annotated[str, typer.Argument(help="Package ID, e.g. bpg.nodes.core@v1")],
    node_id: Annotated[str, typer.Argument(help="Node ID within the package, e.g. passthrough")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Show metadata for a specific installed node."""
    try:
        catalog = discover_nodes()
    except DiscoveryError as exc:
        err_console.print(f"Discovery error: {exc}")
        raise typer.Exit(1)

    key = (package_id, node_id)
    if key not in catalog:
        err_console.print(f"Node not found: {package_id}/{node_id}")
        raise typer.Exit(1)

    discovered = catalog[key]
    m = discovered.manifest

    payload = {
        "package_id": m.package,
        "node_id": m.node_id,
        "capabilities": list(m.capabilities),
        "input_schema": m.input_schema,
        "output_schema": m.output_schema,
        "side_effects": m.side_effects.value,
        "idempotency": m.idempotency.value,
        "retry_safety": m.retry_safety.value,
        "observability": m.observability.value,
    }

    if as_json:
        typer.echo(_json.dumps(payload, indent=2))
        return

    console.print(f"[bold]{m.package}[/bold] / [bold]{m.node_id}[/bold]")
    console.print(f"  capabilities: {', '.join(m.capabilities) or '(none)'}")
    console.print(f"  side_effects: {m.side_effects.value}")
    console.print(f"  idempotency:  {m.idempotency.value}")
    console.print(f"  retry_safety: {m.retry_safety.value}")
    if m.input_schema:
        console.print(f"  input_schema: {_json.dumps(m.input_schema)}")
    if m.output_schema:
        console.print(f"  output_schema: {_json.dumps(m.output_schema)}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    spec_file: Annotated[Path, typer.Argument(help="Path to v2 process spec YAML.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Validate a v2 process spec file."""
    from bpg.compiler.parser import ParseError, parse_process_spec_v2_file
    from bpg.compiler.spec_v2 import validate_process_spec_v2
    from bpg.compiler.validator import ValidationError

    if not spec_file.exists():
        _emit(as_json, ok=False, error=f"File not found: {spec_file}")
        raise typer.Exit(1)

    try:
        spec = parse_process_spec_v2_file(spec_file)
        validate_process_spec_v2(spec)
    except (ParseError, ValidationError, Exception) as exc:
        _emit(as_json, ok=False, error=str(exc))
        raise typer.Exit(1)

    _emit(as_json, ok=True, message=f"Spec {spec_file.name!r} is valid.")


def _emit(as_json: bool, *, ok: bool, message: str = "", error: str = "") -> None:
    if as_json:
        payload: dict = {"ok": ok}
        if message:
            payload["message"] = message
        if error:
            payload["error"] = error
        typer.echo(_json.dumps(payload))
    else:
        if ok:
            console.print(f"[green]OK[/green] {message}")
        else:
            err_console.print(f"Error: {error}")


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


@app.command()
def compile(
    spec_file: Annotated[Path, typer.Argument(help="Path to v2 process spec YAML.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Compile a v2 process spec to a Temporal-ready execution plan."""
    from bpg.compiler.parser import ParseError, parse_process_spec_v2_file
    from bpg.compiler.spec_v2 import compile_process_spec_v2
    from bpg.compiler.validator import ValidationError

    if not spec_file.exists():
        err_console.print(f"File not found: {spec_file}")
        raise typer.Exit(1)

    try:
        spec = parse_process_spec_v2_file(spec_file)
        result = compile_process_spec_v2(spec)
    except (ParseError, ValidationError, Exception) as exc:
        err_console.print(f"Compilation failed: {exc}")
        raise typer.Exit(1)

    plan = result.execution_plan
    nodes_payload = [
        {
            "node_id": n.node_id,
            "package_id": n.package_id,
            "package_node_id": n.package_node_id,
        }
        for n in plan.nodes
    ]
    payload = {
        "process_name": plan.process_name,
        "trigger": plan.trigger,
        "nodes": nodes_payload,
        "edge_count": len(plan.edges),
    }

    if as_json:
        typer.echo(_json.dumps(payload, indent=2))
        return

    console.print(f"[bold]Process:[/bold] {plan.process_name}")
    console.print(f"  trigger: {plan.trigger}")
    console.print(f"  nodes ({len(plan.nodes)}):")
    for n in plan.nodes:
        console.print(f"    {n.node_id}  [{n.package_id}/{n.package_node_id}]")
    console.print(f"  edges: {len(plan.edges)}")


# ---------------------------------------------------------------------------
# worker start
# ---------------------------------------------------------------------------


@worker_app.command("start")
def worker_start(
    host: Annotated[str, typer.Option(help="Temporal server host.")] = "localhost",
    port: Annotated[int, typer.Option(help="Temporal server gRPC port.")] = 7233,
    namespace: Annotated[str, typer.Option(help="Temporal namespace.")] = "default",
    task_queue: Annotated[str, typer.Option(help="Temporal task queue.")] = "bpg",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print config without starting.")] = False,
) -> None:
    """Start a Temporal worker for BPG node execution.

    Use --dry-run to print the resolved configuration without connecting.
    """
    config = {
        "temporal_host": host,
        "temporal_port": port,
        "namespace": namespace,
        "task_queue": task_queue,
    }
    if dry_run:
        console.print("[bold]Worker configuration (dry-run):[/bold]")
        console.print(f"  temporal host:  {host}:{port}")
        console.print(f"  namespace:      {namespace}")
        console.print(f"  task queue:     {task_queue}")
        console.print("[yellow]Dry-run: worker not started.[/yellow]")
        return

    console.print(f"Starting Temporal worker → {host}:{port} / {namespace} / {task_queue}")
    console.print("[yellow]Note: live Temporal connection requires a running Temporal server.[/yellow]")
    console.print("[yellow]Run `temporal server start-dev` to start a local Temporal instance.[/yellow]")
    raise typer.Exit(0)


# ---------------------------------------------------------------------------
# marketplace sub-commands (delegated to legacy bpg.cli)
# ---------------------------------------------------------------------------


@marketplace_app.command("export")
def marketplace_export(
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to write artifacts.")] = Path("marketplace"),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Export marketplace artifacts for all installed node packages."""
    from bpg_sdk.discovery import discover_nodes
    from bpg_sdk.marketplace import export_catalog, write_artifacts

    try:
        catalog = discover_nodes()
    except DiscoveryError as exc:
        err_console.print(f"Discovery error: {exc}")
        raise typer.Exit(1)

    artifacts = export_catalog(catalog.values())
    output_dir.mkdir(parents=True, exist_ok=True)
    written = write_artifacts(artifacts, output_dir)

    if as_json:
        typer.echo(_json.dumps({"exported": [str(p) for p in written]}))
        return

    console.print(f"Exported {len(written)} artifact(s) to {output_dir}/")
    for p in written:
        console.print(f"  {p}")


@marketplace_app.command("validate")
def marketplace_validate(
    artifacts_dir: Annotated[Path, typer.Argument(help="Directory containing marketplace JSON artifacts.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate marketplace artifact JSON files in a directory."""
    from bpg_sdk.marketplace import load_artifact, validate_artifacts

    if not artifacts_dir.exists():
        _emit(as_json, ok=False, error=f"Directory not found: {artifacts_dir}")
        raise typer.Exit(1)

    artifact_files = list(artifacts_dir.glob("*.json"))
    if not artifact_files:
        _emit(as_json, ok=False, error=f"No JSON artifacts found in {artifacts_dir}")
        raise typer.Exit(1)

    artifacts = []
    for f in sorted(artifact_files):
        try:
            artifacts.append(load_artifact(f))
        except Exception as exc:
            _emit(as_json, ok=False, error=f"Failed to load {f.name}: {exc}")
            raise typer.Exit(1)

    errors = validate_artifacts(artifacts)
    if errors:
        msg = "; ".join(str(e) for e in errors)
        _emit(as_json, ok=False, error=msg)
        raise typer.Exit(1)

    _emit(as_json, ok=True, message=f"All {len(artifacts)} artifact(s) are valid.")
