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

import json
from datetime import datetime, timezone
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
providers_app = typer.Typer(help="Provider discovery and metadata.")
app.add_typer(providers_app, name="providers")

console = Console()
err_console = Console(stderr=True, style="bold red")


from bpg.compiler.parser import parse_process_file, ParseError, load_yaml_file
from bpg.compiler.validator import validate_process, ValidationError
from bpg.compiler.visualizer import generate_html
from bpg.compiler.ir import compile_process
from bpg.compiler.planner import ImmutabilityError, Plan
from bpg.compiler.errors import CompilerDiagnostic
from bpg.compiler.formatter import format_process_file
from bpg.compiler.patching import PatchApplyError, apply_json_patch, load_patch_file
from bpg.compiler.normalize import normalize_process_dict
from bpg.packaging import (
    build_runtime_spec,
)
from bpg.runtime.orchestration import build_image_command, compose_command, write_runtime_bundle
from bpg.state.store import StateStore
from bpg.providers import (
    PROVIDER_REGISTRY,
    describe_provider_metadata,
    list_provider_metadata,
)
from bpg.providers.loader import ProviderRegistryError, load_declared_providers


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
_PROVIDERS_FILE_HELP = (
    "Path to declarative provider registry YAML. "
    "When omitted, bpg.providers.yaml / bpg.providers.yml is auto-loaded if present."
)


def main() -> None:
    """Console entrypoint for installed `bpg` command."""
    app()


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


def _load_declared_providers_or_exit(providers_file: Path | None) -> None:
    try:
        loaded_from, loaded_ids = load_declared_providers(
            providers_file,
            registry=PROVIDER_REGISTRY,
        )
    except ProviderRegistryError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    if loaded_from and loaded_ids:
        loaded_preview = ", ".join(sorted(loaded_ids))
        console.print(
            "[bold green]✓[/bold green] Loaded provider registry: "
            f"[cyan]{loaded_from}[/cyan] ({loaded_preview})"
        )


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


def _build_plan_artifact(
    process_name: str,
    process,
    plan: Plan,
    *,
    process_file: Path,
    state_dir: Path,
    old_process=None,
) -> dict:
    old_trigger = old_process.trigger if old_process else None
    added_or_modified = []
    for node_name in plan.added_nodes + plan.modified_nodes:
        node_inst = process.nodes[node_name]
        node_type = process.node_types[node_inst.node_type]
        added_or_modified.append(
            {
                "node": node_name,
                "provider": node_type.provider,
                "config_keys": sorted(node_inst.config.keys()),
            }
        )

    old_ir = plan.old_ir
    new_ir = plan.new_ir
    return {
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "process_name": process_name,
        "process_version": process.metadata.version if process.metadata else None,
        "process_file": str(process_file),
        "state_dir": str(state_dir),
        "has_changes": not plan.is_empty(),
        "changes": {
            "trigger_changed": plan.trigger_changed,
            "trigger": {"old": old_trigger, "new": process.trigger},
            "added_nodes": plan.added_nodes,
            "modified_nodes": plan.modified_nodes,
            "removed_nodes": plan.removed_nodes,
            "added_edges": plan.added_edges,
            "removed_edges": plan.removed_edges,
        },
        "ir_delta": {
            "old": {
                "node_count": len(old_ir.resolved_nodes) if old_ir else 0,
                "edge_count": len(old_ir.resolved_edges) if old_ir else 0,
            },
            "new": {
                "node_count": len(new_ir.resolved_nodes),
                "edge_count": len(new_ir.resolved_edges),
            },
            "topological_order": list(new_ir.topological_order),
        },
        "artifact_preview": {
            "added_or_modified": added_or_modified,
            "removed_nodes": plan.removed_nodes,
        },
    }


