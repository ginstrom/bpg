"""BPG process validator.

Performs semantic validation of a parsed ``Process`` model.  All checks here
correspond to the compilation steps defined in §5 of the specification.
Validation failures raise ``ValidationError`` with a descriptive message; the
caller (typically the ``plan`` command) is responsible for formatting output.

Validation steps:
    1. Resolve all type references — unknown types are a hard error.
    2. Resolve all node type references — unknown or version-mismatched refs fail.
    3. Type-check edge ``with`` mappings against target ``in`` schemas.
    4. Validate all ``when`` expressions are syntactically valid.
    5. Detect cycles in the execution graph (loops require explicit constructs).
    6. Validate all provider configs against their declared ``config_schema``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict
from bpg.compiler.errors import CompilerDiagnostic
from bpg.compiler.types import FieldType, parse_field_type
from bpg.models.schema import Process, TypeDef, NodeInstance, NodeType, ModuleDefinition


@dataclass(frozen=True)
class ResolvedTypeDef:
    """TypeDef with each field string parsed into a FieldType.

    For primitive types (``object``, ``string``, etc.) used as node in/out
    types, ``fields`` will be an empty dict.
    """

    name: str
    fields: Dict[str, FieldType]

    def required_fields(self) -> List[str]:
        """Return names of fields whose FieldType.is_required is True."""
        return [name for name, ft in self.fields.items() if ft.is_required]

    def optional_fields(self) -> List[str]:
        """Return names of fields whose FieldType.is_required is False."""
        return [name for name, ft in self.fields.items() if not ft.is_required]


@dataclass
class ResolvedNode:
    """Node instance with type information fully resolved."""

    name: str
    instance: NodeInstance
    node_type: NodeType | ModuleDefinition
    in_type: ResolvedTypeDef
    out_type: ResolvedTypeDef
    is_module: bool = False


def resolve_typedef(name: str, typedef: TypeDef) -> ResolvedTypeDef:
    """Convert a :class:`TypeDef` into a :class:`ResolvedTypeDef`.

    Each field's type string is passed through :func:`parse_field_type`.

    Args:
        name:    The declared name of the type (e.g. ``"BugReport"``).
        typedef: The raw :class:`TypeDef` from the parsed process.

    Returns:
        A :class:`ResolvedTypeDef` with fully parsed field types.
    """
    fields: Dict[str, FieldType] = {}
    for field_name, type_str in typedef.items():
        fields[field_name] = parse_field_type(type_str)
    return ResolvedTypeDef(name=name, fields=fields)


class ValidationError(Exception):
    """Raised when a process definition fails semantic validation."""

    def __init__(
        self,
        message: str,
        node: str | None = None,
        field: str | None = None,
        *,
        code: str = "E_VALIDATION",
        path: str | None = None,
        fix: str | None = None,
        example_patch: list[dict[str, Any]] | None = None,
        schema_excerpt: dict[str, Any] | None = None,
    ) -> None:
        context = ""
        if node:
            context += f" (node={node!r}"
            if field:
                context += f", field={field!r}"
            context += ")"
        super().__init__(f"ValidationError{context}: {message}")
        self.node = node
        self.field = field
        diagnostic_path = path or (f"$.{field}" if field else "$")
        self.diagnostic = CompilerDiagnostic(
            error_code=code,
            path=diagnostic_path,
            message=message,
            fix=fix,
            example_patch=example_patch or [],
            schema_excerpt=schema_excerpt or {},
        )


def validate_process(process: Process) -> None:
    """Run all semantic validation checks against a parsed process definition.

    Args:
        process: A ``Process`` instance produced by ``parse_process_file``.

    Raises:
        ValidationError: On the first semantic error encountered.
    """
    if not process.types:
        raise ValidationError(
            "Process must declare at least one type definition",
            field="types",
            code="E_TYPES_REQUIRED",
            fix="Add a non-empty `types` section with at least one named type definition.",
            example_patch=[
                {
                    "op": "add",
                    "path": "$.types",
                    "value": {"RequiredType": {"ok": "bool"}},
                }
            ],
            schema_excerpt={"types": {"<TypeName>": {"field_name": "string"}}},
        )

    # Step 1: Resolve all type references
    _validate_type_refs(process)

    # Step 2: Resolve all node type and module references
    _validate_node_type_refs(process)

    # Prepare common registries
    type_registry: Dict[str, ResolvedTypeDef] = {}
    for type_name, typedef in process.types.items():
        type_registry[type_name] = resolve_typedef(type_name, typedef)

    # Step 3: Validate all modules
    # Resolved modules are needed for nodes that refer to them
    resolved_modules: Dict[str, ResolvedModule] = validate_modules(process, type_registry)

    # Step 4: Validate the main process structure
    validate_graph_structure(
        name="process",
        nodes=process.nodes,
        edges=process.edges,
        trigger=process.trigger,
        type_registry=type_registry,
        node_types=process.node_types,
        modules=process.modules,
        resolved_modules=resolved_modules,
        process_output=process.output,
    )

    # Step 5: Validate all provider configs (§5 step 7)
    _validate_provider_configs(process)

    # Step 6: Validate security/policy (§13)
    _validate_policy(process)


def _validate_policy(process: Process) -> None:
    """Assert process security policies are syntactically valid and reference existing nodes."""
    if not process.policy:
        return

    policy = process.policy

    # Access Control
    if policy.access_control:
        for ac in policy.access_control:
            if ac.node not in process.nodes:
                raise ValidationError(
                    f"Policy references unknown node {ac.node!r}", field="policy.access_control"
                )

    # PII Redaction
    if policy.pii_redaction:
        for pr in policy.pii_redaction:
            if pr.node not in process.nodes:
                raise ValidationError(
                    f"Policy references unknown node {pr.node!r}", field="policy.pii_redaction"
                )
            
            # (Optional) Validate that fields exist in the node's types
            # This requires resolving the node's types, which we did in _validate_graph_structure
            # but we don't have the results here easily unless we refactor more.
            # For now, let's just ensure the node exists.

    # Separation of duties advanced rules
    if policy.separation_of_duties:
        rules = policy.separation_of_duties.get("rules", [])
        if rules is not None and not isinstance(rules, list):
            raise ValidationError(
                "policy.separation_of_duties.rules must be a list",
                field="policy.separation_of_duties",
            )
        for rule in rules or []:
            if not isinstance(rule, dict):
                raise ValidationError(
                    "policy.separation_of_duties.rules entries must be objects",
                    field="policy.separation_of_duties",
                )
            if "left_principal_field" not in rule or "right_principal_field" not in rule:
                raise ValidationError(
                    "SoD rule requires left_principal_field and right_principal_field",
                    field="policy.separation_of_duties",
                )
            nodes = rule.get("nodes", [])
            if nodes is not None:
                if not isinstance(nodes, list):
                    raise ValidationError(
                        "SoD rule nodes must be a list",
                        field="policy.separation_of_duties",
                    )
                for node_name in nodes:
                    if node_name not in process.nodes:
                        raise ValidationError(
                            f"SoD rule references unknown node {node_name!r}",
                            field="policy.separation_of_duties",
                        )

    # Escalation policy
    if policy.escalation:
        for i, rule in enumerate(policy.escalation):
            if not isinstance(rule, dict):
                raise ValidationError("policy.escalation entries must be objects", field="policy.escalation")
            node_name = rule.get("node")
            route_to = rule.get("route_to")
            event = rule.get("on", rule.get(True))
            if not isinstance(node_name, str) or node_name not in process.nodes:
                raise ValidationError(
                    f"Escalation rule #{i + 1} has unknown node {node_name!r}",
                    field="policy.escalation",
                )
            if event not in {"timeout", "failure"}:
                raise ValidationError(
                    f"Escalation rule #{i + 1} has invalid 'on' value {event!r}",
                    field="policy.escalation",
                )
            if route_to is not None and route_to not in process.nodes:
                raise ValidationError(
                    f"Escalation rule #{i + 1} route_to references unknown node {route_to!r}",
                    field="policy.escalation",
                )


@dataclass
class ResolvedModule:
    """A module definition with its internal structure and interface resolved."""

    name: str
    definition: ModuleDefinition
    in_type: ResolvedTypeDef
    out_type: ResolvedTypeDef
    # We store the internal resolved nodes for output type resolution
    internal_resolved_nodes: Dict[str, ResolvedNode]


def validate_modules(
    process: Process, type_registry: Dict[str, ResolvedTypeDef]
) -> Dict[str, ResolvedModule]:
    """Recursively validate and resolve all module definitions.

    Returns:
        Mapping from module key to its resolved interface.
    """
    resolved_modules: Dict[str, ResolvedModule] = {}
    resolving: set[str] = set()

    def _resolve_module(mod_name: str) -> None:
        if mod_name in resolved_modules:
            return
        if mod_name in resolving:
            raise ValidationError(
                f"Cyclic module dependency detected at {mod_name!r}",
                node=mod_name,
                field="modules",
            )
        if mod_name not in process.modules:
            raise ValidationError(
                f"Unknown module {mod_name!r}",
                node=mod_name,
                field="modules",
            )
        resolving.add(mod_name)
        mod = process.modules[mod_name]

        for internal_node in mod.nodes.values():
            if internal_node.node_type in process.modules:
                _resolve_module(internal_node.node_type)

        # Validate inputs types
        in_fields: Dict[str, FieldType] = {}
        for input_name, type_str in mod.inputs.items():
            # Check if type_str is a primitive or in the registry
            if type_str not in type_registry and type_str not in {
                "string",
                "number",
                "bool",
                "duration",
                "datetime",
                "object",
            }:
                 # Need to handle enum(...) and list<...> as well
                 try:
                     parse_field_type(type_str)
                 except Exception as e:
                     raise ValidationError(
                         f"Invalid input type {type_str!r} for module {mod_name!r}",
                         node=mod_name,
                         field="inputs",
                     )
            in_fields[input_name] = parse_field_type(type_str)

        in_type = ResolvedTypeDef(name=f"{mod_name}.in", fields=in_fields)

        # Validate the module's internal graph
        # For modules, trigger is "__input__"
        internal_resolved_nodes = validate_graph_structure(
            name=f"module {mod_name!r}",
            nodes=mod.nodes,
            edges=mod.edges,
            trigger="__input__",
            type_registry=type_registry,
            node_types=process.node_types,
            modules=process.modules,
            resolved_modules=resolved_modules,  # Support already resolved modules
            module_in_type=in_type,
        )

        # Resolve output types
        out_fields: Dict[str, FieldType] = {}
        for out_name, out_ref in mod.outputs.items():
            # out_ref is node.out.field
            if not _RE_FIELD_REF.match(out_ref):
                raise ValidationError(
                    f"Invalid output reference {out_ref!r} in module {mod_name!r}",
                    node=mod_name,
                    field="outputs",
                )
            
            parts = out_ref.split(".")
            node_name = parts[0]
            if node_name == "__input__":
                 # Exporting an input as an output is valid
                 if parts[1] != "in":
                     raise ValidationError(
                        f"Output reference {out_ref!r} must use '__input__.in'",
                        node=mod_name,
                        field="outputs",
                     )
                 field_name = parts[2]
                 if field_name not in in_type.fields:
                     raise ValidationError(
                        f"Unknown input field {field_name!r} in output reference {out_ref!r}",
                        node=mod_name,
                        field="outputs",
                     )
                 out_fields[out_name] = in_type.fields[field_name]
                 continue

            if node_name not in internal_resolved_nodes:
                raise ValidationError(
                    f"Output reference {out_ref!r} uses unknown node {node_name!r}",
                    node=mod_name,
                    field="outputs",
                )
            
            if parts[1] != "out":
                 raise ValidationError(
                    f"Output reference {out_ref!r} must use 'out' segment",
                    node=mod_name,
                    field="outputs",
                 )
            
            field_name = parts[2]
            rnode = internal_resolved_nodes[node_name]
            if rnode.out_type.fields and field_name not in rnode.out_type.fields:
                 raise ValidationError(
                    f"Unknown output field {field_name!r} in reference {out_ref!r}",
                    node=mod_name,
                    field="outputs",
                 )
            
            # Use the field type from the internal node's output
            if rnode.out_type.fields:
                out_fields[out_name] = rnode.out_type.fields[field_name]
            else:
                # Primitive out type, but we have a field name? That's an error
                # unless the out_ref was just node.out (which _RE_FIELD_REF wouldn't match with 3 parts)
                raise ValidationError(
                    f"Node {node_name!r} has a primitive output, cannot reference field {field_name!r}",
                    node=mod_name,
                    field="outputs",
                )

        out_type = ResolvedTypeDef(name=f"{mod_name}.out", fields=out_fields)

        resolved_modules[mod_name] = ResolvedModule(
            name=mod_name,
            definition=mod,
            in_type=in_type,
            out_type=out_type,
            internal_resolved_nodes=internal_resolved_nodes,
        )
        resolving.remove(mod_name)

    for mod_name in process.modules:
        _resolve_module(mod_name)

    return resolved_modules


def validate_graph_structure(
    name: str,
    nodes: Dict[str, NodeInstance],
    edges: List[Edge],
    trigger: str,
    type_registry: Dict[str, ResolvedTypeDef],
    node_types: Dict[str, NodeType],
    modules: Dict[str, ModuleDefinition],
    resolved_modules: Dict[str, ResolvedModule],
    module_in_type: ResolvedTypeDef | None = None,
    process_output: str | None = None,
) -> Dict[str, ResolvedNode]:
    """Validate a set of nodes and edges (either for a process or a module).

    Returns:
        Mapping from node name to its resolved structure.
    """

    def _resolve_type(type_name: str) -> ResolvedTypeDef:
        if type_name in type_registry:
            return type_registry[type_name]
        return ResolvedTypeDef(name=type_name, fields={})

    resolved_nodes: Dict[str, ResolvedNode] = {}
    for node_name, node_instance in nodes.items():
        type_ref = node_instance.node_type
        if type_ref in node_types:
            nt = node_types[type_ref]
            in_type = _resolve_type(nt.input_type)
            out_type = _resolve_type(nt.output_type)
            resolved_nodes[node_name] = ResolvedNode(
                name=node_name,
                instance=node_instance,
                node_type=nt,
                in_type=in_type,
                out_type=out_type,
            )
        elif type_ref in resolved_modules:
            rm = resolved_modules[type_ref]
            resolved_nodes[node_name] = ResolvedNode(
                name=node_name,
                instance=node_instance,
                node_type=rm.definition,
                in_type=rm.in_type,
                out_type=rm.out_type,
                is_module=True,
            )
        else:
             # Should be caught by _validate_node_type_refs
             raise ValidationError(f"Unknown node type or module {type_ref!r}", node=node_name)

    # Validate trigger
    if trigger == "__input__":
        # For modules, __input__ acts as a synthetic source
        pass
    elif trigger not in nodes:
        raise ValidationError(f"Trigger node {trigger!r} not found in {name}", field="trigger")

    # Cycle detection
    adj = {n: [] for n in nodes}
    for edge in edges:
        if edge.source == "__input__":
             if trigger != "__input__":
                 raise ValidationError(f"__input__ is only valid in modules, not in {name}")
             continue
        if edge.source not in adj:
            raise ValidationError(f"Edge references unknown source node {edge.source!r} in {name}")
        if edge.target not in adj:
            raise ValidationError(f"Edge references unknown target node {edge.target!r} in {name}")
        adj[edge.source].append(edge.target)

    # Trigger must not have incoming edges (§4.4)
    if trigger != "__input__":
        incoming_to_trigger = [e for e in edges if e.target == trigger]
        if incoming_to_trigger:
            raise ValidationError(
                f"Trigger node {trigger!r} must not have incoming edges in {name}",
                field="trigger",
            )

    visited = set()
    path = set()

    def visit(u):
        if u in path:
            raise ValidationError(f"Cycle detected in {name} involving node {u!r}")
        if u in visited:
            return
        path.add(u)
        for v in adj.get(u, []):
            visit(v)
        path.remove(u)
        visited.add(u)

    for node in nodes:
        if node not in visited:
            visit(node)

    # Edge mappings and when expressions
    for edge in edges:
        src, tgt = edge.source, edge.target
        target_node = resolved_nodes[tgt]
        in_type = target_node.in_type
        mapping = edge.mapping or {}

        # Validate edge references
        for value in mapping.values():
             _validate_mapping_ref_v2(
                 value, resolved_nodes, trigger, src, tgt, module_in_type
             )
        
        # Type-check mapping
        if in_type.fields:
            mapping_keys = set(mapping.keys())
            schema_keys = set(in_type.fields.keys())

            extra = sorted(mapping_keys - schema_keys)
            if extra:
                raise ValidationError(
                    f"Edge {src!r} -> {tgt!r}: mapping contains extra fields: {extra}"
                )

        # When expressions
        if edge.when:
            _parse_when(edge.when, src, tgt)

    # Required input coverage per target across all incoming edges
    incoming_by_target: Dict[str, List[Edge]] = {}
    for edge in edges:
        incoming_by_target.setdefault(edge.target, []).append(edge)
    for tgt, incoming_edges in incoming_by_target.items():
        target_node = resolved_nodes[tgt]
        in_type = target_node.in_type
        if not in_type.fields:
            continue
        required_keys = set(in_type.required_fields())
        provided_union: set[str] = set()
        for edge in incoming_edges:
            provided_union |= set((edge.mapping or {}).keys())
        missing = sorted(required_keys - provided_union)
        if missing:
            raise ValidationError(
                f"Node {tgt!r}: incoming edge mappings are missing required fields: {missing}"
            )

    # Validate process output if present
    if process_output:
        _validate_output_ref(process_output, resolved_nodes, trigger)

    # Human node timeout contract (§9): require timeout + on_timeout.out
    for node_name, rnode in resolved_nodes.items():
        if rnode.is_module or not isinstance(rnode.node_type, NodeType):
            continue
        if rnode.node_type.provider not in _HUMAN_PROVIDER_IDS:
            continue
        if trigger != "__input__" and node_name == trigger:
            # Trigger node is entrypoint passthrough in current runtime model.
            continue

        timeout_value = rnode.instance.config.get("timeout")
        if timeout_value in (None, ""):
            raise ValidationError(
                "Human node requires config.timeout",
                node=node_name,
                field="config.timeout",
            )

        on_timeout = rnode.instance.on_timeout
        if not isinstance(on_timeout, dict) or "out" not in on_timeout:
            raise ValidationError(
                "Human node requires on_timeout.out",
                node=node_name,
                field="on_timeout",
            )
        _validate_typed_payload(
            on_timeout["out"],
            rnode.out_type,
            node_name=node_name,
            field="on_timeout.out",
        )

    return resolved_nodes


def _validate_mapping_ref_v2(
    value: Any,
    resolved_nodes: Dict[str, ResolvedNode],
    trigger_name: str,
    src: str,
    tgt: str,
    module_in_type: ResolvedTypeDef | None = None,
) -> None:
    if not isinstance(value, str) or "{{" in value or not _RE_FIELD_REF.match(value):
        return

    parts = value.split(".")
    node_ref = parts[0]

    if node_ref == "trigger":
        node_ref = trigger_name
    
    if node_ref == "__input__":
        if not module_in_type:
             raise ValidationError(f"Edge {src!r} -> {tgt!r}: '__input__' is only valid in modules")
        if len(parts) >= 3:
             field_name = parts[2]
             if field_name not in module_in_type.fields:
                  raise ValidationError(
                      f"Edge {src!r} -> {tgt!r}: unknown input field {field_name!r}"
                  )
        return

    if node_ref not in resolved_nodes:
        # Check if it's a module input reference
        if module_in_type and node_ref in module_in_type.fields:
             if len(parts) >= 2:
                  field_name = parts[1]
                  input_field_type = module_in_type.fields[node_ref]
                  # Resolve the input_field_type name to its ResolvedTypeDef to check fields
                  # But wait, we don't have the type_registry here.
                  # For now, just allow it if it's a known input.
             return

        raise ValidationError(
            f"Edge {src!r} -> {tgt!r}: mapping references unknown node {node_ref!r}"
        )

    if len(parts) >= 3:
        segment, field_name = parts[1], parts[2]
        rnode = resolved_nodes[node_ref]
        ref_type = rnode.out_type if segment == "out" else rnode.in_type if segment == "in" else None
        if ref_type and ref_type.fields and field_name not in ref_type.fields:
             raise ValidationError(
                f"Edge {src!r} -> {tgt!r}: unknown field {field_name!r} on {node_ref}.{segment}"
             )


def _validate_output_ref(
    val: str, resolved_nodes: Dict[str, ResolvedNode], trigger_name: str
) -> None:
    if not _RE_FIELD_REF.match(val):
        raise ValidationError(f"Invalid output reference {val!r}", field="output")

    parts = val.split(".")
    node_name = parts[0]
    if node_name == "trigger":
        node_name = trigger_name

    if node_name not in resolved_nodes:
        raise ValidationError(f"Output references unknown node {node_name!r}", field="output")

    if parts[1] != "out":
        raise ValidationError(f"Output must reference 'out' segment, got {parts[1]!r}", field="output")

    if len(parts) >= 3:
        field_name = parts[2]
        rnode = resolved_nodes[node_name]
        if rnode.out_type.fields and field_name not in rnode.out_type.fields:
            raise ValidationError(
                f"Output references unknown field {field_name!r} on {node_name}.out",
                field="output",
            )


def _validate_type_refs(process: Process) -> None:
    """Assert all type names referenced by node types exist in the type registry."""
    known_types = set(process.types.keys())
    # Built-in primitive types are always known
    primitives = {"string", "number", "bool", "duration", "datetime", "object"}
    known_types.update(primitives)

    for nt_name, nt in process.node_types.items():
        if nt.input_type not in known_types:
            raise ValidationError(f"Unknown input type {nt.input_type!r}", node=nt_name, field="in")
        if nt.output_type not in known_types:
            raise ValidationError(f"Unknown output type {nt.output_type!r}", node=nt_name, field="out")


def _validate_node_type_refs(process: Process) -> None:
    """Assert all node instance ``type`` references resolve to declared node types or modules.

    Also validates that node types and modules have a valid version and that the version
    matches the reference key if the key uses the name@version convention.
    """
    # Validate node_types
    for nt_name, nt in process.node_types.items():
        if not re.match(r"^v?\d+(?:\.\d+)*", nt.version):
            raise ValidationError(
                f"Invalid version {nt.version!r} for node type {nt_name!r}",
                node=nt_name,
                field="version",
            )

        if "@" in nt_name:
            _, key_version = nt_name.split("@", 1)
            if key_version != nt.version:
                raise ValidationError(
                    f"Node type key version {key_version!r} does not match "
                    f"version field {nt.version!r}",
                    node=nt_name,
                )

    # Validate modules
    for mod_name, mod in process.modules.items():
        if not re.match(r"^v?\d+(?:\.\d+)*", mod.version):
            raise ValidationError(
                f"Invalid version {mod.version!r} for module {mod_name!r}",
                node=mod_name,
                field="version",
            )

        if "@" in mod_name:
            _, key_version = mod_name.split("@", 1)
            if key_version != mod.version:
                raise ValidationError(
                    f"Module key version {key_version!r} does not match "
                    f"version field {mod.version!r}",
                    node=mod_name,
                )

    # Validate instance references
    for node_name, node in process.nodes.items():
        if node.node_type not in process.node_types and node.node_type not in process.modules:
            raise ValidationError(
                f"Unknown node type or module {node.node_type!r}", node=node_name, field="type"
            )


def _validate_config_value(
    field_name: str, value: Any, field_type: FieldType, node_name: str
) -> None:
    """Validate a single configuration value against its FieldType."""
    if value is None:
        if field_type.optional:
            return
        raise ValidationError(f"field {field_name!r} cannot be null", node=node_name)

    base = field_type.base

    if base == "string":
        if not isinstance(value, str):
            raise ValidationError(f"field {field_name!r} expected string", node=node_name)
    elif base == "number":
        if not isinstance(value, (int, float)):
            raise ValidationError(f"field {field_name!r} expected number", node=node_name)
    elif base == "bool":
        if not isinstance(value, bool):
            raise ValidationError(f"field {field_name!r} expected bool", node=node_name)
    elif base == "enum":
        if value not in field_type.enum_values:
            raise ValidationError(
                f"field {field_name!r} expected one of {field_type.enum_values}",
                node=node_name,
            )
    elif base == "list":
        if not isinstance(value, list):
            raise ValidationError(f"field {field_name!r} expected list", node=node_name)
        # Validate elements
        element_type = parse_field_type(field_type.list_element)
        for i, item in enumerate(value):
            _validate_config_value(
                f"{field_name}[{i}]", item, element_type, node_name
            )
    elif base == "duration":
        if not isinstance(value, str):
            raise ValidationError(
                f"field {field_name!r} expected duration string (e.g. '30s')",
                node=node_name,
            )
        # Simple regex for duration: e.g. 30s, 10m, 2h, 1d
        if not re.match(r"^\d+[smhd]$", value):
             # Also allow ISO8601 duration
             if not value.startswith("P"):
                raise ValidationError(
                    f"field {field_name!r} expected duration string (e.g. '30s')",
                    node=node_name,
                )
    elif base == "datetime":
        if not isinstance(value, str):
            raise ValidationError(
                f"field {field_name!r} expected datetime string", node=node_name
            )
        import datetime
        try:
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError(
                f"field {field_name!r} expected datetime string (ISO8601)",
                node=node_name,
            )


def _validate_provider_configs(process: Process) -> None:
    """Assert every node instance config satisfies its node type's config_schema.

    A field is required if its type string does NOT end with ``?``.  Unknown
    fields (keys in ``config`` that are not in ``config_schema``) are also an
    error.
    """
    for node_name, node in process.nodes.items():
        if node.node_type in process.modules:
             # Modules don't have a traditional provider config_schema;
             # their inputs are validated via edge mappings.
             continue
        node_type = process.node_types[node.node_type]
        config_schema = node_type.config_schema
        config = node.config

        def _flatten_leaf_paths(value: Any, prefix: str = "") -> set[str]:
            if isinstance(value, dict):
                out: set[str] = set()
                for k, v in value.items():
                    key = f"{prefix}.{k}" if prefix else str(k)
                    out |= _flatten_leaf_paths(v, key)
                return out
            return {prefix} if prefix else set()

        def _get_path(value: Dict[str, Any], dotted: str) -> tuple[bool, Any]:
            current: Any = value
            for seg in dotted.split("."):
                if not isinstance(current, dict) or seg not in current:
                    return False, None
                current = current[seg]
            return True, current

        # Detect extra fields not declared in the schema.
        # Supports dotted schema keys (e.g. "http.headers.auth").
        extra = _flatten_leaf_paths(config) - set(config_schema.keys())
        if extra:
            raise ValidationError(
                f"config contains unknown fields {sorted(extra)!r}",
                node=node_name,
            )

        # Validate each field in the schema
        for field_name, type_str in config_schema.items():
            field_type = parse_field_type(type_str)
            present, value = _get_path(config, field_name)
            if not present:
                if field_type.is_required:
                    raise ValidationError(
                        f"config is missing required field {field_name!r}",
                        node=node_name,
                    )
                continue
            
            _validate_config_value(field_name, value, field_type, node_name)

    # Validate idempotency field filters
    for node_name, node in process.nodes.items():
        if node.stable_input_fields and node.unstable_input_fields:
            raise ValidationError(
                "stable_input_fields and unstable_input_fields are mutually exclusive",
                node=node_name,
            )
        filter_fields = node.stable_input_fields or node.unstable_input_fields or []
        if not filter_fields:
            continue
        if node.node_type in process.modules:
            continue
        in_type_name = process.node_types[node.node_type].input_type
        in_type = process.types.get(in_type_name)
        if in_type is None:
            # primitive/object input types cannot be statically validated here
            continue
        unknown = [f for f in filter_fields if f not in in_type.root]
        if unknown:
            raise ValidationError(
                f"idempotency field filter references unknown input fields: {sorted(unknown)}",
                node=node_name,
            )


# ---------------------------------------------------------------------------
# Internal: when-expression parser
# ---------------------------------------------------------------------------


class _ParseError(Exception):
    """Internal exception raised by the when-expression tokenizer/parser."""


# Tokenizer -----------------------------------------------------------------

_TOKEN_SPEC = re.compile(
    r"""
    (?P<WS>     \s+)                           |
    (?P<STRING> "[^"]*" | '[^']*')             |
    (?P<FLOAT>  \d+\.\d+)                      |
    (?P<INT>    \d+)                            |
    (?P<OP>     ==|!=|>=|<=|\|\||&&|[><])      |
    (?P<NOT>    !)                              |
    (?P<LPAREN> \()                             |
    (?P<RPAREN> \))                             |
    (?P<COMMA>  ,)                              |
    (?P<WORD>   [a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)
    """,
    re.VERBOSE,
)

_KNOWN_FUNCS: frozenset[str] = frozenset({"is_null", "is_present"})


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenize *expr* into a list of ``(kind, value)`` pairs, skipping WS.

    Raises:
        _ParseError: For any character not matched by the token spec.
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_SPEC.finditer(expr):
        if m.start() != pos:
            # Gap between matches — unrecognized character(s).
            unknown = expr[pos : m.start()]
            raise _ParseError(f"unexpected character(s) {unknown!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "WS":
            continue
        tokens.append((kind, m.group()))

    if pos != len(expr):
        unknown = expr[pos:]
        raise _ParseError(f"unexpected character(s) {unknown!r}")

    return tokens


# Recursive-descent parser ---------------------------------------------------

class _Parser:
    """Recursive-descent parser for BPG ``when`` expressions."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    # -- Helpers -----------------------------------------------------------

    def _peek(self) -> tuple[str, str] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> tuple[str, str]:
        tok = self._peek()
        if tok is None or tok[0] != kind:
            got = repr(tok[1]) if tok else "end of expression"
            raise _ParseError(f"expected {kind}, got {got}")
        return self._consume()

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    # -- Grammar rules -----------------------------------------------------

    def parse(self) -> None:
        """Parse the full expression; raise _ParseError on error."""
        self._or_expr()
        if not self._at_end():
            tok = self._peek()
            raise _ParseError(f"unexpected token {tok[1]!r} after expression")

    def _or_expr(self) -> None:
        self._and_expr()
        while self._peek() and self._peek() == ("OP", "||"):
            self._consume()
            self._and_expr()

    def _and_expr(self) -> None:
        self._not_expr()
        while self._peek() and self._peek() == ("OP", "&&"):
            self._consume()
            self._not_expr()

    def _not_expr(self) -> None:
        if self._peek() and self._peek()[0] == "NOT":
            self._consume()
            self._not_expr()
        else:
            self._cmp_expr()

    def _cmp_expr(self) -> None:
        self._primary()
        tok = self._peek()
        if tok and tok[0] == "OP" and tok[1] in {"==", "!=", ">=", "<=", ">", "<"}:
            self._consume()
            self._primary()

    def _primary(self) -> None:
        tok = self._peek()
        if tok is None:
            raise _ParseError("unexpected end of expression")

        kind, value = tok

        # Grouped expression
        if kind == "LPAREN":
            self._consume()
            self._or_expr()
            self._expect("RPAREN")
            return

        # Literals
        if kind in ("STRING", "FLOAT", "INT"):
            self._consume()
            return
        if kind == "WORD" and value in ("true", "false", "null"):
            self._consume()
            return

        # WORD — could be a function call or a path reference
        if kind == "WORD":
            self._consume()
            next_tok = self._peek()
            if next_tok and next_tok[0] == "LPAREN":
                # Function call
                if value not in _KNOWN_FUNCS:
                    raise _ParseError(f"unknown function {value!r}")
                self._consume()  # consume LPAREN
                self._primary()
                self._expect("RPAREN")
            # else: path reference — nothing extra to do
            return

        raise _ParseError(f"unexpected token {value!r}")


def _parse_when(expr: str, src: str, tgt: str) -> None:
    """Validate a single ``when`` expression string.

    Args:
        expr: The raw expression string.
        src:  Source node name (for error messages).
        tgt:  Target node name (for error messages).

    Raises:
        ValidationError: On any syntax error.
    """
    try:
        tokens = _tokenize(expr)
        if not tokens:
            raise _ParseError("empty expression")
        _Parser(tokens).parse()
    except _ParseError as exc:
        raise ValidationError(
            f"Edge {src!r} -> {tgt!r}: invalid when expression: {exc}"
        )


# ---------------------------------------------------------------------------
# Internal: edge mapping type-checker
# ---------------------------------------------------------------------------

# Pattern that identifies a plain field reference: word.word.word
_RE_FIELD_REF = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+$")
_HUMAN_PROVIDER_IDS: frozenset[str] = frozenset({"slack.interactive", "dashboard.form"})


def _validate_typed_payload(
    payload: Any,
    resolved_type: ResolvedTypeDef,
    *,
    node_name: str,
    field: str,
) -> None:
    """Validate a dict payload against a resolved structured type."""
    if not resolved_type.fields:
        return
    if not isinstance(payload, dict):
        raise ValidationError(
            f"{field} must be an object conforming to {resolved_type.name!r}",
            node=node_name,
            field=field,
        )

    schema_keys = set(resolved_type.fields.keys())
    payload_keys = set(payload.keys())
    required = set(resolved_type.required_fields())

    extra = sorted(payload_keys - schema_keys)
    if extra:
        raise ValidationError(
            f"{field} contains extra fields: {extra}",
            node=node_name,
            field=field,
        )

    missing = sorted(required - payload_keys)
    if missing:
        raise ValidationError(
            f"{field} missing required fields: {missing}",
            node=node_name,
            field=field,
        )

    for fname, val in payload.items():
        _validate_config_value(
            fname,
            val,
            resolved_type.fields[fname],
            node_name,
        )


# ---------------------------------------------------------------------------
# Breaking change detection (§11)
# ---------------------------------------------------------------------------


def is_breaking_node_type_change(old: NodeType, new: NodeType) -> str | None:
    """Return a reason if the change from old to new is breaking, else None.

    A change is breaking if:
      - 'in' or 'out' type changed.
      - 'provider' changed.
      - A field was removed from 'config_schema'.
      - A field in 'config_schema' was changed (type changed, or optional -> required).
    """
    if old.input_type != new.input_type:
        return f"input type changed from {old.input_type!r} to {new.input_type!r}"
    if old.output_type != new.output_type:
        return f"output type changed from {old.output_type!r} to {new.output_type!r}"
    if old.provider != new.provider:
        return f"provider changed from {old.provider!r} to {new.provider!r}"

    old_schema = {k: parse_field_type(v) for k, v in old.config_schema.items()}
    new_schema = {k: parse_field_type(v) for k, v in new.config_schema.items()}

    for field_name, old_ft in old_schema.items():
        if field_name not in new_schema:
            return f"field {field_name!r} was removed from config_schema"

        new_ft = new_schema[field_name]
        if old_ft.base != new_ft.base:
            return f"field {field_name!r} type changed from {old_ft.base!r} to {new_ft.base!r}"
        if old_ft.enum_values != new_ft.enum_values:
            return f"field {field_name!r} enum values changed"
        if old_ft.list_element != new_ft.list_element:
            return f"field {field_name!r} list element type changed"

        if not old_ft.optional and new_ft.optional:
            # Required -> Optional is NOT breaking for existing instances
            pass
        if old_ft.optional and not new_ft.optional:
            return f"field {field_name!r} was changed from optional to required"

    return None
