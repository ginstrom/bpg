"""BPG Visualizer — generates a standalone SVG/HTML page for process visualization."""

from __future__ import annotations

import html as _html
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bpg.compiler.ir import ExecutionIR


def _e(s: object) -> str:
    """HTML/XML-escape a value for safe inline use."""
    return _html.escape(str(s))


def _compute_positions(
    node_names: list[str],
    edges: list,
    topological_order: list[str],
    node_w: float,
    node_h: float,
    h_gap: float,
    v_gap: float,
    canvas_w: float,
    top_pad: float,
) -> tuple[dict[str, tuple[float, float]], dict[str, int], float]:
    """
    Layered-graph layout (longest-path layering using the provided topological order).

    Returns (positions, layer_map, total_svg_height).
    """
    # Build adjacency for layer assignment
    node_set = set(node_names)
    out_adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.source in node_set and e.target in node_set:
            out_adj[e.source].append(e.target)

    topo: list[str] = [n for n in topological_order if n in node_set]
    if not topo:
        topo = list(node_names)
    else:
        # Ensure nodes omitted from topo are still rendered deterministically.
        for n in node_names:
            if n not in topo:
                topo.append(n)

    # Assign layer = max(layer[pred] + 1)
    layer: dict[str, int] = {n: 0 for n in node_names}
    for node in topo:
        for tgt in out_adj[node]:
            layer[tgt] = max(layer[tgt], layer[node] + 1)

    # Group by layer, preserving topo order within each layer
    layer_nodes: dict[int, list[str]] = defaultdict(list)
    for n in topo:
        layer_nodes[layer[n]].append(n)

    # Compute (x, y) for each node
    max_layer = max(layer.values()) if layer else 0
    positions: dict[str, tuple[float, float]] = {}
    for lvl in range(max_layer + 1):
        nodes_in_lvl = layer_nodes[lvl]
        count = len(nodes_in_lvl)
        total_w = count * node_w + (count - 1) * h_gap
        start_x = (canvas_w - total_w) / 2
        for j, n in enumerate(nodes_in_lvl):
            x = start_x + j * (node_w + h_gap)
            y = top_pad + lvl * (node_h + v_gap)
            positions[n] = (x, y)

    svg_h = top_pad + (max_layer + 1) * (node_h + v_gap)
    return positions, layer, svg_h