def _build_plan_explain(
    process_name: str,
    process,
    plan: Plan,
    *,
    store: StateStore,
    old_process=None,
) -> dict:
    old_types = old_process.types if old_process else {}
    new_types = process.types
    old_type_names = set(old_types.keys())
    new_type_names = set(new_types.keys())
    changed_types = sorted(
        name for name in (old_type_names & new_type_names) if old_types[name] != new_types[name]
    )
    schema_diffs = {
        "added_types": sorted(new_type_names - old_type_names),
        "removed_types": sorted(old_type_names - new_type_names),
        "changed_types": changed_types,
    }

    warnings: list[str] = []
    if plan.removed_nodes:
        warnings.append(f"Removed nodes may break in-flight assumptions: {plan.removed_nodes}")
    if schema_diffs["removed_types"] or schema_diffs["changed_types"]:
        warnings.append(
            "Type removals/changes detected; review downstream compatibility before apply."
        )
    if plan.trigger_changed:
        warnings.append("Trigger changed; entrypoint behavior will differ for new runs.")

    runs = store.list_runs(process_name=process_name)
    active = [r for r in runs if str(r.get("status", "")) in {"running", "pending"}]
    blast_radius = {
        "active_runs_count": len(active),
        "active_run_ids": [r.get("run_id") for r in active if r.get("run_id")][:10],
        "affected_process_version": process.metadata.version if process.metadata else None,
    }

    return {
        "graph_summary": {
            "trigger": process.trigger,
            "node_count": len(process.nodes),
            "edge_count": len(process.edges),
            "topological_order_count": len(plan.new_ir.topological_order),
        },
        "changed_nodes": {
            "added": plan.added_nodes,
            "modified": plan.modified_nodes,
            "removed": plan.removed_nodes,
        },
        "changed_edges": {
            "added": plan.added_edges,
            "removed": plan.removed_edges,
        },
        "schema_diffs": schema_diffs,
        "compatibility_warnings": warnings,
        "blast_radius": blast_radius,
    }


def _print_show_summary(plan_doc: dict, plan_file: Path) -> None:
    process_name = plan_doc.get("process_name", "-")
    generated_at = plan_doc.get("generated_at", "-")
    has_changes = bool(plan_doc.get("has_changes", False))
    changes = plan_doc.get("changes", {})
    console.print(f"[bold]Plan File:[/bold] {plan_file}")
    console.print(f"[bold]Process:[/bold] {process_name}")
    console.print(f"[bold]Generated:[/bold] {generated_at}")
    console.print(f"[bold]Has Changes:[/bold] {'yes' if has_changes else 'no'}")
    console.print(
        "[bold]Counts:[/bold] "
        f"added={len(changes.get('added_nodes', []))}, "
        f"modified={len(changes.get('modified_nodes', []))}, "
        f"removed={len(changes.get('removed_nodes', []))}, "
        f"edge+={len(changes.get('added_edges', []))}, "
        f"edge-={len(changes.get('removed_edges', []))}"
    )


def _emit_error_json(exc: Exception) -> None:
    diag = getattr(exc, "diagnostic", None)
    if isinstance(diag, CompilerDiagnostic):
        console.print_json(json.dumps({"errors": [diag.to_dict()]}, sort_keys=True))
        return
    console.print_json(
        json.dumps(
            {
                "errors": [
                    {
                        "error_code": "E_UNKNOWN",
                        "path": "$",
                        "message": str(exc),
                        "severity": "error",
                    }
                ]
            },
            sort_keys=True,
        )
    )


def _diagnostic_for_exception(exc: Exception) -> dict:
    diag = getattr(exc, "diagnostic", None)
    if isinstance(diag, CompilerDiagnostic):
        return diag.to_dict()
    return {
        "error_code": "E_UNKNOWN",
        "path": "$",
        "message": str(exc),
        "fix": None,
        "example_patch": [],
        "schema_excerpt": {},
        "severity": "error",
    }


def _collect_diagnostics(process_file: Path, providers_file: Path | None) -> list[dict]:
    diagnostics: list[dict] = []
    try:
        _load_declared_providers_or_exit(providers_file)
        process = parse_process_file(process_file)
        validate_process(process)
        _ = compile_process(process)
    except (ParseError, ValidationError, ImmutabilityError) as e:
        diagnostics.append(_diagnostic_for_exception(e))
    except Exception as e:
        diagnostics.append(_diagnostic_for_exception(e))
    return diagnostics


def _looks_like_import_registry_file(process_file: Path) -> bool:
    """Return True when file appears to be an import/registry file, not a process graph."""
    try:
        raw = load_yaml_file(process_file)
    except ParseError:
        return False
    if not isinstance(raw, dict):
        return False
    has_process_graph = all(key in raw for key in ("nodes", "edges", "trigger"))
    if has_process_graph:
        return False
    has_registry_content = any(
        key in raw for key in ("types", "node_types", "modules", "imports")
    )
    return has_registry_content


@providers_app.command("list")
def providers_list(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable provider metadata.",
    ),
) -> None:
    """List registered providers."""
    items = list_provider_metadata()
    if json_output:
        console.print_json(
            json.dumps(
                {"providers": [item.model_dump(mode="json") for item in items]},
                sort_keys=True,
            )
        )
        return
    for item in items:
        console.print(f"- {item.name}: {item.description}")


