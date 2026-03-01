"""BPG CLI — entry point for all bpg commands.

Commands:
    plan    Compile and diff process definitions against current state.
    package Generate an artifact-only docker compose bundle.
    up      Start local runtime services for a process.
    down    Stop local runtime services.
    logs    Show local runtime logs.
    apply   Deploy planned changes to the BPG runtime.
    run     Trigger a process run with an input payload.
    status  Show the status of in-flight or completed process runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console

app = typer.Typer(
    name="bpg",
    help="Business Process Graph — declarative workflow automation.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

console = Console()
err_console = Console(stderr=True, style="bold red")


from bpg.compiler.parser import parse_process_file, ParseError
from bpg.compiler.validator import validate_process, ValidationError
from bpg.compiler.visualizer import generate_html
from bpg.compiler.ir import compile_process
from bpg.compiler.planner import Plan
from bpg.packaging import (
    build_runtime_spec,
)
from bpg.runtime.orchestration import build_image_command, compose_command, write_runtime_bundle
from bpg.state.store import StateStore


_PLACEHOLDER_VALUES = {
    "dummy",
    "changeme",
    "change_me",
    "placeholder",
    "__required__",
    "<required>",
    "<placeholder>",
    "todo",
    "tbd",
}
_DEFAULT_PROCESS_FILENAMES = ("process.bpg.yaml", "process.bpg.yml")


def _looks_like_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    if normalized in _PLACEHOLDER_VALUES:
        return True
    if normalized.startswith("dummy-") or normalized.startswith("test-"):
        return True
    return False


def _resolve_local_runtime_dir(local_dir: Path) -> Path:
    if local_dir.exists():
        return local_dir

    default_dir = Path(".bpg/local/default")
    if local_dir == default_dir:
        parent = default_dir.parent
        candidates = sorted([p for p in parent.iterdir() if p.is_dir()]) if parent.exists() else []
        if len(candidates) == 1:
            console.print(
                "[bold yellow]![/bold yellow] Using inferred local runtime directory: "
                f"[cyan]{candidates[0]}[/cyan]"
            )
            return candidates[0]
        if len(candidates) > 1:
            err_console.print(
                "Multiple local runtime directories found under .bpg/local. "
                "Pass --local-dir explicitly."
            )
            raise typer.Exit(code=1)
        err_console.print(
            "No local runtime directory found at .bpg/local/default. "
            "Run 'bpg up <process_file>' first or pass --local-dir."
        )
        raise typer.Exit(code=1)

    err_console.print(
        f"Local runtime directory not found: {local_dir}. "
        "Pass a valid --local-dir."
    )
    raise typer.Exit(code=1)


def _find_default_process_file() -> Path | None:
    for filename in _DEFAULT_PROCESS_FILENAMES:
        candidate = Path(filename)
        if candidate.exists():
            return candidate
    return None


def _resolve_process_file(process_file: Path | None, command_name: str) -> Path:
    if process_file is not None:
        if process_file.exists() and process_file.is_file():
            return process_file
        err_console.print(f"Process file not found: {process_file}")
        raise typer.Exit(code=1)

    inferred = _find_default_process_file()
    if inferred is not None:
        console.print(
            "[bold yellow]![/bold yellow] Using inferred process file: "
            f"[cyan]{inferred}[/cyan]"
        )
        return inferred

    filenames = ", ".join(_DEFAULT_PROCESS_FILENAMES)
    err_console.print(
        f"No process file provided for '{command_name}', and no default file found. "
        f"Tried: {filenames}."
    )
    raise typer.Exit(code=1)


def _resolve_local_dir_from_process_file(process_file: Path | None, command_name: str) -> Path:
    if process_file is None:
        inferred = _find_default_process_file()
        if inferred is None:
            return _resolve_local_runtime_dir(Path(".bpg/local/default"))
        console.print(
            "[bold yellow]![/bold yellow] Using inferred process file: "
            f"[cyan]{inferred}[/cyan]"
        )
        resolved_process_file = inferred
    else:
        resolved_process_file = _resolve_process_file(process_file, command_name)
    process = parse_process_file(resolved_process_file)
    process_name = process.metadata.name if process.metadata else "default"
    local_dir = Path(".bpg/local") / process_name
    return _resolve_local_runtime_dir(local_dir)


def _print_plan(process_name: str, process, plan: Plan, old_process=None) -> None:
    """Render a deterministic plan view with graph + IR + artifact previews."""
    console.print(f"[bold yellow]Plan for process: {process_name}[/bold yellow]")
    if old_process is None:
        console.print("[green]+ New process[/green]")

    if plan.is_empty():
        console.print("[bold green]✓[/bold green] No changes detected.")
        return

    if plan.trigger_changed:
        old_trigger = old_process.trigger if old_process else "None"
        console.print(f"[yellow]~ Trigger[/yellow] {old_trigger} -> {process.trigger}")

    for node in plan.added_nodes:
        console.print(f"[green]+ Node[/green] {node}")
    for node in plan.modified_nodes:
        console.print(f"[yellow]~ Node[/yellow] {node}")
    for node in plan.removed_nodes:
        console.print(f"[red]- Node[/red] {node}")
    for edge in plan.added_edges:
        console.print(f"[green]+ Edge[/green] {edge}")
    for edge in plan.removed_edges:
        console.print(f"[red]- Edge[/red] {edge}")

    old_ir = plan.old_ir
    new_ir = plan.new_ir
    console.print("\n[bold]IR Delta[/bold]")
    if old_ir is None:
        console.print(
            f"  nodes: 0 -> {len(new_ir.resolved_nodes)}, edges: 0 -> {len(new_ir.resolved_edges)}"
        )
    else:
        console.print(
            "  nodes: "
            f"{len(old_ir.resolved_nodes)} -> {len(new_ir.resolved_nodes)}, "
            "edges: "
            f"{len(old_ir.resolved_edges)} -> {len(new_ir.resolved_edges)}"
        )
    topo_preview = ", ".join(new_ir.topological_order[:6])
    if len(new_ir.topological_order) > 6:
        topo_preview += ", ..."
    console.print(f"  topo: [{topo_preview}]")

    console.print("\n[bold]Artifact Preview[/bold]")
    if not (plan.added_nodes or plan.modified_nodes or plan.removed_nodes):
        console.print("  (no provider artifact changes)")
    for node_name in plan.added_nodes + plan.modified_nodes:
        node_inst = process.nodes[node_name]
        node_type = process.node_types[node_inst.node_type]
        config_keys = sorted(node_inst.config.keys())
        console.print(
            f"  [green]{node_name}[/green] provider={node_type.provider} config_keys={config_keys}"
        )
    for node_name in plan.removed_nodes:
        console.print(f"  [red]{node_name}[/red] provider artifacts will be removed")


@app.command()
def visualize(
    process_file: Path = typer.Argument(
        ...,
        help="Path to the process definition file (e.g. process.bpg.yaml).",
        exists=True,
    ),
    output_dir: Path = typer.Option(
        Path(".bpg/viz"),
        "--output-dir",
        "-o",
        help="Directory to save the visualization HTML.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the visualization in the default web browser.",
    ),
) -> None:
    """Generate a React Flow visualization of the process graph."""
    try:
        process = parse_process_file(process_file)
        validate_process(process)
        ir = compile_process(process)

        html = generate_html(ir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{process_file.stem}.html"
        output_path.write_text(html)
        
        console.print(f"[bold green]✓[/bold green] Visualization generated: [cyan]{output_path}[/cyan]")
        
        if open_browser:
            import webbrowser
            webbrowser.open(f"file://{output_path.absolute()}")
            
    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def plan(
    process_file: Path = typer.Argument(
        ...,
        help="Path to the process definition file (e.g. process.bpg.yaml).",
        exists=True,
    ),
    state_dir: Path = typer.Option(
        Path(".bpg-state"),
        "--state-dir",
        help="Directory where BPG state is persisted.",
    ),
) -> None:
    """Compile a process definition and show a diff against the current deployed state.

    Reads the process file, type-checks all node contracts and edge mappings,
    and produces a human-readable plan of what would change on apply.
    No execution occurs during plan.
    """
    try:
        process = parse_process_file(process_file)
        validate_process(process)
        
        process_name = process.metadata.name if process.metadata else "default"
        
        store = StateStore(state_dir)
        old_process = store.load_process(process_name)
        
        ir = compile_process(process)
        old_ir = compile_process(old_process) if old_process else None
        
        plan = Plan(new_ir=ir, old_ir=old_ir)
        
        if plan.is_empty():
            console.print(f"[bold green]✓[/bold green] No changes detected for process [cyan]{process_name}[/cyan].")
            return

        _print_plan(process_name, process, plan, old_process=old_process)
        console.print("\nRun [bold]bpg apply[/bold] to deploy these changes.")
        
    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def package(
    process_file: Path | None = typer.Argument(
        None,
        help=(
            "Path to the process definition file. "
            "Defaults to process.bpg.yaml or process.bpg.yml in current directory."
        ),
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory where package artifacts will be written.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite output directory if it already exists.",
    ),
    dashboard: bool = typer.Option(
        False,
        "--dashboard",
        help="Include the dashboard service in generated compose artifacts.",
    ),
    dashboard_port: int = typer.Option(
        8080,
        "--dashboard-port",
        help="Host/container port for the dashboard service.",
    ),
    image: Optional[str] = typer.Option(
        None,
        "--image",
        help="Container image reference for packaged runtime. When omitted, package output is local-buildable.",
    ),
) -> None:
    """Generate a docker-compose package for a process definition."""
    try:
        resolved_process_file = _resolve_process_file(process_file, "package")
        process_text = resolved_process_file.read_text()
        process = parse_process_file(resolved_process_file)
        validate_process(process)
        _ = compile_process(process)

        process_name = process.metadata.name if process.metadata else "default"
        out_dir = output_dir or Path(".bpg/package") / process_name

        spec = build_runtime_spec(
            process,
            process_text,
            mode="package",
            dashboard=dashboard,
            dashboard_port=dashboard_port,
            image=image,
        )
        write_runtime_bundle(out_dir, process_text, spec, force=force)

        unresolved = [item for item in spec.env_vars if item.required and not item.value]

        console.print(f"[bold green]✓[/bold green] Package generated: [cyan]{out_dir}[/cyan]")
        if unresolved:
            console.print(
                f"[bold yellow]![/bold yellow] {len(unresolved)} unresolved required vars."
            )
            for item in unresolved:
                source = f" ({item.source})" if item.source else ""
                console.print(f"  - [yellow]{item.name}[/yellow]{source}")
    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except FileExistsError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def up(
    process_file: Path | None = typer.Argument(
        None,
        help=(
            "Path to the process definition file. "
            "Defaults to process.bpg.yaml or process.bpg.yml in current directory."
        ),
    ),
    local_dir: Optional[Path] = typer.Option(
        None,
        "--local-dir",
        help="Directory where local runtime compose artifacts are written.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite local runtime directory if it already exists.",
    ),
    dashboard: bool = typer.Option(
        False,
        "--dashboard",
        help="Include and start dashboard service.",
    ),
    dashboard_port: int = typer.Option(
        8080,
        "--dashboard-port",
        help="Host/container port for dashboard service.",
    ),
) -> None:
    """Bring up a local runtime for the process using docker compose."""
    try:
        resolved_process_file = _resolve_process_file(process_file, "up")
        process_text = resolved_process_file.read_text()
        process = parse_process_file(resolved_process_file)
        validate_process(process)
        _ = compile_process(process)
        process_name = process.metadata.name if process.metadata else "default"
        out_dir = local_dir or Path(".bpg/local") / process_name

        spec = build_runtime_spec(
            process,
            process_text,
            mode="local",
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
        unresolved = [item for item in spec.env_vars if item.required and not item.value]
        if unresolved:
            console.print(
                f"[bold red]X[/bold red] {len(unresolved)} unresolved required vars. "
                "Set the following vars before running local runtime:"
            )
            for item in unresolved:
                source = f" ({item.source})" if item.source else ""
                console.print(f"  - [yellow]{item.name}[/yellow]{source}")
            raise typer.Exit(code=1)
        placeholder_vars = [
            item for item in spec.env_vars if item.required and _looks_like_placeholder(item.value)
        ]
        if placeholder_vars:
            console.print(
                f"[bold yellow]![/bold yellow] {len(placeholder_vars)} required vars look like placeholders. "
                "Runtime may start but external integrations can fail:"
            )
            for item in placeholder_vars:
                source = f" ({item.source})" if item.source else ""
                console.print(f"  - [yellow]{item.name}[/yellow]{source}={item.value}")

        project_root = Path(__file__).resolve().parents[2]
        build = build_image_command(spec.runtime_image, project_root)
        if build.returncode != 0:
            err_console.print(build.stderr.strip() or build.stdout.strip() or "docker build failed")
            raise typer.Exit(code=1)

        write_runtime_bundle(out_dir, process_text, spec, force=force)
        result = compose_command(out_dir, ["up", "-d"])
        if result.returncode != 0:
            err_console.print(result.stderr.strip() or result.stdout.strip() or "docker compose up failed")
            raise typer.Exit(code=1)
        console.print(f"[bold green]✓[/bold green] Local runtime up: [cyan]{out_dir}[/cyan]")
        if dashboard:
            console.print(
                "[bold green]✓[/bold green] Dashboard: "
                f"[cyan]http://localhost:{dashboard_port}[/cyan]"
            )
    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except FileExistsError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def down(
    process_file: Path | None = typer.Argument(
        None,
        help=(
            "Optional process definition file used to infer local runtime directory. "
            "Defaults to process.bpg.yaml or process.bpg.yml."
        ),
    ),
    local_dir: Path | None = typer.Option(
        None,
        "--local-dir",
        help="Directory containing local runtime compose artifacts. Overrides process-file inference.",
    ),
) -> None:
    """Tear down a local runtime created by `bpg up`."""
    try:
        if local_dir is not None:
            resolved_dir = _resolve_local_runtime_dir(local_dir)
        else:
            resolved_dir = _resolve_local_dir_from_process_file(process_file, "down")
    except ParseError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except ValidationError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    result = compose_command(resolved_dir, ["down"])
    if result.returncode != 0:
        err_console.print(result.stderr.strip() or result.stdout.strip() or "docker compose down failed")
        raise typer.Exit(code=1)
    console.print(f"[bold green]✓[/bold green] Local runtime down: [cyan]{resolved_dir}[/cyan]")


@app.command()
def logs(
    local_dir: Path = typer.Option(
        Path(".bpg/local/default"),
        "--local-dir",
        help="Directory containing local runtime compose artifacts.",
    ),
    service: Optional[str] = typer.Option(
        None,
        "--service",
        help="Optional service name to filter logs.",
    ),
) -> None:
    """Show local runtime logs."""
    resolved_dir = _resolve_local_runtime_dir(local_dir)
    args = ["logs", "--tail", "200"]
    if service:
        args.append(service)
    result = compose_command(resolved_dir, args)
    if result.returncode != 0:
        err_console.print(result.stderr.strip() or result.stdout.strip() or "docker compose logs failed")
        raise typer.Exit(code=1)
    if result.stdout:
        console.print(result.stdout, end="")


@app.command()
def apply(
    process_file: Path = typer.Argument(
        ...,
        help="Path to the process definition file (e.g. process.bpg.yaml).",
        exists=True,
    ),
    state_dir: Path = typer.Option(
        Path(".bpg-state"),
        "--state-dir",
        help="Directory where BPG state is persisted.",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        help="Skip interactive approval prompt and apply immediately.",
    ),
) -> None:
    """Deploy the planned process changes to the BPG runtime.

    Validates the plan is still current against persisted state, registers the
    updated process definition, deploys provider artifacts, and persists the
    new state. Idempotent — re-applying an already-applied plan is a no-op.
    """
    try:
        process = parse_process_file(process_file)
        validate_process(process)
        
        process_name = process.metadata.name if process.metadata else "default"
        store = StateStore(state_dir)
        old_process = store.load_process(process_name)
        old_record = store.load_record(process_name)
        plan_state_hash = (old_record or {}).get("hash")

        ir = compile_process(process)
        old_ir = compile_process(old_process) if old_process else None

        plan = Plan(new_ir=ir, old_ir=old_ir)
        
        if plan.is_empty():
            console.print(f"[bold green]✓[/bold green] No changes to apply for [cyan]{process_name}[/cyan].")
            return

        # Show plan first
        _print_plan(process_name, process, plan, old_process=old_process)

        if not auto_approve:
            if not typer.confirm("\nDo you want to apply these changes?"):
                console.print("[red]Aborted.[/red]")
                raise typer.Exit()

        # Drift check: re-load the record after confirmation and compare hashes
        current_record = store.load_record(process_name)
        if (current_record or {}).get("hash") != plan_state_hash:
            err_console.print(
                f"State for '{process_name}' has drifted since plan was computed. "
                "Re-run 'bpg plan' before applying."
            )
            raise typer.Exit(code=1)
        if current_record and not store.verify_artifact_checksums(process_name):
            err_console.print(
                f"State for '{process_name}' has invalid artifact checksums. "
                "Re-run 'bpg apply' after resolving drift."
            )
            raise typer.Exit(code=1)

        from bpg.providers import PROVIDER_REGISTRY

        # Use freshest record for undeploy artifacts
        old_deployments = (current_record or {}).get("deployments", {})

        deployments: dict = dict(old_deployments)

        # Deploy added/modified nodes
        with console.status("[bold green]Deploying provider artifacts..."):
            for node_name in plan.added_nodes + plan.modified_nodes:
                node_inst = process.nodes[node_name]
                node_type = process.node_types[node_inst.node_type]
                provider_cls = PROVIDER_REGISTRY.get(node_type.provider)
                if provider_cls:
                    provider = provider_cls()
                    artifacts = provider.deploy(node_name, dict(node_inst.config))
                    deployments[node_name] = {
                        "provider_id": node_type.provider,
                        "artifacts": artifacts,
                    }
                    if artifacts:
                        console.print(f"  [green]✓[/green] Deployed {node_name}: {artifacts}")

            # Undeploy removed nodes
            for node_name in plan.removed_nodes:
                node_inst = old_process.nodes[node_name]
                node_type = old_process.node_types[node_inst.node_type]
                provider_cls = PROVIDER_REGISTRY.get(node_type.provider)
                if provider_cls:
                    provider = provider_cls()
                    old_artifacts = old_deployments.get(node_name, {}).get("artifacts", {})
                    provider.undeploy(node_name, dict(node_inst.config), old_artifacts)
                    deployments.pop(node_name, None)
                    console.print(f"  [red]✓[/red] Undeployed {node_name}")

        h = store.save_process(ir, deployments=deployments)
        # Load record to get the new version number
        record = store.load_record(process_name)
        version = record.get("version", 1) if record else 1
        console.print(f"[bold green]✓[/bold green] Applied successfully. Version [cyan]v{version}[/cyan], hash [cyan]{h[:8]}[/cyan]")
        
    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def run(
    process_name: str = typer.Argument(
        ...,
        help="Name of the deployed process to trigger.",
    ),
    input_file: Optional[Path] = typer.Option(
        None,
        "--input",
        "-i",
        help="Path to a YAML or JSON file containing the trigger input payload.",
        exists=False,
    ),
    state_dir: Path = typer.Option(
        Path(".bpg-state"),
        "--state-dir",
        help="Directory where BPG state is persisted.",
    ),
) -> None:
    """Trigger a new run of a deployed process with an input payload."""
    try:
        store = StateStore(state_dir)
        process = store.load_process(process_name)
        if process is None:
            err_console.print(
                f"Process '{process_name}' not found in state. "
                "Run 'bpg apply' first."
            )
            raise typer.Exit(code=1)

        # Load input payload
        input_payload: dict = {}
        if input_file is not None:
            import json
            content = Path(input_file).read_text()
            if str(input_file).endswith((".yaml", ".yml")):
                input_payload = yaml.safe_load(content) or {}
            else:
                input_payload = json.loads(content)

        from bpg.runtime.engine import Engine

        engine = Engine(process=process, state_store=store)

        with console.status("[bold green]Running process..."):
            run_id = engine.trigger(input_payload)

        run_record = store.load_run(run_id)
        status_val = (run_record or {}).get("status", "unknown")
        color = "green" if status_val == "completed" else "red"
        console.print(
            f"[bold {color}]✓[/bold {color}] Run [cyan]{run_id}[/cyan] "
            f"status=[bold]{status_val}[/bold]"
        )

    except (ParseError, ValidationError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def status(
    run_id: Optional[str] = typer.Argument(
        None,
        help="Specific run ID to inspect. If omitted, lists all recent runs.",
    ),
    process_name: Optional[str] = typer.Option(
        None,
        "--process",
        "-p",
        help="Filter by process name.",
    ),
    state_dir: Path = typer.Option(
        Path(".bpg-state"),
        "--state-dir",
        help="Directory where BPG state is persisted.",
    ),
) -> None:
    """Show the status of in-flight or completed process runs."""
    try:
        store = StateStore(state_dir)

        if run_id:
            record = store.load_run(run_id)
            if record is None:
                err_console.print(f"Run '{run_id}' not found.")
                raise typer.Exit(code=1)

            status_val = record.get("status", "unknown")
            color = "green" if status_val == "completed" else ("red" if status_val == "failed" else "yellow")
            console.print(f"[bold]Run:[/bold]       [cyan]{run_id}[/cyan]")
            console.print(f"[bold]Process:[/bold]   {record.get('process_name', '-')}")
            console.print(f"[bold]Status:[/bold]    [{color}]{status_val}[/{color}]")
            console.print(f"[bold]Started:[/bold]   {record.get('started_at', '-')}")
            if "completed_at" in record:
                console.print(f"[bold]Completed:[/bold] {record['completed_at']}")

            # Show per-node records
            nodes_dir = state_dir / "runs" / run_id / "nodes"
            if nodes_dir.exists():
                console.print("\n[bold]Node Records:[/bold]")
                for node_file in sorted(nodes_dir.glob("*.yaml")):
                    import yaml as _yaml
                    node_rec = _yaml.safe_load(node_file.read_text()) or {}
                    ns = node_rec.get("status", "unknown")
                    nc = "green" if ns == "completed" else ("red" if ns == "failed" else "yellow")
                    attempts = node_rec.get("attempts")
                    error = node_rec.get("error")
                    details = []
                    if attempts is not None:
                        details.append(f"attempts={attempts}")
                    if error:
                        details.append(f"error={error}")
                    suffix = f" ({', '.join(details)})" if details else ""
                    console.print(
                        f"  [{nc}]{node_rec.get('node', node_file.stem):20s}[/{nc}] "
                        f"{ns}{suffix}"
                    )
        else:
            runs = store.list_runs(process_name=process_name)
            if not runs:
                console.print("No runs found.")
                return

            console.print(f"{'RUN ID':<38} {'PROCESS':<28} {'STATUS':<12} STARTED")
            console.print("-" * 90)
            for r in runs:
                rid = r.get("run_id", "-")
                pname = r.get("process_name", "-")
                st = r.get("status", "-")
                started = r.get("started_at", "-")
                color = "green" if st == "completed" else ("red" if st == "failed" else "yellow")
                console.print(
                    f"[cyan]{rid:<38}[/cyan] {pname:<28} [{color}]{st:<12}[/{color}] {started}"
                )

    except Exception as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def cleanup(
    process_name: Optional[str] = typer.Option(
        None,
        "--process",
        "-p",
        help="Only prune runs for this process.",
    ),
    older_than: Optional[str] = typer.Option(
        None,
        "--older-than",
        help="Only prune runs older than this duration (e.g. 30d, 12h).",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        help="Comma-separated statuses to prune (e.g. failed,completed).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show matching runs without deleting them.",
    ),
    state_dir: Path = typer.Option(
        Path(".bpg-state"),
        "--state-dir",
        help="Directory where BPG state is persisted.",
    ),
) -> None:
    """Prune old run records from the local state store."""
    try:
        store = StateStore(state_dir)
        if older_than and store._parse_duration_seconds(older_than) is None:
            err_console.print(f"Error: invalid --older-than value '{older_than}'.")
            raise typer.Exit(code=1)

        status_set = None
        if status:
            status_set = {s.strip() for s in status.split(",") if s.strip()}

        matched = store.prune_runs(
            process_name=process_name,
            older_than=older_than,
            statuses=status_set,
            dry_run=dry_run,
        )
        mode = "Would prune" if dry_run else "Pruned"
        console.print(f"{mode} [bold]{len(matched)}[/bold] run(s).")
        for run_id in matched:
            console.print(f"  - [cyan]{run_id}[/cyan]")
    except typer.Exit:
        raise
    except Exception as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