def generate_html(ir: "ExecutionIR") -> str:
    """Generates a fully self-contained HTML+SVG visualization (no CDN dependencies)."""
    process_name = ir.process.metadata.name if ir.process.metadata else "BPG Process"
    trigger_node = ir.process.trigger

    node_w: float = 200
    node_h: float = 95
    h_gap: float = 60
    v_gap: float = 80
    canvas_w: float = 700
    top_pad: float = 60   # room for the title

    node_names = list(ir.process.nodes.keys())

    positions, layer_map, svg_h = _compute_positions(
        node_names, ir.process.edges, ir.topological_order,
        node_w, node_h, h_gap, v_gap, canvas_w, top_pad
    )

    parts: list[str] = []

    # ── Defs (shadow filter + arrowhead marker) ────────────────────────────
    parts.append(
        '<defs>'
        '<filter id="sh" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0000001a"/>'
        '</filter>'
        '<marker id="ar" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">'
        '<polygon points="0 0, 8 3, 0 6" fill="#94a3b8"/>'
        '</marker>'
        '</defs>'
    )

    # Background
    parts.append(f'<rect width="{canvas_w:.0f}" height="{svg_h:.0f}" fill="#f8fafc"/>')

    # ── Edges (drawn before nodes so they appear behind) ──────────────────
    for edge in ir.process.edges:
        src, tgt = edge.source, edge.target
        if src not in positions or tgt not in positions:
            continue
        sx, sy = positions[src]
        tx, ty = positions[tgt]
        x1 = sx + node_w / 2
        y1 = sy + node_h
        x2 = tx + node_w / 2
        y2 = ty
        mid_y = (y1 + y2) / 2

        src_layer = layer_map.get(src, 0)
        tgt_layer = layer_map.get(tgt, 0)
        is_skip = (tgt_layer - src_layer) > 1
        # Route skip/back edges to the right to avoid crossing intermediate nodes
        arc_x = max(sx + node_w, tx + node_w) + h_gap

        if y2 <= y1:
            # Back-edge: route around the right side
            path_d = (
                f"M {x1:.1f} {y1:.1f} "
                f"C {arc_x:.1f} {y1:.1f}, "
                f"{arc_x:.1f} {y2:.1f}, "
                f"{x2:.1f} {y2:.1f}"
            )
        elif is_skip:
            # Skip-layer forward edge: arc to the right to avoid intermediate nodes
            path_d = (
                f"M {x1:.1f} {y1:.1f} "
                f"C {arc_x:.1f} {y1:.1f}, "
                f"{arc_x:.1f} {y2:.1f}, "
                f"{x2:.1f} {y2:.1f}"
            )
        else:
            path_d = (
                f"M {x1:.1f} {y1:.1f} "
                f"C {x1:.1f} {mid_y:.1f}, "
                f"{x2:.1f} {mid_y:.1f}, "
                f"{x2:.1f} {y2:.1f}"
            )

        parts.append(
            f'<path d="{path_d}" fill="none" stroke="#94a3b8" '
            f'stroke-width="1.5" marker-end="url(#ar)"/>'
        )

        if edge.when:
            if is_skip or y2 <= y1:
                # Label sits beside the right-side arc, clear of intermediate nodes
                lx = arc_x + 4
                ly = mid_y
            else:
                lx = (x1 + x2) / 2 + 8
                ly = mid_y - 3
            label_text = _e(edge.when)
            label_w = len(edge.when) * 6 + 10
            parts.append(
                f'<rect x="{lx - 4:.1f}" y="{ly - 11:.1f}" '
                f'width="{label_w:.0f}" height="15" rx="3" fill="#f1f5f9" stroke="#e2e8f0" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" '
                f'font-family="system-ui,sans-serif" font-size="10" fill="#64748b">'
                f'{label_text}</text>'
            )

    # ── Nodes ─────────────────────────────────────────────────────────────
    for name, (x, y) in positions.items():
        inst = ir.process.nodes[name]
        is_trigger = name == trigger_node

        fill = "#f0f9ff" if is_trigger else "#ffffff"
        stroke = "#0ea5e9" if is_trigger else "#cbd5e1"
        sw = "2" if is_trigger else "1"
        text_color = "#0c4a6e" if is_trigger else "#0f172a"

        parts.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{node_w:.0f}" height="{node_h:.0f}" '
            f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" filter="url(#sh)"/>'
        )

        cx = x + node_w / 2
        prefix = "TRIGGER — " if is_trigger else ""
        fw = "bold" if is_trigger else "600"

        parts.append(
            f'<text x="{cx:.0f}" y="{y + 26:.0f}" '
            f'font-family="system-ui,sans-serif" font-size="13" font-weight="{fw}" '
            f'fill="{text_color}" text-anchor="middle">'
            f'{prefix}{_e(name)}</text>'
        )
        parts.append(
            f'<text x="{cx:.0f}" y="{y + 45:.0f}" '
            f'font-family="system-ui,sans-serif" font-size="11" fill="#64748b" text-anchor="middle">'
            f'{_e(inst.node_type)}</text>'
        )
        if inst.description:
            desc = (
                inst.description if len(inst.description) <= 36
                else inst.description[:33] + "\u2026"
            )
            parts.append(
                f'<text x="{cx:.0f}" y="{y + 63:.0f}" '
                f'font-family="system-ui,sans-serif" font-size="10" fill="#94a3b8" text-anchor="middle">'
                f'{_e(desc)}</text>'
            )

        # ── In/Out type badge ─────────────────────────────────────────────
        rnode = ir.resolved_nodes[name]
        in_name = rnode.in_type.name
        out_name = rnode.out_type.name
        type_label = f"in: {in_name}  \u2192  out: {out_name}"
        parts.append(
            f'<text x="{cx:.0f}" y="{y + 83:.0f}" '
            f'font-family="system-ui,sans-serif" font-size="9" fill="#94a3b8" text-anchor="middle">'
            f'{_e(type_label)}</text>'
        )

    # ── Title ──────────────────────────────────────────────────────────────
    parts.append(
        f'<text x="{canvas_w / 2:.0f}" y="30" '
        f'font-family="system-ui,sans-serif" font-size="16" font-weight="bold" '
        f'fill="#1e293b" text-anchor="middle">{_e(process_name)}</text>'
    )

    svg_inner = "\n    ".join(parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>BPG Visualizer \u2014 {_e(process_name)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #f8fafc;
      font-family: system-ui, -apple-system, sans-serif;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    svg {{ display: block; max-width: 100%; height: auto; }}
  </style>
</head>
<body>
  <svg xmlns="http://www.w3.org/2000/svg"
       width="{canvas_w:.0f}" height="{svg_h:.0f}"
       viewBox="0 0 {canvas_w:.0f} {svg_h:.0f}">
    {svg_inner}
  </svg>
</body>
</html>"""
