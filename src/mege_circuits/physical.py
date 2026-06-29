"""Manual physical stripboard layouts backed by semantic circuits."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import mege_circuits.dsl as dsl
from mege_circuits.circuit import Circuit, Component, export_netlist
from mege_circuits.dsl import Direction, Stripboard, StripboardBlocker, StripboardCut

_logger = logging.getLogger(__name__)

ERROR = "error"
WARNING = "warning"
LAYOUT_JUMPER_STROKE = "#dc2626"
LAYOUT_JUMPER_STROKE_WIDTH = 0.055
LAYOUT_JUMPER_ENDPOINT_RADIUS = 0.115
LAYOUT_JUMPER_ENDPOINT_FILL = "#ffffff"
LAYOUT_CONNECTOR_FILL = "#2563eb"
LAYOUT_CONNECTOR_STROKE = "#ffffff"
LAYOUT_CONNECTOR_RADIUS = 0.135
LAYOUT_COMPONENT_BODY_FILL = "#111827"
LAYOUT_COMPONENT_BODY_LABEL_FILL = "#ffffff"
DIRECTIONAL_TERMINAL_LABEL_KINDS = frozenset(("bjt_npn", "pmos", "zener"))


@dataclass
class _StripboardPlanningStats:
    verified_candidates: int = 0
    optimized_candidates: int = 0
    skipped_optimization_candidates: int = 0
    layout_rebuilds: int = 0
    layout_verifications: int = 0


_STRIPBOARD_PLANNING_STATS = ContextVar("stripboard_planning_stats", default=None)
_LAST_STRIPBOARD_PLANNING_STATS = None


@dataclass(frozen=True)
class Footprint:
    """Relative stripboard holes for one family of through-hole components.

    Pin and blocker coordinates are `(row_delta, col_delta)` pairs relative to
    a placed component origin. Rotations are clockwise in 90-degree steps in
    rendered top-view grid coordinates.
    """

    name: str
    component_kinds: tuple[str, ...]
    pins: Mapping[str, tuple[int, int]]
    allowed_rotations: tuple[int, ...] = (0, 180)
    blockers: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "name", str(self.name))
        component_kinds = tuple(str(kind) for kind in self.component_kinds)
        if not component_kinds:
            raise ValueError("Footprint must support at least one component kind.")
        object.__setattr__(self, "component_kinds", component_kinds)
        pins = {
            str(terminal): _coerce_grid_point(point, "footprint pin")
            for terminal, point in self.pins.items()
        }
        if not pins:
            raise ValueError("Footprint must define at least one pin.")
        object.__setattr__(self, "pins", MappingProxyType(pins))
        rotations = tuple(
            _normalize_rotation(rotation) for rotation in self.allowed_rotations
        )
        if not rotations:
            raise ValueError("Footprint must allow at least one rotation.")
        object.__setattr__(self, "allowed_rotations", rotations)
        object.__setattr__(
            self,
            "blockers",
            tuple(
                _coerce_grid_point(point, "footprint blocker")
                for point in self.blockers
            ),
        )


@dataclass(frozen=True)
class PlacedComponent:
    refdes: str
    footprint_name: str
    origin: tuple[int, int]
    rotation: int = 0

    def __post_init__(self):
        object.__setattr__(self, "refdes", str(self.refdes))
        object.__setattr__(self, "footprint_name", str(self.footprint_name))
        object.__setattr__(self, "origin", _coerce_grid_point(self.origin, "origin"))
        object.__setattr__(self, "rotation", _normalize_rotation(self.rotation))


@dataclass(frozen=True)
class Jumper:
    start: tuple[int, int]
    end: tuple[int, int]
    net_name: str

    def __post_init__(self):
        object.__setattr__(
            self, "start", _coerce_grid_point(self.start, "jumper start")
        )
        object.__setattr__(self, "end", _coerce_grid_point(self.end, "jumper end"))
        object.__setattr__(self, "net_name", str(self.net_name))


@dataclass(frozen=True)
class PlacedConnector:
    name: str
    net_name: str
    hole: tuple[int, int]
    label: str | None = None
    kind: str = "nail"

    def __post_init__(self):
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "net_name", str(self.net_name))
        object.__setattr__(self, "hole", _coerce_grid_point(self.hole, "connector"))
        if self.label is not None:
            object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "kind", str(self.kind))

    @property
    def row(self):
        return self.hole[0]

    @property
    def col(self):
        return self.hole[1]


@dataclass(frozen=True)
class PlacedPin:
    refdes: str
    terminal_name: str
    net_name: str
    row: int
    col: int
    footprint_name: str

    @property
    def hole(self):
        return (self.row, self.col)


@dataclass(frozen=True)
class PhysicalLayout:
    """Manual stripboard layout independent of schematic drawing coordinates."""

    board: Stripboard
    placed_components: tuple[PlacedComponent, ...]
    cuts: tuple[StripboardCut, ...]
    jumpers: tuple[Jumper, ...]
    connectors: tuple[PlacedConnector, ...] = ()
    blockers: tuple[StripboardBlocker, ...] = ()
    annotations: tuple[str, ...] = ()
    footprints: tuple[Footprint, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PhysicalConductor:
    index: int
    holes: tuple[tuple[int, int], ...]
    pins: tuple[PlacedPin, ...] = ()
    net_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhysicalNetlist:
    board: Stripboard
    conductors: tuple[PhysicalConductor, ...]


@dataclass(frozen=True)
class PhysicalIssue:
    severity: str
    code: str
    message: str
    subject: str | None = None
    holes: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class PhysicalVerificationReport:
    issues: tuple[PhysicalIssue, ...] = ()
    physical_netlist: PhysicalNetlist | None = None

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
            return "Physical verification passed with no issues."
        return "\n".join(
            f"{issue.severity.upper()} {issue.code}: {issue.message}"
            for issue in self.issues
        )


@dataclass(frozen=True)
class StripboardDensityMetrics:
    total_holes: int
    occupied_holes: int
    empty_holes: int
    empty_ratio: float
    used_width: int
    used_height: int
    component_pin_holes: int
    connector_holes: int
    cut_holes: int
    blocker_holes: int
    jumper_endpoint_holes: int

    def as_dict(self):
        return {
            "total_holes": self.total_holes,
            "occupied_holes": self.occupied_holes,
            "empty_holes": self.empty_holes,
            "empty_ratio": self.empty_ratio,
            "used_width": self.used_width,
            "used_height": self.used_height,
            "component_pin_holes": self.component_pin_holes,
            "connector_holes": self.connector_holes,
            "cut_holes": self.cut_holes,
            "blocker_holes": self.blocker_holes,
            "jumper_endpoint_holes": self.jumper_endpoint_holes,
        }


@dataclass(frozen=True)
class StripboardRoutingHints:
    """Placement hints for the conservative stripboard router."""

    net_rows: Mapping[str, int] = field(default_factory=dict)
    component_columns: Mapping[str, int] = field(default_factory=dict)
    component_terminal_holes: Mapping[tuple[str, str], tuple[int, int]] = field(
        default_factory=dict
    )
    connector_holes: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    connector_net_names: Mapping[str, str] = field(default_factory=dict)
    connector_labels: Mapping[str, str] = field(default_factory=dict)
    component_order: tuple[str, ...] = ()
    board_width_pitches: int | None = None
    board_height_pitches: int | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "net_rows",
            MappingProxyType(
                {
                    str(net_name): _coerce_integer(row, "net row")
                    for net_name, row in self.net_rows.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "component_columns",
            MappingProxyType(
                {
                    str(refdes): _coerce_integer(column, "component column")
                    for refdes, column in self.component_columns.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "component_terminal_holes",
            MappingProxyType(
                {
                    (str(refdes), str(terminal_name)): _coerce_grid_point(
                        hole,
                        "component terminal hole",
                    )
                    for (refdes, terminal_name), hole in (
                        self.component_terminal_holes or {}
                    ).items()
                }
            ),
        )
        object.__setattr__(
            self,
            "connector_holes",
            MappingProxyType(
                {
                    str(name): _coerce_grid_point(hole, "connector hole")
                    for name, hole in self.connector_holes.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "connector_net_names",
            MappingProxyType(
                {
                    str(name): str(net_name)
                    for name, net_name in self.connector_net_names.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "connector_labels",
            MappingProxyType(
                {str(name): str(label) for name, label in self.connector_labels.items()}
            ),
        )
        object.__setattr__(
            self,
            "component_order",
            tuple(str(refdes) for refdes in self.component_order),
        )
        for attr_name in ("board_width_pitches", "board_height_pitches"):
            value = getattr(self, attr_name)
            if value is not None:
                object.__setattr__(
                    self,
                    attr_name,
                    _coerce_integer(value, attr_name),
                )


@dataclass(frozen=True)
class StripboardBuildOutputs:
    top_svg: Path
    top_png: Path
    top_values_svg: Path
    top_values_png: Path
    bottom_svg: Path
    bottom_png: Path
    debug_svg: Path
    debug_png: Path
    checklist_md: Path
    data_json: Path

    def as_tuple(self):
        return (
            self.top_svg,
            self.top_png,
            self.top_values_svg,
            self.top_values_png,
            self.bottom_svg,
            self.bottom_png,
            self.debug_svg,
            self.debug_png,
            self.checklist_md,
            self.data_json,
        )


def default_footprints():
    """Return the built-in through-hole footprint library."""

    return (
        Footprint(
            name="axial_2pin_span3",
            component_kinds=("resistor", "fuse", "zener"),
            pins={"start": (0, 0), "end": (0, 3)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1), (0, 2)),
        ),
        Footprint(
            name="axial_2pin_span1",
            component_kinds=("resistor", "fuse", "zener"),
            pins={"start": (0, 0), "end": (0, 1)},
            allowed_rotations=(0, 90, 180, 270),
        ),
        Footprint(
            name="axial_2pin_span2",
            component_kinds=("resistor", "fuse", "zener"),
            pins={"start": (0, 0), "end": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1),),
        ),
        Footprint(
            name="axial_2pin_span4",
            component_kinds=("resistor", "fuse", "zener"),
            pins={"start": (0, 0), "end": (0, 4)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1), (0, 2), (0, 3)),
        ),
        Footprint(
            name="capacitor_2pin_span2",
            component_kinds=("capacitor",),
            pins={"start": (0, 0), "end": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1),),
        ),
        Footprint(
            name="capacitor_2pin_span1",
            component_kinds=("capacitor",),
            pins={"start": (0, 0), "end": (0, 1)},
            allowed_rotations=(0, 90, 180, 270),
        ),
        Footprint(
            name="capacitor_2pin_span4",
            component_kinds=("capacitor",),
            pins={"start": (0, 0), "end": (0, 4)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1), (0, 2), (0, 3)),
        ),
        Footprint(
            name="to92_cbe",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "base": (0, 2), "emitter": (0, 4)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1), (0, 3)),
        ),
        Footprint(
            name="to92_cbe_compact",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "base": (0, 1), "emitter": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=(),
        ),
        Footprint(
            name="to92_ceb_compact",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "emitter": (0, 1), "base": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=(),
        ),
        Footprint(
            name="to92_cbe_staggered_013",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "base": (0, 1), "emitter": (0, 3)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 2),),
        ),
        Footprint(
            name="to92_ceb_staggered_013",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "emitter": (0, 1), "base": (0, 3)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 2),),
        ),
        Footprint(
            name="to220_gds",
            component_kinds=("pmos",),
            pins={"gate": (0, 0), "drain": (0, 2), "source": (0, 4)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1), (0, 3)),
        ),
        Footprint(
            name="to220_gds_compact",
            component_kinds=("pmos",),
            pins={"gate": (0, 0), "drain": (0, 1), "source": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=(),
        ),
    )


def create_manual_stripboard_layout(
    circuit,
    *,
    board,
    footprints=None,
    placements=None,
    cuts=(),
    jumpers=(),
    connectors=(),
    blockers=(),
    annotations=(),
):
    """Create a validated manual physical stripboard layout for a circuit."""

    if not isinstance(circuit, Circuit):
        raise TypeError("create_manual_stripboard_layout expects a Circuit object.")
    if not isinstance(board, Stripboard):
        raise TypeError("board must be a Stripboard object.")

    footprint_map = _footprints_by_name(
        default_footprints() if footprints is None else footprints
    )
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    placed_components = _normalize_placements(
        placements or {},
        components_by_refdes,
        footprint_map,
    )
    layout_cuts = _normalize_cuts(cuts)
    layout_jumpers = _normalize_jumpers(jumpers)
    layout_connectors = _normalize_connectors(connectors)
    explicit_blockers = _normalize_blockers(blockers)
    generated_blockers = _generated_component_blockers(
        placed_components,
        footprint_map,
    )
    layout = PhysicalLayout(
        board=board,
        placed_components=placed_components,
        cuts=layout_cuts,
        jumpers=layout_jumpers,
        connectors=layout_connectors,
        blockers=_dedupe_blockers((*explicit_blockers, *generated_blockers)),
        annotations=tuple(str(annotation) for annotation in annotations),
        footprints=tuple(footprint_map[name] for name in sorted(footprint_map)),
    )
    _record_stripboard_layout_rebuild()
    _validate_layout_geometry(layout, circuit, footprint_map)
    return layout


def placed_component_pins(layout, circuit):
    """Enumerate absolute pin holes for the placed components in a layout."""

    if not isinstance(layout, PhysicalLayout):
        raise TypeError("placed_component_pins expects a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("placed_component_pins expects a Circuit object.")

    footprint_map = _footprints_by_name(layout.footprints)
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    pins = []
    for placed_component in layout.placed_components:
        component = _require_component(components_by_refdes, placed_component.refdes)
        footprint = _require_footprint(footprint_map, placed_component.footprint_name)
        _validate_component_footprint(component, footprint)
        for terminal_name, net_name in _component_terminal_nets(component):
            row, col = _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                footprint.pins[terminal_name],
            )
            pins.append(
                PlacedPin(
                    refdes=component.refdes,
                    terminal_name=terminal_name,
                    net_name=net_name,
                    row=row,
                    col=col,
                    footprint_name=footprint.name,
                )
            )
    return tuple(sorted(pins, key=lambda pin: (pin.refdes, pin.terminal_name)))


def extract_physical_netlist(layout, circuit):
    """Extract physical copper connectivity from a stripboard layout."""

    _validate_physical_inputs(layout, circuit)
    issues = _physical_layout_drc_issues(layout, circuit)
    errors = tuple(issue for issue in issues if issue.severity == ERROR)
    if errors:
        raise ValueError(_issue_summary(errors))
    return _extract_physical_netlist_unchecked(layout, circuit)


def verify_stripboard_layout(layout, circuit):
    """Return DRC, open-circuit, and short-circuit diagnostics for a layout."""

    _record_stripboard_layout_verification()
    _validate_physical_inputs(layout, circuit)
    issues = list(_physical_layout_drc_issues(layout, circuit))
    if any(issue.severity == ERROR for issue in issues):
        return PhysicalVerificationReport(tuple(issues), physical_netlist=None)

    physical_netlist = _extract_physical_netlist_unchecked(layout, circuit)
    issues.extend(_physical_connectivity_issues(physical_netlist))
    return PhysicalVerificationReport(tuple(issues), physical_netlist=physical_netlist)


def stripboard_hints_from_schema(
    schema,
    *,
    compact=True,
    priority_element_names=(),
):
    """Derive deterministic routing hints from the legacy schematic projection."""

    if not isinstance(schema, dsl.Schema):
        raise TypeError("stripboard_hints_from_schema expects a Schema object.")
    if not isinstance(compact, bool):
        raise TypeError("compact must be a bool.")

    priority_element_names = tuple(str(name) for name in priority_element_names)
    _logger.info(
        "Deriving stripboard routing hints compact=%s priority=%s elements=%s nodes=%s",
        compact,
        priority_element_names,
        len(schema.elements),
        len(schema.node_views),
    )
    assignment = dsl.assign_schema_nets_to_stripboard(schema)
    if compact:
        try:
            assignment = dsl.compact_sparse_stripboard_rows(assignment, schema=schema)
        except ValueError as error:
            _logger.warning(
                "Sparse stripboard row compaction failed; continuing with "
                "uncompacted rows: %s",
                error,
            )
            pass
        assignment = dsl.compact_stripboard_connections_left(
            schema,
            assignment,
            strict=True,
        )
        assignment = dsl.permute_stripboard_rows_for_element_span(
            schema,
            assignment,
            priority_element_names=priority_element_names,
        )

    element_nets = {
        (element.name, terminal_name): net_name
        for element in schema.elements
        for terminal_name, net_name in element.terminal_nets.items()
    }
    component_terminal_holes = {}
    terminal_columns_by_component = {}
    node_views_by_name = {node_view.name: node_view for node_view in schema.node_views}
    connector_holes = {}
    connector_net_names = {}
    connector_labels = {}
    for marker_key, column in assignment.marker_column_maps.items():
        if len(marker_key) == 2 and marker_key[0] == "node":
            _kind, node_name = marker_key
            node_view = node_views_by_name.get(node_name)
            if (
                node_view is None
                or not _is_stripboard_physical_node_view(node_view)
                or node_view.net.name not in assignment.net_rows
            ):
                continue
            connector_holes[node_name] = (
                assignment.net_rows[node_view.net.name],
                column,
            )
            connector_net_names[node_name] = node_view.net.name
            connector_labels[node_name] = node_view.label or node_name
            continue
        if len(marker_key) != 3 or marker_key[0] != "terminal":
            continue
        _kind, refdes, terminal_name = marker_key
        net_name = element_nets.get((refdes, terminal_name))
        if net_name in assignment.net_rows:
            component_terminal_holes[(refdes, terminal_name)] = (
                assignment.net_rows[net_name],
                column,
            )
        terminal_columns_by_component.setdefault(refdes, []).append(column)

    component_columns = {}
    for element in schema.elements:
        columns = terminal_columns_by_component.get(element.name)
        if columns:
            component_columns[element.name] = int(round(sum(columns) / len(columns)))
        else:
            component_columns[element.name] = int(round(element.position[0]))

    component_order = tuple(
        refdes
        for refdes, _column in sorted(
            component_columns.items(),
            key=lambda item: (item[1], item[0]),
        )
    )
    hints = StripboardRoutingHints(
        net_rows=assignment.net_rows,
        component_columns=component_columns,
        component_terminal_holes=component_terminal_holes,
        connector_holes=connector_holes,
        connector_net_names=connector_net_names,
        connector_labels=connector_labels,
        component_order=component_order,
        board_width_pitches=assignment.stripboard.width_pitches,
        board_height_pitches=assignment.stripboard.height_pitches,
    )
    _logger.info(
        "Derived stripboard routing hints board=%sx%s nets=%s components=%s "
        "connectors=%s terminal_holes=%s",
        hints.board_width_pitches,
        hints.board_height_pitches,
        len(hints.net_rows),
        len(hints.component_columns),
        len(hints.connector_holes),
        len(hints.component_terminal_holes),
    )
    _logger.debug(
        "Stripboard hint details net_rows=%s component_columns=%s "
        "connector_holes=%s terminal_holes=%s component_order=%s",
        dict(hints.net_rows),
        dict(hints.component_columns),
        dict(hints.connector_holes),
        dict(hints.component_terminal_holes),
        hints.component_order,
    )
    return hints


def plan_stripboard(
    circuit,
    *,
    board,
    footprints=None,
    hints=None,
    fixed_placements=None,
    fixed_cuts=(),
    fixed_jumpers=(),
):
    """Route a conservative, verification-gated stripboard layout."""

    if not isinstance(circuit, Circuit):
        raise TypeError("plan_stripboard expects a Circuit object.")
    if not isinstance(board, Stripboard):
        raise TypeError("board must be a Stripboard object.")
    if board.strip_direction is not Direction.HORIZONTAL:
        _logger.error(
            "Cannot plan stripboard circuit=%s board=%sx%s: unsupported strip "
            "direction %s",
            _circuit_log_name(circuit),
            board.width_pitches,
            board.height_pitches,
            board.strip_direction,
        )
        return None, _routing_failure_report(
            "Only horizontal stripboards are supported by the first router.",
            code="unsupported_strip_direction",
        )
    routing_hints = _coerce_routing_hints(hints)
    planning_stats, planning_stats_token = _begin_stripboard_planning_stats()

    _logger.info(
        "Planning stripboard layout circuit=%s board=%sx%s components=%s nets=%s "
        "fixed_placements=%s fixed_cuts=%s fixed_jumpers=%s",
        _circuit_log_name(circuit),
        board.width_pitches,
        board.height_pitches,
        len(circuit.components),
        len(circuit.nets),
        len(fixed_placements or {}),
        len(fixed_cuts),
        len(fixed_jumpers),
    )
    try:
        footprint_map = _footprints_by_name(
            default_footprints() if footprints is None else footprints
        )
        fixed_placement_map = _normalize_fixed_placements(
            fixed_placements or {},
            circuit,
            footprint_map,
        )
        normalized_fixed_cuts = _normalize_cuts(fixed_cuts)
        normalized_fixed_jumpers = _normalize_jumpers(fixed_jumpers)
        routing_connectors = _routing_connectors_from_hints(
            routing_hints,
            circuit,
            board,
        )
    except (TypeError, ValueError) as error:
        _logger.error("Stripboard planning input normalization failed: %s", error)
        _finish_stripboard_planning_stats(planning_stats, planning_stats_token)
        return None, _routing_failure_report(str(error))

    net_rows = _routing_net_rows(circuit, routing_hints)
    _logger.info(
        "Prepared stripboard routing inputs footprints=%s connectors=%s net_rows=%s "
        "shake_limit=%s",
        len(footprint_map),
        len(routing_connectors),
        len(net_rows),
        _routing_shake_order_limit(),
    )
    _logger.debug(
        "Routing inputs net_rows=%s connectors=%s fixed_placements=%s "
        "fixed_cuts=%s fixed_jumpers=%s",
        dict(net_rows),
        routing_connectors,
        fixed_placement_map,
        normalized_fixed_cuts,
        normalized_fixed_jumpers,
    )
    best_layout = None
    best_report = None
    best_score = None
    last_routing_error = None
    pending_orders = [_routing_component_order(circuit, routing_hints)]
    seen_orders = set()
    queued_orders = set(pending_orders)
    attempt_index = 0
    while pending_orders and len(seen_orders) < _routing_shake_order_limit():
        component_order = pending_orders.pop(0)
        queued_orders.discard(component_order)
        if component_order in seen_orders:
            continue
        seen_orders.add(component_order)
        attempt_index += 1
        _logger.info(
            "Routing placement order %s/%s components=%s",
            attempt_index,
            _routing_shake_order_limit(),
            component_order,
        )
        order_hints = replace(routing_hints, component_order=component_order)
        planned_states, placement_error = _route_component_placements(
            circuit,
            board,
            footprint_map,
            order_hints,
            fixed_placement_map,
            net_rows,
            reserved_holes={connector.hole for connector in routing_connectors},
        )
        if placement_error is not None:
            last_routing_error = placement_error
            _logger.warning(
                "Placement order failed components=%s: %s",
                component_order,
                placement_error,
            )
            continue

        _logger.info(
            "Placement order produced %s candidate state(s) components=%s",
            len(planned_states),
            component_order,
        )
        run_best_layout = None
        run_best_score = None
        cut_failures = 0
        manual_failures = 0
        jumper_failures = 0
        verified_candidates = 0
        verified_candidate_entries = []
        for planned, placement_score in planned_states:
            _logger.debug(
                "Evaluating placement candidate placement_score=%s placements=%s",
                placement_score,
                planned,
            )
            generated_cuts, cut_error = _routing_conflict_cuts(
                circuit,
                planned,
                footprint_map,
                normalized_fixed_cuts,
                routing_connectors,
            )
            if cut_error is not None:
                cut_failures += 1
                _logger.debug("Cut routing rejected candidate: %s", cut_error)
                continue

            try:
                base_layout = create_manual_stripboard_layout(
                    circuit,
                    board=board,
                    footprints=tuple(
                        footprint_map[name] for name in sorted(footprint_map)
                    ),
                    placements=planned,
                    cuts=_dedupe_cuts((*normalized_fixed_cuts, *generated_cuts)),
                    jumpers=_dedupe_jumpers(normalized_fixed_jumpers),
                    connectors=routing_connectors,
                )
            except (TypeError, ValueError) as error:
                manual_failures += 1
                _logger.debug(
                    "Manual layout rebuild rejected candidate before jumpers: %s",
                    error,
                )
                continue

            base_report = verify_stripboard_layout(base_layout, circuit)
            if _routing_report_has_unfixable_errors(base_report):
                report = base_report
                layout = base_layout
            else:
                try:
                    generated_jumpers = _routing_connectivity_jumpers(
                        base_layout,
                        circuit,
                        base_report.physical_netlist,
                    )
                except ValueError as error:
                    last_routing_error = str(error)
                    jumper_failures += 1
                    _logger.debug("Connectivity jumper routing failed: %s", error)
                    continue
                try:
                    layout = create_manual_stripboard_layout(
                        circuit,
                        board=board,
                        footprints=tuple(
                            footprint_map[name] for name in sorted(footprint_map)
                        ),
                        placements=planned,
                        cuts=base_layout.cuts,
                        jumpers=_dedupe_jumpers(
                            (*normalized_fixed_jumpers, *generated_jumpers)
                        ),
                        connectors=routing_connectors,
                    )
                except (TypeError, ValueError) as error:
                    manual_failures += 1
                    _logger.debug(
                        "Manual layout rebuild rejected candidate after jumpers: %s",
                        error,
                    )
                    continue
                report = verify_stripboard_layout(layout, circuit)

            if report.ok:
                verified_candidates += 1
                planning_stats.verified_candidates += 1
                score = _routing_layout_score(
                    layout,
                    report,
                    placement_score,
                    circuit,
                )
                verified_candidate_entries.append(
                    (score, layout, report, placement_score)
                )
                continue

            score = _routing_layout_score(layout, report, placement_score, circuit)
            if best_score is None or score < best_score:
                best_layout = layout
                best_report = report
                best_score = score
                _logger.info(
                    "New best stripboard candidate ok=%s %s errors=%s score=%s",
                    report.ok,
                    _layout_log_summary(layout),
                    len(report.errors),
                    score,
                )
            if report.ok and (run_best_score is None or score < run_best_score):
                run_best_layout = layout
                run_best_score = score

        optimized_indexes = _routing_optimization_shortlist(
            verified_candidate_entries,
            current_best_jumper_count=(
                len(best_layout.jumpers)
                if best_layout is not None
                and best_report is not None
                and best_report.ok
                else None
            ),
        )
        optimized_index_set = set(optimized_indexes)
        skipped_optimizations = len(verified_candidate_entries) - len(
            optimized_index_set
        )
        planning_stats.skipped_optimization_candidates += skipped_optimizations
        if verified_candidate_entries:
            _logger.info(
                "Optimizing routed candidate shortlist verified=%s optimized=%s "
                "skipped=%s candidate_limit=%s",
                len(verified_candidate_entries),
                len(optimized_index_set),
                skipped_optimizations,
                _routing_optimization_candidate_limit(),
            )
        optimized_position = 0
        for index, (
            pre_optimization_score,
            layout,
            report,
            placement_score,
        ) in enumerate(verified_candidate_entries):
            if index not in optimized_index_set:
                continue
            optimized_position += 1
            planning_stats.optimized_candidates += 1
            _logger.info(
                "Optimizing routed candidate %s/%s pre_score=%s %s",
                optimized_position,
                len(optimized_index_set),
                pre_optimization_score,
                _layout_log_summary(layout),
            )
            layout, report = _optimize_routed_stripboard_layout(
                layout,
                circuit,
                locked_refdeses=fixed_placement_map,
                fixed_cuts=normalized_fixed_cuts,
                fixed_jumpers=normalized_fixed_jumpers,
            )

            score = _routing_layout_score(layout, report, placement_score, circuit)
            if best_score is None or score < best_score:
                best_layout = layout
                best_report = report
                best_score = score
                _logger.info(
                    "New best stripboard candidate ok=%s %s errors=%s score=%s",
                    report.ok,
                    _layout_log_summary(layout),
                    len(report.errors),
                    score,
                )
            if report.ok and (run_best_score is None or score < run_best_score):
                run_best_layout = layout
                run_best_score = score

        _logger.info(
            "Finished placement order components=%s verified=%s optimized=%s "
            "skipped_optimization=%s cut_failures=%s jumper_failures=%s "
            "rebuild_failures=%s layout_rebuilds=%s layout_verifications=%s",
            component_order,
            verified_candidates,
            len(optimized_index_set),
            skipped_optimizations,
            cut_failures,
            jumper_failures,
            manual_failures,
            planning_stats.layout_rebuilds,
            planning_stats.layout_verifications,
        )
        if run_best_layout is None:
            continue
        if len(run_best_layout.jumpers) <= _routing_shake_jumper_threshold():
            continue
        queued_count = 0
        for order in _routing_shake_orders_from_layout(
            circuit,
            routing_hints,
            run_best_layout,
        ):
            if order in seen_orders or order in queued_orders:
                continue
            pending_orders.append(order)
            queued_orders.add(order)
            queued_count += 1
        if queued_count:
            _logger.info(
                "Queued %s bridge-focused routing restart(s) from jumper nets=%s",
                queued_count,
                tuple(
                    dict.fromkeys(jumper.net_name for jumper in run_best_layout.jumpers)
                ),
            )

    if best_layout is not None:
        planning_stats = _finish_stripboard_planning_stats(
            planning_stats,
            planning_stats_token,
        )
        _logger.info(
            "Finished stripboard planning circuit=%s ok=%s %s errors=%s score=%s "
            "verified_candidates=%s optimized_candidates=%s "
            "skipped_optimization_candidates=%s layout_rebuilds=%s "
            "layout_verifications=%s",
            _circuit_log_name(circuit),
            best_report.ok,
            _layout_log_summary(best_layout),
            len(best_report.errors),
            best_score,
            planning_stats.verified_candidates,
            planning_stats.optimized_candidates,
            planning_stats.skipped_optimization_candidates,
            planning_stats.layout_rebuilds,
            planning_stats.layout_verifications,
        )
        return best_layout, best_report
    _logger.error(
        "Stripboard planning failed circuit=%s: %s",
        _circuit_log_name(circuit),
        last_routing_error
        or "No verified stripboard routing candidate could be built.",
    )
    _finish_stripboard_planning_stats(planning_stats, planning_stats_token)
    return None, _routing_failure_report(
        last_routing_error or "No verified stripboard routing candidate could be built."
    )


def score_stripboard_layout(layout, circuit, report=None):
    """Return a deterministic score tuple for comparing routed layouts."""

    if report is None:
        report = verify_stripboard_layout(layout, circuit)
    if not isinstance(report, PhysicalVerificationReport):
        raise TypeError("report must be a PhysicalVerificationReport.")
    return (
        len(report.errors),
        len(layout.jumpers),
        len(layout.cuts),
        _layout_used_height(layout),
        _layout_used_width(layout),
    )


def _begin_stripboard_planning_stats():
    stats = _StripboardPlanningStats()
    token = _STRIPBOARD_PLANNING_STATS.set(stats)
    return stats, token


def _finish_stripboard_planning_stats(stats, token):
    global _LAST_STRIPBOARD_PLANNING_STATS
    _LAST_STRIPBOARD_PLANNING_STATS = stats
    _STRIPBOARD_PLANNING_STATS.reset(token)
    return stats


def _record_stripboard_layout_rebuild():
    stats = _STRIPBOARD_PLANNING_STATS.get()
    if stats is not None:
        stats.layout_rebuilds += 1


def _record_stripboard_layout_verification():
    stats = _STRIPBOARD_PLANNING_STATS.get()
    if stats is not None:
        stats.layout_verifications += 1


def _circuit_log_name(circuit):
    return getattr(circuit, "name", None) or "<unnamed>"


def _layout_log_summary(layout):
    metrics = _stripboard_density_metrics(layout)
    return (
        f"board={layout.board.width_pitches}x{layout.board.height_pitches} "
        f"components={len(layout.placed_components)} "
        f"connectors={len(layout.connectors)} cuts={len(layout.cuts)} "
        f"jumpers={len(layout.jumpers)} empty_holes={metrics.empty_holes}"
    )


def _stripboard_density_metrics(layout, circuit=None):
    total_holes = layout.board.width_pitches * layout.board.height_pitches
    if circuit is None:
        component_pins = {pin.hole for pin in _layout_score_pins(layout)}
    else:
        component_pins = {pin.hole for pin in placed_component_pins(layout, circuit)}
    connector_holes = {connector.hole for connector in layout.connectors}
    cut_holes = {(cut.row, cut.col) for cut in layout.cuts}
    blocker_holes = {(blocker.row, blocker.col) for blocker in layout.blockers}
    jumper_endpoint_holes = {
        hole for jumper in layout.jumpers for hole in (jumper.start, jumper.end)
    }
    occupied_holes = (
        component_pins
        | connector_holes
        | cut_holes
        | blocker_holes
        | jumper_endpoint_holes
    )
    empty_holes = max(0, total_holes - len(occupied_holes))
    return StripboardDensityMetrics(
        total_holes=total_holes,
        occupied_holes=len(occupied_holes),
        empty_holes=empty_holes,
        empty_ratio=0.0 if total_holes == 0 else empty_holes / total_holes,
        used_width=_layout_used_width(layout),
        used_height=_layout_used_height(layout),
        component_pin_holes=len(component_pins),
        connector_holes=len(connector_holes),
        cut_holes=len(cut_holes),
        blocker_holes=len(blocker_holes),
        jumper_endpoint_holes=len(jumper_endpoint_holes),
    )


def _layout_optimization_score(layout, circuit, report):
    metrics = _stripboard_density_metrics(layout, circuit)
    return (
        int(not report.ok),
        len(report.errors),
        len(layout.jumpers),
        len(layout.cuts),
        metrics.total_holes,
        metrics.empty_holes,
        metrics.used_height,
        metrics.used_width,
        _layout_row_sum(layout),
        _layout_col_sum(layout),
        _layout_jumper_length(layout),
    )


def _optimize_routed_stripboard_layout(
    layout,
    circuit,
    *,
    trim_margin=1,
    locked_refdeses=(),
    fixed_cuts=(),
    fixed_jumpers=(),
):
    report = verify_stripboard_layout(layout, circuit)
    if not report.ok:
        return layout, report

    locked_refdeses = frozenset(str(refdes) for refdes in locked_refdeses)
    fixed_cut_holes = frozenset((cut.row, cut.col) for cut in fixed_cuts)
    fixed_jumper_keys = frozenset(
        _jumper_identity_key(jumper) for jumper in fixed_jumpers
    )

    best_layout = layout
    best_report = report
    best_score = _layout_optimization_score(best_layout, circuit, best_report)
    working = layout
    working_report = report
    max_iterations = max(1, _optimization_cycle_limit())

    _logger.debug(
        "Starting routed layout optimization %s score=%s fixed_cuts=%s "
        "fixed_jumpers=%s",
        _layout_log_summary(layout),
        best_score,
        tuple(sorted(fixed_cut_holes)),
        len(fixed_jumper_keys),
    )
    for iteration in range(max_iterations):
        cycle = working
        cycle_report = working_report
        changed = False

        cycle, cycle_report, absorbed = _absorb_connector_only_jumpers(
            cycle,
            circuit,
            fixed_jumper_keys=fixed_jumper_keys,
        )
        changed = changed or absorbed

        cycle, cycle_report, relaxed = _right_relax_flexible_terminals(
            cycle,
            circuit,
            fixed_jumper_keys=fixed_jumper_keys,
        )
        changed = changed or relaxed

        cycle, cycle_report = _left_compact_stripboard_layout(
            cycle,
            circuit,
            trim_margin=trim_margin,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )

        cycle, cycle_report, moved_down = _down_compact_stripboard_layout(
            cycle,
            circuit,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )
        changed = changed or moved_down

        cycle, cycle_report = _left_compact_stripboard_layout(
            cycle,
            circuit,
            trim_margin=trim_margin,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )

        cycle, cycle_report, pruned_cuts = _prune_redundant_cuts(
            cycle,
            circuit,
            fixed_cuts=fixed_cut_holes,
        )
        changed = changed or pruned_cuts

        cycle, cycle_report = _left_compact_stripboard_layout(
            cycle,
            circuit,
            trim_margin=trim_margin,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )

        cycle, cycle_report, moved_down_after_prune = _down_compact_stripboard_layout(
            cycle,
            circuit,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )
        changed = changed or moved_down_after_prune

        cycle, cycle_report = _left_compact_stripboard_layout(
            cycle,
            circuit,
            trim_margin=trim_margin,
            locked_refdeses=locked_refdeses,
            fixed_cuts=fixed_cut_holes,
            fixed_jumpers=fixed_jumper_keys,
        )

        cycle_score = _layout_optimization_score(cycle, circuit, cycle_report)
        if cycle_score < best_score:
            _logger.debug(
                "Accepted routed layout optimization iteration=%s score=%s->%s %s",
                iteration + 1,
                best_score,
                cycle_score,
                _layout_log_summary(cycle),
            )
            best_layout = cycle
            best_report = cycle_report
            best_score = cycle_score
            working = cycle
            working_report = cycle_report
            continue
        if not changed:
            break
        break

    _logger.debug(
        "Finished routed layout optimization %s score=%s metrics=%s",
        _layout_log_summary(best_layout),
        best_score,
        _stripboard_density_metrics(best_layout, circuit).as_dict(),
    )
    return best_layout, best_report


def _left_compact_stripboard_layout(
    layout,
    circuit,
    *,
    trim_margin=1,
    locked_refdeses=(),
    fixed_cuts=(),
    fixed_jumpers=(),
):
    report = verify_stripboard_layout(layout, circuit)
    if not report.ok:
        _logger.warning(
            "Skipping left compaction because layout is not verified: %s",
            report.summary(),
        )
        return layout, report

    locked_refdeses = frozenset(str(refdes) for refdes in locked_refdeses)
    fixed_cuts = frozenset(fixed_cuts)
    fixed_jumpers = frozenset(fixed_jumpers)
    compacted = layout
    compacted_report = report
    compacted_score = _left_compaction_score(compacted)
    max_iterations = max(
        1,
        _left_compaction_unit_count(compacted) * compacted.board.width_pitches * 2 + 1,
    )

    _logger.debug(
        "Starting left compaction %s units=%s locked_refdeses=%s score=%s "
        "max_iterations=%s",
        _layout_log_summary(compacted),
        _left_compaction_unit_count(compacted),
        tuple(sorted(locked_refdeses)),
        compacted_score,
        max_iterations,
    )
    accepted_count = 0
    iteration = 0
    for iteration in range(max_iterations):
        accepted = None
        for unit in _left_compaction_units(
            compacted,
            locked_refdeses,
            fixed_cuts=fixed_cuts,
            fixed_jumpers=fixed_jumpers,
        ):
            accepted = _left_compaction_best_move(
                compacted,
                circuit,
                unit,
                compacted_score,
            )
            if accepted is not None:
                break
        if accepted is None:
            break
        compacted, compacted_report, compacted_score = accepted
        accepted_count += 1

    if accepted_count and iteration + 1 >= max_iterations:
        _logger.debug(
            "Left compaction reached iteration guard accepted_moves=%s "
            "max_iterations=%s",
            accepted_count,
            max_iterations,
        )

    compacted, compacted_report = _trim_left_compacted_layout(
        compacted,
        circuit,
        compacted_report,
        trim_margin=trim_margin,
    )
    _logger.debug(
        "Finished left compaction accepted_moves=%s %s score=%s",
        accepted_count,
        _layout_log_summary(compacted),
        _left_compaction_score(compacted),
    )
    return compacted, compacted_report


def _left_compaction_unit_count(layout):
    return (
        len(layout.placed_components)
        + len(layout.connectors)
        + len(layout.cuts)
        + len(layout.jumpers) * 2
    )


def _left_compaction_units(
    layout,
    locked_refdeses=frozenset(),
    *,
    fixed_cuts=frozenset(),
    fixed_jumpers=frozenset(),
):
    footprint_map = _footprints_by_name(layout.footprints)
    units = []
    components = []
    for placed_component in layout.placed_components:
        if placed_component.refdes in locked_refdeses:
            continue
        holes = _placed_component_occupied_holes(placed_component, footprint_map)
        components.append(
            (
                _holes_min_col(holes),
                _holes_min_row(holes),
                placed_component.refdes,
                ("component", placed_component.refdes),
            )
        )
    units.extend(item[-1] for item in sorted(components))

    connectors = []
    for connector in layout.connectors:
        connectors.append(
            (
                connector.col,
                connector.row,
                connector.name,
                ("connector", connector.name),
            )
        )
    units.extend(item[-1] for item in sorted(connectors))

    cuts = []
    for cut in layout.cuts:
        if (cut.row, cut.col) in fixed_cuts:
            continue
        cuts.append((cut.col, cut.row, ("cut", cut.row, cut.col)))
    units.extend(item[-1] for item in sorted(cuts))

    jumper_endpoints = []
    for index, jumper in enumerate(layout.jumpers):
        if _jumper_identity_key(jumper) in fixed_jumpers:
            continue
        for endpoint_name, hole in (("start", jumper.start), ("end", jumper.end)):
            jumper_endpoints.append(
                (
                    hole[1],
                    hole[0],
                    jumper.net_name,
                    index,
                    endpoint_name,
                    ("jumper", index, endpoint_name),
                )
            )
    units.extend(item[-1] for item in sorted(jumper_endpoints))
    return tuple(units)


def _left_compaction_best_move(layout, circuit, unit, current_score):
    unit_type = unit[0]
    if unit_type == "component":
        return _left_compaction_best_component_move(
            layout,
            circuit,
            unit[1],
            current_score,
        )
    if unit_type == "connector":
        return _left_compaction_best_connector_move(
            layout,
            circuit,
            unit[1],
            current_score,
        )
    if unit_type == "cut":
        return _left_compaction_best_cut_move(
            layout,
            circuit,
            unit[1:],
            current_score,
        )
    if unit_type == "jumper":
        return _left_compaction_best_jumper_endpoint_move(
            layout,
            circuit,
            unit[1],
            unit[2],
            current_score,
        )
    return None


def _left_compaction_best_component_move(layout, circuit, refdes, current_score):
    footprint_map = _footprints_by_name(layout.footprints)
    placed_component = _layout_component_by_refdes(layout, refdes)
    if placed_component is None:
        return None
    holes = _placed_component_occupied_holes(placed_component, footprint_map)
    min_col = _holes_min_col(holes)
    if min_col <= 0:
        return None

    row, col = placed_component.origin
    for delta in range(min_col, 0, -1):
        moved = PlacedComponent(
            refdes=placed_component.refdes,
            footprint_name=placed_component.footprint_name,
            origin=(row, col - delta),
            rotation=placed_component.rotation,
        )
        candidate_components = tuple(
            moved if component.refdes == refdes else component
            for component in layout.placed_components
        )
        accepted = _left_compaction_verified_candidate(
            layout,
            circuit,
            current_score,
            placed_components=candidate_components,
        )
        if accepted is not None:
            _logger.debug(
                "Left compaction moved component refdes=%s origin=%s->%s score=%s",
                refdes,
                placed_component.origin,
                moved.origin,
                accepted[2],
            )
            return accepted
    return None


def _left_compaction_best_connector_move(layout, circuit, name, current_score):
    connector = _layout_connector_by_name(layout, name)
    if connector is None or connector.col <= 0:
        return None

    for col in range(0, connector.col):
        moved = PlacedConnector(
            name=connector.name,
            net_name=connector.net_name,
            hole=(connector.row, col),
            label=connector.label,
            kind=connector.kind,
        )
        candidate_connectors = tuple(
            moved if candidate.name == name else candidate
            for candidate in layout.connectors
        )
        accepted = _left_compaction_verified_candidate(
            layout,
            circuit,
            current_score,
            connectors=candidate_connectors,
        )
        if accepted is not None:
            _logger.debug(
                "Left compaction moved connector name=%s hole=%s->%s score=%s",
                name,
                connector.hole,
                moved.hole,
                accepted[2],
            )
            return accepted
    return None


def _left_compaction_best_cut_move(layout, circuit, cut_key, current_score):
    row, col = cut_key
    cut_index = _layout_cut_index(layout, row, col)
    if cut_index is None or col <= 0:
        return None

    blocked_holes = _left_compaction_cut_blocked_holes(layout, circuit, cut_index)
    for candidate_col in range(0, col):
        if (row, candidate_col) in blocked_holes:
            continue
        moved = StripboardCut(row=row, col=candidate_col)
        candidate_cuts = tuple(
            moved if index == cut_index else cut
            for index, cut in enumerate(layout.cuts)
        )
        accepted = _left_compaction_verified_candidate(
            layout,
            circuit,
            current_score,
            cuts=candidate_cuts,
        )
        if accepted is not None:
            _logger.debug(
                "Left compaction moved cut row=%s col=%s->%s score=%s",
                row,
                col,
                candidate_col,
                accepted[2],
            )
            return accepted
    return None


def _left_compaction_best_jumper_endpoint_move(
    layout,
    circuit,
    jumper_index,
    endpoint_name,
    current_score,
):
    if jumper_index >= len(layout.jumpers):
        return None
    jumper = layout.jumpers[jumper_index]
    hole = jumper.start if endpoint_name == "start" else jumper.end
    row, col = hole
    min_col = _left_compaction_segment_min_col(layout, row, col)
    if col <= min_col:
        return None

    blocked_holes = _left_compaction_jumper_blocked_holes(
        layout,
        circuit,
        jumper_index,
        endpoint_name,
    )
    for candidate_col in range(min_col, col):
        candidate_hole = (row, candidate_col)
        if candidate_hole in blocked_holes:
            continue
        moved = (
            Jumper(start=candidate_hole, end=jumper.end, net_name=jumper.net_name)
            if endpoint_name == "start"
            else Jumper(
                start=jumper.start, end=candidate_hole, net_name=jumper.net_name
            )
        )
        candidate_jumpers = tuple(
            moved if index == jumper_index else candidate
            for index, candidate in enumerate(layout.jumpers)
        )
        accepted = _left_compaction_verified_candidate(
            layout,
            circuit,
            current_score,
            jumpers=candidate_jumpers,
        )
        if accepted is not None:
            _logger.debug(
                "Left compaction moved jumper endpoint net=%s index=%s endpoint=%s "
                "hole=%s->%s score=%s",
                jumper.net_name,
                jumper_index,
                endpoint_name,
                hole,
                candidate_hole,
                accepted[2],
            )
            return accepted
    return None


def _left_compaction_verified_candidate(
    layout,
    circuit,
    current_score,
    *,
    board=None,
    placed_components=None,
    cuts=None,
    jumpers=None,
    connectors=None,
):
    candidate, report = _rebuild_planned_stripboard_layout(
        layout,
        circuit,
        board=layout.board if board is None else board,
        placed_components=(
            layout.placed_components if placed_components is None else placed_components
        ),
        cuts=layout.cuts if cuts is None else cuts,
        jumpers=layout.jumpers if jumpers is None else jumpers,
        connectors=layout.connectors if connectors is None else connectors,
    )
    if candidate is None or not report.ok:
        return None
    if _left_compaction_cut_blocker_collisions(
        candidate
    ) - _left_compaction_cut_blocker_collisions(layout):
        return None
    candidate_score = _left_compaction_score(candidate)
    if candidate_score >= current_score:
        return None
    return candidate, report, candidate_score


def _rebuild_planned_stripboard_layout(
    layout,
    circuit,
    *,
    board,
    placed_components,
    cuts,
    jumpers,
    connectors,
):
    try:
        candidate = create_manual_stripboard_layout(
            circuit,
            board=board,
            footprints=layout.footprints,
            placements={component.refdes: component for component in placed_components},
            cuts=cuts,
            jumpers=jumpers,
            connectors=connectors,
            annotations=layout.annotations,
        )
    except (TypeError, ValueError) as error:
        _logger.debug("Rejected invalid compaction candidate: %s", error)
        return None, _routing_failure_report("Compaction candidate is invalid.")
    return candidate, verify_stripboard_layout(candidate, circuit)


def _trim_left_compacted_layout(layout, circuit, report, *, trim_margin):
    margin = max(0, _coerce_integer(trim_margin, "trim_margin"))
    target_width = min(
        layout.board.width_pitches,
        max(1, _layout_used_width(layout) + margin),
    )
    if target_width == layout.board.width_pitches:
        _logger.debug(
            "Left compaction trim skipped width=%s target_width=%s",
            layout.board.width_pitches,
            target_width,
        )
        return layout, report

    _logger.debug(
        "Trying left compaction trim width=%s->%s margin=%s",
        layout.board.width_pitches,
        target_width,
        margin,
    )
    board = Stripboard(
        width_pitches=target_width,
        height_pitches=layout.board.height_pitches,
        strip_direction=layout.board.strip_direction,
        pitch_mm=layout.board.pitch_mm,
    )
    candidate, candidate_report = _rebuild_planned_stripboard_layout(
        layout,
        circuit,
        board=board,
        placed_components=layout.placed_components,
        cuts=layout.cuts,
        jumpers=layout.jumpers,
        connectors=layout.connectors,
    )
    if candidate is None or not candidate_report.ok:
        _logger.debug(
            "Left compaction trim rejected width=%s->%s",
            layout.board.width_pitches,
            target_width,
        )
        return layout, report
    _logger.debug(
        "Left compaction trimmed board width=%s->%s",
        layout.board.width_pitches,
        target_width,
    )
    return candidate, candidate_report


def _left_compaction_score(layout):
    return (
        _layout_used_width(layout),
        layout.board.width_pitches,
        _layout_col_sum(layout),
        _layout_jumper_length(layout),
    )


def _prune_redundant_cuts(layout, circuit, *, fixed_cuts=frozenset()):
    current = layout
    current_report = verify_stripboard_layout(current, circuit)
    if not current_report.ok:
        return current, current_report, False

    fixed_cuts = frozenset(fixed_cuts)
    current_score = _layout_optimization_score(current, circuit, current_report)
    pruned_count = 0
    while True:
        best_candidate = None
        best_report = None
        best_score = current_score
        best_cut = None
        for index, cut in enumerate(current.cuts):
            cut_hole = (cut.row, cut.col)
            if cut_hole in fixed_cuts:
                continue
            candidate_cuts = tuple(
                candidate
                for cut_index, candidate in enumerate(current.cuts)
                if cut_index != index
            )
            candidate, candidate_report = _rebuild_planned_stripboard_layout(
                current,
                circuit,
                board=current.board,
                placed_components=current.placed_components,
                cuts=candidate_cuts,
                jumpers=current.jumpers,
                connectors=current.connectors,
            )
            if candidate is None or not candidate_report.ok:
                continue
            candidate_score = _layout_optimization_score(
                candidate,
                circuit,
                candidate_report,
            )
            if candidate_score < best_score:
                best_candidate = candidate
                best_report = candidate_report
                best_score = candidate_score
                best_cut = cut

        if best_candidate is None:
            break

        _logger.debug(
            "Pruned redundant cut row=%s col=%s cuts=%s->%s score=%s->%s",
            best_cut.row,
            best_cut.col,
            len(current.cuts),
            len(best_candidate.cuts),
            current_score,
            best_score,
        )
        current = best_candidate
        current_report = best_report
        current_score = best_score
        pruned_count += 1

    if pruned_count:
        _logger.debug(
            "Finished redundant cut pruning pruned=%s %s score=%s",
            pruned_count,
            _layout_log_summary(current),
            current_score,
        )
    return current, current_report, bool(pruned_count)


def _absorb_connector_only_jumpers(layout, circuit, *, fixed_jumper_keys=frozenset()):
    current = layout
    current_report = verify_stripboard_layout(current, circuit)
    changed = False
    for jumper in tuple(current.jumpers):
        if _jumper_identity_key(jumper) in fixed_jumper_keys:
            continue
        index = _layout_jumper_index(current, jumper)
        if index is None:
            continue
        accepted = _absorb_connector_only_jumper(
            current,
            circuit,
            index,
        )
        if accepted is None:
            continue
        current, current_report = accepted
        changed = True
    return current, current_report, changed


def _absorb_connector_only_jumper(layout, circuit, jumper_index):
    jumper = layout.jumpers[jumper_index]
    jumpers_without = tuple(
        candidate
        for index, candidate in enumerate(layout.jumpers)
        if index != jumper_index
    )
    jumperless, jumperless_report = _rebuild_planned_stripboard_layout(
        layout,
        circuit,
        board=layout.board,
        placed_components=layout.placed_components,
        cuts=layout.cuts,
        jumpers=jumpers_without,
        connectors=layout.connectors,
    )
    if jumperless is None or jumperless_report.physical_netlist is None:
        return None

    start_conductor = _conductor_for_hole(
        jumperless_report.physical_netlist, jumper.start
    )
    end_conductor = _conductor_for_hole(jumperless_report.physical_netlist, jumper.end)
    if start_conductor is None or end_conductor is None:
        return None

    attempts = (
        (start_conductor, end_conductor, jumper.end),
        (end_conductor, start_conductor, jumper.start),
    )
    for connector_conductor, target_conductor, preferred_hole in attempts:
        connector_pin = _single_connector_pin_for_net(
            connector_conductor,
            layout,
            jumper.net_name,
        )
        if connector_pin is None:
            continue
        connector = _layout_connector_by_name(layout, connector_pin.refdes)
        if connector is None:
            continue
        target_holes = _connector_absorption_target_holes(
            target_conductor,
            preferred_hole,
        )
        occupied_holes = _left_compaction_occupied_holes(
            layout,
            circuit,
            ignored_connector_name=connector.name,
            ignored_jumper_indexes=frozenset((jumper_index,)),
        )
        for hole in target_holes:
            if hole in occupied_holes:
                continue
            candidate_connectors = tuple(
                (
                    PlacedConnector(
                        name=candidate.name,
                        net_name=candidate.net_name,
                        hole=hole,
                        label=candidate.label,
                        kind=candidate.kind,
                    )
                    if candidate.name == connector.name
                    else candidate
                )
                for candidate in layout.connectors
            )
            candidate, candidate_report = _rebuild_planned_stripboard_layout(
                layout,
                circuit,
                board=layout.board,
                placed_components=layout.placed_components,
                cuts=layout.cuts,
                jumpers=jumpers_without,
                connectors=candidate_connectors,
            )
            if candidate is None or not candidate_report.ok:
                continue
            _logger.debug(
                "Absorbed connector-only jumper net=%s connector=%s hole=%s->%s",
                jumper.net_name,
                connector.name,
                connector.hole,
                hole,
            )
            return candidate, candidate_report
    return None


def _single_connector_pin_for_net(conductor, layout, net_name):
    connector_names = {connector.name for connector in layout.connectors}
    pins_for_net = tuple(pin for pin in conductor.pins if pin.net_name == net_name)
    if len(pins_for_net) != 1:
        return None
    pin = pins_for_net[0]
    if pin.refdes not in connector_names or pin.terminal_name != "pin":
        return None
    return pin


def _connector_absorption_target_holes(conductor, preferred_hole):
    holes = tuple(conductor.holes)
    preferred = (preferred_hole,) if preferred_hole in set(holes) else ()
    rest = tuple(
        hole
        for hole in sorted(
            holes,
            key=lambda hole: (
                _hole_distance(hole, preferred_hole),
                hole[1],
                hole[0],
            ),
        )
        if hole not in preferred
    )
    return (*preferred, *rest)


def _right_relax_flexible_terminals(
    layout,
    circuit,
    *,
    fixed_jumper_keys=frozenset(),
):
    current = layout
    current_report = verify_stripboard_layout(current, circuit)
    changed = False

    for connector in sorted(
        current.connectors,
        key=lambda connector: (connector.row, -connector.col, connector.name),
    ):
        moved = _right_relax_connector(current, circuit, connector.name)
        if moved is None:
            continue
        current, current_report = moved
        changed = True

    endpoint_keys = []
    for index, jumper in enumerate(current.jumpers):
        if _jumper_identity_key(jumper) in fixed_jumper_keys:
            continue
        for endpoint_name, hole in (("start", jumper.start), ("end", jumper.end)):
            endpoint_keys.append((hole[0], -hole[1], index, endpoint_name))
    for _row, _negative_col, index, endpoint_name in sorted(endpoint_keys):
        moved = _right_relax_jumper_endpoint(current, circuit, index, endpoint_name)
        if moved is None:
            continue
        current, current_report = moved
        changed = True

    return current, current_report, changed


def _right_relax_connector(layout, circuit, name):
    connector = _layout_connector_by_name(layout, name)
    if connector is None:
        return None
    _left, right = _cut_bounded_segment_bounds(layout, connector.row, connector.col)
    if connector.col >= right:
        return None

    occupied_holes = _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_connector_name=connector.name,
    )
    for col in range(right, connector.col, -1):
        hole = (connector.row, col)
        if hole in occupied_holes:
            continue
        candidate_connectors = tuple(
            (
                PlacedConnector(
                    name=candidate.name,
                    net_name=candidate.net_name,
                    hole=hole,
                    label=candidate.label,
                    kind=candidate.kind,
                )
                if candidate.name == name
                else candidate
            )
            for candidate in layout.connectors
        )
        accepted = _verified_layout_variant(
            layout,
            circuit,
            connectors=candidate_connectors,
        )
        if accepted is not None:
            _logger.debug(
                "Right-relaxed connector name=%s hole=%s->%s",
                name,
                connector.hole,
                hole,
            )
            return accepted
    return None


def _right_relax_jumper_endpoint(layout, circuit, jumper_index, endpoint_name):
    if jumper_index >= len(layout.jumpers):
        return None
    jumper = layout.jumpers[jumper_index]
    hole = jumper.start if endpoint_name == "start" else jumper.end
    row, col = hole
    _left, right = _cut_bounded_segment_bounds(layout, row, col)
    if col >= right:
        return None

    occupied_holes = _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_jumper_endpoint=(jumper_index, endpoint_name),
    )
    for candidate_col in range(right, col, -1):
        candidate_hole = (row, candidate_col)
        if candidate_hole in occupied_holes:
            continue
        moved = _replace_jumper_endpoint(jumper, endpoint_name, candidate_hole)
        candidate_jumpers = tuple(
            moved if index == jumper_index else candidate
            for index, candidate in enumerate(layout.jumpers)
        )
        accepted = _verified_layout_variant(
            layout,
            circuit,
            jumpers=candidate_jumpers,
        )
        if accepted is not None:
            _logger.debug(
                "Right-relaxed jumper endpoint net=%s index=%s endpoint=%s "
                "hole=%s->%s",
                jumper.net_name,
                jumper_index,
                endpoint_name,
                hole,
                candidate_hole,
            )
            return accepted
    return None


def _down_compact_stripboard_layout(
    layout,
    circuit,
    *,
    locked_refdeses=frozenset(),
    fixed_cuts=frozenset(),
    fixed_jumpers=frozenset(),
):
    report = verify_stripboard_layout(layout, circuit)
    if not report.ok:
        return layout, report, False

    locked_refdeses = frozenset(str(refdes) for refdes in locked_refdeses)
    fixed_cuts = frozenset(fixed_cuts)
    fixed_jumpers = frozenset(fixed_jumpers)
    compacted = layout
    compacted_report = report
    accepted_count = 0
    max_iterations = max(
        1,
        _left_compaction_unit_count(compacted) * compacted.board.height_pitches + 1,
    )
    for _iteration in range(max_iterations):
        accepted = None
        for unit in _down_compaction_units(
            compacted,
            locked_refdeses,
            fixed_cuts=fixed_cuts,
            fixed_jumpers=fixed_jumpers,
        ):
            accepted = _down_compaction_best_move(compacted, circuit, unit)
            if accepted is not None:
                break
        if accepted is None:
            break
        compacted, compacted_report = accepted
        accepted_count += 1

    if accepted_count:
        _logger.debug(
            "Finished down compaction accepted_moves=%s %s",
            accepted_count,
            _layout_log_summary(compacted),
        )
    return compacted, compacted_report, bool(accepted_count)


def _down_compaction_units(
    layout,
    locked_refdeses=frozenset(),
    *,
    fixed_cuts=frozenset(),
    fixed_jumpers=frozenset(),
):
    footprint_map = _footprints_by_name(layout.footprints)
    units = []
    for placed_component in layout.placed_components:
        if placed_component.refdes in locked_refdeses:
            continue
        holes = _placed_component_occupied_holes(placed_component, footprint_map)
        units.append(
            (
                -max((row for row, _col in holes), default=0),
                _holes_min_col(holes),
                "component",
                placed_component.refdes,
                ("component", placed_component.refdes),
            )
        )
    for connector in layout.connectors:
        units.append(
            (
                -connector.row,
                connector.col,
                "connector",
                connector.name,
                ("connector", connector.name),
            )
        )
    for cut in layout.cuts:
        if (cut.row, cut.col) in fixed_cuts:
            continue
        units.append(
            (-cut.row, cut.col, "cut", cut.row, cut.col, ("cut", cut.row, cut.col))
        )
    for index, jumper in enumerate(layout.jumpers):
        if _jumper_identity_key(jumper) in fixed_jumpers:
            continue
        for endpoint_name, hole in (("start", jumper.start), ("end", jumper.end)):
            units.append(
                (
                    -hole[0],
                    hole[1],
                    "jumper",
                    jumper.net_name,
                    index,
                    endpoint_name,
                    ("jumper", index, endpoint_name),
                )
            )
    return tuple(item[-1] for item in sorted(units))


def _down_compaction_best_move(layout, circuit, unit):
    unit_type = unit[0]
    if unit_type == "component":
        return _down_compaction_best_component_move(layout, circuit, unit[1])
    if unit_type == "connector":
        return _down_compaction_best_connector_move(layout, circuit, unit[1])
    if unit_type == "cut":
        return _down_compaction_best_cut_move(layout, circuit, unit[1:])
    if unit_type == "jumper":
        return _down_compaction_best_jumper_endpoint_move(
            layout,
            circuit,
            unit[1],
            unit[2],
        )
    return None


def _down_compaction_best_component_move(layout, circuit, refdes):
    footprint_map = _footprints_by_name(layout.footprints)
    placed_component = _layout_component_by_refdes(layout, refdes)
    if placed_component is None:
        return None
    holes = _placed_component_occupied_holes(placed_component, footprint_map)
    max_row = max((row for row, _col in holes), default=0)
    max_delta = layout.board.height_pitches - 1 - max_row
    if max_delta <= 0:
        return None
    row, col = placed_component.origin
    for delta in range(max_delta, 0, -1):
        moved = PlacedComponent(
            refdes=placed_component.refdes,
            footprint_name=placed_component.footprint_name,
            origin=(row + delta, col),
            rotation=placed_component.rotation,
        )
        candidate_components = tuple(
            moved if component.refdes == refdes else component
            for component in layout.placed_components
        )
        accepted = _verified_layout_variant(
            layout,
            circuit,
            placed_components=candidate_components,
        )
        if accepted is not None:
            _logger.debug(
                "Down-compacted component refdes=%s origin=%s->%s",
                refdes,
                placed_component.origin,
                moved.origin,
            )
            return accepted
    return None


def _down_compaction_best_connector_move(layout, circuit, name):
    connector = _layout_connector_by_name(layout, name)
    if connector is None or connector.row >= layout.board.height_pitches - 1:
        return None
    occupied_holes = _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_connector_name=connector.name,
    )
    for row in range(layout.board.height_pitches - 1, connector.row, -1):
        hole = (row, connector.col)
        if hole in occupied_holes:
            continue
        candidate_connectors = tuple(
            (
                PlacedConnector(
                    name=candidate.name,
                    net_name=candidate.net_name,
                    hole=hole,
                    label=candidate.label,
                    kind=candidate.kind,
                )
                if candidate.name == name
                else candidate
            )
            for candidate in layout.connectors
        )
        accepted = _verified_layout_variant(
            layout,
            circuit,
            connectors=candidate_connectors,
        )
        if accepted is not None:
            _logger.debug(
                "Down-compacted connector name=%s hole=%s->%s",
                name,
                connector.hole,
                hole,
            )
            return accepted
    return None


def _down_compaction_best_cut_move(layout, circuit, cut_key):
    row, col = cut_key
    cut_index = _layout_cut_index(layout, row, col)
    if cut_index is None or row >= layout.board.height_pitches - 1:
        return None
    occupied_holes = _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_cut_index=cut_index,
    )
    for candidate_row in range(layout.board.height_pitches - 1, row, -1):
        if (candidate_row, col) in occupied_holes:
            continue
        moved = StripboardCut(row=candidate_row, col=col)
        candidate_cuts = tuple(
            moved if index == cut_index else cut
            for index, cut in enumerate(layout.cuts)
        )
        accepted = _verified_layout_variant(layout, circuit, cuts=candidate_cuts)
        if accepted is not None:
            _logger.debug(
                "Down-compacted cut row=%s->%s col=%s",
                row,
                candidate_row,
                col,
            )
            return accepted
    return None


def _down_compaction_best_jumper_endpoint_move(
    layout,
    circuit,
    jumper_index,
    endpoint_name,
):
    if jumper_index >= len(layout.jumpers):
        return None
    jumper = layout.jumpers[jumper_index]
    hole = jumper.start if endpoint_name == "start" else jumper.end
    row, col = hole
    if row >= layout.board.height_pitches - 1:
        return None
    occupied_holes = _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_jumper_endpoint=(jumper_index, endpoint_name),
    )
    for candidate_row in range(layout.board.height_pitches - 1, row, -1):
        candidate_hole = (candidate_row, col)
        if candidate_hole in occupied_holes:
            continue
        moved = _replace_jumper_endpoint(jumper, endpoint_name, candidate_hole)
        candidate_jumpers = tuple(
            moved if index == jumper_index else candidate
            for index, candidate in enumerate(layout.jumpers)
        )
        accepted = _verified_layout_variant(
            layout,
            circuit,
            jumpers=candidate_jumpers,
        )
        if accepted is not None:
            _logger.debug(
                "Down-compacted jumper endpoint net=%s index=%s endpoint=%s "
                "hole=%s->%s",
                jumper.net_name,
                jumper_index,
                endpoint_name,
                hole,
                candidate_hole,
            )
            return accepted
    return None


def _verified_layout_variant(
    layout,
    circuit,
    *,
    placed_components=None,
    cuts=None,
    jumpers=None,
    connectors=None,
):
    candidate, report = _rebuild_planned_stripboard_layout(
        layout,
        circuit,
        board=layout.board,
        placed_components=(
            layout.placed_components if placed_components is None else placed_components
        ),
        cuts=layout.cuts if cuts is None else cuts,
        jumpers=layout.jumpers if jumpers is None else jumpers,
        connectors=layout.connectors if connectors is None else connectors,
    )
    if candidate is None or not report.ok:
        return None
    if _left_compaction_cut_blocker_collisions(
        candidate
    ) - _left_compaction_cut_blocker_collisions(layout):
        return None
    return candidate, report


def _left_compaction_cut_blocker_collisions(layout):
    cut_holes = {(cut.row, cut.col) for cut in layout.cuts}
    return frozenset(
        (blocker.row, blocker.col, blocker.element_name)
        for blocker in layout.blockers
        if (blocker.row, blocker.col) in cut_holes
    )


def _layout_col_sum(layout):
    return sum(
        (
            *[pin.col for pin in _layout_score_pins(layout)],
            *[connector.col for connector in layout.connectors],
            *[cut.col for cut in layout.cuts],
            *[
                hole[1]
                for jumper in layout.jumpers
                for hole in (jumper.start, jumper.end)
            ],
            *[blocker.col for blocker in layout.blockers],
        )
    )


def _layout_row_sum(layout):
    return sum(
        (
            *[pin.row for pin in _layout_score_pins(layout)],
            *[connector.row for connector in layout.connectors],
            *[cut.row for cut in layout.cuts],
            *[
                hole[0]
                for jumper in layout.jumpers
                for hole in (jumper.start, jumper.end)
            ],
            *[blocker.row for blocker in layout.blockers],
        )
    )


def _layout_component_by_refdes(layout, refdes):
    for placed_component in layout.placed_components:
        if placed_component.refdes == refdes:
            return placed_component
    return None


def _layout_connector_by_name(layout, name):
    for connector in layout.connectors:
        if connector.name == name:
            return connector
    return None


def _layout_cut_index(layout, row, col):
    for index, cut in enumerate(layout.cuts):
        if cut.row == row and cut.col == col:
            return index
    return None


def _layout_jumper_index(layout, jumper):
    jumper_key = _jumper_identity_key(jumper)
    for index, candidate in enumerate(layout.jumpers):
        if _jumper_identity_key(candidate) == jumper_key:
            return index
    return None


def _jumper_identity_key(jumper):
    return (jumper.net_name, tuple(sorted((jumper.start, jumper.end))))


def _replace_jumper_endpoint(jumper, endpoint_name, hole):
    if endpoint_name == "start":
        return Jumper(start=hole, end=jumper.end, net_name=jumper.net_name)
    return Jumper(start=jumper.start, end=hole, net_name=jumper.net_name)


def _conductor_for_hole(physical_netlist, hole):
    for conductor in physical_netlist.conductors:
        if hole in set(conductor.holes):
            return conductor
    return None


def _cut_bounded_segment_bounds(layout, row, col):
    left = max(
        (cut.col for cut in layout.cuts if cut.row == row and cut.col < col),
        default=-1,
    )
    right = min(
        (cut.col for cut in layout.cuts if cut.row == row and cut.col > col),
        default=layout.board.width_pitches,
    )
    return left + 1, right - 1


def _placed_component_occupied_holes(placed_component, footprint_map):
    footprint = _require_footprint(footprint_map, placed_component.footprint_name)
    return tuple(
        _absolute_footprint_point(
            placed_component.origin,
            placed_component.rotation,
            point,
        )
        for point in (*footprint.pins.values(), *footprint.blockers)
    )


def _holes_min_col(holes):
    return min((col for _row, col in holes), default=0)


def _holes_min_row(holes):
    return min((row for row, _col in holes), default=0)


def _left_compaction_segment_min_col(layout, row, col):
    left_cut = max(
        (cut.col for cut in layout.cuts if cut.row == row and cut.col < col),
        default=-1,
    )
    return left_cut + 1


def _left_compaction_cut_blocked_holes(layout, circuit, cut_index):
    return _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_cut_index=cut_index,
    )


def _left_compaction_jumper_blocked_holes(
    layout,
    circuit,
    jumper_index,
    endpoint_name,
):
    return _left_compaction_occupied_holes(
        layout,
        circuit,
        ignored_jumper_endpoint=(jumper_index, endpoint_name),
    )


def _left_compaction_occupied_holes(
    layout,
    circuit,
    *,
    ignored_cut_index=None,
    ignored_jumper_endpoint=None,
    ignored_jumper_indexes=frozenset(),
    ignored_connector_name=None,
):
    holes = {pin.hole for pin in placed_component_pins(layout, circuit)}
    holes.update(
        connector.hole
        for connector in layout.connectors
        if connector.name != ignored_connector_name
    )
    holes.update((blocker.row, blocker.col) for blocker in layout.blockers)
    for index, cut in enumerate(layout.cuts):
        if index != ignored_cut_index:
            holes.add((cut.row, cut.col))
    for index, jumper in enumerate(layout.jumpers):
        if index in ignored_jumper_indexes:
            continue
        for endpoint_name, hole in (("start", jumper.start), ("end", jumper.end)):
            if ignored_jumper_endpoint == (index, endpoint_name):
                continue
            holes.add(hole)
    return holes


def write_stripboard_build_outputs(
    layout,
    circuit,
    *,
    output_dir,
    stem,
    report=None,
    run_id=None,
    scale=32,
):
    """Write top, bottom, debug, checklist, and JSON build artifacts."""

    if report is None:
        report = verify_stripboard_layout(layout, circuit)
    if not isinstance(report, PhysicalVerificationReport):
        raise TypeError("report must be a PhysicalVerificationReport.")
    if not report.ok:
        _logger.error(
            "Refusing to write stripboard build outputs circuit=%s: %s",
            _circuit_log_name(circuit),
            report.summary(),
        )
        raise ValueError(report.summary())

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = _build_output_paths(output_dir, stem, run_id)

    _logger.info(
        "Writing stripboard build outputs circuit=%s stem=%s output_dir=%s %s "
        "verification_ok=%s metrics=%s",
        _circuit_log_name(circuit),
        stem,
        output_dir,
        _layout_log_summary(layout),
        report.ok,
        _stripboard_density_metrics(layout, circuit).as_dict(),
    )
    render_stripboard_layout(layout, circuit, file=paths.top_svg, scale=scale)
    render_stripboard_layout(layout, circuit, file=paths.top_png, scale=scale)
    render_stripboard_layout(
        layout,
        circuit,
        file=paths.top_values_svg,
        scale=scale,
        component_labels="refdes_value",
    )
    render_stripboard_layout(
        layout,
        circuit,
        file=paths.top_values_png,
        scale=scale,
        component_labels="refdes_value",
    )
    render_stripboard_bottom(layout, circuit, file=paths.bottom_svg, scale=scale)
    render_stripboard_bottom(layout, circuit, file=paths.bottom_png, scale=scale)
    render_stripboard_debug(
        layout,
        circuit,
        report,
        file=paths.debug_svg,
        scale=scale,
    )
    render_stripboard_debug(
        layout,
        circuit,
        report,
        file=paths.debug_png,
        scale=scale,
    )
    write_stripboard_build_checklist(layout, circuit, report, file=paths.checklist_md)
    write_stripboard_build_json(layout, circuit, report, file=paths.data_json)
    for artifact in paths.as_tuple():
        _logger.info("Wrote stripboard build artifact %s", artifact)
    return paths


def render_stripboard_bottom(layout, circuit, file, scale=32):
    """Render the solder-side copper and cut view for a physical layout."""

    _validate_renderable_layout(layout, circuit)
    path = Path(file)
    _logger.debug(
        "Rendering stripboard bottom file=%s scale=%s %s",
        path,
        scale,
        _layout_log_summary(layout),
    )
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_bottom_svg(layout, circuit, path, scale)
    elif suffix == ".png":
        _render_stripboard_bottom_png(layout, circuit, path, scale)
    else:
        raise ValueError("Stripboard bottom output file must end in .svg or .png.")
    _logger.debug("Rendered stripboard bottom file=%s", path)


def render_stripboard_debug(layout, circuit, report, file, scale=32):
    """Render a connectivity debug view from a verification report."""

    _validate_renderable_layout(layout, circuit)
    if not isinstance(report, PhysicalVerificationReport):
        raise TypeError("report must be a PhysicalVerificationReport.")
    if report.physical_netlist is None:
        raise ValueError("Debug rendering requires a physical netlist in the report.")

    path = Path(file)
    _logger.debug(
        "Rendering stripboard debug file=%s scale=%s %s conductors=%s",
        path,
        scale,
        _layout_log_summary(layout),
        len(report.physical_netlist.conductors),
    )
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_debug_svg(layout, circuit, report, path, scale)
    elif suffix == ".png":
        _render_stripboard_debug_png(layout, circuit, report, path, scale)
    else:
        raise ValueError("Stripboard debug output file must end in .svg or .png.")
    _logger.debug("Rendered stripboard debug file=%s", path)


def write_stripboard_build_checklist(layout, circuit, report, file):
    """Write a Markdown build checklist for a verified stripboard layout."""

    if not isinstance(report, PhysicalVerificationReport):
        raise TypeError("report must be a PhysicalVerificationReport.")
    _logger.debug("Writing stripboard build checklist file=%s", file)
    lines = _stripboard_build_checklist_lines(layout, circuit, report)
    Path(file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    _logger.debug("Wrote stripboard build checklist file=%s lines=%s", file, len(lines))


def write_stripboard_build_json(layout, circuit, report, file):
    """Write machine-readable circuit, layout, and verification data."""

    if not isinstance(report, PhysicalVerificationReport):
        raise TypeError("report must be a PhysicalVerificationReport.")
    _logger.debug("Writing stripboard build JSON file=%s", file)
    Path(file).write_text(
        json.dumps(
            _stripboard_build_json_data(layout, circuit, report),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _logger.debug("Wrote stripboard build JSON file=%s", file)


def render_stripboard_layout(
    layout,
    circuit,
    file,
    scale=32,
    *,
    detail="assembly",
    component_labels="refdes",
):
    """Render a manual physical stripboard layout as SVG or PNG."""

    if not isinstance(layout, PhysicalLayout):
        raise TypeError("render_stripboard_layout expects a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("render_stripboard_layout expects a Circuit object.")
    if layout.board.strip_direction is not Direction.HORIZONTAL:
        raise NotImplementedError("Only horizontal stripboards are supported for now.")
    detail = _validate_layout_detail(detail)
    component_labels = _validate_component_label_mode(component_labels)

    _validate_layout_geometry(layout, circuit, _footprints_by_name(layout.footprints))

    path = Path(file)
    _logger.debug(
        "Rendering stripboard layout file=%s detail=%s component_labels=%s scale=%s %s",
        path,
        detail,
        component_labels,
        scale,
        _layout_log_summary(layout),
    )
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_layout_svg(
            layout,
            circuit,
            path,
            scale,
            detail,
            component_labels,
        )
    elif suffix == ".png":
        _render_stripboard_layout_png(
            layout,
            circuit,
            path,
            scale,
            detail,
            component_labels,
        )
    else:
        raise ValueError("Stripboard layout output file must end in .svg or .png.")
    _logger.debug("Rendered stripboard layout file=%s", path)


def _validate_renderable_layout(layout, circuit):
    if not isinstance(layout, PhysicalLayout):
        raise TypeError("layout must be a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("circuit must be a Circuit object.")
    if layout.board.strip_direction is not Direction.HORIZONTAL:
        raise NotImplementedError("Only horizontal stripboards are supported for now.")
    _validate_layout_geometry(layout, circuit, _footprints_by_name(layout.footprints))


def _build_output_paths(output_dir, stem, run_id):
    stem = str(stem)

    def path_for(suffix, extension):
        artifact_stem = f"{stem}{suffix}"
        if run_id is not None:
            artifact_stem = f"{artifact_stem}__{run_id}"
        return output_dir / f"{artifact_stem}{extension}"

    return StripboardBuildOutputs(
        top_svg=path_for("", ".svg"),
        top_png=path_for("", ".png"),
        top_values_svg=path_for("_values", ".svg"),
        top_values_png=path_for("_values", ".png"),
        bottom_svg=path_for("_bottom", ".svg"),
        bottom_png=path_for("_bottom", ".png"),
        debug_svg=path_for("_debug", ".svg"),
        debug_png=path_for("_debug", ".png"),
        checklist_md=path_for("_checklist", ".md"),
        data_json=path_for("_data", ".json"),
    )


def _render_stripboard_bottom_svg(layout, circuit, path, scale):
    scale = dsl._validate_render_scale(scale)
    width, height = dsl._stripboard_size(layout.board)
    width_px = width * scale
    height_px = height * scale
    pins = placed_component_pins(layout, circuit)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px:.0f}" height="{height_px:.0f}" '
            f'viewBox="0 0 {width:.3f} {height:.3f}">'
        ),
        "  <title>Bottom Copper And Cuts</title>",
        (
            f'  <rect class="board bottom-view" x="0" y="0" width="{width:.3f}" '
            f'height="{height:.3f}" fill="{dsl.STRIPBOARD_BOARD_FILL}" '
            f'stroke="{dsl.STRIPBOARD_BOARD_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        ),
    ]
    _append_svg_bottom_board(lines, layout.board)
    _append_svg_bottom_cuts(lines, layout)
    _append_svg_bottom_pins(lines, layout, pins)
    _append_svg_bottom_connectors(lines, layout)
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_svg_bottom_board(lines, board):
    for row in range(board.height_pitches):
        x, y, strip_width, strip_height = dsl._stripboard_strip_rect(board, row)
        lines.append(
            f'  <rect class="bottom-copper-strip" data-row="{row}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{strip_width:.3f}" '
            f'height="{strip_height:.3f}" fill="{dsl.STRIPBOARD_STRIP_FILL}" '
            f'stroke="{dsl.STRIPBOARD_STRIP_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )
    for row in range(board.height_pitches):
        for col in range(board.width_pitches):
            x, y = _bottom_hole_position(board, (row, col))
            lines.append(
                f'  <circle class="bottom-hole" data-col="{col}" data-row="{row}" '
                f'cx="{x:.3f}" cy="{y:.3f}" r="{dsl.STRIPBOARD_HOLE_RADIUS:.3f}" '
                f'fill="{dsl.STRIPBOARD_HOLE_FILL}" stroke="{dsl.STRIPBOARD_HOLE_STROKE}" '
                f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
            )


def _append_svg_bottom_cuts(lines, layout):
    for cut in layout.cuts:
        x, y = _bottom_hole_position(layout.board, (cut.row, cut.col))
        radius = dsl.STRIPBOARD_CUT_RADIUS
        lines.append(
            f'  <circle class="bottom-strip-cut" data-row="{cut.row}" '
            f'data-col="{cut.col}" cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{radius:.3f}" fill="none" stroke="{dsl.STRIPBOARD_CUT_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
        )
        for x1, y1, x2, y2 in dsl._cut_cross_lines(x, y, radius):
            lines.append(
                f'  <line class="bottom-strip-cut-mark" data-row="{cut.row}" '
                f'data-col="{cut.col}" x1="{x1:.3f}" y1="{y1:.3f}" '
                f'x2="{x2:.3f}" y2="{y2:.3f}" '
                f'stroke="{dsl.STRIPBOARD_CUT_STROKE}" '
                f'stroke-width="{dsl.STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
            )


def _append_svg_bottom_pins(lines, layout, pins):
    for pin in pins:
        x, y = _bottom_hole_position(layout.board, pin.hole)
        lines.append(
            f'  <circle class="bottom-pin" data-net="{dsl._svg_attr(pin.net_name)}" '
            f'data-element="{dsl._svg_attr(pin.refdes)}" '
            f'data-terminal="{dsl._svg_attr(pin.terminal_name)}" '
            f'data-row="{pin.row}" data-col="{pin.col}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS:.3f}" '
            f'fill="{dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL}"/>'
        )


def _append_svg_bottom_connectors(lines, layout):
    for connector in layout.connectors:
        x, y = _bottom_hole_position(layout.board, connector.hole)
        lines.append(
            f'  <circle class="bottom-connector" '
            f'data-net="{dsl._svg_attr(connector.net_name)}" '
            f'data-connector="{dsl._svg_attr(connector.name)}" '
            f'data-row="{connector.row}" data-col="{connector.col}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{LAYOUT_CONNECTOR_RADIUS:.3f}" '
            f'fill="{LAYOUT_CONNECTOR_FILL}" '
            f'stroke="{LAYOUT_CONNECTOR_STROKE}" '
            f'stroke-width="{LAYOUT_JUMPER_STROKE_WIDTH:.3f}"/>'
        )


def _render_stripboard_bottom_png(layout, circuit, path, scale):
    scale = dsl._validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard bottom PNG files."
        ) from error

    width, height = dsl._stripboard_size(layout.board)
    image = Image.new(
        "RGB",
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        "white",
    )
    draw = ImageDraw.Draw(image)
    dsl._draw_stripboard_base_png(draw, layout.board, scale)

    for cut in layout.cuts:
        _draw_bottom_cut_png(draw, layout.board, cut, scale)
    for pin in placed_component_pins(layout, circuit):
        dsl._draw_px_circle(
            draw,
            _bottom_hole_position(layout.board, pin.hole),
            dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS,
            scale,
            fill=dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL,
        )
    for connector in layout.connectors:
        _draw_layout_connector_png_at(
            draw,
            _bottom_hole_position(layout.board, connector.hole),
            scale,
        )

    image.save(path)


def _draw_bottom_cut_png(draw, board, cut, scale):
    x, y = _bottom_hole_position(board, (cut.row, cut.col))
    radius = dsl.STRIPBOARD_CUT_RADIUS
    stroke = max(1, int(round(dsl.STRIPBOARD_CUT_STROKE_WIDTH * scale)))
    draw.ellipse(
        dsl._px_rect(x - radius, y - radius, radius * 2, radius * 2, scale),
        outline=dsl.STRIPBOARD_CUT_STROKE,
        width=stroke,
    )
    for x1, y1, x2, y2 in dsl._cut_cross_lines(x, y, radius):
        draw.line(
            [dsl._px_point((x1, y1), scale), dsl._px_point((x2, y2), scale)],
            fill=dsl.STRIPBOARD_CUT_STROKE,
            width=stroke,
        )


def _render_stripboard_debug_svg(layout, circuit, report, path, scale):
    scale = dsl._validate_render_scale(scale)
    width, height = dsl._stripboard_size(layout.board)
    width_px = width * scale
    height_px = height * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px:.0f}" height="{height_px:.0f}" '
            f'viewBox="0 0 {width:.3f} {height:.3f}">'
        ),
        "  <title>Connectivity Debug View</title>",
        (
            f'  <rect class="board debug-view" x="0" y="0" width="{width:.3f}" '
            f'height="{height:.3f}" fill="{dsl.STRIPBOARD_BOARD_FILL}" '
            f'stroke="{dsl.STRIPBOARD_BOARD_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        ),
    ]
    _append_svg_debug_board(lines, layout.board)
    _append_svg_debug_conductors(lines, report.physical_netlist)
    _append_svg_debug_jumpers(lines, layout)
    _append_svg_layout_pins(lines, placed_component_pins(layout, circuit))
    _append_svg_layout_connectors(lines, layout.connectors)
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_svg_debug_board(lines, board):
    for row in range(board.height_pitches):
        x, y, strip_width, strip_height = dsl._stripboard_strip_rect(board, row)
        lines.append(
            f'  <rect class="debug-copper-strip" data-row="{row}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{strip_width:.3f}" '
            f'height="{strip_height:.3f}" fill="{dsl.STRIPBOARD_STRIP_FILL}" '
            f'opacity="0.25" stroke="{dsl.STRIPBOARD_STRIP_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )
    for col, row, x, y in dsl._stripboard_holes(board):
        lines.append(
            f'  <circle class="debug-hole" data-col="{col}" data-row="{row}" '
            f'cx="{x:.3f}" cy="{y:.3f}" r="{dsl.STRIPBOARD_HOLE_RADIUS:.3f}" '
            f'fill="{dsl.STRIPBOARD_HOLE_FILL}" stroke="{dsl.STRIPBOARD_HOLE_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}" opacity="0.35"/>'
        )


def _append_svg_debug_conductors(lines, physical_netlist):
    for conductor in physical_netlist.conductors:
        color = _debug_conductor_color(conductor.index)
        data_net = ",".join(conductor.net_names)
        for segment in _conductor_row_segments(conductor.holes):
            row, start_col, end_col = segment
            start = dsl._stripboard_hole_position((row, start_col))
            end = dsl._stripboard_hole_position((row, end_col))
            lines.append(
                f'  <line class="debug-conductor-segment" '
                f'data-conductor="{conductor.index}" '
                f'data-net="{dsl._svg_attr(data_net)}" data-row="{row}" '
                f'data-start-col="{start_col}" data-end-col="{end_col}" '
                f'x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
                f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" '
                f'stroke="{color}" stroke-width="0.180" stroke-linecap="round"/>'
            )
        for hole in conductor.holes:
            x, y = dsl._stripboard_hole_position(hole)
            lines.append(
                f'  <circle class="debug-conductor-hole" '
                f'data-conductor="{conductor.index}" '
                f'data-net="{dsl._svg_attr(data_net)}" '
                f'data-row="{hole[0]}" data-col="{hole[1]}" '
                f'cx="{x:.3f}" cy="{y:.3f}" r="0.120" fill="{color}"/>'
            )
        if conductor.net_names:
            x, y = dsl._stripboard_hole_position(conductor.holes[0])
            lines.append(
                f'  <text class="debug-net-label" '
                f'data-conductor="{conductor.index}" '
                f'data-net="{dsl._svg_attr(data_net)}" '
                f'x="{x:.3f}" y="{y - 0.260:.3f}" font-size="0.180" '
                f'font-weight="700" text-anchor="start" '
                f'fill="{color}" stroke="{dsl.STRIPBOARD_OVERLAY_TEXT_HALO}" '
                f'stroke-width="0.060" paint-order="stroke">'
                f"{dsl._svg_text(data_net)}</text>"
            )


def _append_svg_debug_jumpers(lines, layout):
    for jumper in layout.jumpers:
        _append_svg_jumper_wire(
            lines,
            jumper,
            class_name="debug-jumper",
            stroke=dsl.STRIPBOARD_OVERLAY_NODE_FILL,
            stroke_width=0.115,
            stroke_dasharray="0.180 0.110",
        )


def _render_stripboard_debug_png(layout, circuit, report, path, scale):
    scale = dsl._validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard debug PNG files."
        ) from error

    width, height = dsl._stripboard_size(layout.board)
    image = Image.new(
        "RGB",
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        "white",
    )
    draw = ImageDraw.Draw(image)
    dsl._draw_stripboard_base_png(draw, layout.board, scale)

    for conductor in report.physical_netlist.conductors:
        color = _debug_conductor_color(conductor.index)
        stroke = max(2, int(round(0.18 * scale)))
        for row, start_col, end_col in _conductor_row_segments(conductor.holes):
            draw.line(
                [
                    dsl._px_point(
                        dsl._stripboard_hole_position((row, start_col)), scale
                    ),
                    dsl._px_point(dsl._stripboard_hole_position((row, end_col)), scale),
                ],
                fill=color,
                width=stroke,
            )
        for hole in conductor.holes:
            dsl._draw_px_circle(
                draw,
                dsl._stripboard_hole_position(hole),
                0.12,
                scale,
                fill=color,
            )

    jumper_width = max(1, int(round(0.115 * scale)))
    for jumper in layout.jumpers:
        draw.line(
            [dsl._px_point(point, scale) for point in _jumper_display_points(jumper)],
            fill=dsl.STRIPBOARD_OVERLAY_NODE_FILL,
            width=jumper_width,
        )

    for pin in placed_component_pins(layout, circuit):
        dsl._draw_px_circle(
            draw,
            dsl._stripboard_hole_position(pin.hole),
            dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS,
            scale,
            fill=dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL,
        )
    for connector in layout.connectors:
        _draw_layout_connector_png(draw, connector, 0, scale)

    image.save(path)


def _bottom_hole_position(board, hole):
    row, col = hole
    return (
        dsl.STRIPBOARD_BOARD_MARGIN + (board.width_pitches - 1 - col),
        dsl.STRIPBOARD_BOARD_MARGIN + row,
    )


def _jumper_display_points(jumper):
    start = dsl._stripboard_hole_position(jumper.start)
    end = dsl._stripboard_hole_position(jumper.end)
    if jumper.start[0] != jumper.end[0]:
        return (start, end)

    lane_y = start[1] + (0.5 if jumper.start[0] == 0 else -0.5)
    return (start, (start[0], lane_y), (end[0], lane_y), end)


def _conductor_row_segments(holes):
    segments = []
    holes_by_row = {}
    for row, col in holes:
        holes_by_row.setdefault(row, []).append(col)
    for row, cols in sorted(holes_by_row.items()):
        sorted_cols = sorted(cols)
        start = sorted_cols[0]
        previous = start
        for col in sorted_cols[1:]:
            if col == previous + 1:
                previous = col
                continue
            segments.append((row, start, previous))
            start = col
            previous = col
        segments.append((row, start, previous))
    return tuple(segments)


def _debug_conductor_color(index):
    colors = (
        "#2563eb",
        "#dc2626",
        "#16a34a",
        "#9333ea",
        "#ea580c",
        "#0891b2",
        "#be123c",
        "#4f46e5",
        "#65a30d",
        "#ca8a04",
    )
    return colors[index % len(colors)]


def _stripboard_build_checklist_lines(layout, circuit, report):
    metrics = _stripboard_density_metrics(layout, circuit)
    lines = [
        f"# {circuit.name} Stripboard Build Checklist",
        "",
        f"- Verification: {'OK' if report.ok else 'FAILED'}",
        f"- Board: {layout.board.width_pitches} x {layout.board.height_pitches} holes",
        f"- Pitch: {layout.board.pitch_mm:g} mm",
        f"- Used area: {metrics.used_width} x {metrics.used_height} holes",
        f"- Occupied holes: {metrics.occupied_holes} / {metrics.total_holes}",
        f"- Empty holes: {metrics.empty_holes} ({metrics.empty_ratio:.1%})",
        "",
        "## Components",
    ]
    pins_by_component = {}
    for pin in placed_component_pins(layout, circuit):
        pins_by_component.setdefault(pin.refdes, []).append(pin)
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    for placed_component in layout.placed_components:
        component = components_by_refdes[placed_component.refdes]
        value = "" if component.value is None else f" {component.value}"
        lines.append(
            "- [ ] "
            f"{component.refdes}{value} ({component.kind}) "
            f"footprint `{placed_component.footprint_name}` "
            f"origin row {placed_component.origin[0]}, col {placed_component.origin[1]}, "
            f"rotation {placed_component.rotation}"
        )
        for pin in pins_by_component.get(component.refdes, ()):
            lines.append(
                "  - "
                f"{pin.terminal_name}: net `{pin.net_name}`, "
                f"row {pin.row}, col {pin.col}"
            )

    lines.extend(["", "## External Connectors"])
    for connector in layout.connectors:
        label = "" if connector.label is None else f" `{connector.label}`"
        lines.append(
            "- [ ] "
            f"{connector.name}{label}: net `{connector.net_name}`, "
            f"row {connector.row}, col {connector.col}"
        )

    lines.extend(["", "## Strip Cuts"])
    for cut in layout.cuts:
        lines.append(
            "- [ ] "
            f"Cut row {cut.row}, col {cut.col} "
            f"(bottom-view col {_bottom_view_col(layout.board, cut.col)})"
        )

    lines.extend(["", "## Top Jumpers"])
    for jumper in layout.jumpers:
        lines.append(
            "- [ ] "
            f"`{jumper.net_name}`: row {jumper.start[0]}, col {jumper.start[1]} "
            f"to row {jumper.end[0]}, col {jumper.end[1]}"
        )

    lines.extend(["", "## Verification"])
    if report.issues:
        for issue in report.issues:
            lines.append(f"- {issue.severity.upper()} `{issue.code}`: {issue.message}")
    else:
        lines.append("- No verification issues.")

    return lines


def _stripboard_build_json_data(layout, circuit, report):
    metrics = _stripboard_density_metrics(layout, circuit)
    return {
        "circuit": export_netlist(circuit),
        "layout": {
            "board": {
                "width_pitches": layout.board.width_pitches,
                "height_pitches": layout.board.height_pitches,
                "strip_direction": layout.board.strip_direction.name.lower(),
                "pitch_mm": layout.board.pitch_mm,
            },
            "placed_components": [
                {
                    "refdes": component.refdes,
                    "footprint_name": component.footprint_name,
                    "origin": list(component.origin),
                    "rotation": component.rotation,
                }
                for component in layout.placed_components
            ],
            "cuts": [{"row": cut.row, "col": cut.col} for cut in layout.cuts],
            "connectors": [
                {
                    "name": connector.name,
                    "label": connector.label,
                    "kind": connector.kind,
                    "net_name": connector.net_name,
                    "row": connector.row,
                    "col": connector.col,
                }
                for connector in layout.connectors
            ],
            "jumpers": [
                {
                    "net_name": jumper.net_name,
                    "start": list(jumper.start),
                    "end": list(jumper.end),
                }
                for jumper in layout.jumpers
            ],
            "blockers": [
                {
                    "row": blocker.row,
                    "col": blocker.col,
                    "element_name": blocker.element_name,
                }
                for blocker in layout.blockers
            ],
            "metrics": metrics.as_dict(),
        },
        "verification": {
            "ok": report.ok,
            "issues": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "subject": issue.subject,
                    "holes": [list(hole) for hole in issue.holes],
                }
                for issue in report.issues
            ],
            "physical_netlist": (
                None
                if report.physical_netlist is None
                else _physical_netlist_json_data(report.physical_netlist)
            ),
        },
    }


def _physical_netlist_json_data(physical_netlist):
    return {
        "conductors": [
            {
                "index": conductor.index,
                "holes": [list(hole) for hole in conductor.holes],
                "net_names": list(conductor.net_names),
                "pins": [
                    {
                        "refdes": pin.refdes,
                        "terminal_name": pin.terminal_name,
                        "net_name": pin.net_name,
                        "row": pin.row,
                        "col": pin.col,
                        "footprint_name": pin.footprint_name,
                    }
                    for pin in conductor.pins
                ],
            }
            for conductor in physical_netlist.conductors
        ],
    }


def _bottom_view_col(board, col):
    return board.width_pitches - 1 - col


def footprint_for_component(component, footprints):
    """Return the preferred footprint matching a component kind."""

    if not isinstance(component, Component):
        raise TypeError("footprint_for_component expects a Component object.")
    matches = _footprints_for_component(component, _footprints_by_name(footprints))
    if not matches:
        raise ValueError(f"No footprint supports component kind {component.kind!r}.")
    return matches[0]


def _footprints_for_component(component, footprint_map):
    return tuple(
        footprint
        for footprint in footprint_map.values()
        if component.kind in footprint.component_kinds
    )


def _validate_physical_inputs(layout, circuit):
    if not isinstance(layout, PhysicalLayout):
        raise TypeError("layout must be a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("circuit must be a Circuit object.")
    if not isinstance(layout.board, Stripboard):
        raise TypeError("layout.board must be a Stripboard object.")


def _coerce_routing_hints(hints):
    if hints is None:
        return StripboardRoutingHints()
    if not isinstance(hints, StripboardRoutingHints):
        raise TypeError("hints must be a StripboardRoutingHints object.")
    return hints


def _normalize_fixed_placements(fixed_placements, circuit, footprint_map):
    if not isinstance(fixed_placements, Mapping):
        raise TypeError("fixed_placements must be a mapping.")
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    fixed = {}
    for refdes, placement in fixed_placements.items():
        if refdes not in components_by_refdes:
            raise ValueError(f"Fixed placement refers to unknown component {refdes!r}.")
        fixed[refdes] = _coerce_placement(
            refdes,
            components_by_refdes[refdes],
            placement,
            footprint_map,
        )
    return fixed


def _routing_net_rows(circuit, hints):
    hinted_rows = hints.net_rows
    net_rows = {
        net.name: hinted_rows[net.name]
        for net in circuit.nets
        if net.name in hinted_rows
    }
    next_row = max(net_rows.values(), default=-1) + 1
    for net_name in sorted(
        net.name for net in circuit.nets if net.name not in net_rows
    ):
        net_rows[net_name] = next_row
        next_row += 1
    return net_rows


def _routing_connectors_from_hints(hints, circuit, board):
    net_names = {net.name for net in circuit.nets}
    connectors = []
    seen_holes = set()
    for name, hole in hints.connector_holes.items():
        net_name = hints.connector_net_names.get(name)
        if net_name is None:
            raise ValueError(f"Connector hint {name!r} has no net name.")
        if net_name not in net_names:
            raise ValueError(f"Connector hint {name!r} uses unknown net {net_name!r}.")
        if not _hole_on_board(board, hole[0], hole[1]):
            raise ValueError(f"Connector hint {name!r} is outside the board: {hole}.")
        if hole in seen_holes:
            raise ValueError(f"Multiple connector hints share hole {hole}.")
        seen_holes.add(hole)
        connectors.append(
            PlacedConnector(
                name=name,
                net_name=net_name,
                hole=hole,
                label=hints.connector_labels.get(name, name),
            )
        )
    return tuple(sorted(connectors, key=lambda connector: connector.name))


def _route_component_placements(
    circuit,
    board,
    footprint_map,
    hints,
    fixed_placements,
    net_rows,
    reserved_holes=frozenset(),
):
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    ordered_refdeses = _routing_component_order(circuit, hints)
    preferred_columns = _routing_preferred_component_columns(
        circuit,
        board,
        hints,
        ordered_refdeses,
    )
    terminal_targets = _routing_terminal_targets(
        circuit,
        board,
        hints,
        net_rows,
        preferred_columns,
    )
    _logger.info(
        "Placing components order=%s beam_width=%s candidate_limit=%s "
        "reserved_holes=%s",
        ordered_refdeses,
        _routing_beam_width(),
        _routing_candidate_limit(),
        len(reserved_holes),
    )
    _logger.debug(
        "Placement targets preferred_columns=%s terminal_targets=%s",
        preferred_columns,
        terminal_targets,
    )
    initial_state, initial_error = _routing_initial_placement_state(
        fixed_placements,
        components_by_refdes,
        footprint_map,
        board,
        reserved_holes,
    )
    if initial_error is not None:
        _logger.error("Initial fixed placement state is invalid: %s", initial_error)
        return None, initial_error
    states = (initial_state,)

    total_refdeses = len(ordered_refdeses)
    for refdes_index, refdes in enumerate(ordered_refdeses, start=1):
        if refdes in fixed_placements:
            _logger.info(
                "Placed component %s/%s refdes=%s fixed=True states=%s",
                refdes_index,
                total_refdeses,
                refdes,
                len(states),
            )
            continue
        component = components_by_refdes[refdes]
        _logger.debug(
            "Finding placement candidates refdes=%s kind=%s preferred_col=%s",
            refdes,
            component.kind,
            preferred_columns.get(refdes, 0),
        )
        candidates, candidate_error = _routing_component_candidates(
            component,
            board,
            footprint_map,
            terminal_targets.get(refdes, {}),
            preferred_columns.get(refdes, 0),
        )
        if candidate_error is not None:
            _logger.warning(
                "Placement candidate search failed refdes=%s: %s",
                refdes,
                candidate_error,
            )
            return None, candidate_error
        _logger.debug(
            "Found placement candidates refdes=%s candidates=%s",
            refdes,
            len(candidates),
        )
        next_states = []
        for state_score, state_planned, state_pins, state_blockers in states:
            for (
                candidate_score,
                placed_component,
                pin_holes,
                blocker_holes,
            ) in candidates:
                if state_pins & pin_holes:
                    continue
                if state_pins & blocker_holes:
                    continue
                if state_blockers & pin_holes:
                    continue
                planned = dict(state_planned)
                planned[refdes] = placed_component
                next_states.append(
                    (
                        _add_routing_scores(state_score, candidate_score),
                        planned,
                        frozenset((*state_pins, *pin_holes)),
                        frozenset((*state_blockers, *blocker_holes)),
                    )
                )
        if not next_states:
            _logger.warning(
                "No collision-free placement survived refdes=%s states=%s "
                "candidates=%s",
                refdes,
                len(states),
                len(candidates),
            )
            return None, (
                f"No collision-free placement is available for {refdes!r} "
                f"on a {board.width_pitches}x{board.height_pitches} board."
            )
        states = tuple(
            sorted(next_states, key=lambda state: state[0])[: _routing_beam_width()]
        )
        _logger.info(
            "Placed component %s/%s refdes=%s candidates=%s states=%s best_score=%s",
            refdes_index,
            total_refdeses,
            refdes,
            len(candidates),
            len(states),
            states[0][0] if states else None,
        )

    planned_states = tuple(
        (planned, score)
        for score, planned, _pin_holes, _blocker_holes in sorted(
            states,
            key=lambda state: state[0],
        )
    )
    _logger.info("Finished component placement states=%s", len(planned_states))
    return planned_states, None


def _routing_component_order(circuit, hints):
    component_refdeses = {component.refdes for component in circuit.components}
    ordered = []
    seen = set()
    for refdes in hints.component_order:
        if refdes not in component_refdeses or refdes in seen:
            continue
        ordered.append(refdes)
        seen.add(refdes)
    remaining = sorted(component_refdeses - seen)
    return tuple((*ordered, *remaining))


def _routing_shake_orders_from_layout(circuit, hints, layout):
    baseline = _routing_component_order(circuit, hints)
    jumper_net_names = tuple(
        dict.fromkeys(jumper.net_name for jumper in layout.jumpers)
    )
    orders = []
    seen = {baseline}
    for net_name in jumper_net_names:
        order = _routing_focus_net_component_order(circuit, hints, net_name)
        if order and order not in seen:
            orders.append(order)
            seen.add(order)

    combined_order = _routing_focus_net_component_order(
        circuit, hints, jumper_net_names
    )
    if combined_order and combined_order not in seen:
        orders.append(combined_order)
    return tuple(orders)


def _routing_focus_net_component_order(circuit, hints, net_names):
    if isinstance(net_names, str):
        net_names = (net_names,)
    focus_net_names = frozenset(str(net_name) for net_name in net_names)
    if not focus_net_names:
        return ()

    baseline = _routing_component_order(circuit, hints)
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    seed_refdeses = {
        component.refdes
        for component in circuit.components
        if any(terminal.net_name in focus_net_names for terminal in component.terminals)
    }
    if not seed_refdeses:
        return ()

    seed_net_names = {
        terminal.net_name
        for refdes in seed_refdeses
        for terminal in components_by_refdes[refdes].terminals
    }
    focus_refdeses = {
        component.refdes
        for component in circuit.components
        if any(terminal.net_name in seed_net_names for terminal in component.terminals)
    }
    focus_order = tuple(
        sorted(
            focus_refdeses,
            key=lambda refdes: _routing_focus_component_sort_key(
                components_by_refdes[refdes],
                hints,
                seed_refdeses,
            ),
        )
    )
    return tuple(
        (*focus_order, *(refdes for refdes in baseline if refdes not in focus_refdeses))
    )


def _routing_focus_component_sort_key(component, hints, seed_refdeses):
    return (
        int(component.refdes not in seed_refdeses),
        int(component.kind not in DIRECTIONAL_TERMINAL_LABEL_KINDS),
        hints.component_columns.get(component.refdes, 0),
        component.refdes,
    )


def _routing_preferred_component_columns(circuit, board, hints, ordered_refdeses):
    spread_columns = {}
    denominator = max(1, len(ordered_refdeses) + 1)
    for index, refdes in enumerate(ordered_refdeses, start=1):
        spread_columns[refdes] = int(
            round(index * (board.width_pitches - 1) / denominator)
        )
    return {
        component.refdes: int(
            _clamp(
                hints.component_columns.get(
                    component.refdes,
                    spread_columns.get(component.refdes, 0),
                ),
                0,
                board.width_pitches - 1,
            )
        )
        for component in circuit.components
    }


def _routing_terminal_targets(circuit, board, hints, net_rows, preferred_columns):
    targets = {}
    for component in circuit.components:
        component_targets = {}
        preferred_col = preferred_columns.get(component.refdes, 0)
        for terminal in component.terminals:
            hinted_hole = hints.component_terminal_holes.get(
                (component.refdes, terminal.name)
            )
            if hinted_hole is not None:
                row, col = hinted_hole
                component_targets[terminal.name] = (
                    int(_clamp(row, 0, board.height_pitches - 1)),
                    int(_clamp(col, 0, board.width_pitches - 1)),
                )
                continue
            component_targets[terminal.name] = (
                int(
                    _clamp(
                        net_rows.get(terminal.net_name, 0),
                        0,
                        board.height_pitches - 1,
                    )
                ),
                preferred_col,
            )
        targets[component.refdes] = component_targets
    return targets


def _routing_initial_placement_state(
    fixed_placements,
    components_by_refdes,
    footprint_map,
    board,
    reserved_holes=frozenset(),
):
    planned = {}
    pin_holes = frozenset(reserved_holes)
    blocker_holes = frozenset()
    for refdes, placed_component in fixed_placements.items():
        component = components_by_refdes[refdes]
        footprint = _require_footprint(footprint_map, placed_component.footprint_name)
        pins, blockers = _routing_placement_holes(
            component,
            placed_component,
            footprint,
        )
        outside = tuple(
            hole
            for hole in (*pins, *blockers)
            if not _hole_on_board(board, hole[0], hole[1])
        )
        if outside:
            return None, (
                f"Fixed placement for {refdes!r} has holes outside the board: "
                f"{outside}."
            )
        if pin_holes & pins:
            return None, f"Fixed placement for {refdes!r} collides with another pin."
        if pin_holes & blockers or blocker_holes & pins:
            return None, f"Fixed placement for {refdes!r} collides with a body blocker."
        planned[refdes] = placed_component
        pin_holes = frozenset((*pin_holes, *pins))
        blocker_holes = frozenset((*blocker_holes, *blockers))
    return ((_routing_zero_score(), planned, pin_holes, blocker_holes), None)


def _routing_component_candidates(
    component,
    board,
    footprint_map,
    terminal_targets,
    preferred_column,
):
    candidates = []
    compatible_footprints = _footprints_for_component(component, footprint_map)
    if not compatible_footprints:
        _logger.error(
            "No footprint supports component refdes=%s kind=%s",
            component.refdes,
            component.kind,
        )
        return (), f"No footprint supports component kind {component.kind!r}."

    _logger.debug(
        "Routing component candidate search refdes=%s compatible_footprints=%s "
        "terminal_targets=%s preferred_column=%s",
        component.refdes,
        tuple(footprint.name for footprint in compatible_footprints),
        terminal_targets,
        preferred_column,
    )
    for footprint_index, footprint in enumerate(compatible_footprints):
        try:
            _validate_component_footprint(component, footprint)
        except ValueError as error:
            _logger.debug(
                "Skipping incompatible footprint refdes=%s footprint=%s: %s",
                component.refdes,
                footprint.name,
                error,
            )
            continue
        for rotation_index, rotation in enumerate(
            _preferred_footprint_rotations(footprint)
        ):
            base_origins = _routing_candidate_base_origins(
                component,
                footprint,
                rotation,
                terminal_targets,
                preferred_column,
            )
            for origin in _routing_shifted_origins(
                base_origins,
                board,
                footprint,
                rotation,
            ):
                placed_component = PlacedComponent(
                    refdes=component.refdes,
                    footprint_name=footprint.name,
                    origin=origin,
                    rotation=rotation,
                )
                pin_holes, blocker_holes = _routing_placement_holes(
                    component,
                    placed_component,
                    footprint,
                )
                if any(
                    not _hole_on_board(board, hole[0], hole[1])
                    for hole in (*pin_holes, *blocker_holes)
                ):
                    continue
                score = _routing_candidate_score(
                    component,
                    placed_component,
                    footprint,
                    terminal_targets,
                    preferred_column,
                    footprint_index,
                    rotation_index,
                )
                candidates.append((score, placed_component, pin_holes, blocker_holes))

    candidates = tuple(sorted(candidates, key=lambda item: item[0]))
    if not candidates:
        _logger.error(
            "No legal placement candidates refdes=%s board=%sx%s",
            component.refdes,
            board.width_pitches,
            board.height_pitches,
        )
        return (), (
            f"No legal placement candidates are available for {component.refdes!r} "
            f"on a {board.width_pitches}x{board.height_pitches} board."
        )
    _logger.debug(
        "Routing component candidates refdes=%s generated=%s kept=%s best_score=%s",
        component.refdes,
        len(candidates),
        min(len(candidates), _routing_candidate_limit()),
        candidates[0][0],
    )
    return candidates[: _routing_candidate_limit()], None


def _routing_candidate_base_origins(
    component,
    footprint,
    rotation,
    terminal_targets,
    preferred_column,
):
    origins = set()
    rotated_pins = {
        terminal_name: _rotate_grid_point(point, rotation)
        for terminal_name, point in footprint.pins.items()
    }
    for terminal in component.terminals:
        target = terminal_targets.get(terminal.name)
        rotated_pin = rotated_pins.get(terminal.name)
        if target is None or rotated_pin is None:
            continue
        origins.add((target[0] - rotated_pin[0], target[1] - rotated_pin[1]))

    if terminal_targets:
        target_rows = [hole[0] for hole in terminal_targets.values()]
        target_cols = [hole[1] for hole in terminal_targets.values()]
        pin_rows = [point[0] for point in rotated_pins.values()]
        pin_cols = [point[1] for point in rotated_pins.values()]
        origins.add(
            (
                round(
                    sum(target_rows) / len(target_rows) - sum(pin_rows) / len(pin_rows)
                ),
                round(
                    sum(target_cols) / len(target_cols) - sum(pin_cols) / len(pin_cols)
                ),
            )
        )
        origins.add(
            (min(target_rows) - min(pin_rows), preferred_column - min(pin_cols))
        )
        origins.add(
            (max(target_rows) - max(pin_rows), preferred_column - max(pin_cols))
        )

    if not origins:
        origins.add((0, preferred_column))
    return tuple(sorted(origins))


def _routing_shifted_origins(base_origins, board, footprint, rotation):
    rotated_points = tuple(
        _rotate_grid_point(point, rotation)
        for point in (*footprint.pins.values(), *footprint.blockers)
    )
    if not rotated_points:
        return ()
    min_row = min(point[0] for point in rotated_points)
    max_row = max(point[0] for point in rotated_points)
    min_col = min(point[1] for point in rotated_points)
    max_col = max(point[1] for point in rotated_points)
    row_low = -min_row
    row_high = board.height_pitches - 1 - max_row
    col_low = -min_col
    col_high = board.width_pitches - 1 - max_col
    origins = set()
    for row, col in base_origins:
        for row_offset in _routing_small_offsets():
            shifted_row = row + row_offset
            if shifted_row < row_low or shifted_row > row_high:
                continue
            for col_offset in _routing_column_offsets(board.width_pitches):
                shifted_col = col + col_offset
                if shifted_col < col_low or shifted_col > col_high:
                    continue
                origins.add((shifted_row, shifted_col))
    return tuple(sorted(origins))


def _routing_placement_holes(component, placed_component, footprint):
    pin_holes = frozenset(
        _absolute_footprint_point(
            placed_component.origin,
            placed_component.rotation,
            footprint.pins[terminal.name],
        )
        for terminal in component.terminals
    )
    blocker_holes = frozenset(
        _absolute_footprint_point(
            placed_component.origin,
            placed_component.rotation,
            point,
        )
        for point in footprint.blockers
    )
    return pin_holes, blocker_holes - pin_holes


def _routing_candidate_score(
    component,
    placed_component,
    footprint,
    terminal_targets,
    preferred_column,
    footprint_index,
    rotation_index,
):
    distances = []
    row_distances = []
    exact_matches = 0
    row_net_conflicts = 0
    pins_by_row = {}
    pin_cols = []
    pin_rows = []
    for pin, row, col in _component_route_pins(component, placed_component, footprint):
        target = terminal_targets.get(pin.terminal_name, (row, col))
        distance = abs(row - target[0]) + abs(col - target[1])
        distances.append(distance)
        row_distances.append(abs(row - target[0]))
        exact_matches += int(distance == 0)
        pins_by_row.setdefault(row, set()).add(pin.net_name)
        pin_rows.append(row)
        pin_cols.append(col)
    for net_names in pins_by_row.values():
        if len(net_names) > 1:
            row_net_conflicts += len(net_names) - 1
    center_col = round(sum(pin_cols) / len(pin_cols)) if pin_cols else preferred_column
    return (
        sum(row_distances),
        sum(distances),
        -exact_matches,
        row_net_conflicts,
        abs(center_col - preferred_column),
        max(pin_rows, default=0) - min(pin_rows, default=0),
        max(pin_cols, default=0) - min(pin_cols, default=0),
        footprint_index,
        rotation_index,
    )


def _preferred_footprint_rotations(footprint):
    preferred = (0, 180, 90, 270)
    return tuple(
        rotation
        for rotation in preferred
        if rotation in set(footprint.allowed_rotations)
    )


def _routing_component_cuts(component, placed_component, footprint):
    cuts = []
    pins_by_row = _component_route_pins_by_row(component, placed_component, footprint)
    for row, row_pins in pins_by_row.items():
        sorted_pins = sorted(row_pins, key=lambda item: item[2])
        pin_columns = {col for _pin, _row, col in sorted_pins}
        for left, right in zip(sorted_pins, sorted_pins[1:]):
            left_pin, _left_row, left_col = left
            right_pin, _right_row, right_col = right
            if left_pin.net_name == right_pin.net_name:
                continue
            cut_col = _first_cut_column_between(left_col, right_col, pin_columns)
            if cut_col is None:
                return (), (
                    f"Cannot isolate {placed_component.refdes!r} pins "
                    f"{left_pin.terminal_name!r} and {right_pin.terminal_name!r}; "
                    "there is no empty hole between them for a strip cut."
                )
            cuts.append(StripboardCut(row=row, col=cut_col))
    return tuple(cuts), None


def _routing_component_jumpers(component, placed_component, footprint, net_rows):
    jumpers = []
    for pin, row, col in _component_route_pins(component, placed_component, footprint):
        target = (net_rows[pin.net_name], col)
        if target == (row, col):
            continue
        jumpers.append(Jumper(start=(row, col), end=target, net_name=pin.net_name))
    return tuple(jumpers)


def _component_route_pins_by_row(component, placed_component, footprint):
    pins_by_row = {}
    for pin, row, col in _component_route_pins(component, placed_component, footprint):
        pins_by_row.setdefault(row, []).append((pin, row, col))
    return pins_by_row


def _component_route_pins(component, placed_component, footprint):
    for terminal in component.terminals:
        if terminal.name not in footprint.pins:
            continue
        row, col = _absolute_footprint_point(
            placed_component.origin,
            placed_component.rotation,
            footprint.pins[terminal.name],
        )
        yield (
            PlacedPin(
                refdes=component.refdes,
                terminal_name=terminal.name,
                net_name=terminal.net_name,
                row=row,
                col=col,
                footprint_name=footprint.name,
            ),
            row,
            col,
        )


def _routing_conflict_cuts(circuit, planned, footprint_map, fixed_cuts, connectors=()):
    cuts_by_hole = {(cut.row, cut.col): cut for cut in fixed_cuts}
    generated_count = 0
    pins_by_row = {}
    for connector in connectors:
        pin = _connector_pin(connector)
        pins_by_row.setdefault(pin.row, []).append((pin, pin.col))
    for component in circuit.components:
        placed_component = planned[component.refdes]
        footprint = footprint_map[placed_component.footprint_name]
        for pin, row, col in _component_route_pins(
            component, placed_component, footprint
        ):
            pins_by_row.setdefault(row, []).append((pin, col))

    for row, row_pins in pins_by_row.items():
        sorted_pins = sorted(row_pins, key=lambda item: item[1])
        pin_columns = {col for _pin, col in sorted_pins}
        for left, right in zip(sorted_pins, sorted_pins[1:]):
            left_pin, left_col = left
            right_pin, right_col = right
            if left_pin.net_name == right_pin.net_name:
                continue
            if _routing_pins_separated_by_cut(row, left_col, right_col, cuts_by_hole):
                continue
            cut_col = _first_cut_column_between(left_col, right_col, pin_columns)
            if cut_col is None:
                _logger.debug(
                    "Cannot isolate row=%s left=%s.%s col=%s net=%s right=%s.%s "
                    "col=%s net=%s: no empty cut hole",
                    row,
                    left_pin.refdes,
                    left_pin.terminal_name,
                    left_col,
                    left_pin.net_name,
                    right_pin.refdes,
                    right_pin.terminal_name,
                    right_col,
                    right_pin.net_name,
                )
                return (), (
                    f"Cannot isolate row {row} pins {left_pin.refdes}."
                    f"{left_pin.terminal_name} and {right_pin.refdes}."
                    f"{right_pin.terminal_name}; there is no empty cut hole "
                    "between them."
                )
            cuts_by_hole[(row, cut_col)] = StripboardCut(row=row, col=cut_col)
            generated_count += 1
            _logger.debug(
                "Inserted conflict cut row=%s col=%s between %s.%s net=%s and "
                "%s.%s net=%s",
                row,
                cut_col,
                left_pin.refdes,
                left_pin.terminal_name,
                left_pin.net_name,
                right_pin.refdes,
                right_pin.terminal_name,
                right_pin.net_name,
            )
    if generated_count:
        _logger.debug(
            "Generated routing conflict cuts count=%s total_cuts=%s",
            generated_count,
            len(cuts_by_hole),
        )
    return tuple(cuts_by_hole[key] for key in sorted(cuts_by_hole)), None


def _routing_pins_separated_by_cut(row, left_col, right_col, cuts_by_hole):
    return any(
        cut_row == row and left_col < cut_col < right_col
        for cut_row, cut_col in cuts_by_hole
    )


def _routing_report_has_unfixable_errors(report):
    return any(issue.code != "open_circuit" for issue in report.errors)


def _routing_connectivity_jumpers(layout, circuit, physical_netlist):
    if physical_netlist is None:
        return ()
    jumpers = []
    reserved_holes = _reserved_jumper_endpoint_holes(layout, circuit)
    conductors_by_net = {}
    for conductor in physical_netlist.conductors:
        for net_name in conductor.net_names:
            if len(conductor.net_names) == 1:
                conductors_by_net.setdefault(net_name, []).append(conductor)

    split_nets = {
        net_name: conductors
        for net_name, conductors in conductors_by_net.items()
        if len(conductors) >= 2
    }
    if split_nets:
        _logger.debug(
            "Routing connectivity jumpers split_nets=%s reserved_holes=%s",
            {net_name: len(conductors) for net_name, conductors in split_nets.items()},
            len(reserved_holes),
        )
    for net_name, conductors in sorted(conductors_by_net.items()):
        if len(conductors) < 2:
            continue
        anchor = max(
            conductors,
            key=lambda conductor: (
                len(_conductor_pins_for_net(conductor, net_name)),
                -conductor.index,
            ),
        )
        connected = [anchor]
        remaining = [
            conductor for conductor in conductors if conductor.index != anchor.index
        ]
        while remaining:
            start, end, conductor = _shortest_conductor_empty_hole_link(
                connected,
                remaining,
                net_name,
                reserved_holes,
            )
            jumpers.append(Jumper(start=start, end=end, net_name=net_name))
            reserved_holes.update((start, end))
            _logger.debug(
                "Selected jumper endpoints net=%s start=%s end=%s "
                "conductor=%s connected=%s",
                net_name,
                start,
                end,
                conductor.index,
                tuple(connected_conductor.index for connected_conductor in connected),
            )
            connected.append(conductor)
            remaining = [
                remaining_conductor
                for remaining_conductor in remaining
                if remaining_conductor.index != conductor.index
            ]
    if jumpers:
        _logger.debug("Routed connectivity jumpers count=%s", len(jumpers))
    return tuple(jumpers)


def _reserved_jumper_endpoint_holes(layout, circuit):
    return (
        {pin.hole for pin in placed_component_pins(layout, circuit)}
        | {connector.hole for connector in layout.connectors}
        | {(cut.row, cut.col) for cut in layout.cuts}
        | {(blocker.row, blocker.col) for blocker in layout.blockers}
        | {hole for jumper in layout.jumpers for hole in (jumper.start, jumper.end)}
    )


def _conductor_pins_for_net(conductor, net_name):
    return tuple(pin for pin in conductor.pins if pin.net_name == net_name)


def _shortest_conductor_empty_hole_link(
    connected,
    remaining,
    net_name,
    reserved_holes,
):
    candidates = []
    for conductor in remaining:
        conductor_holes = _available_conductor_jumper_holes(conductor, reserved_holes)
        if not conductor_holes:
            continue
        for connected_conductor in connected:
            connected_holes = _available_conductor_jumper_holes(
                connected_conductor,
                reserved_holes,
            )
            if not connected_holes:
                continue
            for start in conductor_holes:
                for end in connected_holes:
                    candidates.append(
                        (
                            _hole_distance(start, end),
                            conductor.index,
                            connected_conductor.index,
                            start,
                            end,
                            conductor,
                        )
                    )
    if not candidates:
        _logger.debug(
            "Cannot route jumper net=%s: no empty endpoint holes on disconnected "
            "conductors",
            net_name,
        )
        raise ValueError(
            f"Cannot route jumper for net {net_name!r}; no empty jumper endpoint "
            "holes are available on the disconnected conductors."
        )
    _distance, _from_index, _to_index, start, end, conductor = min(candidates)
    return start, end, conductor


def _available_conductor_jumper_holes(conductor, reserved_holes):
    return tuple(hole for hole in conductor.holes if hole not in reserved_holes)


def _routing_layout_score(layout, report, placement_score, circuit=None):
    return (
        int(not report.ok),
        len(report.errors),
        len(layout.jumpers),
        _layout_pre_jumper_fragment_count(layout, circuit) if report.ok else 0,
        len(layout.cuts),
        _layout_used_height(layout),
        _layout_jumper_length(layout),
        *placement_score,
        _layout_used_width(layout),
    )


def _routing_optimization_shortlist(
    verified_candidate_entries,
    *,
    current_best_jumper_count=None,
):
    if not verified_candidate_entries:
        return ()

    selected_indexes = set()
    ranked_indexes = tuple(
        index
        for index, _entry in sorted(
            enumerate(verified_candidate_entries),
            key=lambda item: item[1][0],
        )
    )
    selected_indexes.update(ranked_indexes[: _routing_optimization_candidate_limit()])
    if current_best_jumper_count is not None:
        selected_indexes.update(
            index
            for index, (_score, layout, _report, _placement_score) in enumerate(
                verified_candidate_entries
            )
            if len(layout.jumpers) < current_best_jumper_count
        )
    return tuple(
        index
        for index in range(len(verified_candidate_entries))
        if index in selected_indexes
    )


def _layout_pre_jumper_fragment_count(layout, circuit):
    if circuit is None or not layout.jumpers:
        return 0
    jumperless_layout = PhysicalLayout(
        board=layout.board,
        placed_components=layout.placed_components,
        cuts=layout.cuts,
        jumpers=(),
        connectors=layout.connectors,
        blockers=layout.blockers,
        annotations=layout.annotations,
        footprints=layout.footprints,
    )
    physical_netlist = _extract_physical_netlist_unchecked(jumperless_layout, circuit)
    conductor_indexes_by_net = {}
    for conductor in physical_netlist.conductors:
        for pin in conductor.pins:
            conductor_indexes_by_net.setdefault(pin.net_name, set()).add(
                conductor.index
            )
    return sum(
        max(0, len(conductor_indexes) - 1)
        for conductor_indexes in conductor_indexes_by_net.values()
    )


def _layout_jumper_length(layout):
    return sum(_hole_distance(jumper.start, jumper.end) for jumper in layout.jumpers)


def _hole_distance(left, right):
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _routing_zero_score():
    return (0, 0, 0, 0, 0, 0, 0, 0, 0)


def _add_routing_scores(left, right):
    return tuple(
        left_value + right_value for left_value, right_value in zip(left, right)
    )


def _routing_beam_width():
    return 256


def _routing_candidate_limit():
    return 192


def _routing_optimization_candidate_limit():
    return 12


def _routing_shake_order_limit():
    return 4


def _optimization_cycle_limit():
    return 3


def _routing_shake_jumper_threshold():
    return 2


def _routing_small_offsets():
    return (0, -1, 1, -2, 2)


def _routing_column_offsets(width):
    offsets = [0]
    for distance in range(1, max(1, width)):
        offsets.extend((-distance, distance))
    return tuple(offsets)


def _absolute_footprint_holes(placed_component, footprint):
    return tuple(
        _absolute_footprint_point(
            placed_component.origin,
            placed_component.rotation,
            point,
        )
        for point in footprint.pins.values()
    )


def _first_cut_column_between(left_col, right_col, pin_columns):
    candidates = tuple(
        cut_col
        for cut_col in range(left_col + 1, right_col)
        if cut_col not in pin_columns
    )
    if not candidates:
        return None
    middle = (left_col + right_col) / 2
    return min(candidates, key=lambda cut_col: (abs(cut_col - middle), cut_col))


def _dedupe_cuts(cuts):
    cuts_by_hole = {}
    for cut in cuts:
        cuts_by_hole.setdefault((cut.row, cut.col), cut)
    return tuple(cuts_by_hole[key] for key in sorted(cuts_by_hole))


def _dedupe_jumpers(jumpers):
    jumpers_by_key = {}
    for jumper in jumpers:
        key = (jumper.net_name, jumper.start, jumper.end)
        reverse_key = (jumper.net_name, jumper.end, jumper.start)
        if reverse_key in jumpers_by_key:
            continue
        jumpers_by_key.setdefault(key, jumper)
    return tuple(jumpers_by_key[key] for key in sorted(jumpers_by_key))


def _routing_failure_report(message, code="routing_failed"):
    return PhysicalVerificationReport(
        issues=(
            PhysicalIssue(
                ERROR,
                code,
                str(message),
            ),
        ),
        physical_netlist=None,
    )


def _layout_used_height(layout):
    rows = [
        *[pin.row for pin in _layout_score_pins(layout)],
        *[connector.row for connector in layout.connectors],
        *[cut.row for cut in layout.cuts],
        *[hole[0] for jumper in layout.jumpers for hole in (jumper.start, jumper.end)],
        *[blocker.row for blocker in layout.blockers],
    ]
    return 0 if not rows else max(rows) + 1


def _layout_used_width(layout):
    cols = [
        *[pin.col for pin in _layout_score_pins(layout)],
        *[connector.col for connector in layout.connectors],
        *[cut.col for cut in layout.cuts],
        *[hole[1] for jumper in layout.jumpers for hole in (jumper.start, jumper.end)],
        *[blocker.col for blocker in layout.blockers],
    ]
    return 0 if not cols else max(cols) + 1


def _layout_score_pins(layout):
    footprint_map = _footprints_by_name(layout.footprints)
    pins = []
    for placed_component in layout.placed_components:
        footprint = footprint_map[placed_component.footprint_name]
        for terminal_name, point in footprint.pins.items():
            row, col = _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                point,
            )
            pins.append(
                PlacedPin(
                    refdes=placed_component.refdes,
                    terminal_name=terminal_name,
                    net_name="",
                    row=row,
                    col=col,
                    footprint_name=footprint.name,
                )
            )
    return tuple(pins)


def _physical_layout_drc_issues(layout, circuit):
    issues = []
    if layout.board.strip_direction is not Direction.HORIZONTAL:
        issues.append(
            PhysicalIssue(
                ERROR,
                "unsupported_strip_direction",
                "Only horizontal stripboards are supported for verification.",
            )
        )

    footprint_map = _safe_footprints_by_name(layout.footprints, issues)
    pins, pin_issues, generated_blockers = _layout_pins_and_issues(
        layout,
        circuit,
        footprint_map,
    )
    issues.extend(pin_issues)
    connector_pins, connector_issues = _layout_connectors_and_issues(layout, circuit)
    issues.extend(connector_issues)
    physical_pins = (*pins, *connector_pins)

    blockers = _valid_blockers(
        (*layout.blockers, *generated_blockers),
        layout.board,
        issues,
    )
    cut_holes = _valid_cut_holes(layout, issues)
    _check_jumpers(layout, circuit, cut_holes, physical_pins, blockers, issues)
    _check_pin_hole_collisions(physical_pins, issues)
    _check_pins_on_cuts(physical_pins, cut_holes, issues)
    _check_blocker_pin_collisions(blockers, physical_pins, issues)
    return tuple(issues)


def _safe_footprints_by_name(footprints, issues):
    try:
        return _footprints_by_name(footprints)
    except (TypeError, ValueError) as error:
        issues.append(
            PhysicalIssue(
                ERROR,
                "invalid_footprint_library",
                str(error),
            )
        )
        return {}


def _layout_pins_and_issues(layout, circuit, footprint_map):
    issues = []
    pins = []
    generated_blockers = []
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    placed_refdeses = set()

    for placed_component in layout.placed_components:
        if not isinstance(placed_component, PlacedComponent):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_placement",
                    (
                        "Layout placement is "
                        f"{type(placed_component).__name__}, not PlacedComponent."
                    ),
                )
            )
            continue

        if placed_component.refdes in placed_refdeses:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "duplicate_component_placement",
                    f"Component {placed_component.refdes!r} is placed more than once.",
                    subject=placed_component.refdes,
                )
            )
        placed_refdeses.add(placed_component.refdes)

        component = components_by_refdes.get(placed_component.refdes)
        if component is None:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "unknown_component_placement",
                    f"Layout places unknown component {placed_component.refdes!r}.",
                    subject=placed_component.refdes,
                )
            )
            continue

        footprint = footprint_map.get(placed_component.footprint_name)
        if footprint is None:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "unknown_footprint",
                    (
                        f"Component {placed_component.refdes!r} uses unknown "
                        f"footprint {placed_component.footprint_name!r}."
                    ),
                    subject=placed_component.refdes,
                )
            )
            continue

        _check_component_footprint_assignment(component, footprint, issues)
        if placed_component.rotation not in footprint.allowed_rotations:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_footprint_rotation",
                    (
                        f"Component {placed_component.refdes!r} uses rotation "
                        f"{placed_component.rotation}, but footprint "
                        f"{footprint.name!r} allows {footprint.allowed_rotations}."
                    ),
                    subject=placed_component.refdes,
                )
            )

        for terminal in component.terminals:
            if terminal.name not in footprint.pins:
                continue
            row, col = _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                footprint.pins[terminal.name],
            )
            pin = PlacedPin(
                refdes=component.refdes,
                terminal_name=terminal.name,
                net_name=terminal.net_name,
                row=row,
                col=col,
                footprint_name=footprint.name,
            )
            pins.append(pin)
            if not _hole_on_board(layout.board, row, col):
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "component_outside_board",
                        (
                            f"Component pin {pin.refdes}.{pin.terminal_name} "
                            f"at {pin.hole} is outside the board."
                        ),
                        subject=pin.refdes,
                        holes=(pin.hole,),
                    )
                )

        pin_holes = {
            _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                point,
            )
            for point in footprint.pins.values()
        }
        for point in footprint.blockers:
            row, col = _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                point,
            )
            if (row, col) in pin_holes:
                continue
            generated_blockers.append(
                StripboardBlocker(
                    row=row,
                    col=col,
                    element_name=placed_component.refdes,
                )
            )
            if not _hole_on_board(layout.board, row, col):
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "component_outside_board",
                        (
                            f"Component body blocker for {placed_component.refdes!r} "
                            f"at {(row, col)} is outside the board."
                        ),
                        subject=placed_component.refdes,
                        holes=((row, col),),
                    )
                )

    missing = tuple(sorted(set(components_by_refdes) - placed_refdeses))
    for refdes in missing:
        issues.append(
            PhysicalIssue(
                ERROR,
                "missing_component_placement",
                f"Component {refdes!r} has no physical placement.",
                subject=refdes,
            )
        )

    return tuple(pins), tuple(issues), tuple(generated_blockers)


def _layout_connectors_and_issues(layout, circuit):
    issues = []
    pins = []
    net_names = {net.name for net in circuit.nets}
    seen_names = set()
    for connector in layout.connectors:
        if not isinstance(connector, PlacedConnector):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_connector",
                    (
                        "Layout connector is "
                        f"{type(connector).__name__}, not PlacedConnector."
                    ),
                )
            )
            continue
        if connector.name in seen_names:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "duplicate_connector",
                    f"Connector {connector.name!r} is placed more than once.",
                    subject=connector.name,
                    holes=(connector.hole,),
                )
            )
        seen_names.add(connector.name)
        if connector.net_name not in net_names:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "unknown_connector_net",
                    (
                        f"Connector {connector.name!r} uses unknown net "
                        f"{connector.net_name!r}."
                    ),
                    subject=connector.name,
                    holes=(connector.hole,),
                )
            )
        pins.append(_connector_pin(connector))
        if not _hole_on_board(layout.board, connector.row, connector.col):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "connector_outside_board",
                    (
                        f"Connector {connector.name!r} at {connector.hole} "
                        "is outside the board."
                    ),
                    subject=connector.name,
                    holes=(connector.hole,),
                )
            )
    return tuple(pins), tuple(issues)


def _connector_pin(connector):
    return PlacedPin(
        refdes=connector.name,
        terminal_name="pin",
        net_name=connector.net_name,
        row=connector.row,
        col=connector.col,
        footprint_name=connector.kind,
    )


def _check_component_footprint_assignment(component, footprint, issues):
    if component.kind not in footprint.component_kinds:
        issues.append(
            PhysicalIssue(
                ERROR,
                "footprint_kind_mismatch",
                (
                    f"Footprint {footprint.name!r} does not support component "
                    f"kind {component.kind!r} for {component.refdes!r}."
                ),
                subject=component.refdes,
            )
        )

    component_terminals = {terminal.name for terminal in component.terminals}
    footprint_terminals = set(footprint.pins)
    for terminal_name in sorted(component_terminals - footprint_terminals):
        issues.append(
            PhysicalIssue(
                ERROR,
                "unassigned_footprint_terminal",
                (
                    f"Component {component.refdes!r} terminal {terminal_name!r} "
                    f"is not assigned by footprint {footprint.name!r}."
                ),
                subject=component.refdes,
            )
        )
    for terminal_name in sorted(footprint_terminals - component_terminals):
        issues.append(
            PhysicalIssue(
                ERROR,
                "unknown_footprint_terminal",
                (
                    f"Footprint {footprint.name!r} assigns unknown terminal "
                    f"{terminal_name!r} for component {component.refdes!r}."
                ),
                subject=component.refdes,
            )
        )


def _valid_cut_holes(layout, issues):
    cut_holes = set()
    for cut in layout.cuts:
        if not isinstance(cut, StripboardCut):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_cut",
                    f"Layout cut is {type(cut).__name__}, not StripboardCut.",
                )
            )
            continue
        if not _hole_on_board(layout.board, cut.row, cut.col):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "cut_outside_board",
                    f"Cut at {(cut.row, cut.col)} is outside the board.",
                    holes=((cut.row, cut.col),),
                )
            )
            continue
        cut_holes.add((cut.row, cut.col))
    return cut_holes


def _check_jumpers(layout, circuit, cut_holes, pins, blockers, issues):
    net_names = {net.name for net in circuit.nets}
    pin_holes = {pin.hole for pin in pins}
    blocker_holes = {(blocker.row, blocker.col) for blocker in blockers}
    for jumper in layout.jumpers:
        if not isinstance(jumper, Jumper):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_jumper",
                    f"Layout jumper is {type(jumper).__name__}, not Jumper.",
                )
            )
            continue
        if jumper.net_name not in net_names:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "unknown_jumper_net",
                    f"Jumper uses unknown net {jumper.net_name!r}.",
                    subject=jumper.net_name,
                    holes=(jumper.start, jumper.end),
                )
            )
        for label, hole in (("start", jumper.start), ("end", jumper.end)):
            if not _hole_on_board(layout.board, *hole):
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "jumper_outside_board",
                        f"Jumper {label} endpoint {hole} is outside the board.",
                        subject=jumper.net_name,
                        holes=(hole,),
                    )
                )
                continue
            if hole in pin_holes:
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "jumper_on_component_pin",
                        (
                            f"Jumper {label} endpoint {hole} for net "
                            f"{jumper.net_name!r} shares a component pin hole."
                        ),
                        subject=jumper.net_name,
                        holes=(hole,),
                    )
                )
            if hole in blocker_holes:
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "jumper_on_blocker",
                        (
                            f"Jumper {label} endpoint {hole} for net "
                            f"{jumper.net_name!r} shares a component body hole."
                        ),
                        subject=jumper.net_name,
                        holes=(hole,),
                    )
                )
            if hole in cut_holes:
                issues.append(
                    PhysicalIssue(
                        ERROR,
                        "jumper_on_cut",
                        (
                            f"Jumper {label} endpoint {hole} for net "
                            f"{jumper.net_name!r} shares a strip cut hole."
                        ),
                        subject=jumper.net_name,
                        holes=(hole,),
                    )
                )


def _valid_blockers(blockers, board, issues):
    valid = []
    for blocker in blockers:
        if not isinstance(blocker, StripboardBlocker):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "invalid_blocker",
                    f"Layout blocker is {type(blocker).__name__}, not StripboardBlocker.",
                )
            )
            continue
        if not _hole_on_board(board, blocker.row, blocker.col):
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "blocker_outside_board",
                    (
                        f"Blocker for {blocker.element_name!r} at "
                        f"{(blocker.row, blocker.col)} is outside the board."
                    ),
                    subject=blocker.element_name,
                    holes=((blocker.row, blocker.col),),
                )
            )
            continue
        valid.append(blocker)
    return tuple(valid)


def _check_pin_hole_collisions(pins, issues):
    pins_by_hole = {}
    for pin in pins:
        pins_by_hole.setdefault(pin.hole, []).append(pin)
    for hole, colliding_pins in sorted(pins_by_hole.items()):
        if len(colliding_pins) < 2:
            continue
        pin_names = tuple(
            f"{pin.refdes}.{pin.terminal_name}"
            for pin in sorted(
                colliding_pins,
                key=lambda item: (item.refdes, item.terminal_name),
            )
        )
        issues.append(
            PhysicalIssue(
                ERROR,
                "pin_hole_collision",
                f"Multiple component pins share hole {hole}: {pin_names}.",
                holes=(hole,),
            )
        )


def _check_pins_on_cuts(pins, cut_holes, issues):
    for pin in pins:
        if pin.hole not in cut_holes:
            continue
        issues.append(
            PhysicalIssue(
                ERROR,
                "pin_on_cut",
                f"Component pin {pin.refdes}.{pin.terminal_name} is on cut hole {pin.hole}.",
                subject=pin.refdes,
                holes=(pin.hole,),
            )
        )


def _check_blocker_pin_collisions(blockers, pins, issues):
    pins_by_hole = {}
    for pin in pins:
        pins_by_hole.setdefault(pin.hole, []).append(pin)
    seen = set()
    for blocker in blockers:
        hole = (blocker.row, blocker.col)
        for pin in pins_by_hole.get(hole, ()):
            key = (blocker.element_name, pin.refdes, pin.terminal_name, hole)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "blocker_pin_collision",
                    (
                        f"Blocker for {blocker.element_name!r} collides with "
                        f"pin {pin.refdes}.{pin.terminal_name} at {hole}."
                    ),
                    subject=blocker.element_name,
                    holes=(hole,),
                )
            )


def _extract_physical_netlist_unchecked(layout, circuit):
    cut_holes = {(cut.row, cut.col) for cut in layout.cuts}
    graph = _UnionFind(_board_holes(layout.board))

    for row in range(layout.board.height_pitches):
        for col in range(layout.board.width_pitches - 1):
            left = (row, col)
            right = (row, col + 1)
            if left in cut_holes or right in cut_holes:
                continue
            graph.union(left, right)

    for jumper in layout.jumpers:
        graph.union(jumper.start, jumper.end)

    pins_by_root = {}
    for pin in _layout_physical_pins(layout, circuit):
        root = graph.find(pin.hole)
        pins_by_root.setdefault(root, []).append(pin)

    holes_by_root = {}
    for hole in _board_holes(layout.board):
        holes_by_root.setdefault(graph.find(hole), []).append(hole)

    conductors = []
    for index, (_root, holes) in enumerate(
        sorted(
            holes_by_root.items(),
            key=lambda item: (min(item[1]), len(item[1])),
        )
    ):
        sorted_holes = tuple(sorted(holes))
        pins = tuple(
            sorted(
                pins_by_root.get(_root, ()),
                key=lambda pin: (pin.refdes, pin.terminal_name),
            )
        )
        net_names = tuple(sorted({pin.net_name for pin in pins}))
        conductors.append(
            PhysicalConductor(
                index=index,
                holes=sorted_holes,
                pins=pins,
                net_names=net_names,
            )
        )
    return PhysicalNetlist(
        board=layout.board,
        conductors=tuple(conductors),
    )


def _layout_physical_pins(layout, circuit):
    return (
        *placed_component_pins(layout, circuit),
        *(_connector_pin(c) for c in layout.connectors),
    )


def _physical_connectivity_issues(physical_netlist):
    issues = []
    net_conductors = {}
    for conductor in physical_netlist.conductors:
        if len(conductor.net_names) > 1:
            issues.append(
                PhysicalIssue(
                    ERROR,
                    "short_circuit",
                    (
                        f"Physical conductor {conductor.index} contains multiple "
                        f"semantic nets: {conductor.net_names}."
                    ),
                    subject=str(conductor.index),
                    holes=conductor.holes,
                )
            )
        for net_name in conductor.net_names:
            net_conductors.setdefault(net_name, []).append(conductor)

    for net_name, conductors in sorted(net_conductors.items()):
        if len(conductors) < 2:
            continue
        issues.append(
            PhysicalIssue(
                ERROR,
                "open_circuit",
                (
                    f"Semantic net {net_name!r} appears in "
                    f"{len(conductors)} disconnected physical conductors."
                ),
                subject=net_name,
                holes=tuple(
                    hole for conductor in conductors for hole in conductor.holes
                ),
            )
        )
    return tuple(issues)


def _board_holes(board):
    return tuple(
        (row, col)
        for row in range(board.height_pitches)
        for col in range(board.width_pitches)
    )


def _hole_on_board(board, row, col):
    return 0 <= row < board.height_pitches and 0 <= col < board.width_pitches


def _issue_summary(issues):
    return "\n".join(
        f"{issue.severity.upper()} {issue.code}: {issue.message}" for issue in issues
    )


def _normalize_placements(placements, components_by_refdes, footprint_map):
    if not isinstance(placements, Mapping):
        raise TypeError("placements must be a mapping of refdes to placement data.")
    if set(placements) != set(components_by_refdes):
        missing = tuple(sorted(set(components_by_refdes) - set(placements)))
        unexpected = tuple(sorted(set(placements) - set(components_by_refdes)))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unknown {unexpected}")
        raise ValueError(
            f"Manual placements must cover the circuit components: {', '.join(details)}."
        )

    placed_components = []
    for refdes, placement in placements.items():
        component = components_by_refdes[refdes]
        placed_component = _coerce_placement(
            refdes, component, placement, footprint_map
        )
        footprint = _require_footprint(footprint_map, placed_component.footprint_name)
        _validate_component_footprint(component, footprint)
        if placed_component.rotation not in footprint.allowed_rotations:
            raise ValueError(
                f"Placement for {refdes!r} uses rotation {placed_component.rotation}, "
                f"but footprint {footprint.name!r} allows {footprint.allowed_rotations}."
            )
        placed_components.append(placed_component)
    return tuple(sorted(placed_components, key=lambda item: item.refdes))


def _coerce_placement(refdes, component, placement, footprint_map):
    if isinstance(placement, PlacedComponent):
        if placement.refdes != refdes:
            raise ValueError(
                f"Placement key {refdes!r} does not match PlacedComponent "
                f"refdes {placement.refdes!r}."
            )
        return placement

    if isinstance(placement, Mapping):
        footprint_name = placement.get("footprint_name", placement.get("footprint"))
        if footprint_name is None:
            footprint_name = footprint_for_component(component, footprint_map).name
        return PlacedComponent(
            refdes=refdes,
            footprint_name=footprint_name,
            origin=placement["origin"],
            rotation=placement.get("rotation", 0),
        )

    if isinstance(placement, tuple):
        if len(placement) == 2:
            origin, rotation = placement
            footprint_name = footprint_for_component(component, footprint_map).name
        elif len(placement) == 3:
            footprint_name, origin, rotation = placement
        else:
            raise TypeError(
                "Placement tuples must be (origin, rotation) or "
                "(footprint_name, origin, rotation)."
            )
        return PlacedComponent(
            refdes=refdes,
            footprint_name=footprint_name,
            origin=origin,
            rotation=rotation,
        )

    raise TypeError(
        "Placement values must be PlacedComponent objects, mappings, or tuples."
    )


def _normalize_cuts(cuts):
    normalized = []
    for cut in cuts:
        if isinstance(cut, StripboardCut):
            normalized.append(cut)
            continue
        row, col = _coerce_grid_point(cut, "cut")
        normalized.append(StripboardCut(row=row, col=col))
    return tuple(sorted(normalized, key=lambda item: (item.row, item.col)))


def _normalize_jumpers(jumpers):
    normalized = []
    for jumper in jumpers:
        if isinstance(jumper, Jumper):
            normalized.append(jumper)
            continue
        if not isinstance(jumper, tuple) or len(jumper) != 3:
            raise TypeError("Jumpers must be Jumper objects or (start, end, net_name).")
        normalized.append(Jumper(start=jumper[0], end=jumper[1], net_name=jumper[2]))
    return tuple(
        sorted(normalized, key=lambda item: (item.net_name, item.start, item.end))
    )


def _normalize_connectors(connectors):
    normalized = []
    for connector in connectors:
        if isinstance(connector, PlacedConnector):
            normalized.append(connector)
            continue
        if not isinstance(connector, tuple) or len(connector) not in (3, 4, 5):
            raise TypeError(
                "Connectors must be PlacedConnector objects or "
                "(name, net_name, hole[, label[, kind]])."
            )
        label = connector[3] if len(connector) >= 4 else None
        kind = connector[4] if len(connector) >= 5 else "nail"
        normalized.append(
            PlacedConnector(
                name=connector[0],
                net_name=connector[1],
                hole=connector[2],
                label=label,
                kind=kind,
            )
        )
    return tuple(sorted(normalized, key=lambda item: item.name))


def _normalize_blockers(blockers):
    normalized = []
    for blocker in blockers:
        if isinstance(blocker, StripboardBlocker):
            normalized.append(blocker)
            continue
        if not isinstance(blocker, tuple) or len(blocker) != 3:
            raise TypeError(
                "Blockers must be StripboardBlocker objects or "
                "(row, col, element_name)."
            )
        row, col = _coerce_grid_point(blocker[:2], "blocker")
        normalized.append(
            StripboardBlocker(row=row, col=col, element_name=str(blocker[2]))
        )
    return tuple(
        sorted(normalized, key=lambda item: (item.row, item.col, item.element_name))
    )


def _generated_component_blockers(placed_components, footprint_map):
    blockers = []
    for placed_component in placed_components:
        footprint = _require_footprint(footprint_map, placed_component.footprint_name)
        pin_holes = {
            _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                point,
            )
            for point in footprint.pins.values()
        }
        for point in footprint.blockers:
            row, col = _absolute_footprint_point(
                placed_component.origin,
                placed_component.rotation,
                point,
            )
            if (row, col) in pin_holes:
                continue
            blockers.append(
                StripboardBlocker(
                    row=row,
                    col=col,
                    element_name=placed_component.refdes,
                )
            )
    return tuple(blockers)


def _validate_layout_geometry(layout, circuit, footprint_map):
    cut_holes = {(cut.row, cut.col) for cut in layout.cuts}
    for row, col in cut_holes:
        _require_hole_on_board(layout.board, row, col, "cut")

    net_names = {net.name for net in circuit.nets}
    for jumper in layout.jumpers:
        if jumper.net_name not in net_names:
            raise ValueError(f"Jumper uses unknown net {jumper.net_name!r}.")
        _require_hole_on_board(layout.board, *jumper.start, "jumper start")
        _require_hole_on_board(layout.board, *jumper.end, "jumper end")

    pin_holes = {}
    for pin in placed_component_pins(layout, circuit):
        _require_hole_on_board(layout.board, pin.row, pin.col, "component pin")
        if pin.hole in cut_holes:
            raise ValueError(
                f"Component pin {pin.refdes}.{pin.terminal_name} is on cut hole "
                f"{pin.hole}."
            )
        if pin.hole in pin_holes:
            other = pin_holes[pin.hole]
            raise ValueError(
                f"Multiple component pins share hole {pin.hole}: "
                f"{other.refdes}.{other.terminal_name} and "
                f"{pin.refdes}.{pin.terminal_name}."
            )
        pin_holes[pin.hole] = pin

    connector_names = set()
    for connector in layout.connectors:
        if connector.name in connector_names:
            raise ValueError(f"Connector {connector.name!r} is placed more than once.")
        connector_names.add(connector.name)
        if connector.net_name not in net_names:
            raise ValueError(
                f"Connector {connector.name!r} uses unknown net "
                f"{connector.net_name!r}."
            )
        _require_hole_on_board(layout.board, *connector.hole, "connector")
        connector_pin = _connector_pin(connector)
        if connector.hole in cut_holes:
            raise ValueError(
                f"Connector {connector.name!r} is on cut hole {connector.hole}."
            )
        if connector.hole in pin_holes:
            other = pin_holes[connector.hole]
            raise ValueError(
                f"Multiple physical terminals share hole {connector.hole}: "
                f"{other.refdes}.{other.terminal_name} and connector "
                f"{connector.name}."
            )
        pin_holes[connector.hole] = connector_pin

    for blocker in layout.blockers:
        _require_hole_on_board(layout.board, blocker.row, blocker.col, "blocker")
        pin = pin_holes.get((blocker.row, blocker.col))
        if pin is not None:
            raise ValueError(
                f"Blocker for {blocker.element_name!r} collides with pin "
                f"{pin.refdes}.{pin.terminal_name} at {(blocker.row, blocker.col)}."
            )

    blocker_holes = {(blocker.row, blocker.col) for blocker in layout.blockers}
    for jumper in layout.jumpers:
        for label, hole in (("start", jumper.start), ("end", jumper.end)):
            if hole in pin_holes:
                pin = pin_holes[hole]
                raise ValueError(
                    f"Jumper {label} endpoint {hole} shares component pin "
                    f"{pin.refdes}.{pin.terminal_name}."
                )
            if hole in blocker_holes:
                raise ValueError(
                    f"Jumper {label} endpoint {hole} shares a component body blocker."
                )
            if hole in cut_holes:
                raise ValueError(
                    f"Jumper {label} endpoint {hole} shares a strip cut hole."
                )

    for placed_component in layout.placed_components:
        _require_footprint(footprint_map, placed_component.footprint_name)


def _validate_layout_detail(detail):
    detail = str(detail)
    if detail not in {"assembly", "annotated"}:
        raise ValueError("Stripboard layout detail must be 'assembly' or 'annotated'.")
    return detail


def _validate_component_label_mode(component_labels):
    component_labels = str(component_labels)
    if component_labels not in {"refdes", "refdes_value"}:
        raise ValueError(
            "Stripboard component_labels must be 'refdes' or 'refdes_value'."
        )
    return component_labels


def _render_stripboard_layout_svg(
    layout, circuit, path, scale, detail, component_labels
):
    scale = dsl._validate_render_scale(scale)
    width, height = dsl._stripboard_size(layout.board)
    pins = placed_component_pins(layout, circuit)
    labels = _placed_layout_labels(layout, circuit, pins, detail)
    label_margin = _layout_label_margin(labels)
    width_px = (width + label_margin) * scale
    height_px = height * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px:.0f}" height="{height_px:.0f}" '
            f'viewBox="{-label_margin:.3f} 0 '
            f'{width + label_margin:.3f} {height:.3f}">'
        ),
        "  <title>Manual Stripboard Layout</title>",
        (
            f'  <rect class="board" x="0" y="0" width="{width:.3f}" '
            f'height="{height:.3f}" fill="{dsl.STRIPBOARD_BOARD_FILL}" '
            f'stroke="{dsl.STRIPBOARD_BOARD_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        ),
    ]
    _append_svg_board(lines, layout.board)
    _append_svg_layout_cuts(lines, layout.cuts)
    _append_svg_layout_jumpers(lines, layout.jumpers)
    overlays = _layout_component_overlays(layout, circuit, pins, component_labels)
    _append_svg_layout_component_segments(lines, overlays)
    if detail == "assembly" and component_labels == "refdes":
        _append_svg_layout_component_bodies(lines, overlays)
    if detail == "annotated":
        _append_svg_layout_blockers(lines, layout.blockers)
    _append_svg_layout_pins(lines, pins)
    _append_svg_layout_connectors(lines, layout.connectors)
    _append_svg_layout_terminal_hole_labels(lines, circuit, pins)
    if detail == "assembly":
        _append_svg_layout_component_body_labels(lines, overlays, component_labels)
    for label in labels:
        lines.append(dsl._svg_stripboard_overlay_label(label))
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_svg_board(lines, board):
    for row in range(board.height_pitches):
        x, y, strip_width, strip_height = dsl._stripboard_strip_rect(board, row)
        lines.append(
            f'  <rect class="copper-strip" data-row="{row}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{strip_width:.3f}" '
            f'height="{strip_height:.3f}" fill="{dsl.STRIPBOARD_STRIP_FILL}" '
            f'stroke="{dsl.STRIPBOARD_STRIP_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )
    for col, row, x, y in dsl._stripboard_holes(board):
        lines.append(
            f'  <circle class="hole" data-col="{col}" data-row="{row}" '
            f'cx="{x:.3f}" cy="{y:.3f}" r="{dsl.STRIPBOARD_HOLE_RADIUS:.3f}" '
            f'fill="{dsl.STRIPBOARD_HOLE_FILL}" stroke="{dsl.STRIPBOARD_HOLE_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )


def _append_svg_layout_cuts(lines, cuts):
    for cut in cuts:
        x = dsl._stripboard_column_center(cut.col)
        y = dsl._stripboard_row_center(cut.row)
        radius = dsl.STRIPBOARD_CUT_RADIUS
        lines.append(
            f'  <circle class="strip-cut" data-row="{cut.row}" '
            f'data-col="{cut.col}" cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{radius:.3f}" fill="none" stroke="{dsl.STRIPBOARD_CUT_STROKE}" '
            f'stroke-width="{dsl.STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
        )
        for x1, y1, x2, y2 in dsl._cut_cross_lines(x, y, radius):
            lines.append(
                f'  <line class="strip-cut-mark" data-row="{cut.row}" '
                f'data-col="{cut.col}" x1="{x1:.3f}" y1="{y1:.3f}" '
                f'x2="{x2:.3f}" y2="{y2:.3f}" '
                f'stroke="{dsl.STRIPBOARD_CUT_STROKE}" '
                f'stroke-width="{dsl.STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
            )


def _append_svg_layout_jumpers(lines, jumpers):
    for jumper in jumpers:
        _append_svg_jumper_wire(
            lines,
            jumper,
            class_name="layout-jumper",
            stroke=LAYOUT_JUMPER_STROKE,
            stroke_width=LAYOUT_JUMPER_STROKE_WIDTH,
        )
        for row, col in (jumper.start, jumper.end):
            x, y = dsl._stripboard_hole_position((row, col))
            lines.append(
                f'  <circle class="layout-jumper-endpoint" '
                f'data-net="{dsl._svg_attr(jumper.net_name)}" '
                f'data-row="{row}" data-col="{col}" '
                f'cx="{x:.3f}" cy="{y:.3f}" '
                f'r="{LAYOUT_JUMPER_ENDPOINT_RADIUS:.3f}" '
                f'fill="{LAYOUT_JUMPER_ENDPOINT_FILL}" '
                f'stroke="{LAYOUT_JUMPER_STROKE}" '
                f'stroke-width="{LAYOUT_JUMPER_STROKE_WIDTH:.3f}"/>'
            )


def _append_svg_jumper_wire(
    lines,
    jumper,
    *,
    class_name,
    stroke,
    stroke_width,
    stroke_dasharray=None,
):
    data_attrs = (
        f'class="{class_name}" '
        f'data-net="{dsl._svg_attr(jumper.net_name)}" '
        f'data-start-row="{jumper.start[0]}" data-start-col="{jumper.start[1]}" '
        f'data-end-row="{jumper.end[0]}" data-end-col="{jumper.end[1]}"'
    )
    dash_attr = (
        "" if stroke_dasharray is None else f' stroke-dasharray="{stroke_dasharray}"'
    )
    points = _jumper_display_points(jumper)
    if len(points) == 2:
        start, end = points
        lines.append(
            f"  <line {data_attrs} "
            f'x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
            f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width:.3f}" '
            f'stroke-linecap="round"{dash_attr}/>'
        )
        return

    lines.append(
        f'  <polyline {data_attrs} data-shape="elbow" '
        f'points="{_svg_points(points)}" fill="none" '
        f'stroke="{stroke}" stroke-width="{stroke_width:.3f}" '
        f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>'
    )


def _svg_points(points):
    return " ".join(f"{x:.3f},{y:.3f}" for x, y in points)


def _append_svg_layout_component_segments(lines, overlays):
    for overlay in overlays:
        for start, end in overlay["segments"]:
            lines.append(
                f'  <line class="layout-component" '
                f'data-element="{dsl._svg_attr(overlay["refdes"])}" '
                f'data-footprint="{dsl._svg_attr(overlay["footprint_name"])}" '
                f'x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
                f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" '
                f'stroke="{dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE}" '
                f'stroke-width="{dsl.STRIPBOARD_OVERLAY_STROKE_WIDTH:.3f}"/>'
            )


def _append_svg_layout_component_bodies(lines, overlays):
    for overlay in overlays:
        _append_svg_layout_component_body(lines, overlay)


def _append_svg_layout_component_body(lines, overlay):
    x, y = overlay["body_center"]
    radius = _layout_component_body_radius(overlay)
    lines.append(
        f'  <circle class="layout-component-body" '
        f'data-element="{dsl._svg_attr(overlay["refdes"])}" '
        f'data-value="{dsl._svg_attr(overlay["value"])}" '
        f'data-label="{dsl._svg_attr(overlay["label"])}" '
        f'data-footprint="{dsl._svg_attr(overlay["footprint_name"])}" '
        f'cx="{x:.3f}" cy="{y:.3f}" r="{radius:.3f}" '
        f'fill="{LAYOUT_COMPONENT_BODY_FILL}"/>'
    )


def _append_svg_layout_component_body_labels(lines, overlays, component_labels):
    for overlay in overlays:
        _append_svg_layout_component_body_label(lines, overlay, component_labels)


def _append_svg_layout_component_body_label(lines, overlay, component_labels):
    x, y = _layout_component_body_label_position(overlay, component_labels)
    font_size = _layout_component_body_font_size(overlay, component_labels)
    style_attrs = ""
    transform_attr = ""
    if component_labels == "refdes_value":
        style_attrs = (
            ' stroke="#ffffff" stroke-width="0.060" paint-order="stroke" '
            'stroke-linejoin="round"'
        )
        transform_attr = f' transform="rotate(-25 {x:.3f} {y:.3f})"'
    lines.append(
        f'  <text class="layout-component-body-label" '
        f'data-element="{dsl._svg_attr(overlay["refdes"])}" '
        f'data-value="{dsl._svg_attr(overlay["value"])}" '
        f'data-label="{dsl._svg_attr(overlay["label"])}" '
        f'x="{x:.3f}" y="{y:.3f}" '
        f'font-size="{font_size:.3f}" font-weight="800" text-anchor="middle" '
        f'fill="{_layout_component_body_label_fill(component_labels)}"'
        f"{style_attrs}{transform_attr}>"
        f'{dsl._svg_text(overlay["label"])}</text>'
    )


def _append_svg_layout_blockers(lines, blockers):
    for blocker in blockers:
        center = dsl._stripboard_hole_position((blocker.row, blocker.col))
        radius = dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS * 0.95
        lines.append(
            f'  <rect class="layout-blocker" data-element="{dsl._svg_attr(blocker.element_name)}" '
            f'data-row="{blocker.row}" data-col="{blocker.col}" '
            f'x="{center[0] - radius:.3f}" y="{center[1] - radius:.3f}" '
            f'width="{radius * 2:.3f}" height="{radius * 2:.3f}" '
            f'fill="{dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE}" opacity="0.42"/>'
        )


def _append_svg_layout_pins(lines, pins):
    for pin in pins:
        x, y = dsl._stripboard_hole_position(pin.hole)
        lines.append(
            f'  <circle class="layout-pin" data-net="{dsl._svg_attr(pin.net_name)}" '
            f'data-element="{dsl._svg_attr(pin.refdes)}" '
            f'data-terminal="{dsl._svg_attr(pin.terminal_name)}" '
            f'data-footprint="{dsl._svg_attr(pin.footprint_name)}" '
            f'data-row="{pin.row}" data-col="{pin.col}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS:.3f}" '
            f'fill="{dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL}"/>'
        )


def _append_svg_layout_connectors(lines, connectors):
    for connector in connectors:
        x, y = dsl._stripboard_hole_position(connector.hole)
        lines.append(
            f'  <circle class="layout-connector" '
            f'data-net="{dsl._svg_attr(connector.net_name)}" '
            f'data-connector="{dsl._svg_attr(connector.name)}" '
            f'data-kind="{dsl._svg_attr(connector.kind)}" '
            f'data-row="{connector.row}" data-col="{connector.col}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{LAYOUT_CONNECTOR_RADIUS:.3f}" '
            f'fill="{LAYOUT_CONNECTOR_FILL}" '
            f'stroke="{LAYOUT_CONNECTOR_STROKE}" '
            f'stroke-width="{LAYOUT_JUMPER_STROKE_WIDTH:.3f}"/>'
        )


def _append_svg_layout_terminal_hole_labels(lines, circuit, pins):
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    for pin in pins:
        if not _pin_terminal_label_visible(pin, components_by_refdes):
            continue
        x, y = dsl._stripboard_hole_position(pin.hole)
        lines.append(
            f'  <text class="layout-terminal-hole-label" '
            f'data-net="{dsl._svg_attr(pin.net_name)}" '
            f'data-element="{dsl._svg_attr(pin.refdes)}" '
            f'data-terminal="{dsl._svg_attr(pin.terminal_name)}" '
            f'data-row="{pin.row}" data-col="{pin.col}" '
            f'x="{x:.3f}" y="{y + 0.045:.3f}" '
            f'font-size="0.145" font-weight="800" text-anchor="middle" '
            f'fill="{LAYOUT_COMPONENT_BODY_LABEL_FILL}">'
            f"{dsl._svg_text(_terminal_label(pin.terminal_name))}</text>"
        )


def _render_stripboard_layout_png(
    layout, circuit, path, scale, detail, component_labels
):
    scale = dsl._validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard layout PNG files."
        ) from error

    width, height = dsl._stripboard_size(layout.board)
    pins = placed_component_pins(layout, circuit)
    labels = _placed_layout_labels(layout, circuit, pins, detail)
    label_margin = _layout_label_margin(labels)
    image_width = max(1, int(round((width + label_margin) * scale)))
    image_height = max(1, int(round(height * scale)))
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)
    board_image = Image.new(
        "RGB",
        (
            max(1, int(round(width * scale))),
            image_height,
        ),
        "white",
    )
    dsl._draw_stripboard_base_png(ImageDraw.Draw(board_image), layout.board, scale)
    image.paste(board_image, (int(round(label_margin * scale)), 0))

    for cut in layout.cuts:
        dsl._draw_stripboard_cut_png(draw, cut, label_margin, scale)

    jumper_width = max(1, int(round(LAYOUT_JUMPER_STROKE_WIDTH * scale)))
    jumper_endpoint_width = max(1, int(round(LAYOUT_JUMPER_STROKE_WIDTH * scale)))
    for jumper in layout.jumpers:
        draw.line(
            [
                dsl._px_point(dsl._offset_point(point, label_margin, 0), scale)
                for point in _jumper_display_points(jumper)
            ],
            fill=LAYOUT_JUMPER_STROKE,
            width=jumper_width,
        )
        for hole in (jumper.start, jumper.end):
            center = dsl._offset_point(
                dsl._stripboard_hole_position(hole),
                label_margin,
                0,
            )
            draw.ellipse(
                dsl._px_rect(
                    center[0] - LAYOUT_JUMPER_ENDPOINT_RADIUS,
                    center[1] - LAYOUT_JUMPER_ENDPOINT_RADIUS,
                    LAYOUT_JUMPER_ENDPOINT_RADIUS * 2,
                    LAYOUT_JUMPER_ENDPOINT_RADIUS * 2,
                    scale,
                ),
                fill=LAYOUT_JUMPER_ENDPOINT_FILL,
                outline=LAYOUT_JUMPER_STROKE,
                width=jumper_endpoint_width,
            )

    element_width = dsl._px_overlay_stroke(scale)
    overlays = _layout_component_overlays(layout, circuit, pins, component_labels)
    for overlay in overlays:
        for start, end in overlay["segments"]:
            draw.line(
                [
                    dsl._px_point(dsl._offset_point(start, label_margin, 0), scale),
                    dsl._px_point(dsl._offset_point(end, label_margin, 0), scale),
                ],
                fill=dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE,
                width=element_width,
            )
    if detail == "assembly" and component_labels == "refdes":
        for overlay in overlays:
            _draw_layout_component_body_png(draw, overlay, label_margin, scale)

    if detail == "annotated":
        for blocker in layout.blockers:
            center = dsl._offset_point(
                dsl._stripboard_hole_position((blocker.row, blocker.col)),
                label_margin,
                0,
            )
            radius = dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS * 0.95
            draw.rectangle(
                dsl._px_rect(
                    center[0] - radius,
                    center[1] - radius,
                    radius * 2,
                    radius * 2,
                    scale,
                ),
                fill=dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE,
            )

    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    for pin in pins:
        dsl._draw_px_circle(
            draw,
            dsl._offset_point(
                dsl._stripboard_hole_position(pin.hole),
                label_margin,
                0,
            ),
            dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS,
            scale,
            fill=dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL,
        )
        if _pin_terminal_label_visible(pin, components_by_refdes):
            _draw_layout_terminal_hole_label_png(image, pin, label_margin, scale)

    for connector in layout.connectors:
        _draw_layout_connector_png(draw, connector, label_margin, scale)

    if detail == "assembly":
        for overlay in overlays:
            _draw_layout_component_body_label_png(
                image,
                overlay,
                label_margin,
                scale,
                component_labels,
            )

    for label in labels:
        dsl._draw_stripboard_overlay_label_png(image, label, label_margin, scale)

    image.save(path)


def _draw_layout_component_body_png(draw, overlay, label_margin, scale):
    center = dsl._offset_point(overlay["body_center"], label_margin, 0)
    dsl._draw_px_circle(
        draw,
        center,
        _layout_component_body_radius(overlay),
        scale,
        fill=LAYOUT_COMPONENT_BODY_FILL,
    )


def _draw_layout_component_body_label_png(
    image,
    overlay,
    label_margin,
    scale,
    component_labels,
):
    label_position = _layout_component_body_label_position(overlay, component_labels)
    center = dsl._offset_point(label_position, label_margin, 0)
    dsl._draw_png_text_rotated(
        image,
        (center[0], center[1] + 0.005),
        overlay["label"],
        font=dsl._overlay_png_font(
            scale,
            _layout_component_body_font_size(overlay, component_labels),
        ),
        scale=scale,
        fill=_layout_component_body_label_fill(component_labels),
        angle=-25 if component_labels == "refdes_value" else 0,
        anchor="center",
    )


def _draw_layout_terminal_hole_label_png(image, pin, label_margin, scale):
    center = dsl._offset_point(dsl._stripboard_hole_position(pin.hole), label_margin, 0)
    dsl._draw_png_text_rotated(
        image,
        (center[0], center[1] + 0.005),
        _terminal_label(pin.terminal_name),
        font=dsl._overlay_png_font(scale, 0.145),
        scale=scale,
        fill=LAYOUT_COMPONENT_BODY_LABEL_FILL,
        angle=0,
        anchor="center",
    )


def _draw_layout_connector_png(draw, connector, label_margin, scale):
    center = dsl._offset_point(
        dsl._stripboard_hole_position(connector.hole),
        label_margin,
        0,
    )
    _draw_layout_connector_png_at(draw, center, scale)


def _draw_layout_connector_png_at(draw, center, scale):
    stroke_width = max(1, int(round(LAYOUT_JUMPER_STROKE_WIDTH * scale)))
    draw.ellipse(
        dsl._px_rect(
            center[0] - LAYOUT_CONNECTOR_RADIUS,
            center[1] - LAYOUT_CONNECTOR_RADIUS,
            LAYOUT_CONNECTOR_RADIUS * 2,
            LAYOUT_CONNECTOR_RADIUS * 2,
            scale,
        ),
        fill=LAYOUT_CONNECTOR_FILL,
        outline=LAYOUT_CONNECTOR_STROKE,
        width=stroke_width,
    )


def _layout_label_margin(labels):
    longest_label = max((len(label.text) for label in labels), default=0)
    return max(
        dsl.STRIPBOARD_OVERLAY_NET_LABEL_MARGIN,
        0.8 + longest_label * 0.17,
    )


def _placed_layout_labels(layout, circuit, pins, detail):
    labels = list(
        _layout_row_labels(
            layout, (*pins, *(_connector_pin(c) for c in layout.connectors))
        )
    )
    for connector in layout.connectors:
        label = connector.label or connector.name
        if not label:
            continue
        x, y = dsl._stripboard_hole_position(connector.hole)
        labels.append(
            dsl._StripboardOverlayLabel(
                class_name="layout-connector-label",
                text=label,
                x=x + 0.18,
                y=y - 0.16,
                font_size=dsl.STRIPBOARD_OVERLAY_NODE_LABEL_SIZE,
                font_weight="800",
                text_anchor="start",
                rotation_degrees=dsl.STRIPBOARD_OVERLAY_LABEL_ANGLE,
                data_attrs=(
                    ("data-net", connector.net_name),
                    ("data-connector", connector.name),
                ),
                collision_priority=2,
                candidates=dsl._stripboard_node_label_candidates(x, y),
            )
        )
    if detail != "annotated":
        return dsl._resolve_stripboard_overlay_label_collisions(tuple(labels))
    for overlay in _layout_component_overlays(layout, circuit, pins, "refdes_value"):
        center = overlay["center"]
        labels.append(
            dsl._StripboardOverlayLabel(
                class_name="layout-component-label",
                text=overlay["label"],
                x=center[0],
                y=center[1] - 0.18,
                font_size=dsl.STRIPBOARD_OVERLAY_ELEMENT_LABEL_SIZE,
                font_weight="700",
                text_anchor="middle",
                rotation_degrees=dsl.STRIPBOARD_OVERLAY_LABEL_ANGLE,
                data_attrs=(
                    ("data-element", overlay["refdes"]),
                    ("data-footprint", overlay["footprint_name"]),
                ),
                collision_priority=3,
                candidates=dsl._stripboard_element_label_candidates(center),
            )
        )

    return dsl._resolve_stripboard_overlay_label_collisions(tuple(labels))


def _layout_row_labels(layout, pins):
    row_nets = {}
    for pin in pins:
        row_nets.setdefault(pin.row, set()).add(pin.net_name)
    labels = []
    for row in range(layout.board.height_pitches):
        net_names = tuple(sorted(row_nets.get(row, ())))
        if not net_names:
            continue
        text = " / ".join(net_names)
        labels.append(
            dsl._StripboardOverlayLabel(
                class_name="layout-row-label",
                text=text,
                x=-0.22,
                y=dsl._stripboard_row_center(row) + 0.115,
                font_size=dsl.STRIPBOARD_OVERLAY_NODE_LABEL_SIZE,
                font_weight="800",
                text_anchor="end",
                data_attrs=(("data-row", row), ("data-net", text)),
                collision_priority=0,
            )
        )
    return tuple(labels)


def _layout_component_overlays(layout, circuit, pins, component_labels="refdes"):
    pins_by_refdes = {}
    for pin in pins:
        pins_by_refdes.setdefault(pin.refdes, []).append(pin)
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    overlays = []
    for placed_component in layout.placed_components:
        component = components_by_refdes[placed_component.refdes]
        component_pins = pins_by_refdes.get(placed_component.refdes, ())
        terminal_holes = tuple(pin.hole for pin in component_pins)
        if not terminal_holes:
            continue
        segments = tuple(
            (
                dsl._stripboard_hole_position(start),
                dsl._stripboard_hole_position(end),
            )
            for start, end in dsl._stripboard_element_body_segments_from_terminal_holes(
                terminal_holes,
            )
        )
        center = _component_overlay_center(terminal_holes)
        body_center = _component_body_center(terminal_holes, component.kind)
        overlays.append(
            {
                "refdes": component.refdes,
                "kind": component.kind,
                "footprint_name": placed_component.footprint_name,
                "value": "" if component.value is None else str(component.value),
                "label": _component_label(component, component_labels),
                "segments": segments,
                "center": center,
                "body_center": body_center,
            }
        )
    return tuple(overlays)


def _component_overlay_center(terminal_holes):
    if len(terminal_holes) == 1:
        return dsl._stripboard_hole_position(terminal_holes[0])
    if len(terminal_holes) == 2:
        return dsl._average_points(
            tuple(dsl._stripboard_hole_position(hole) for hole in terminal_holes)
        )
    return dsl._stripboard_hole_position(
        dsl._stripboard_terminal_center_hole(terminal_holes)
    )


def _component_body_center(terminal_holes, component_kind):
    center = _component_overlay_center(terminal_holes)
    if component_kind not in {"bjt_npn", "pmos"}:
        return center
    rows = {row for row, _col in terminal_holes}
    cols = {col for _row, col in terminal_holes}
    if len(cols) == 1:
        return center[0] + 0.38, center[1]
    if len(rows) == 1:
        return center[0], center[1] - 0.38
    return center[0] + 0.28, center[1] - 0.28


def _layout_component_body_radius(overlay):
    return 0.300 if overlay["kind"] in {"bjt_npn", "pmos"} else 0.165


def _layout_component_body_label_position(overlay, component_labels):
    x, y = overlay["body_center"]
    if component_labels == "refdes":
        return x, y + 0.055
    return x, y - _layout_component_body_radius(overlay) - 0.090


def _layout_component_body_font_size(overlay, component_labels="refdes"):
    if component_labels == "refdes":
        return 0.210 if overlay["kind"] in {"bjt_npn", "pmos"} else 0.165
    return 0.145


def _layout_component_body_label_fill(component_labels):
    if component_labels == "refdes":
        return LAYOUT_COMPONENT_BODY_LABEL_FILL
    return "#b91c1c"


def _pin_terminal_label_visible(pin, components_by_refdes):
    component = components_by_refdes.get(pin.refdes)
    return component is not None and component.kind in DIRECTIONAL_TERMINAL_LABEL_KINDS


def _is_stripboard_physical_node_view(node_view):
    return node_view.kind not in dsl.STRIPBOARD_NON_PHYSICAL_NODE_KINDS


def _component_label(component, component_labels="refdes"):
    if component_labels == "refdes" or component.value is None:
        return component.refdes
    return f"{component.refdes} {component.value}"


def _terminal_label(terminal_name):
    label = str(terminal_name)
    if len(label) <= 2:
        return label.upper()
    return label[0].upper()


def _component_terminal_nets(component):
    return tuple(
        sorted(
            ((terminal.name, terminal.net_name) for terminal in component.terminals),
            key=lambda item: item[0],
        )
    )


def _validate_component_footprint(component, footprint):
    if component.kind not in footprint.component_kinds:
        raise ValueError(
            f"Footprint {footprint.name!r} does not support component kind "
            f"{component.kind!r} for {component.refdes!r}."
        )
    component_terminals = {terminal.name for terminal in component.terminals}
    footprint_terminals = set(footprint.pins)
    missing = component_terminals - footprint_terminals
    extra = footprint_terminals - component_terminals
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing pins {tuple(sorted(missing))}")
        if extra:
            details.append(f"unknown pins {tuple(sorted(extra))}")
        raise ValueError(
            f"Footprint {footprint.name!r} does not match {component.refdes!r}: "
            f"{', '.join(details)}."
        )


def _footprints_by_name(footprints):
    if isinstance(footprints, Mapping):
        footprints = footprints.values()
    footprints_by_name = {}
    for footprint in footprints:
        if not isinstance(footprint, Footprint):
            raise TypeError("footprints must contain Footprint objects.")
        if footprint.name in footprints_by_name:
            raise ValueError(f"Duplicate footprint name {footprint.name!r}.")
        footprints_by_name[footprint.name] = footprint
    if not footprints_by_name:
        raise ValueError("At least one footprint is required.")
    return footprints_by_name


def _require_component(components_by_refdes, refdes):
    try:
        return components_by_refdes[refdes]
    except KeyError as error:
        raise ValueError(f"Layout refers to unknown component {refdes!r}.") from error


def _require_footprint(footprint_map, footprint_name):
    try:
        return footprint_map[footprint_name]
    except KeyError as error:
        raise ValueError(f"Unknown footprint {footprint_name!r}.") from error


def _absolute_footprint_point(origin, rotation, point):
    delta_row, delta_col = _rotate_grid_point(point, rotation)
    return origin[0] + delta_row, origin[1] + delta_col


def _rotate_grid_point(point, rotation):
    row, col = point
    normalized = _normalize_rotation(rotation)
    if normalized == 0:
        return row, col
    if normalized == 90:
        return col, -row
    if normalized == 180:
        return -row, -col
    if normalized == 270:
        return -col, row
    raise ValueError("Rotations must be multiples of 90 degrees.")


def _normalize_rotation(rotation):
    if not isinstance(rotation, int) or isinstance(rotation, bool):
        raise TypeError("rotation must be an integer degree value.")
    normalized = rotation % 360
    if normalized % 90 != 0:
        raise ValueError("rotation must be a multiple of 90 degrees.")
    return normalized


def _coerce_integer(value, label):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer.")
    return value


def _coerce_grid_point(point, label):
    if not isinstance(point, tuple) or len(point) != 2:
        raise TypeError(f"{label} must be a (row, col) tuple.")
    row, col = point
    if not isinstance(row, int) or isinstance(row, bool):
        raise TypeError(f"{label} row must be an integer.")
    if not isinstance(col, int) or isinstance(col, bool):
        raise TypeError(f"{label} col must be an integer.")
    return row, col


def _clamp(value, low, high):
    return max(low, min(high, value))


def _require_hole_on_board(board, row, col, label):
    if row < 0 or row >= board.height_pitches or col < 0 or col >= board.width_pitches:
        raise ValueError(
            f"{label} hole {(row, col)} is outside board "
            f"{board.width_pitches}x{board.height_pitches}."
        )


def _dedupe_blockers(blockers):
    blockers_by_key = {}
    for blocker in blockers:
        blockers_by_key.setdefault(
            (blocker.row, blocker.col, blocker.element_name),
            blocker,
        )
    return tuple(blockers_by_key[key] for key in sorted(blockers_by_key))


class _UnionFind:
    def __init__(self, items):
        self._parents = {item: item for item in items}

    def find(self, item):
        parent = self._parents[item]
        if parent != item:
            parent = self.find(parent)
            self._parents[item] = parent
        return parent

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        self._parents[right_root] = left_root
