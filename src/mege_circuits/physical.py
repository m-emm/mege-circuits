"""Manual physical stripboard layouts backed by semantic circuits."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import mege_circuits.dsl as dsl
from mege_circuits.circuit import Circuit, Component
from mege_circuits.dsl import Direction, Stripboard, StripboardBlocker, StripboardCut

ERROR = "error"
WARNING = "warning"


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
class StripboardRoutingHints:
    """Placement hints for the conservative stripboard router."""

    net_rows: Mapping[str, int] = field(default_factory=dict)
    component_columns: Mapping[str, int] = field(default_factory=dict)
    component_order: tuple[str, ...] = ()

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
            "component_order",
            tuple(str(refdes) for refdes in self.component_order),
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
            name="capacitor_2pin_span2",
            component_kinds=("capacitor",),
            pins={"start": (0, 0), "end": (0, 2)},
            allowed_rotations=(0, 90, 180, 270),
            blockers=((0, 1),),
        ),
        Footprint(
            name="to92_cbe",
            component_kinds=("bjt_npn",),
            pins={"collector": (0, 0), "base": (0, 2), "emitter": (0, 4)},
            allowed_rotations=(0, 180),
            blockers=((0, 1), (0, 3)),
        ),
        Footprint(
            name="to220_gds",
            component_kinds=("pmos",),
            pins={"gate": (0, 0), "drain": (0, 2), "source": (0, 4)},
            allowed_rotations=(0, 180),
            blockers=((0, 1), (0, 3)),
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
        blockers=_dedupe_blockers((*explicit_blockers, *generated_blockers)),
        annotations=tuple(str(annotation) for annotation in annotations),
        footprints=tuple(footprint_map[name] for name in sorted(footprint_map)),
    )
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

    _validate_physical_inputs(layout, circuit)
    issues = list(_physical_layout_drc_issues(layout, circuit))
    if any(issue.severity == ERROR for issue in issues):
        return PhysicalVerificationReport(tuple(issues), physical_netlist=None)

    physical_netlist = _extract_physical_netlist_unchecked(layout, circuit)
    issues.extend(_physical_connectivity_issues(physical_netlist))
    return PhysicalVerificationReport(tuple(issues), physical_netlist=physical_netlist)


def stripboard_hints_from_schema(schema):
    """Derive deterministic routing hints from the legacy schematic projection."""

    if not isinstance(schema, dsl.Schema):
        raise TypeError("stripboard_hints_from_schema expects a Schema object.")

    assignment = dsl.assign_schema_nets_to_stripboard(schema)
    terminal_columns_by_component = {}
    for marker_key, column in assignment.marker_column_maps.items():
        if len(marker_key) != 3 or marker_key[0] != "terminal":
            continue
        _kind, refdes, _terminal_name = marker_key
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
    return StripboardRoutingHints(
        net_rows=assignment.net_rows,
        component_columns=component_columns,
        component_order=component_order,
    )


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
        return None, _routing_failure_report(
            "Only horizontal stripboards are supported by the first router.",
            code="unsupported_strip_direction",
        )
    routing_hints = _coerce_routing_hints(hints)

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
    except (TypeError, ValueError) as error:
        return None, _routing_failure_report(str(error))

    net_rows = _routing_net_rows(circuit, routing_hints)
    planned, placement_error = _route_component_placements(
        circuit,
        board,
        footprint_map,
        routing_hints,
        fixed_placement_map,
        net_rows,
    )
    if placement_error is not None:
        return None, _routing_failure_report(placement_error)

    cuts = list(normalized_fixed_cuts)
    jumpers = list(normalized_fixed_jumpers)
    for component in circuit.components:
        placed_component = planned[component.refdes]
        footprint = footprint_map[placed_component.footprint_name]
        component_cuts, cut_error = _routing_component_cuts(
            component,
            placed_component,
            footprint,
        )
        if cut_error is not None:
            return None, _routing_failure_report(cut_error)
        cuts.extend(component_cuts)
        jumpers.extend(
            _routing_component_jumpers(
                component,
                placed_component,
                footprint,
                net_rows,
            )
        )

    try:
        layout = create_manual_stripboard_layout(
            circuit,
            board=board,
            footprints=tuple(footprint_map[name] for name in sorted(footprint_map)),
            placements=planned,
            cuts=_dedupe_cuts(cuts),
            jumpers=_dedupe_jumpers(jumpers),
        )
    except (TypeError, ValueError) as error:
        return None, _routing_failure_report(str(error))

    report = verify_stripboard_layout(layout, circuit)
    if not report.ok:
        return layout, report
    return layout, report


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


def render_stripboard_layout(layout, circuit, file, scale=32):
    """Render a manual physical stripboard layout as SVG or PNG."""

    if not isinstance(layout, PhysicalLayout):
        raise TypeError("render_stripboard_layout expects a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("render_stripboard_layout expects a Circuit object.")
    if layout.board.strip_direction is not Direction.HORIZONTAL:
        raise NotImplementedError("Only horizontal stripboards are supported for now.")

    _validate_layout_geometry(layout, circuit, _footprints_by_name(layout.footprints))

    path = Path(file)
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_layout_svg(layout, circuit, path, scale)
    elif suffix == ".png":
        _render_stripboard_layout_png(layout, circuit, path, scale)
    else:
        raise ValueError("Stripboard layout output file must end in .svg or .png.")


def footprint_for_component(component, footprints):
    """Return the single footprint matching a component kind."""

    if not isinstance(component, Component):
        raise TypeError("footprint_for_component expects a Component object.")
    matches = tuple(
        footprint
        for footprint in _footprints_by_name(footprints).values()
        if component.kind in footprint.component_kinds
    )
    if not matches:
        raise ValueError(f"No footprint supports component kind {component.kind!r}.")
    if len(matches) > 1:
        names = tuple(footprint.name for footprint in matches)
        raise ValueError(
            f"Component kind {component.kind!r} has multiple matching footprints: {names}."
        )
    return matches[0]


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
    net_names = tuple(net.name for net in circuit.nets)
    ordered_net_names = tuple(
        sorted(
            net_names,
            key=lambda name: (
                hinted_rows.get(name, len(hinted_rows)),
                name,
            ),
        )
    )
    return {net_name: row for row, net_name in enumerate(ordered_net_names)}


def _route_component_placements(
    circuit,
    board,
    footprint_map,
    hints,
    fixed_placements,
    net_rows,
):
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    planned = dict(fixed_placements)
    ordered_refdeses = _routing_component_order(circuit, hints)
    next_row = len(net_rows)

    fixed_rows = []
    for placed_component in fixed_placements.values():
        footprint = footprint_map[placed_component.footprint_name]
        fixed_rows.extend(
            row for row, _col in _absolute_footprint_holes(placed_component, footprint)
        )
    if fixed_rows:
        next_row = max(next_row, max(fixed_rows) + 1)

    for refdes in ordered_refdeses:
        if refdes in planned:
            continue
        component = components_by_refdes[refdes]
        try:
            footprint = footprint_for_component(component, footprint_map)
        except ValueError as error:
            return None, str(error)
        if next_row >= board.height_pitches:
            return None, (
                f"Board has {board.height_pitches} rows, but routing "
                f"{refdes!r} needs component row {next_row}."
            )
        placed_component, error = _route_single_component_placement(
            component,
            footprint,
            board,
            row=next_row,
            preferred_column=hints.component_columns.get(refdes, 0),
        )
        if error is not None:
            return None, error
        planned[refdes] = placed_component
        next_row += 1

    missing = tuple(sorted(set(components_by_refdes) - set(planned)))
    if missing:
        return None, f"Missing routed placements for components {missing}."
    return planned, None


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


def _route_single_component_placement(
    component, footprint, board, row, preferred_column
):
    for rotation in _preferred_footprint_rotations(footprint):
        relative_points = tuple(
            _rotate_grid_point(point, rotation) for point in footprint.pins.values()
        )
        if {point[0] for point in relative_points} != {0}:
            continue
        min_col = min(point[1] for point in relative_points)
        max_col = max(point[1] for point in relative_points)
        width = max_col - min_col + 1
        if width > board.width_pitches:
            continue
        origin_col = int(
            _clamp(
                preferred_column - min_col,
                -min_col,
                board.width_pitches - 1 - max_col,
            )
        )
        placed_component = PlacedComponent(
            refdes=component.refdes,
            footprint_name=footprint.name,
            origin=(row, origin_col),
            rotation=rotation,
        )
        if not _routing_component_isolatable(component, placed_component, footprint):
            continue
        return placed_component, None
    return None, (
        f"No horizontal, cut-isolatable placement is available for "
        f"{component.refdes!r} with footprint {footprint.name!r}."
    )


def _preferred_footprint_rotations(footprint):
    preferred = (0, 180, 90, 270)
    return tuple(
        rotation
        for rotation in preferred
        if rotation in set(footprint.allowed_rotations)
    )


def _routing_component_isolatable(component, placed_component, footprint):
    pins_by_row = _component_route_pins_by_row(component, placed_component, footprint)
    for row_pins in pins_by_row.values():
        sorted_pins = sorted(row_pins, key=lambda item: item[2])
        for left, right in zip(sorted_pins, sorted_pins[1:]):
            if left[0].net_name == right[0].net_name:
                continue
            if right[2] - left[2] < 2:
                return False
    return True


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
    for cut_col in range(left_col + 1, right_col):
        if cut_col not in pin_columns:
            return cut_col
    return None


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
        *[cut.row for cut in layout.cuts],
        *[hole[0] for jumper in layout.jumpers for hole in (jumper.start, jumper.end)],
        *[blocker.row for blocker in layout.blockers],
    ]
    return 0 if not rows else max(rows) + 1


def _layout_used_width(layout):
    cols = [
        *[pin.col for pin in _layout_score_pins(layout)],
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

    cut_holes = _valid_cut_holes(layout, issues)
    _check_jumpers(layout, circuit, issues)
    blockers = _valid_blockers(
        (*layout.blockers, *generated_blockers),
        layout.board,
        issues,
    )
    _check_pin_hole_collisions(pins, issues)
    _check_pins_on_cuts(pins, cut_holes, issues)
    _check_blocker_pin_collisions(blockers, pins, issues)
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


def _check_jumpers(layout, circuit, issues):
    net_names = {net.name for net in circuit.nets}
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
    for pin in placed_component_pins(layout, circuit):
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

    for blocker in layout.blockers:
        _require_hole_on_board(layout.board, blocker.row, blocker.col, "blocker")
        pin = pin_holes.get((blocker.row, blocker.col))
        if pin is not None:
            raise ValueError(
                f"Blocker for {blocker.element_name!r} collides with pin "
                f"{pin.refdes}.{pin.terminal_name} at {(blocker.row, blocker.col)}."
            )

    for placed_component in layout.placed_components:
        _require_footprint(footprint_map, placed_component.footprint_name)


def _render_stripboard_layout_svg(layout, circuit, path, scale):
    scale = dsl._validate_render_scale(scale)
    width, height = dsl._stripboard_size(layout.board)
    width_px = width * scale
    height_px = height * scale
    pins = placed_component_pins(layout, circuit)
    labels = _placed_layout_labels(layout, circuit, pins)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px:.0f}" height="{height_px:.0f}" '
            f'viewBox="0 0 {width:.3f} {height:.3f}">'
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
    _append_svg_layout_components(lines, layout, circuit, pins)
    _append_svg_layout_blockers(lines, layout.blockers)
    _append_svg_layout_pins(lines, pins)
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
        start = dsl._stripboard_hole_position(jumper.start)
        end = dsl._stripboard_hole_position(jumper.end)
        lines.append(
            f'  <line class="layout-jumper" data-net="{dsl._svg_attr(jumper.net_name)}" '
            f'data-start-row="{jumper.start[0]}" data-start-col="{jumper.start[1]}" '
            f'data-end-row="{jumper.end[0]}" data-end-col="{jumper.end[1]}" '
            f'x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
            f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" '
            f'stroke="{dsl.STRIPBOARD_OVERLAY_NODE_FILL}" '
            f'stroke-width="{dsl.STRIPBOARD_OVERLAY_STROKE_WIDTH * 1.35:.3f}" '
            f'stroke-linecap="round" stroke-dasharray="0.180 0.120"/>'
        )


def _append_svg_layout_components(lines, layout, circuit, pins):
    for overlay in _layout_component_overlays(layout, circuit, pins):
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


def _render_stripboard_layout_png(layout, circuit, path, scale):
    scale = dsl._validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard layout PNG files."
        ) from error

    width, height = dsl._stripboard_size(layout.board)
    image_width = max(1, int(round(width * scale)))
    image_height = max(1, int(round(height * scale)))
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)
    dsl._draw_stripboard_base_png(draw, layout.board, scale)

    for cut in layout.cuts:
        dsl._draw_stripboard_cut_png(draw, cut, 0.0, scale)

    jumper_width = max(
        1, int(round(dsl.STRIPBOARD_OVERLAY_STROKE_WIDTH * 1.35 * scale))
    )
    for jumper in layout.jumpers:
        draw.line(
            [
                dsl._px_point(dsl._stripboard_hole_position(jumper.start), scale),
                dsl._px_point(dsl._stripboard_hole_position(jumper.end), scale),
            ],
            fill=dsl.STRIPBOARD_OVERLAY_NODE_FILL,
            width=jumper_width,
        )

    element_width = dsl._px_overlay_stroke(scale)
    pins = placed_component_pins(layout, circuit)
    for overlay in _layout_component_overlays(layout, circuit, pins):
        for start, end in overlay["segments"]:
            draw.line(
                [dsl._px_point(start, scale), dsl._px_point(end, scale)],
                fill=dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE,
                width=element_width,
            )

    for blocker in layout.blockers:
        center = dsl._stripboard_hole_position((blocker.row, blocker.col))
        radius = dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS * 0.95
        draw.rectangle(
            dsl._px_rect(
                center[0] - radius, center[1] - radius, radius * 2, radius * 2, scale
            ),
            fill=dsl.STRIPBOARD_OVERLAY_ELEMENT_STROKE,
        )

    for pin in pins:
        dsl._draw_px_circle(
            draw,
            dsl._stripboard_hole_position(pin.hole),
            dsl.STRIPBOARD_OVERLAY_TERMINAL_RADIUS,
            scale,
            fill=dsl.STRIPBOARD_OVERLAY_TERMINAL_FILL,
        )

    for label in _placed_layout_labels(layout, circuit, pins):
        dsl._draw_stripboard_overlay_label_png(image, label, 0.0, scale)

    image.save(path)


def _placed_layout_labels(layout, circuit, pins):
    labels = []
    for pin in pins:
        x, y = dsl._stripboard_hole_position(pin.hole)
        labels.append(
            dsl._StripboardOverlayLabel(
                class_name="layout-pin-label",
                text=_terminal_label(pin.terminal_name),
                x=x + 0.155,
                y=y - 0.125,
                font_size=dsl.STRIPBOARD_OVERLAY_TERMINAL_LABEL_SIZE,
                font_weight="800",
                text_anchor="middle",
                data_attrs=(
                    ("data-net", pin.net_name),
                    ("data-element", pin.refdes),
                    ("data-terminal", pin.terminal_name),
                ),
                collision_priority=1,
                candidates=dsl._stripboard_terminal_label_candidates(x, y),
            )
        )

    for overlay in _layout_component_overlays(layout, circuit, pins):
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


def _layout_component_overlays(layout, circuit, pins):
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
        overlays.append(
            {
                "refdes": component.refdes,
                "footprint_name": placed_component.footprint_name,
                "label": _component_label(component),
                "segments": segments,
                "center": center,
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


def _component_label(component):
    return (
        component.refdes
        if component.value is None
        else f"{component.refdes} {component.value}"
    )


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