@providers_app.command("describe")
def providers_describe(
    provider: str = typer.Argument(..., help="Provider ID, for example http.webhook."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable provider metadata.",
    ),
) -> None:
    """Describe one provider."""
    try:
        meta = describe_provider_metadata(provider)
    except KeyError:
        err_console.print(f"Unknown provider: {provider}")
        raise typer.Exit(code=1)

    payload = meta.model_dump(mode="json")
    if json_output:
        console.print_json(json.dumps(payload, sort_keys=True))
        return

    console.print(f"[bold]{payload['name']}[/bold]")
    console.print(payload["description"])
    console.print(
        f"side_effects={payload['side_effects']} idempotency={payload['idempotency']} latency={payload['latency_class']}"
    )


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
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Generate a React Flow visualization of the process graph."""
    try:
        _load_declared_providers_or_exit(providers_file)
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
            
    except ParseError as e:
        if _looks_like_import_registry_file(process_file):
            err_console.print(
                "Error: This file looks like a shared import/registry file "
                "(types/node_types/modules) and not a process graph. "
                "Visualize a file with nodes/edges/trigger, for example "
                "'examples/search/ingest.bpg.yaml' or 'examples/search/retrieve.bpg.yaml'."
            )
        else:
            err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except (ValidationError, ImmutabilityError) as e:
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
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write machine-readable plan artifact JSON to this file.",
    ),
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Include graph, compatibility, and blast-radius explanation payload.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit plan artifact as JSON to stdout.",
    ),
    json_errors: bool = typer.Option(
        False,
        "--json-errors",
        help="Emit machine-readable diagnostics on plan errors.",
    ),
) -> None:
    """Compile a process definition and show a diff against the current deployed state.

    Reads the process file, type-checks all node contracts and edge mappings,
    and produces a human-readable plan of what would change on apply.
    No execution occurs during plan.
    """
    try:
        _load_declared_providers_or_exit(providers_file)
        process = parse_process_file(process_file)
        validate_process(process)
        
        process_name = process.metadata.name if process.metadata else "default"
        
        store = StateStore(state_dir)
        old_process = store.load_process(process_name)
        
        ir = compile_process(process)
        old_ir = compile_process(old_process) if old_process else None
        
        plan = Plan(new_ir=ir, old_ir=old_ir)
        plan_doc = _build_plan_artifact(
            process_name,
            process,
            plan,
            process_file=process_file,
            state_dir=state_dir,
            old_process=old_process,
        )
        if explain:
            plan_doc["explain"] = _build_plan_explain(
                process_name,
                process,
                plan,
                store=store,
                old_process=old_process,
            )
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(plan_doc, indent=2, sort_keys=True) + "\n")
            console.print(f"[bold green]✓[/bold green] Plan artifact written: [cyan]{out}[/cyan]")

        if json_output:
            console.print_json(json.dumps(plan_doc, sort_keys=True))
            return
        
        if plan.is_empty():
            console.print(f"[bold green]✓[/bold green] No changes detected for process [cyan]{process_name}[/cyan].")
            return

        _print_plan(process_name, process, plan, old_process=old_process)
        console.print("\nRun [bold]bpg apply[/bold] to deploy these changes.")
        
    except (ParseError, ValidationError, ImmutabilityError) as e:
        if json_errors:
            _emit_error_json(e)
        else:
            err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"Unexpected error: {e}")
        raise typer.Exit(code=1)


@app.command()
def doctor(
    process_file: Path = typer.Argument(
        ...,
        help="Path to the process definition file (e.g. process.bpg.yaml).",
        exists=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable diagnostics JSON.",
    ),
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Validate a process and print actionable diagnostics for agents."""
    diagnostics = _collect_diagnostics(process_file, providers_file)

    if json_output:
        console.print_json(json.dumps({"ok": not diagnostics, "errors": diagnostics}, sort_keys=True))
    else:
        if diagnostics:
            for diag in diagnostics:
                err_console.print(
                    f"{diag['error_code']} {diag['path']}: {diag['message']}"
                )
                if diag.get("fix"):
                    err_console.print(f"  fix: {diag['fix']}")
        else:
            console.print("[bold green]✓[/bold green] No diagnostics found.")

    raise typer.Exit(code=1 if diagnostics else 0)


@app.command("apply-patch")
def apply_patch_cmd(
    process_file: Path = typer.Argument(..., help="Path to process YAML.", exists=True),
    patch_file: Path = typer.Argument(..., help="Path to JSON patch file.", exists=True),
    in_place: bool = typer.Option(
        True,
        "--in-place/--no-in-place",
        help="Write patched spec back to process file.",
    ),
) -> None:
    """Apply JSON patch operations to a process spec."""
    try:
        raw = load_yaml_file(process_file)
        operations = load_patch_file(patch_file)
        patched = apply_json_patch(raw, operations)
        canonical = normalize_process_dict(patched)
        rendered = yaml.safe_dump(canonical, sort_keys=False).rstrip() + "\n"
    except (ParseError, PatchApplyError) as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)

    if in_place:
        process_file.write_text(rendered)
        console.print(f"[bold green]✓[/bold green] Patch applied: [cyan]{process_file}[/cyan]")
        return
    console.print(rendered, end="")


