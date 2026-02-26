"""BPG CLI — entry point for all bpg commands.

Commands:
    plan    Compile and diff process definitions against current state.
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
from bpg.state.store import StateStore


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

        from bpg.compiler.parser import ParseError
        from bpg.compiler.validator import ValidationError
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


if __name__ == "__main__":
    app()
