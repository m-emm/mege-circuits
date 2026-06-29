"""Semantic circuit model and netlist export for schematic `Schema` objects."""

from __future__ import annotations

from dataclasses import dataclass

from mege_circuits.dsl import (
    ELEMENT_SPECS,
    Element,
    Net,
    NodeView,
    Schema,
    WireSegment,
)

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Terminal:
    name: str
    net_name: str


@dataclass(frozen=True)
class Component:
    refdes: str
    kind: str
    value: str | None
    terminals: tuple[Terminal, ...]
    terminal_views: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Circuit:
    name: str
    components: tuple[Component, ...]
    nets: tuple[Net, ...]


@dataclass(frozen=True)
class ERCIssue:
    severity: str
    code: str
    message: str
    subject: str | None = None


@dataclass(frozen=True)
class ERCReport:
    issues: tuple[ERCIssue, ...] = ()

    @property
    def errors(self):
        return tuple(issue for issue in self.issues if issue.severity == ERROR)

    @property
    def warnings(self):
        return tuple(issue for issue in self.issues if issue.severity == WARNING)

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        if not self.issues:
            return "ERC passed with no issues."
        return "\n".join(
            f"{issue.severity.upper()} {issue.code}: {issue.message}"
            for issue in self.issues
        )


def check_schema_erc(schema):
    """Return semantic ERC errors and warnings for a `Schema`."""

    if not isinstance(schema, Schema):
        raise TypeError("check_schema_erc expects a Schema object.")

    issues = []
    node_views_by_name = _collect_unique_node_views(schema.node_views, issues)
    schema_net_names = _schema_net_names(schema, issues)

    _check_components(schema.elements, schema_net_names, issues)
    _check_wires(schema.wires, node_views_by_name, issues)
    _check_floating_single_terminal_nets(schema.elements, issues)

    return ERCReport(tuple(issues))


def circuit_from_schema(schema, name=None, strict=True):
    """Lower a `Schema` into the canonical semantic `Circuit` model."""

    report = check_schema_erc(schema)
    if strict and report.errors:
        raise ValueError(report.summary())

    circuit_name = "circuit" if name is None else str(name)
    nets_by_name = {
        net.name: net for net in sorted(schema.nets, key=lambda item: item.name)
    }
    components = tuple(
        _component_from_element(element)
        for element in sorted(schema.elements, key=lambda item: item.name)
    )
    return Circuit(
        name=circuit_name,
        components=components,
        nets=tuple(nets_by_name[name] for name in sorted(nets_by_name)),
    )


def export_netlist(circuit):
    """Export a deterministic structured netlist from a semantic `Circuit`."""

    if not isinstance(circuit, Circuit):
        raise TypeError("export_netlist expects a Circuit object.")

    components = {}
    for component in sorted(circuit.components, key=lambda item: item.refdes):
        components[component.refdes] = {
            "kind": component.kind,
            "value": component.value,
            "terminals": {
                terminal.name: terminal.net_name
                for terminal in sorted(
                    component.terminals,
                    key=lambda item: item.name,
                )
            },
        }

    return {
        "name": circuit.name,
        "nets": tuple(
            net.name for net in sorted(circuit.nets, key=lambda item: item.name)
        ),
        "components": components,
    }


def _collect_unique_node_views(node_views, issues):
    node_views_by_name = {}
    for node_view in node_views:
        if not isinstance(node_view, NodeView):
            issues.append(
                ERCIssue(
                    ERROR,
                    "invalid_node_view",
                    f"Schema node view is {type(node_view).__name__}, not NodeView.",
                )
            )
            continue
        if node_view.name in node_views_by_name:
            issues.append(
                ERCIssue(
                    ERROR,
                    "duplicate_node_view",
                    f"Duplicate node view name {node_view.name!r}.",
                    subject=node_view.name,
                )
            )
            continue
        node_views_by_name[node_view.name] = node_view
    return node_views_by_name


def _schema_net_names(schema, issues):
    net_names = set()
    for net in schema.nets:
        if not isinstance(net, Net):
            issues.append(
                ERCIssue(
                    ERROR,
                    "invalid_net",
                    f"Schema net is {type(net).__name__}, not Net.",
                )
            )
            continue
        if net.name in net_names:
            issues.append(
                ERCIssue(
                    ERROR,
                    "duplicate_net",
                    f"Duplicate net name {net.name!r}.",
                    subject=net.name,
                )
            )
        net_names.add(net.name)
    return net_names