@app.command("suggest-fix")
def suggest_fix(
    process_file: Path = typer.Argument(..., help="Path to process YAML.", exists=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable suggestions."),
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Suggest patch-based repairs from diagnostics."""
    diagnostics = _collect_diagnostics(process_file, providers_file)
    suggestions: list[dict] = []
    for diag in diagnostics:
        patch = diag.get("example_patch") or []
        if patch:
            suggestions.append(
                {
                    "error_code": diag.get("error_code"),
                    "path": diag.get("path"),
                    "patch": patch,
                }
            )

    if json_output:
        console.print_json(
            json.dumps(
                {
                    "ok": not diagnostics,
                    "errors": diagnostics,
                    "suggestions": suggestions,
                },
                sort_keys=True,
            )
        )
    else:
        if suggestions:
            for item in suggestions:
                console.print(
                    f"{item['error_code']} {item['path']}: {json.dumps(item['patch'], sort_keys=True)}"
                )
        elif diagnostics:
            err_console.print("No patch suggestions available for current diagnostics.")
        else:
            console.print("[bold green]✓[/bold green] No diagnostics found.")

    if diagnostics and not suggestions:
        raise typer.Exit(code=1)


@app.command()
def fmt(
    process_file: Path = typer.Argument(
        ...,
        help="Path to the process definition file (e.g. process.bpg.yaml).",
        exists=True,
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Check formatting only; exit non-zero if file would change.",
    ),
    write: bool = typer.Option(
        True,
        "--write/--no-write",
        help="Write canonical formatting back to file.",
    ),
) -> None:
    """Canonicalize process YAML ordering and formatting."""
    try:
        formatted, changed = format_process_file(process_file)
    except ParseError as e:
        err_console.print(f"Error: {e}")
        raise typer.Exit(code=1)

    if check:
        if changed:
            err_console.print(f"Formatting needed: {process_file}")
            raise typer.Exit(code=1)
        console.print(f"[bold green]✓[/bold green] Already canonical: [cyan]{process_file}[/cyan]")
        return

    if write and changed:
        process_file.write_text(formatted)
        console.print(f"[bold green]✓[/bold green] Formatted: [cyan]{process_file}[/cyan]")
        return

    if write:
        console.print(f"[bold green]✓[/bold green] Already canonical: [cyan]{process_file}[/cyan]")
        return

    console.print(formatted, end="")


@app.command()
def show(
    plan_file: Path = typer.Argument(
        ...,
        help="Path to a plan artifact generated by `bpg plan --out`.",
        exists=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit raw JSON (similar to `terraform show -json`).",
    ),
) -> None:
    """Inspect a saved BPG plan artifact."""
    try:
        raw = plan_file.read_text()
        plan_doc = json.loads(raw)
        if not isinstance(plan_doc, dict):
            err_console.print("Error: plan artifact must be a JSON object.")
            raise typer.Exit(code=1)
        if "format_version" not in plan_doc:
            err_console.print("Error: not a BPG plan artifact (missing format_version).")
            raise typer.Exit(code=1)

        if json_output:
            console.print_json(json.dumps(plan_doc, sort_keys=True))
            return

        _print_show_summary(plan_doc, plan_file)
    except json.JSONDecodeError as e:
        err_console.print(f"Error: invalid JSON plan artifact: {e}")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        err_console.print(f"Error: {e}")
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
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Generate a docker-compose package for a process definition."""
    try:
        _load_declared_providers_or_exit(providers_file)
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
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Bring up a local runtime for the process using docker compose."""
    try:
        _load_declared_providers_or_exit(providers_file)
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
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
) -> None:
    """Deploy the planned process changes to the BPG runtime.

    Validates the plan is still current against persisted state, registers the
    updated process definition, deploys provider artifacts, and persists the
    new state. Idempotent — re-applying an already-applied plan is a no-op.
    """
    try:
        _load_declared_providers_or_exit(providers_file)
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
    providers_file: Path | None = typer.Option(
        None,
        "--providers-file",
        help=_PROVIDERS_FILE_HELP,
        exists=False,
    ),
    engine: str = typer.Option(
        "langgraph",
        "--engine",
        help="Execution backend to use (langgraph or local).",
    ),
) -> None:
    """Trigger a new run of a deployed process with an input payload."""
    try:
        _load_declared_providers_or_exit(providers_file)
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

        engine_runner = Engine(process=process, state_store=store, backend=engine)

        with console.status("[bold green]Running process..."):
            run_id = engine_runner.trigger(input_payload)

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
