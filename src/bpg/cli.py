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
        
        html = generate_html(process)
        
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
        
        console.print(f"[bold green]✓[/bold green] Process [cyan]{process_file}[/cyan] is valid.")
        console.print(f"Nodes: {len(process.nodes)}, Edges: {len(process.edges)}, Trigger: {process.trigger}")
        
        # TODO: Implement diffing against state_dir
        console.print(
            f"\n[bold yellow]bpg plan[/bold yellow]: diffing against [cyan]{state_dir}[/cyan] "
            "not yet implemented."
        )
        
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
        exists=False,
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
    console.print(
        f"[bold yellow]bpg apply[/bold yellow]: not yet implemented "
        f"(file=[cyan]{process_file}[/cyan], state-dir=[cyan]{state_dir}[/cyan], "
        f"auto-approve={auto_approve})"
    )


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
    """Trigger a new run of a deployed process with an input payload.

    Creates a new process run with a unique run_id, validates the input payload
    against the trigger node's declared input type, and begins event-driven
    execution of the process graph.
    """
    console.print(
        f"[bold yellow]bpg run[/bold yellow]: not yet implemented "
        f"(process=[cyan]{process_name}[/cyan], input=[cyan]{input_file}[/cyan], "
        f"state-dir=[cyan]{state_dir}[/cyan])"
    )


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
    """Show the status of in-flight or completed process runs.

    Without a run_id, displays a summary table of recent runs. With a run_id,
    shows per-node execution status, timestamps, and any error details for that
    specific run.
    """
    console.print(
        f"[bold yellow]bpg status[/bold yellow]: not yet implemented "
        f"(run-id=[cyan]{run_id or 'all'}[/cyan], "
        f"process=[cyan]{process_name or 'all'}[/cyan], "
        f"state-dir=[cyan]{state_dir}[/cyan])"
    )


if __name__ == "__main__":
    app()