def _check_components(elements, schema_net_names, issues):
    refdes_seen = set()
    for element in elements:
        if not isinstance(element, Element):
            issues.append(
                ERCIssue(
                    ERROR,
                    "invalid_component",
                    f"Schema element is {type(element).__name__}, not Element.",
                )
            )
            continue

        if element.name in refdes_seen:
            issues.append(
                ERCIssue(
                    ERROR,
                    "duplicate_refdes",
                    f"Duplicate component reference designator {element.name!r}.",
                    subject=element.name,
                )
            )
        refdes_seen.add(element.name)

        spec = ELEMENT_SPECS.get(element.element_type)
        if spec is None:
            issues.append(
                ERCIssue(
                    ERROR,
                    "unsupported_component_type",
                    f"Unsupported component type {element.element_type!r}.",
                    subject=element.name,
                )
            )
            continue

        expected_terminals = set(spec.terminals)
        provided_terminal_views = set(element.terminal_views)
        provided_terminal_nets = set(element.terminal_nets)
        provided_terminals = provided_terminal_views | provided_terminal_nets

        missing = expected_terminals - provided_terminals
        unexpected = provided_terminals - expected_terminals
        mismatched = provided_terminal_views ^ provided_terminal_nets
        if missing:
            issues.append(
                ERCIssue(
                    ERROR,
                    "missing_terminal",
                    f"{element.name!r} is missing terminals {tuple(sorted(missing))}.",
                    subject=element.name,
                )
            )
        if unexpected:
            issues.append(
                ERCIssue(
                    ERROR,
                    "unknown_terminal",
                    f"{element.name!r} has unknown terminals {tuple(sorted(unexpected))}.",
                    subject=element.name,
                )
            )
        if mismatched:
            issues.append(
                ERCIssue(
                    ERROR,
                    "terminal_metadata_mismatch",
                    (
                        f"{element.name!r} terminal view/net metadata differs for "
                        f"{tuple(sorted(mismatched))}."
                    ),
                    subject=element.name,
                )
            )

        for terminal_name, net_name in element.terminal_nets.items():
            if net_name not in schema_net_names:
                issues.append(
                    ERCIssue(
                        ERROR,
                        "unknown_net",
                        (
                            f"{element.name!r} terminal {terminal_name!r} uses "
                            f"unknown net {net_name!r}."
                        ),
                        subject=element.name,
                    )
                )


def _check_wires(wires, node_views_by_name, issues):
    for wire in wires:
        if not isinstance(wire, WireSegment):
            issues.append(
                ERCIssue(
                    ERROR,
                    "invalid_wire",
                    f"Schema wire is {type(wire).__name__}, not WireSegment.",
                )
            )
            continue

        start = node_views_by_name.get(wire.start_view)
        end = node_views_by_name.get(wire.end_view)
        if start is None or end is None:
            issues.append(
                ERCIssue(
                    ERROR,
                    "missing_wire_endpoint",
                    f"Wire {wire.name!r} refers to a missing endpoint.",
                    subject=wire.name or None,
                )
            )
            continue

        if start.net.name != end.net.name:
            issues.append(
                ERCIssue(
                    ERROR,
                    "wire_net_mismatch",
                    (
                        f"Wire {wire.name!r} endpoints are on different nets: "
                        f"{start.net.name!r} and {end.net.name!r}."
                    ),
                    subject=wire.name or None,
                )
            )
            continue

        if wire.net_name != start.net.name:
            issues.append(
                ERCIssue(
                    ERROR,
                    "wire_declared_net_mismatch",
                    (
                        f"Wire {wire.name!r} declares net {wire.net_name!r}, "
                        f"but endpoints are on {start.net.name!r}."
                    ),
                    subject=wire.name or None,
                )
            )


def _check_floating_single_terminal_nets(elements, issues):
    terminal_counts_by_net = {}
    for element in elements:
        if not isinstance(element, Element):
            continue
        for net_name in element.terminal_nets.values():
            terminal_counts_by_net[net_name] = (
                terminal_counts_by_net.get(net_name, 0) + 1
            )

    for net_name, terminal_count in sorted(terminal_counts_by_net.items()):
        if terminal_count == 1:
            issues.append(
                ERCIssue(
                    WARNING,
                    "single_terminal_net",
                    f"Net {net_name!r} has only one component terminal.",
                    subject=net_name,
                )
            )


def _component_from_element(element):
    return Component(
        refdes=element.name,
        kind=element.element_type.name.lower(),
        value=element.value,
        terminals=tuple(
            Terminal(name=terminal_name, net_name=net_name)
            for terminal_name, net_name in sorted(element.terminal_nets.items())
        ),
        terminal_views=tuple(sorted(element.terminal_views.items())),
    )
