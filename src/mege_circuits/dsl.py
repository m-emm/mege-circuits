"""Minimal alignment-first schematic DSL.

The DSL keeps the electrical graph separate from the drawn layout:

- ``Net`` is the logical electrical node.
- ``NodeView`` is a placed visual representation of a net.
- ``Element`` stores stable terminal view ids and net names.
- ``WireSegment`` draws a conductor between two views of the same net.
"""

from __future__ import annotations

import copy
import html
import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from itertools import permutations, product
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

from mege_circuits.pinout.svg import DEFAULT_COLOR_MAP as DEFAULT_KIND_COLOR_MAP

TWO_TERMINAL_WIDTH = 0.8
TWO_TERMINAL_HEIGHT = 2.0
DIODE_HEIGHT = 1.25
ZENER_HEIGHT = 1.25
FET_DX = 0.8333333333333333
FET_Y = 0.8333333333333333
BJT_X = 0.752
BJT_Y = 0.697
DUAL_OPTOCOUPLER_HALF_WIDTH = 1.5
DUAL_OPTOCOUPLER_HALF_HEIGHT = 2.4
HEX_OPEN_COLLECTOR_HALF_WIDTH = 2.4
HEX_OPEN_COLLECTOR_HALF_HEIGHT = 4.3
HEX_OPEN_COLLECTOR_CHANNEL_YS = (3.0, 1.8, 0.6, -0.6, -1.8, -3.0)
DEFAULT_ELEMENT_BBOX_PADDING = 0.35
LABEL_GAP = 0.16
EPS = 1e-9
STRIPBOARD_BOARD_MARGIN = 0.5
STRIPBOARD_STRIP_INSET = 0.25
STRIPBOARD_STRIP_HEIGHT = 0.55
STRIPBOARD_HOLE_RADIUS = 0.22
STRIPBOARD_STROKE_WIDTH = 0.035
STRIPBOARD_BOARD_FILL = "#f7e48b"
STRIPBOARD_BOARD_STROKE = "#e6ca70"
STRIPBOARD_STRIP_FILL = "#d98b61"
STRIPBOARD_STRIP_STROKE = "#b66d47"
STRIPBOARD_HOLE_FILL = "#fbfbfb"
STRIPBOARD_HOLE_STROKE = "#333333"
STRIPBOARD_OVERLAY_NODE_FILL = "#2563eb"
STRIPBOARD_OVERLAY_TERMINAL_FILL = "#111827"
STRIPBOARD_OVERLAY_ELEMENT_STROKE = "#1f2937"
STRIPBOARD_OVERLAY_TEXT_FILL = "#b91c1c"
STRIPBOARD_OVERLAY_TEXT_HALO = "#ffffff"
STRIPBOARD_OVERLAY_STROKE_WIDTH = 0.045
STRIPBOARD_OVERLAY_NODE_RADIUS = 0.14
STRIPBOARD_OVERLAY_TERMINAL_RADIUS = 0.09
STRIPBOARD_OVERLAY_ELEMENT_LABEL_SIZE = 0.19
STRIPBOARD_OVERLAY_TERMINAL_LABEL_SIZE = 0.17
STRIPBOARD_OVERLAY_NODE_LABEL_SIZE = 0.17
STRIPBOARD_OVERLAY_NET_LABEL_SIZE = 0.34
STRIPBOARD_OVERLAY_RUN_LABEL_SIZE = 0.20
STRIPBOARD_OVERLAY_NET_LABEL_MARGIN = 3.1
STRIPBOARD_OVERLAY_LABEL_ANGLE = -30.0
STRIPBOARD_OVERLAY_LABEL_COLLISION_PADDING = 0.035
STRIPBOARD_RUN_BLOCK_STROKE = "#111111"
STRIPBOARD_RUN_BLOCK_STROKE_WIDTH = 0.085
STRIPBOARD_CUT_STROKE = "#000000"
STRIPBOARD_CUT_RADIUS = 0.31
STRIPBOARD_CUT_STROKE_WIDTH = 0.14
STRIPBOARD_NON_PHYSICAL_NODE_KINDS = frozenset({"schematic_junction", "layout"})
DEFAULT_NET_KIND = "default"


class NodeType(Enum):
    DOT = auto()
    GROUND = auto()


class ElementType(Enum):
    WIRE = auto()
    RESISTOR = auto()
    FUSE = auto()
    CAPACITOR = auto()
    DIODE = auto()
    PMOS = auto()
    BJT_NPN = auto()
    BJT_PNP = auto()
    ZENER = auto()
    DUAL_OPTOCOUPLER = auto()
    HEX_OPEN_COLLECTOR_BUFFER = auto()


Dot = NodeType.DOT
Ground = NodeType.GROUND
Resistor = ElementType.RESISTOR
Fuse = ElementType.FUSE
Capacitor = ElementType.CAPACITOR
Diode = ElementType.DIODE
PMos = ElementType.PMOS
BjtNpn = ElementType.BJT_NPN
BjtPnp = ElementType.BJT_PNP
Wire = ElementType.WIRE
Zener = ElementType.ZENER
DualOptocoupler = ElementType.DUAL_OPTOCOUPLER
HexOpenCollectorBuffer = ElementType.HEX_OPEN_COLLECTOR_BUFFER


class Alignment(Enum):
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()
    CENTER = auto()
    TOP_CENTER = auto()
    BOTTOM_CENTER = auto()
    LEFT_CENTER = auto()
    RIGHT_CENTER = auto()
    STACK_LEFT = auto()
    STACK_RIGHT = auto()
    STACK_TOP = auto()
    STACK_BOTTOM = auto()


class Direction(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()


@dataclass(frozen=True)
class Net:
    name: str
    kind: str = DEFAULT_NET_KIND

    def __post_init__(self):
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "kind", _normalize_net_kind(self.kind))


@dataclass(frozen=True)
class Stripboard:
    width_pitches: int
    height_pitches: int
    strip_direction: Direction = Direction.HORIZONTAL
    pitch_mm: float = 2.54

    def __post_init__(self):
        _validate_positive_integer(self.width_pitches, "width_pitches")
        _validate_positive_integer(self.height_pitches, "height_pitches")
        if self.strip_direction not in (Direction.HORIZONTAL, Direction.VERTICAL):
            raise ValueError(
                "strip_direction must be Direction.HORIZONTAL or VERTICAL."
            )
        if not isinstance(self.pitch_mm, (int, float)) or isinstance(
            self.pitch_mm, bool
        ):
            raise TypeError("pitch_mm must be a positive number.")
        if self.pitch_mm <= 0:
            raise ValueError("pitch_mm must be positive.")
        object.__setattr__(self, "pitch_mm", float(self.pitch_mm))


@dataclass(frozen=True)
class SchemaTerminalVisualization:
    element_name: str
    terminal_name: str
    view_name: str
    net_name: str
    position: tuple[float, float]


@dataclass(frozen=True)
class SchemaNetVisualization:
    net_name: str
    node_views: tuple[NodeView, ...]
    terminal_points: tuple[SchemaTerminalVisualization, ...]
    representative_y: float
    x_min: float
    x_max: float


@dataclass(frozen=True)
class StripboardNetRun:
    net_name: str
    y: int
    start_x: int
    end_x: int
    source_xs: tuple[int, ...]
    compacted: bool = False


@dataclass(frozen=True)
class StripboardCut:
    x: int
    y: int


@dataclass(frozen=True)
class StripboardLocalPoint:
    net_name: str
    x: int
    y: int
    source_x: int


@dataclass(frozen=True)
class StripboardBlocker:
    x: int
    y: int
    element_name: str


@dataclass(frozen=True)
class StripboardNetAssignment:
    """Visualization-derived assignment for the legacy stripboard projection.

    This is a diagnostic layout preview model, not a verified physical layout:
    ys and runs come from schematic net visualizations, while marker xs
    are chosen for readable overlays. It intentionally does not represent real
    footprints, jumpers, or extracted conductor connectivity.
    """

    stripboard: Stripboard
    net_visualizations: tuple[SchemaNetVisualization, ...]
    net_y: dict[str, int]
    used_source_xs: tuple[int, ...]
    x_map: dict[int, int]
    x_offset: int
    x_pitch: float
    left_margin_pitches: int
    right_margin_pitches: int
    net_runs: tuple[StripboardNetRun, ...] = ()
    cuts: tuple[StripboardCut, ...] = ()
    local_points: tuple[StripboardLocalPoint, ...] = ()
    net_x_maps: dict[str, dict[int, int]] = field(default_factory=dict)
    marker_x_maps: dict[tuple[str, ...], int] = field(default_factory=dict)
    blockers: tuple[StripboardBlocker, ...] = ()


@dataclass
class ElementSpec:
    terminals: tuple[str, ...]
    local_anchors: dict[str, tuple[float, float]]
    local_bbox: list[list[float]]
    schemdraw_factory: Callable[[], object]
    positional_terminals: tuple[str, ...] = ()
    bbox_padding: float = DEFAULT_ELEMENT_BBOX_PADDING
    terminal_labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _StripboardOverlayLabelCandidate:
    x: float
    y: float
    text_anchor: str
    rotation_degrees: float


@dataclass(frozen=True)
class _StripboardOverlayLabel:
    class_name: str
    text: str
    x: float
    y: float
    font_size: float
    font_weight: str
    text_anchor: str
    rotation_degrees: float = 0.0
    data_attrs: tuple[tuple[str, str], ...] = ()
    collision_priority: int = 0
    candidates: tuple[_StripboardOverlayLabelCandidate, ...] = ()
    bbox: tuple[float, float, float, float] | None = None


def _two_terminal_spec(factory, height=TWO_TERMINAL_HEIGHT, terminal_labels=None):
    half_width = TWO_TERMINAL_WIDTH / 2.0
    half_height = height / 2.0
    return ElementSpec(
        terminals=("start", "end"),
        local_anchors={
            "start": (0.0, half_height),
            "end": (0.0, -half_height),
        },
        local_bbox=[[-half_width, -half_height], [half_width, half_height]],
        schemdraw_factory=factory,
        positional_terminals=("start", "end"),
        terminal_labels={} if terminal_labels is None else dict(terminal_labels),
    )


class _DualOptocouplerSchematic(elm.ElementCompound):
    """Two optocoupler channels inside one aligned package outline."""

    def setup(self):
        self.add(
            elm.Rect(
                corner1=(-0.75, -DUAL_OPTOCOUPLER_HALF_HEIGHT),
                corner2=(2.25, DUAL_OPTOCOUPLER_HALF_HEIGHT),
                fill="none",
            )
        )
        self.channel_a = self.add(elm.Optocoupler(box=False).at((0.0, 2.1)))
        self.channel_b = self.add(elm.Optocoupler(box=False).at((0.0, -0.6)))
        self.add(elm.Label("A").at((0.75, 1.7)))
        self.add(elm.Label("B").at((0.75, -1.0)))

        self.anchors["center"] = (0.75, 0.0)
        for prefix, channel in (
            ("a", self.channel_a),
            ("b", self.channel_b),
        ):
            for terminal in ("anode", "cathode", "collector", "emitter"):
                self.anchors[f"{prefix}_{terminal}"] = getattr(channel, terminal)


class _HexOpenCollectorBufferSchematic(elm.ElementCompound):
    """Six non-inverting open-collector channels in one DIP-style package."""

    _input_pins = (1, 3, 5, 9, 11, 13)
    _output_pins = (2, 4, 6, 8, 10, 12)

    def setup(self):
        self.add(
            elm.Rect(
                corner1=(-2.0, -3.55),
                corner2=(2.0, 3.55),
                fill="none",
            )
        )
        for channel, (y, input_pin, output_pin) in enumerate(
            zip(
                HEX_OPEN_COLLECTOR_CHANNEL_YS,
                self._input_pins,
                self._output_pins,
            ),
            start=1,
        ):
            self.add(elm.Line().at((-2.4, y)).to((-1.35, y)))
            self.add(elm.Arrow().at((-1.35, y)).to((1.05, y)))
            self.add(elm.Line().at((1.05, y)).to((2.4, y)))
            self.add(
                elm.Label(f"{input_pin}  {channel}A", fontsize=7).at((-1.7, y + 0.22))
            )
            self.add(
                elm.Label(f"{channel}Y  {output_pin}", fontsize=7).at((1.65, y + 0.22))
            )
            self.add(elm.Label("OC", fontsize=7).at((0.65, y + 0.22)))
            self.anchors[f"a{channel}"] = (-2.4, y)
            self.anchors[f"y{channel}"] = (2.4, y)

        self.add(elm.Line().at((0.0, 3.55)).to((0.0, 4.3)))
        self.add(elm.Label("14  VCC", fontsize=7).at((0.4, 3.92)))
        self.add(elm.Line().at((0.0, -3.55)).to((0.0, -4.3)))
        self.add(elm.Label("7  GND", fontsize=7).at((0.4, -3.92)))
        self.anchors["vcc"] = (0.0, 4.3)
        self.anchors["gnd"] = (0.0, -4.3)
        self.anchors["center"] = (0.0, 0.0)


ELEMENT_SPECS = {
    Wire: _two_terminal_spec(elm.Line),
    Resistor: _two_terminal_spec(elm.Resistor),
    Fuse: _two_terminal_spec(elm.Fuse),
    Capacitor: _two_terminal_spec(elm.Capacitor),
    Diode: _two_terminal_spec(
        elm.Diode,
        height=DIODE_HEIGHT,
        terminal_labels={"start": "A", "end": "K"},
    ),
    Zener: _two_terminal_spec(
        elm.Zener,
        height=ZENER_HEIGHT,
        terminal_labels={"start": "A", "end": "K"},
    ),
    PMos: ElementSpec(
        terminals=("source", "gate", "drain"),
        local_anchors={
            "source": (0.0, FET_Y),
            "gate": (-FET_DX, FET_Y - 0.5),
            "drain": (0.0, -FET_Y),
        },
        local_bbox=[[-FET_DX, -FET_Y], [0.35, FET_Y]],
        schemdraw_factory=lambda: elm.PMos(diode=True),
        terminal_labels={"source": "S", "gate": "G", "drain": "D"},
    ),
    BjtNpn: ElementSpec(
        terminals=("base", "collector", "emitter"),
        local_anchors={
            "base": (-BJT_X, 0.0),
            "collector": (0.0, BJT_Y),
            "emitter": (0.0, -BJT_Y),
        },
        local_bbox=[[-BJT_X, -0.72], [0.35, BJT_Y]],
        schemdraw_factory=lambda: elm.BjtNpn(circle=True),
        terminal_labels={"base": "B", "collector": "C", "emitter": "E"},
    ),
    BjtPnp: ElementSpec(
        terminals=("base", "collector", "emitter"),
        local_anchors={
            "base": (-BJT_X, 0.0),
            "collector": (0.0, -BJT_Y),
            "emitter": (0.0, BJT_Y),
        },
        local_bbox=[[-BJT_X, -BJT_Y], [0.35, 0.72]],
        schemdraw_factory=lambda: elm.BjtPnp(circle=True),
        terminal_labels={"base": "B", "collector": "C", "emitter": "E"},
    ),
    DualOptocoupler: ElementSpec(
        terminals=(
            "a_anode",
            "a_cathode",
            "a_collector",
            "a_emitter",
            "b_anode",
            "b_cathode",
            "b_collector",
            "b_emitter",
        ),
        local_anchors={
            "a_anode": (-1.2, 2.1),
            "a_cathode": (-1.2, 0.6),
            "a_collector": (1.2016666666666664, 2.046666666666667),
            "a_emitter": (1.2016666666666664, 0.6533333333333333),
            "b_anode": (-1.2, -0.6),
            "b_cathode": (-1.2, -2.1),
            "b_collector": (1.2016666666666664, -0.6533333333333333),
            "b_emitter": (1.2016666666666664, -2.046666666666667),
        },
        local_bbox=[
            [-DUAL_OPTOCOUPLER_HALF_WIDTH, -DUAL_OPTOCOUPLER_HALF_HEIGHT],
            [DUAL_OPTOCOUPLER_HALF_WIDTH, DUAL_OPTOCOUPLER_HALF_HEIGHT],
        ],
        schemdraw_factory=_DualOptocouplerSchematic,
        terminal_labels={
            "a_anode": "A1",
            "a_cathode": "K1",
            "a_collector": "C1",
            "a_emitter": "E1",
            "b_anode": "A2",
            "b_cathode": "K2",
            "b_collector": "C2",
            "b_emitter": "E2",
        },
    ),
    HexOpenCollectorBuffer: ElementSpec(
        terminals=(
            "vcc",
            "gnd",
            "a1",
            "y1",
            "a2",
            "y2",
            "a3",
            "y3",
            "a4",
            "y4",
            "a5",
            "y5",
            "a6",
            "y6",
        ),
        local_anchors={
            "vcc": (0.0, 4.3),
            "gnd": (0.0, -4.3),
            **{
                terminal: position
                for channel, y in enumerate(HEX_OPEN_COLLECTOR_CHANNEL_YS, start=1)
                for terminal, position in (
                    (f"a{channel}", (-2.4, y)),
                    (f"y{channel}", (2.4, y)),
                )
            },
        },
        local_bbox=[
            [-HEX_OPEN_COLLECTOR_HALF_WIDTH, -HEX_OPEN_COLLECTOR_HALF_HEIGHT],
            [HEX_OPEN_COLLECTOR_HALF_WIDTH, HEX_OPEN_COLLECTOR_HALF_HEIGHT],
        ],
        schemdraw_factory=_HexOpenCollectorBufferSchematic,
        terminal_labels={
            "vcc": "14 VCC",
            "gnd": "7 GND",
            "a1": "1 1A",
            "y1": "2 1Y",
            "a2": "3 2A",
            "y2": "4 2Y",
            "a3": "5 3A",
            "y3": "6 3Y",
            "a4": "9 4A",
            "y4": "8 4Y",
            "a5": "11 5A",
            "y5": "10 5Y",
            "a6": "13 6A",
            "y6": "12 6Y",
        },
    ),
}


@dataclass
class NodeView:
    node_type: NodeType
    name: str
    net: Net
    label: str | None = None
    kind: str | None = None
    label_loc: str = "right"
    position: tuple[float, float] = (0.0, 0.0)
    placement_explicit: bool = False
    rail_direction: Direction | None = None
    rail_length: float | None = None
    rail_anchor: Alignment = Alignment.CENTER

    def get_bounding_box(self):
        if self.rail_direction is not None:
            start, end = _rail_endpoints(self)
            return [
                [min(start[0], end[0]), min(start[1], end[1])],
                [max(start[0], end[0]), max(start[1], end[1])],
            ]
        return [
            [self.position[0], self.position[1]],
            [self.position[0], self.position[1]],
        ]


Node = NodeView


@dataclass
class Anchor:
    owner: object
    name: str

    @property
    def position(self):
        return self.owner.anchor_position(self.name)

    def get_bounding_box(self):
        x, y = self.position
        return [[x, y], [x, y]]

    def point(self):
        return self.position


@dataclass
class ReferencePoint:
    owner: object
    subject: object
    alignment: Alignment

    @property
    def position(self):
        return _aligned_point(self.subject, self.alignment)

    def get_bounding_box(self):
        x, y = self.position
        return [[x, y], [x, y]]

    def point(self):
        return self.position


@dataclass
class Element:
    element_type: ElementType
    name: str
    value: str | None
    terminal_views: dict[str, str]
    terminal_nets: dict[str, str]
    label_loc: str = "auto"
    position: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0

    def __getattr__(self, name):
        element_type = self.__dict__.get("element_type")
        spec = ELEMENT_SPECS.get(element_type)
        if spec is not None and name in spec.terminals:
            return Anchor(self, name)
        raise AttributeError(name)

    def anchor(self, name):
        if name not in _element_spec(self).terminals:
            raise KeyError(f"Unknown anchor {name!r} for {self.name}")
        return Anchor(self, name)

    def local_anchor(self, name):
        try:
            return _element_spec(self).local_anchors[name]
        except KeyError as error:
            raise KeyError(f"Unknown anchor {name!r} for {self.name}") from error

    def anchor_position(self, name):
        return _add_points(
            self.position, _rotate_point(self.local_anchor(name), self.angle)
        )

    def get_bounding_box(self):
        spec = _element_spec(self)
        corners = _box_corners(_padded_box(spec.local_bbox, spec.bbox_padding))
        points = [
            _add_points(self.position, _rotate_point(corner, self.angle))
            for corner in corners
        ]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return [[min(xs), min(ys)], [max(xs), max(ys)]]


@dataclass
class WireSegment:
    start_view: str
    end_view: str
    net_name: str
    name: str = ""

    @property
    def position(self):
        return (0.0, 0.0)


@dataclass
class Schema:
    nets: list[Net]
    node_views: list[NodeView]
    elements: list[Element]
    wires: list[WireSegment]

    @property
    def nodes(self):
        return self.node_views

    def get_bounding_box(self):
        node_views_by_name = _node_views_by_name(self.node_views)
        boxes = [
            *[element.get_bounding_box() for element in self.elements],
            *[node.get_bounding_box() for node in self.node_views],
            *[_wire_bounding_box(wire, node_views_by_name) for wire in self.wires],
        ]
        if not boxes:
            return [[0.0, 0.0], [0.0, 0.0]]
        return [
            [min(box[0][0] for box in boxes), min(box[0][1] for box in boxes)],
            [max(box[1][0] for box in boxes), max(box[1][1] for box in boxes)],
        ]


def create_net(name, kind=DEFAULT_NET_KIND):
    return Net(name=str(name), kind=kind)


def create_stripboard(
    width_pitches,
    height_pitches,
    strip_direction=Direction.HORIZONTAL,
    pitch_mm=2.54,
):
    return Stripboard(
        width_pitches=width_pitches,
        height_pitches=height_pitches,
        strip_direction=strip_direction,
        pitch_mm=pitch_mm,
    )


def create_node(
    node_type,
    name,
    label=None,
    kind=None,
    label_alignment=None,
    net=None,
    **kwargs,
):
    if node_type not in (Dot, Ground):
        raise ValueError("Only Dot and Ground node views are supported in this DSL.")
    if kwargs:
        raise TypeError(f"Unsupported node arguments: {sorted(kwargs)}")
    label_loc = "right"
    if label_alignment is not None:
        label_loc = _label_loc_from_alignment(label_alignment)
    return NodeView(
        node_type=node_type,
        name=name,
        net=_coerce_net(net, default_name=name),
        label=label,
        kind=kind,
        label_loc=label_loc,
    )


def create_rail(node, direction, length, anchor=Alignment.CENTER):
    if not isinstance(node, NodeView):
        raise TypeError("create_rail expects a NodeView.")
    if direction not in (Direction.HORIZONTAL, Direction.VERTICAL):
        raise ValueError("Rail direction must be HORIZONTAL or VERTICAL.")
    if length <= 0:
        raise ValueError("Rail length must be positive.")
    if anchor not in {
        Alignment.CENTER,
        Alignment.LEFT,
        Alignment.RIGHT,
        Alignment.TOP,
        Alignment.BOTTOM,
    }:
        raise ValueError("Rail anchor must be CENTER, LEFT, RIGHT, TOP, or BOTTOM.")

    modified = copy.deepcopy(node)
    modified.rail_direction = direction
    modified.rail_length = float(length)
    modified.rail_anchor = anchor
    return modified


def create_element(
    element_type, name, value=None, *nodes, label_loc="auto", **terminal_nodes
):
    if element_type is Wire:
        return _create_wire_from_element_args(name, nodes, terminal_nodes)

    spec = _spec_for_type(element_type)
    if nodes and terminal_nodes:
        raise TypeError("Use either positional nodes or named terminal nodes.")
    if nodes:
        if len(nodes) != len(spec.positional_terminals):
            raise TypeError(
                f"{element_type.name} expects named terminals: "
                f"{', '.join(spec.terminals)}"
            )
        terminal_nodes = dict(zip(spec.positional_terminals, nodes))

    terminal_nodes = _validate_terminal_views(element_type, terminal_nodes)
    return Element(
        element_type=element_type,
        name=name,
        value=value,
        terminal_views={
            terminal: node_view.name for terminal, node_view in terminal_nodes.items()
        },
        terminal_nets={
            terminal: node_view.net.name
            for terminal, node_view in terminal_nodes.items()
        },
        label_loc=label_loc,
    )


def create_wire(start, end, name=""):
    if not isinstance(start, NodeView) or not isinstance(end, NodeView):
        raise TypeError("create_wire endpoints must be NodeView objects.")
    if start.net.name != end.net.name:
        raise ValueError(
            f"Wire endpoints must be views of the same net: "
            f"{start.name!r} is {start.net.name!r}, "
            f"{end.name!r} is {end.net.name!r}."
        )
    return WireSegment(
        start_view=start.name,
        end_view=end.name,
        net_name=start.net.name,
        name=name,
    )


def create_schema(node_views, elements, wires=None):
    schema_node_views = list(node_views)
    schema_elements = []
    schema_wires = list(wires or [])
    for item in elements:
        if isinstance(item, WireSegment):
            schema_wires.append(item)
        else:
            schema_elements.append(item)

    nets = _validate_schema_items(schema_node_views, schema_elements, schema_wires)
    nets_by_name = {net.name: net for net in nets}
    for node_view in schema_node_views:
        node_view.net = nets_by_name[node_view.net.name]
    return Schema(
        nets=nets,
        node_views=schema_node_views,
        elements=schema_elements,
        wires=schema_wires,
    )


def get_schema_net_visualizations(schema):
    """Collect drawing-derived net points used by the projection preview."""

    if not isinstance(schema, Schema):
        raise TypeError("get_schema_net_visualizations expects a Schema object.")

    node_views_by_name = _node_views_by_name(schema.node_views)
    node_points = _schema_node_points(schema, node_views_by_name)
    visual_nodes_by_net = {net.name: [] for net in schema.nets}
    terminals_by_net = {net.name: [] for net in schema.nets}

    for node_view in schema.node_views:
        point = node_points.get(node_view.name, (node_view.position,))[0]
        visual_node = copy.deepcopy(node_view)
        visual_node.position = point
        visual_node.placement_explicit = True
        visual_nodes_by_net.setdefault(node_view.net.name, []).append(visual_node)

    for element in schema.elements:
        for terminal_name, view_name in element.terminal_views.items():
            net_name = element.terminal_nets[terminal_name]
            terminals_by_net.setdefault(net_name, []).append(
                SchemaTerminalVisualization(
                    element_name=element.name,
                    terminal_name=terminal_name,
                    view_name=view_name,
                    net_name=net_name,
                    position=element.anchor_position(terminal_name),
                )
            )

    visualizations = []
    for net in schema.nets:
        node_views = tuple(visual_nodes_by_net.get(net.name, ()))
        terminal_points = tuple(terminals_by_net.get(net.name, ()))
        points = [
            *[node_view.position for node_view in node_views],
            *[terminal.position for terminal in terminal_points],
        ]
        if not points:
            continue
        visualizations.append(
            SchemaNetVisualization(
                net_name=net.name,
                node_views=node_views,
                terminal_points=terminal_points,
                representative_y=_median(point[1] for point in points),
                x_min=min(point[0] for point in points),
                x_max=max(point[0] for point in points),
            )
        )

    return tuple(
        sorted(
            visualizations,
            key=lambda visualization: (
                visualization.representative_y,
                visualization.net_name,
            ),
        )
    )


def assign_schema_nets_to_stripboard(
    schema,
    left_margin_pitches=1,
    right_margin_pitches=1,
    x_pitch=1.0,
):
    """Create the legacy schematic-to-stripboard projection assignment.

    The returned `StripboardNetAssignment` is derived from schematic drawing
    positions: each visible net starts as one horizontal stripboard y, with
    node and terminal markers snapped to holes. It is a visualization aid and
    placement hint source, not a routed or electrically verified stripboard
    layout.
    """

    _validate_nonnegative_integer(left_margin_pitches, "left_margin_pitches")
    _validate_nonnegative_integer(right_margin_pitches, "right_margin_pitches")
    if not isinstance(x_pitch, (int, float)) or isinstance(x_pitch, bool):
        raise TypeError("x_pitch must be a positive number.")
    if x_pitch <= 0:
        raise ValueError("x_pitch must be positive.")

    net_visualizations = get_schema_net_visualizations(schema)
    markers_by_net = _stripboard_markers_by_net(net_visualizations, x_pitch)
    net_visualizations = tuple(
        visualization
        for visualization in net_visualizations
        if markers_by_net.get(visualization.net_name)
    )
    markers_by_net = {
        visualization.net_name: markers_by_net[visualization.net_name]
        for visualization in net_visualizations
    }
    if not net_visualizations:
        return StripboardNetAssignment(
            stripboard=create_stripboard(1, 1),
            net_visualizations=(),
            net_y={},
            used_source_xs=(),
            x_map={},
            x_offset=left_margin_pitches,
            x_pitch=float(x_pitch),
            left_margin_pitches=left_margin_pitches,
            right_margin_pitches=right_margin_pitches,
        )

    source_xs_by_net = {
        visualization.net_name: tuple(
            sorted(
                {
                    source_x
                    for _marker_key, source_x in markers_by_net[visualization.net_name]
                }
            )
        )
        for visualization in net_visualizations
    }
    used_source_xs = tuple(sorted({x for xs in source_xs_by_net.values() for x in xs}))
    active_width = max(
        len(used_source_xs),
        max(len(markers) for markers in markers_by_net.values()),
    )
    x_map = {
        source_x: left_margin_pitches + index
        for index, source_x in enumerate(used_source_xs)
    }
    board_width = active_width + left_margin_pitches + right_margin_pitches
    board_height = len(net_visualizations)
    x_offset = left_margin_pitches - used_source_xs[0]
    active_start = left_margin_pitches
    active_end = board_width - right_margin_pitches - 1

    board_visualizations = tuple(reversed(net_visualizations))
    net_y = {
        visualization.net_name: y
        for y, visualization in enumerate(board_visualizations)
    }
    net_runs = tuple(
        StripboardNetRun(
            net_name=visualization.net_name,
            y=net_y[visualization.net_name],
            start_x=0,
            end_x=board_width - 1,
            source_xs=source_xs_by_net[visualization.net_name],
        )
        for visualization in board_visualizations
    )
    net_x_maps = {
        net_name: {source_x: x_map[source_x] for source_x in source_xs}
        for net_name, source_xs in source_xs_by_net.items()
    }
    marker_x_maps = {
        marker_key: x
        for net_name, markers in markers_by_net.items()
        for marker_key, x in _unique_marker_x_map(
            markers,
            net_x_maps.get(net_name, {}),
            active_start,
            active_end,
        ).items()
    }

    return StripboardNetAssignment(
        stripboard=create_stripboard(board_width, board_height),
        net_visualizations=board_visualizations,
        net_y=net_y,
        used_source_xs=used_source_xs,
        x_map=x_map,
        x_offset=x_offset,
        x_pitch=float(x_pitch),
        left_margin_pitches=left_margin_pitches,
        right_margin_pitches=right_margin_pitches,
        net_runs=net_runs,
        net_x_maps=net_x_maps,
        marker_x_maps=marker_x_maps,
    )


def compact_sparse_stripboard_tracks(
    assignment,
    min_run_holes=4,
    max_connections_per_sparse_net=3,
    schema=None,
):
    """Compact sparse y tracks inside a stripboard projection assignment.

    This improves the diagnostic overlay by packing low-marker-count nets into
    cut-separated runs. The cuts are projection artifacts until a future
    physical-layout verifier can prove a routed board.
    """

    if not isinstance(assignment, StripboardNetAssignment):
        raise TypeError("assignment must be a StripboardNetAssignment.")
    if schema is not None and not isinstance(schema, Schema):
        raise TypeError("schema must be a Schema object when provided.")
    _validate_positive_integer(min_run_holes, "min_run_holes")
    _validate_positive_integer(
        max_connections_per_sparse_net,
        "max_connections_per_sparse_net",
    )
    if not assignment.net_runs:
        return assignment

    markers_by_net = _stripboard_markers_by_net(
        assignment.net_visualizations,
        assignment.x_pitch,
    )
    if schema is None:
        sparse_net_names = _sparse_stripboard_candidate_net_names(
            assignment,
            markers_by_net,
            max_connections_per_sparse_net,
        )
    else:
        sparse_net_names = _route_checked_sparse_stripboard_net_names(
            schema,
            assignment,
            markers_by_net,
            min_run_holes,
            max_connections_per_sparse_net,
        )

    return _compact_sparse_stripboard_tracks_for_net_names(
        assignment,
        min_run_holes,
        sparse_net_names,
        markers_by_net,
    )


def _compact_sparse_stripboard_tracks_for_net_names(
    assignment,
    min_run_holes,
    sparse_net_names,
    markers_by_net=None,
):
    sparse_net_names = frozenset(sparse_net_names)

    width = assignment.stripboard.width_pitches
    active_start = assignment.left_margin_pitches
    active_end = width - assignment.right_margin_pitches - 1
    active_width = active_end - active_start + 1
    if active_width < min_run_holes:
        raise ValueError(
            "Stripboard active width is too small for min_run_holes; "
            f"active width is {active_width}, min_run_holes is {min_run_holes}."
        )

    visualization_by_net = {
        visualization.net_name: visualization
        for visualization in assignment.net_visualizations
    }
    source_xs_by_net = {
        run.net_name: tuple(run.source_xs) for run in assignment.net_runs
    }
    if markers_by_net is None:
        markers_by_net = _stripboard_markers_by_net(
            assignment.net_visualizations,
            assignment.x_pitch,
        )

    output_tracks = []
    pending_sparse_tracks = []
    for run in sorted(assignment.net_runs, key=lambda item: (item.y, item.start_x)):
        source_xs = source_xs_by_net[run.net_name]
        if run.net_name in sparse_net_names:
            pending_sparse_tracks.append(run.net_name)
            continue
        if pending_sparse_tracks:
            output_tracks.extend(
                _pack_sparse_stripboard_runs(
                    pending_sparse_tracks,
                    source_xs_by_net,
                    markers_by_net,
                    assignment.x_map,
                    active_start,
                    active_end,
                    min_run_holes,
                )
            )
            pending_sparse_tracks = []
        output_tracks.append(
            (
                [
                    StripboardNetRun(
                        net_name=run.net_name,
                        y=0,
                        start_x=0,
                        end_x=width - 1,
                        source_xs=source_xs,
                        compacted=False,
                    )
                ],
                (),
                (),
            )
        )

    if pending_sparse_tracks:
        output_tracks.extend(
            _pack_sparse_stripboard_runs(
                pending_sparse_tracks,
                source_xs_by_net,
                markers_by_net,
                assignment.x_map,
                active_start,
                active_end,
                min_run_holes,
            )
        )

    net_runs = []
    cuts = []
    local_points = []
    net_x_maps = {}
    marker_x_maps = {}
    net_y = {}
    net_visualizations = []
    for y, (track_runs, track_cuts, track_local_points) in enumerate(output_tracks):
        for run in track_runs:
            placed_run = StripboardNetRun(
                net_name=run.net_name,
                y=y,
                start_x=run.start_x,
                end_x=run.end_x,
                source_xs=run.source_xs,
                compacted=run.compacted,
            )
            net_runs.append(placed_run)
            net_y[placed_run.net_name] = y
            if placed_run.compacted:
                net_x_maps[placed_run.net_name] = _run_x_map(placed_run)
                marker_x_maps.update(
                    _spread_marker_x_map(
                        markers_by_net.get(placed_run.net_name, ()),
                        placed_run.start_x,
                        placed_run.end_x,
                    )
                )
            else:
                net_x_maps[placed_run.net_name] = assignment.net_x_maps.get(
                    placed_run.net_name,
                    _run_x_map(placed_run),
                )
                if placed_run.net_name in markers_by_net:
                    marker_x_maps.update(
                        {
                            marker_key: assignment.marker_x_maps.get(
                                marker_key,
                                x,
                            )
                            for marker_key, x in _spread_marker_x_map(
                                markers_by_net[placed_run.net_name],
                                active_start,
                                active_end,
                            ).items()
                        }
                    )
            net_visualizations.append(visualization_by_net[placed_run.net_name])
        for local_point in track_local_points:
            placed_point = StripboardLocalPoint(
                net_name=local_point.net_name,
                y=y,
                x=local_point.x,
                source_x=local_point.source_x,
            )
            local_points.append(placed_point)
            net_y[placed_point.net_name] = y
            net_x_maps[placed_point.net_name] = {placed_point.source_x: placed_point.x}
            markers = markers_by_net.get(placed_point.net_name, ())
            if markers:
                marker_x_maps[markers[0][0]] = placed_point.x
            net_visualizations.append(visualization_by_net[placed_point.net_name])
        for cut in track_cuts:
            cuts.append(StripboardCut(x=cut.x, y=y))

    return StripboardNetAssignment(
        stripboard=create_stripboard(width, len(output_tracks)),
        net_visualizations=tuple(net_visualizations),
        net_y=net_y,
        used_source_xs=assignment.used_source_xs,
        x_map=assignment.x_map,
        x_offset=assignment.x_offset,
        x_pitch=assignment.x_pitch,
        left_margin_pitches=assignment.left_margin_pitches,
        right_margin_pitches=assignment.right_margin_pitches,
        net_runs=tuple(net_runs),
        cuts=tuple(cuts),
        local_points=tuple(local_points),
        net_x_maps=net_x_maps,
        marker_x_maps=marker_x_maps,
    )


def _route_checked_sparse_stripboard_net_names(
    schema,
    assignment,
    markers_by_net,
    min_run_holes,
    max_connections_per_sparse_net,
):
    accepted_net_names = set()
    for net_name in _sparse_stripboard_candidate_net_names(
        assignment,
        markers_by_net,
        max_connections_per_sparse_net,
    ):
        trial_net_names = {*accepted_net_names, net_name}
        trial_assignment = _compact_sparse_stripboard_tracks_for_net_names(
            assignment,
            min_run_holes,
            trial_net_names,
            markers_by_net,
        )
        if _stripboard_assignment_routes_strictly(schema, trial_assignment):
            accepted_net_names.add(net_name)
    return frozenset(accepted_net_names)


def _sparse_stripboard_candidate_net_names(
    assignment,
    markers_by_net,
    max_connections_per_sparse_net,
):
    return tuple(
        run.net_name
        for run in sorted(
            assignment.net_runs,
            key=lambda item: (item.y, item.start_x),
        )
        if len(markers_by_net.get(run.net_name, ())) <= max_connections_per_sparse_net
    )


def _stripboard_assignment_routes_strictly(schema, assignment):
    try:
        compact_stripboard_connections_left(
            schema,
            assignment,
            trim_board=False,
            strict=True,
        )
    except ValueError:
        return False
    return True


def compact_stripboard_connections_left(
    schema,
    assignment,
    trim_board=True,
    use_component_blockers=True,
    strict=True,
):
    """Move projection markers left while preserving readable overlay geometry.

    The pass chooses marker xs and body blockers for the diagnostic
    projection. It is not footprint placement and does not establish physical
    circuit correctness.
    """

    if not isinstance(schema, Schema):
        raise TypeError("compact_stripboard_connections_left expects a Schema object.")
    if not isinstance(assignment, StripboardNetAssignment):
        raise TypeError("assignment must be a StripboardNetAssignment.")
    if not isinstance(trim_board, bool):
        raise TypeError("trim_board must be a bool.")
    if not isinstance(use_component_blockers, bool):
        raise TypeError("use_component_blockers must be a bool.")
    if not isinstance(strict, bool):
        raise TypeError("strict must be a bool.")

    marker_x_maps, blockers = _height_ordered_stripboard_marker_xs(
        schema,
        assignment,
        use_component_blockers=use_component_blockers,
        strict=strict,
    )
    current = replace(
        assignment,
        marker_x_maps=marker_x_maps,
        net_x_maps=_net_x_maps_from_marker_xs(
            assignment,
            marker_x_maps,
        ),
        blockers=blockers,
    )
    if trim_board:
        current = _trim_stripboard_assignment_width(current)
    return current


def permute_stripboard_tracks_for_element_span(
    schema,
    assignment,
    priority_element_names=("Q1", "Q2", "Q3"),
    max_exact_ys=9,
    beam_width=512,
):
    """Reorder projection ys to reduce visual component spans.

    This keeps all marker xs and shared-y net groupings intact. It is a
    readability heuristic for the projection preview, not a routing step.
    """

    if not isinstance(schema, Schema):
        raise TypeError(
            "permute_stripboard_tracks_for_element_span expects a Schema object."
        )
    if not isinstance(assignment, StripboardNetAssignment):
        raise TypeError("assignment must be a StripboardNetAssignment.")
    _validate_positive_integer(max_exact_ys, "max_exact_ys")
    _validate_positive_integer(beam_width, "beam_width")

    y_count = assignment.stripboard.height_pitches
    _validate_stripboard_assignment_ys(assignment)
    if y_count <= 1:
        return assignment

    priority_element_names = frozenset(str(name) for name in priority_element_names)
    y_order = _best_stripboard_y_order(
        schema,
        assignment,
        priority_element_names,
        max_exact_ys,
        beam_width,
    )
    if y_order == tuple(range(y_count)):
        return assignment
    old_to_new = {old_y: new_y for new_y, old_y in enumerate(y_order)}
    return _remap_stripboard_assignment_ys(assignment, old_to_new)


def _best_stripboard_y_order(
    schema,
    assignment,
    priority_element_names,
    max_exact_ys,
    beam_width,
):
    y_count = assignment.stripboard.height_pitches
    y_ids = tuple(range(y_count))
    if y_count <= max_exact_ys:
        return min(
            permutations(y_ids),
            key=lambda y_order: _stripboard_y_order_score(
                schema,
                assignment,
                y_order,
                priority_element_names,
            ),
        )
    return _beam_search_stripboard_y_order(
        schema,
        assignment,
        priority_element_names,
        beam_width,
    )


def _beam_search_stripboard_y_order(
    schema,
    assignment,
    priority_element_names,
    beam_width,
):
    y_count = assignment.stripboard.height_pitches
    partial_orders = [()]
    for _new_y in range(y_count):
        candidates = []
        for partial_order in partial_orders:
            remaining = set(range(y_count)) - set(partial_order)
            candidates.extend((*partial_order, old_y) for old_y in sorted(remaining))
        partial_orders = sorted(
            candidates,
            key=lambda y_order: _stripboard_y_order_prefix_score(
                schema,
                assignment,
                y_order,
                priority_element_names,
            ),
        )[:beam_width]
    return min(
        partial_orders,
        key=lambda y_order: _stripboard_y_order_score(
            schema,
            assignment,
            y_order,
            priority_element_names,
        ),
    )


def _stripboard_y_order_score(
    schema,
    assignment,
    y_order,
    priority_element_names,
):
    old_to_new = {old_y: new_y for new_y, old_y in enumerate(y_order)}
    element_spans = _stripboard_element_y_spans(schema, assignment, old_to_new)
    priority_spans = [
        span
        for element_name, span, _element_type in element_spans
        if element_name in priority_element_names
    ]
    weighted_span = sum(
        _stripboard_element_span_weight(element_type) * span
        for _element_name, span, element_type in element_spans
    )
    movement = sum(abs(old_y - new_y) for new_y, old_y in enumerate(y_order))
    return (
        max(priority_spans, default=0),
        sum(priority_spans),
        weighted_span,
        movement,
        tuple(y_order),
    )


def _stripboard_y_order_prefix_score(
    schema,
    assignment,
    y_order,
    priority_element_names,
):
    old_to_new = {old_y: new_y for new_y, old_y in enumerate(y_order)}
    element_spans = _stripboard_element_y_spans(
        schema,
        assignment,
        old_to_new,
        require_all_terminals_placed=True,
    )
    priority_spans = [
        span
        for element_name, span, _element_type in element_spans
        if element_name in priority_element_names
    ]
    weighted_span = sum(
        _stripboard_element_span_weight(element_type) * span
        for _element_name, span, element_type in element_spans
    )
    movement = sum(abs(old_y - new_y) for new_y, old_y in enumerate(y_order))
    return (
        max(priority_spans, default=0),
        sum(priority_spans),
        weighted_span,
        movement,
        tuple(y_order),
    )


def _stripboard_element_y_spans(
    schema,
    assignment,
    old_to_new,
    require_all_terminals_placed=False,
):
    spans = []
    for element in schema.elements:
        ys = []
        skipped = False
        for net_name in element.terminal_nets.values():
            old_y = assignment.net_y.get(net_name)
            if old_y is None:
                skipped = True
                continue
            new_y = old_to_new.get(old_y)
            if new_y is None:
                skipped = True
                continue
            ys.append(new_y)
        if require_all_terminals_placed and skipped:
            continue
        if len(ys) < 2:
            continue
        spans.append(
            (
                element.name,
                max(ys) - min(ys),
                element.element_type,
            )
        )
    return tuple(spans)


def _stripboard_element_span_weight(element_type):
    if element_type in (
        BjtNpn,
        BjtPnp,
        PMos,
        DualOptocoupler,
        HexOpenCollectorBuffer,
    ):
        return 10
    if element_type in (Resistor, Fuse, Diode, Zener):
        return 3
    if element_type == Capacitor:
        return 1
    return 1


def _validate_stripboard_assignment_ys(assignment):
    y_count = assignment.stripboard.height_pitches
    for net_name, y in assignment.net_y.items():
        _validate_stripboard_y(y, y_count, f"net {net_name!r}")
    for run in assignment.net_runs:
        _validate_stripboard_y(run.y, y_count, f"net run {run.net_name!r}")
    for cut in assignment.cuts:
        _validate_stripboard_y(cut.y, y_count, "stripboard cut")
    for local_point in assignment.local_points:
        _validate_stripboard_y(
            local_point.y,
            y_count,
            f"local point {local_point.net_name!r}",
        )
    for blocker in assignment.blockers:
        _validate_stripboard_y(
            blocker.y,
            y_count,
            f"blocker {blocker.element_name!r}",
        )


def _validate_stripboard_y(y, y_count, label):
    if y not in range(y_count):
        raise ValueError(
            f"Inconsistent stripboard assignment: {label} has y {y}, "
            f"but valid ys are 0..{y_count - 1}."
        )


def _remap_stripboard_assignment_ys(assignment, old_to_new):
    _validate_stripboard_y_map(assignment, old_to_new)
    visualization_indexes = {
        visualization.net_name: index
        for index, visualization in enumerate(assignment.net_visualizations)
    }
    net_y = {net_name: old_to_new[y] for net_name, y in assignment.net_y.items()}
    return replace(
        assignment,
        net_visualizations=tuple(
            sorted(
                assignment.net_visualizations,
                key=lambda visualization: (
                    net_y[visualization.net_name],
                    visualization_indexes[visualization.net_name],
                ),
            )
        ),
        net_y=net_y,
        net_runs=tuple(
            sorted(
                (replace(run, y=old_to_new[run.y]) for run in assignment.net_runs),
                key=lambda run: (run.y, run.start_x, run.net_name),
            )
        ),
        cuts=tuple(
            sorted(
                (replace(cut, y=old_to_new[cut.y]) for cut in assignment.cuts),
                key=lambda cut: (cut.x, cut.y),
            )
        ),
        local_points=tuple(
            sorted(
                (
                    replace(local_point, y=old_to_new[local_point.y])
                    for local_point in assignment.local_points
                ),
                key=lambda local_point: (
                    local_point.y,
                    local_point.x,
                    local_point.net_name,
                ),
            )
        ),
        blockers=tuple(
            sorted(
                (
                    replace(blocker, y=old_to_new[blocker.y])
                    for blocker in assignment.blockers
                ),
                key=lambda blocker: (
                    blocker.y,
                    blocker.x,
                    blocker.element_name,
                ),
            )
        ),
    )


def _validate_stripboard_y_map(assignment, old_to_new):
    y_ids = set(range(assignment.stripboard.height_pitches))
    if set(old_to_new) != y_ids or set(old_to_new.values()) != y_ids:
        raise ValueError(
            "Inconsistent stripboard assignment: y permutation must map "
            "every physical y exactly once."
        )


def snap_schema_to_stripboard(schema, assignment, x_pitch=None):
    if not isinstance(schema, Schema):
        raise TypeError("snap_schema_to_stripboard expects a Schema object.")
    if not isinstance(assignment, StripboardNetAssignment):
        raise TypeError("assignment must be a StripboardNetAssignment.")

    pitch = assignment.x_pitch if x_pitch is None else x_pitch
    if not isinstance(pitch, (int, float)) or isinstance(pitch, bool):
        raise TypeError("x_pitch must be a positive number.")
    if pitch <= 0:
        raise ValueError("x_pitch must be positive.")

    snapped = copy.deepcopy(schema)
    for node_view in snapped.node_views:
        if node_view.net.name not in assignment.net_y:
            continue
        node_view.position = _snap_schema_point_to_stripboard(
            node_view.position,
            node_view.net.name,
            assignment,
            pitch,
        )
        node_view.placement_explicit = True

    for element in snapped.elements:
        translations = []
        for terminal_name, net_name in element.terminal_nets.items():
            if net_name not in assignment.net_y:
                continue
            source = element.anchor_position(terminal_name)
            target = _snap_schema_point_to_stripboard(
                source,
                net_name,
                assignment,
                pitch,
            )
            translations.append((target[0] - source[0], target[1] - source[1]))
        if translations:
            element.position = _add_points(
                element.position,
                (
                    _median(delta[0] for delta in translations),
                    _median(delta[1] for delta in translations),
                ),
            )

    return snapped


def translate(x, y):
    def retval(obj):
        moved = copy.deepcopy(obj)
        _translate_in_place(moved, (float(x), float(y)))
        return moved

    return retval


def rotate(angle, center=None):
    def retval(obj):
        rotated = copy.deepcopy(obj)
        _rotate_in_place(rotated, float(angle), center)
        return rotated

    return retval


def point_at(obj, alignment):
    if alignment not in {
        Alignment.CENTER,
        Alignment.LEFT,
        Alignment.RIGHT,
        Alignment.TOP,
        Alignment.BOTTOM,
        Alignment.TOP_CENTER,
        Alignment.BOTTOM_CENTER,
        Alignment.LEFT_CENTER,
        Alignment.RIGHT_CENTER,
    }:
        raise ValueError(
            "point_at alignment must be CENTER, LEFT, RIGHT, TOP, BOTTOM, "
            "TOP_CENTER, BOTTOM_CENTER, LEFT_CENTER, or RIGHT_CENTER."
        )
    owner = obj.owner if isinstance(obj, (Anchor, ReferencePoint)) else obj
    return ReferencePoint(owner, obj, alignment)


def align_translation(part, to, alignment, axes=None, stack_gap=0):
    dx, dy = _alignment_delta(part, to, alignment, axes=axes, stack_gap=stack_gap)
    return translate(dx, dy)


def align(part, to, alignment, axes=None, stack_gap=0):
    target = part.owner if isinstance(part, (Anchor, ReferencePoint)) else part
    return align_translation(part, to, alignment, axes=axes, stack_gap=stack_gap)(
        target
    )


def modify_label_alignment(element, alignment):
    modified = copy.deepcopy(element)
    modified.label_loc = _label_loc_from_alignment(alignment)
    return modified


def render_schemdraw(
    schema,
    file,
    show=False,
    kind_color_map=None,
    background_color=None,
):
    if Path(file).suffix.lower() != ".svg":
        schemdraw.use("matplotlib")

    node_views_by_name = _node_views_by_name(schema.node_views)
    node_points = _schema_node_points(schema, node_views_by_name)
    net_color_map = _net_colors_by_name(schema, kind_color_map)
    rail_taps = {
        name: []
        for name, (_, node_view, _) in node_points.items()
        if _is_rail(node_view)
    }

    with schemdraw.Drawing(file=file, show=show) as drawing:
        drawing.config(
            unit=2.0,
            inches_per_unit=0.55,
            fontsize=10,
            bgcolor=background_color,
        )

        for wire in schema.wires:
            start, end = _wire_endpoints(wire, node_points, node_views_by_name)
            _record_wire_rail_taps(wire, node_views_by_name, rail_taps, start, end)
            _add_wire(
                drawing,
                start,
                end,
                direct=True,
                color=net_color_map.get(wire.net_name),
            )

        for element in schema.elements:
            for anchor_name, view_name in element.terminal_views.items():
                node_view = node_views_by_name[view_name]
                terminal = element.anchor_position(anchor_name)
                node_point = _node_connection_point(
                    node_view,
                    node_points[node_view.name][0],
                    terminal,
                )
                if _is_rail(node_view):
                    rail_taps[node_view.name].append(node_point)
                _add_wire(
                    drawing,
                    terminal,
                    node_point,
                    direct=_prefers_direct_terminal_wire(element),
                    color=net_color_map.get(element.terminal_nets[anchor_name]),
                )

        for element in schema.elements:
            label = (
                element.name
                if element.value is None
                else f"{element.name}\n{element.value}"
            )
            drawing.add(_schemdraw_element(element))
            if label:
                drawing.add(elm.Label(label).at(_element_label_position(element)))

        for node_name in sorted(node_points):
            point, node_view, terminal_count = node_points[node_name]
            color = net_color_map.get(node_view.net.name)
            if _is_rail(node_view):
                rail = elm.Line().endpoints(*_rail_endpoints(node_view))
                if color:
                    rail = rail.color(color)
                drawing.add(rail)
            if _should_render_node(node_view, terminal_count):
                if node_view.node_type is Ground:
                    ground = elm.Ground().at(point)
                    if color:
                        ground = ground.color(color)
                    if node_view.label:
                        ground = ground.label(node_view.label, loc=node_view.label_loc)
                    drawing.add(ground)
                else:
                    dot = elm.Dot().at(point)
                    if color:
                        dot = dot.color(color).fill(color)
                    if node_view.label:
                        dot = dot.label(node_view.label, loc=node_view.label_loc)
                    drawing.add(dot)
            if _is_rail(node_view):
                for tap in _unique_points(rail_taps.get(node_name, [])):
                    dot = elm.Dot().at(tap)
                    if color:
                        dot = dot.color(color).fill(color)
                    drawing.add(dot)

    if Path(file).suffix == ".svg":
        _strip_trailing_whitespace(file)


def render_stripboard(stripboard, file, scale=32):
    if not isinstance(stripboard, Stripboard):
        raise TypeError("render_stripboard expects a Stripboard object.")
    if stripboard.strip_direction is not Direction.HORIZONTAL:
        raise NotImplementedError("Only horizontal stripboards are supported for now.")

    path = Path(file)
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_svg(stripboard, path, scale=scale)
    elif suffix == ".png":
        _render_stripboard_png(stripboard, path, scale=scale)
    else:
        raise ValueError("Stripboard output file must end in .svg or .png.")


def render_stripboard_overlay(
    stripboard,
    assignment,
    schema,
    file,
    scale=32,
    *,
    kind_color_map=None,
):
    """Render a diagnostic `StripboardNetAssignment` overlay.

    This renderer remains the supported view for the stripboard projection path. It
    visualizes schematic-derived ys, compacted runs, diagnostic cuts, markers,
    labels, and body blockers; it does not imply that the layout has been
    routed or electrically verified.
    """

    if not isinstance(stripboard, Stripboard):
        raise TypeError("render_stripboard_overlay expects a Stripboard object.")
    if not isinstance(assignment, StripboardNetAssignment):
        raise TypeError("assignment must be a StripboardNetAssignment.")
    if not isinstance(schema, Schema):
        raise TypeError("schema must be a Schema.")
    if stripboard.strip_direction is not Direction.HORIZONTAL:
        raise NotImplementedError("Only horizontal stripboards are supported for now.")
    if (
        stripboard.width_pitches != assignment.stripboard.width_pitches
        or stripboard.height_pitches != assignment.stripboard.height_pitches
        or stripboard.strip_direction is not assignment.stripboard.strip_direction
    ):
        raise ValueError("stripboard must match assignment.stripboard dimensions.")

    path = Path(file)
    suffix = path.suffix.lower()
    if suffix == ".svg":
        _render_stripboard_overlay_svg(
            stripboard,
            assignment,
            schema,
            path,
            scale,
            kind_color_map,
        )
    elif suffix == ".png":
        _render_stripboard_overlay_png(
            stripboard,
            assignment,
            schema,
            path,
            scale,
            kind_color_map,
        )
    else:
        raise ValueError("Stripboard overlay output file must end in .svg or .png.")


def _render_stripboard_svg(stripboard, path, scale):
    scale = _validate_render_scale(scale)
    width, height = _stripboard_size(stripboard)
    width_px = width * scale
    height_px = height * scale

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width_px:.0f}" height="{height_px:.0f}" '
            f'viewBox="0 0 {width:.3f} {height:.3f}">'
        ),
        "  <title>Stripboard</title>",
        (
            f'  <rect class="board" x="0" y="0" width="{width:.3f}" '
            f'height="{height:.3f}" fill="{STRIPBOARD_BOARD_FILL}" '
            f'stroke="{STRIPBOARD_BOARD_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        ),
    ]

    for model_y in range(stripboard.height_pitches):
        x, y, strip_width, strip_height = _stripboard_strip_rect(stripboard, model_y)
        lines.append(
            f'  <rect class="copper-strip" data-y="{model_y}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{strip_width:.3f}" '
            f'height="{strip_height:.3f}" fill="{STRIPBOARD_STRIP_FILL}" '
            f'stroke="{STRIPBOARD_STRIP_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )

    for model_x, model_y, x, y in _stripboard_holes(stripboard):
        lines.append(
            f'  <circle class="hole" data-x="{model_x}" data-y="{model_y}" '
            f'cx="{x:.3f}" cy="{y:.3f}" r="{STRIPBOARD_HOLE_RADIUS:.3f}" '
            f'fill="{STRIPBOARD_HOLE_FILL}" stroke="{STRIPBOARD_HOLE_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_stripboard_png(stripboard, path, scale):
    scale = _validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard PNG files."
        ) from error

    width, height = _stripboard_size(stripboard)
    image_width = max(1, int(round(width * scale)))
    image_height = max(1, int(round(height * scale)))
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    draw.rectangle(
        _px_rect(0, 0, width, height, scale),
        fill=STRIPBOARD_BOARD_FILL,
        outline=STRIPBOARD_BOARD_STROKE,
        width=_px_stroke(scale),
    )

    for y in range(stripboard.height_pitches):
        strip_rect = _stripboard_strip_rect(stripboard, y)
        draw.rectangle(
            _px_rect(*strip_rect, scale),
            fill=STRIPBOARD_STRIP_FILL,
            outline=STRIPBOARD_STRIP_STROKE,
            width=_px_stroke(scale),
        )

    radius = STRIPBOARD_HOLE_RADIUS
    for _, _, x, y in _stripboard_holes(stripboard):
        draw.ellipse(
            _px_rect(x - radius, y - radius, radius * 2, radius * 2, scale),
            fill=STRIPBOARD_HOLE_FILL,
            outline=STRIPBOARD_HOLE_STROKE,
            width=_px_stroke(scale),
        )

    image.save(path)


def _render_stripboard_overlay_svg(
    stripboard,
    assignment,
    schema,
    path,
    scale,
    kind_color_map,
):
    scale = _validate_render_scale(scale)
    width, height = _stripboard_size(stripboard)
    label_margin = STRIPBOARD_OVERLAY_NET_LABEL_MARGIN
    overlay_labels = _placed_stripboard_overlay_labels(stripboard, assignment, schema)
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
        "  <title>Stripboard Schematic Overlay</title>",
        (
            f'  <rect class="board" x="0" y="0" width="{width:.3f}" '
            f'height="{height:.3f}" fill="{STRIPBOARD_BOARD_FILL}" '
            f'stroke="{STRIPBOARD_BOARD_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        ),
    ]

    for model_y in range(stripboard.height_pitches):
        x, y, strip_width, strip_height = _stripboard_strip_rect(stripboard, model_y)
        y_net_name = _stripboard_y_net_name(assignment, model_y)
        lines.append(
            f'  <rect class="copper-strip" data-y="{model_y}" '
            f'data-net="{_svg_attr(y_net_name)}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{strip_width:.3f}" '
            f'height="{strip_height:.3f}" fill="{STRIPBOARD_STRIP_FILL}" '
            f'stroke="{STRIPBOARD_STRIP_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )

    for model_x, model_y, x, y in _stripboard_holes(stripboard):
        lines.append(
            f'  <circle class="hole" data-x="{model_x}" data-y="{model_y}" '
            f'cx="{x:.3f}" cy="{y:.3f}" r="{STRIPBOARD_HOLE_RADIUS:.3f}" '
            f'fill="{STRIPBOARD_HOLE_FILL}" stroke="{STRIPBOARD_HOLE_STROKE}" '
            f'stroke-width="{STRIPBOARD_STROKE_WIDTH:.3f}"/>'
        )

    for run in _stripboard_compacted_runs(assignment, stripboard):
        x, y, width, height = _stripboard_run_block_rect(stripboard, run)
        lines.append(
            f'  <rect class="strip-run-block" data-y="{run.y}" '
            f'data-net="{_svg_attr(run.net_name)}" '
            f'x="{x:.3f}" y="{y:.3f}" width="{width:.3f}" '
            f'height="{height:.3f}" fill="none" '
            f'stroke="{STRIPBOARD_RUN_BLOCK_STROKE}" '
            f'stroke-width="{STRIPBOARD_RUN_BLOCK_STROKE_WIDTH:.3f}"/>'
        )

    for cut in assignment.cuts:
        x = _stripboard_x_center(cut.x)
        y = _stripboard_y_center(stripboard, cut.y)
        radius = STRIPBOARD_CUT_RADIUS
        lines.append(
            f'  <circle class="strip-cut" data-y="{cut.y}" '
            f'data-x="{cut.x}" cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{radius:.3f}" fill="none" stroke="{STRIPBOARD_CUT_STROKE}" '
            f'stroke-width="{STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
        )
        for x1, y1, x2, y2 in _cut_cross_lines(x, y, radius):
            lines.append(
                f'  <line class="strip-cut-mark" data-y="{cut.y}" '
                f'data-x="{cut.x}" x1="{x1:.3f}" y1="{y1:.3f}" '
                f'x2="{x2:.3f}" y2="{y2:.3f}" '
                f'stroke="{STRIPBOARD_CUT_STROKE}" '
                f'stroke-width="{STRIPBOARD_CUT_STROKE_WIDTH:.3f}"/>'
            )

    for element_overlay in _stripboard_overlay_elements(schema, assignment):
        for start, end in element_overlay["segments"]:
            lines.append(
                f'  <line class="overlay-element" '
                f'data-element="{_svg_attr(element_overlay["name"])}" '
                f'x1="{start[0]:.3f}" y1="{start[1]:.3f}" '
                f'x2="{end[0]:.3f}" y2="{end[1]:.3f}" '
                f'stroke="{STRIPBOARD_OVERLAY_ELEMENT_STROKE}" '
                f'stroke-width="{STRIPBOARD_OVERLAY_STROKE_WIDTH:.3f}"/>'
            )

    for terminal in _stripboard_overlay_terminals(schema, assignment):
        x, y = terminal["position"]
        lines.append(
            f'  <circle class="overlay-terminal" '
            f'data-net="{_svg_attr(terminal["net_name"])}" '
            f'data-element="{_svg_attr(terminal["element_name"])}" '
            f'data-terminal="{_svg_attr(terminal["terminal_name"])}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{STRIPBOARD_OVERLAY_TERMINAL_RADIUS:.3f}" '
            f'fill="{STRIPBOARD_OVERLAY_TERMINAL_FILL}"/>'
        )

    for marker in _stripboard_overlay_node_markers(schema, assignment):
        x, y = marker["position"]
        color = kind_color(
            marker["net_kind"],
            kind_color_map,
            fallback=STRIPBOARD_OVERLAY_NODE_FILL,
        )
        lines.append(
            f'  <circle class="overlay-node" '
            f'data-net="{_svg_attr(marker["net_name"])}" '
            f'data-node="{_svg_attr(marker["node_name"])}" '
            f'data-net-kind="{_svg_attr(marker["net_kind"])}" '
            f'data-color="{_svg_attr(color)}" '
            f'cx="{x:.3f}" cy="{y:.3f}" '
            f'r="{STRIPBOARD_OVERLAY_NODE_RADIUS:.3f}" '
            f'fill="{color}"/>'
        )

    for label in overlay_labels:
        lines.append(_svg_stripboard_overlay_label(label))

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_stripboard_overlay_png(
    stripboard,
    assignment,
    schema,
    path,
    scale,
    kind_color_map,
):
    scale = _validate_render_scale(scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required to render stripboard overlay PNG files."
        ) from error

    width, height = _stripboard_size(stripboard)
    label_margin = STRIPBOARD_OVERLAY_NET_LABEL_MARGIN
    overlay_labels = _placed_stripboard_overlay_labels(stripboard, assignment, schema)
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
    _draw_stripboard_base_png(ImageDraw.Draw(board_image), stripboard, scale)
    image.paste(board_image, (int(round(label_margin * scale)), 0))

    for run in _stripboard_compacted_runs(assignment, stripboard):
        _draw_stripboard_run_block_png(draw, stripboard, run, label_margin, scale)

    for cut in assignment.cuts:
        _draw_stripboard_cut_png(draw, stripboard, cut, label_margin, scale)

    element_width = _px_overlay_stroke(scale)
    for element_overlay in _stripboard_overlay_elements(schema, assignment):
        for start, end in element_overlay["segments"]:
            draw.line(
                [
                    _px_point(_offset_point(start, label_margin, 0), scale),
                    _px_point(_offset_point(end, label_margin, 0), scale),
                ],
                fill=STRIPBOARD_OVERLAY_ELEMENT_STROKE,
                width=element_width,
            )

    for terminal in _stripboard_overlay_terminals(schema, assignment):
        _draw_px_circle(
            draw,
            _offset_point(terminal["position"], label_margin, 0),
            STRIPBOARD_OVERLAY_TERMINAL_RADIUS,
            scale,
            fill=STRIPBOARD_OVERLAY_TERMINAL_FILL,
        )

    for marker in _stripboard_overlay_node_markers(schema, assignment):
        _draw_px_circle(
            draw,
            _offset_point(marker["position"], label_margin, 0),
            STRIPBOARD_OVERLAY_NODE_RADIUS,
            scale,
            fill=kind_color(
                marker["net_kind"],
                kind_color_map,
                fallback=STRIPBOARD_OVERLAY_NODE_FILL,
            ),
        )

    for label in overlay_labels:
        _draw_stripboard_overlay_label_png(image, label, label_margin, scale)

    image.save(path)


def _draw_stripboard_base_png(draw, stripboard, scale):
    width, height = _stripboard_size(stripboard)
    draw.rectangle(
        _px_rect(0, 0, width, height, scale),
        fill=STRIPBOARD_BOARD_FILL,
        outline=STRIPBOARD_BOARD_STROKE,
        width=_px_stroke(scale),
    )

    for y in range(stripboard.height_pitches):
        strip_rect = _stripboard_strip_rect(stripboard, y)
        draw.rectangle(
            _px_rect(*strip_rect, scale),
            fill=STRIPBOARD_STRIP_FILL,
            outline=STRIPBOARD_STRIP_STROKE,
            width=_px_stroke(scale),
        )

    radius = STRIPBOARD_HOLE_RADIUS
    for _, _, x, y in _stripboard_holes(stripboard):
        draw.ellipse(
            _px_rect(x - radius, y - radius, radius * 2, radius * 2, scale),
            fill=STRIPBOARD_HOLE_FILL,
            outline=STRIPBOARD_HOLE_STROKE,
            width=_px_stroke(scale),
        )


def _stripboard_size(stripboard):
    return float(stripboard.width_pitches), float(stripboard.height_pitches)


def _stripboard_strip_rect(stripboard, y):
    y = _stripboard_y_center(stripboard, y) - STRIPBOARD_STRIP_HEIGHT / 2.0
    x = STRIPBOARD_STRIP_INSET
    width = stripboard.width_pitches - 2 * STRIPBOARD_STRIP_INSET
    return x, y, width, STRIPBOARD_STRIP_HEIGHT


def _stripboard_holes(stripboard):
    for y in range(stripboard.height_pitches):
        for x in range(stripboard.width_pitches):
            yield (
                x,
                y,
                STRIPBOARD_BOARD_MARGIN + x,
                _stripboard_y_center(stripboard, y),
            )


def _stripboard_track_runs(assignment, y):
    return tuple(run for run in assignment.net_runs if run.y == y)


def _stripboard_full_y_label(assignment, stripboard, y):
    runs = _stripboard_track_runs(assignment, y)
    if len(runs) != 1:
        return ""
    run = runs[0]
    if run.start_x == 0 and run.end_x == stripboard.width_pitches - 1:
        return run.net_name
    return ""


def _stripboard_compacted_runs(assignment, stripboard):
    return tuple(
        run
        for run in assignment.net_runs
        if run.compacted
        or run.start_x != 0
        or run.end_x != stripboard.width_pitches - 1
    )


def _stripboard_x_center(x):
    return STRIPBOARD_BOARD_MARGIN + x


def _stripboard_y_center(stripboard, y):
    return STRIPBOARD_BOARD_MARGIN + (stripboard.height_pitches - 1 - y)


def _stripboard_run_center(run):
    return STRIPBOARD_BOARD_MARGIN + (run.start_x + run.end_x) / 2.0


def _stripboard_run_block_rect(stripboard, run):
    x = STRIPBOARD_BOARD_MARGIN + run.start_x - 0.44
    y = _stripboard_y_center(stripboard, run.y) - STRIPBOARD_STRIP_HEIGHT / 2.0 - 0.07
    width = run.end_x - run.start_x + 0.88
    height = STRIPBOARD_STRIP_HEIGHT + 0.14
    return x, y, width, height


def _cut_cross_lines(x, y, radius):
    inset = radius * 0.7
    return (
        (x - inset, y - inset, x + inset, y + inset),
        (x - inset, y + inset, x + inset, y - inset),
    )


def _draw_stripboard_run_block_png(draw, stripboard, run, label_margin, scale):
    x, y, width, height = _stripboard_run_block_rect(stripboard, run)
    draw.rectangle(
        _px_rect(x + label_margin, y, width, height, scale),
        outline=STRIPBOARD_RUN_BLOCK_STROKE,
        width=max(1, int(round(STRIPBOARD_RUN_BLOCK_STROKE_WIDTH * scale))),
    )


def _draw_stripboard_cut_png(draw, stripboard, cut, label_margin, scale):
    x = _stripboard_x_center(cut.x) + label_margin
    y = _stripboard_y_center(stripboard, cut.y)
    radius = STRIPBOARD_CUT_RADIUS
    stroke = max(1, int(round(STRIPBOARD_CUT_STROKE_WIDTH * scale)))
    draw.ellipse(
        _px_rect(x - radius, y - radius, radius * 2, radius * 2, scale),
        outline=STRIPBOARD_CUT_STROKE,
        width=stroke,
    )
    for x1, y1, x2, y2 in _cut_cross_lines(x, y, radius):
        draw.line(
            [_px_point((x1, y1), scale), _px_point((x2, y2), scale)],
            fill=STRIPBOARD_CUT_STROKE,
            width=stroke,
        )


def _placed_stripboard_overlay_labels(stripboard, assignment, schema):
    labels = []

    for model_y in range(stripboard.height_pitches):
        full_y_label = _stripboard_full_y_label(assignment, stripboard, model_y)
        if not full_y_label:
            continue
        x = -0.180
        y = _stripboard_y_center(stripboard, model_y) + 0.135
        labels.append(
            _StripboardOverlayLabel(
                class_name="overlay-net-label",
                text=full_y_label,
                x=x,
                y=y,
                font_size=STRIPBOARD_OVERLAY_NET_LABEL_SIZE,
                font_weight="700",
                text_anchor="end",
                data_attrs=(
                    ("data-y", str(model_y)),
                    ("data-net", full_y_label),
                ),
                collision_priority=0,
            )
        )

    for terminal in _stripboard_overlay_terminals(schema, assignment):
        if not terminal["label"]:
            continue
        x, y = terminal["position"]
        labels.append(
            _StripboardOverlayLabel(
                class_name="overlay-terminal-label",
                text=terminal["label"],
                x=x + 0.155,
                y=y - 0.125,
                font_size=STRIPBOARD_OVERLAY_TERMINAL_LABEL_SIZE,
                font_weight="800",
                text_anchor="middle",
                data_attrs=(
                    ("data-net", terminal["net_name"]),
                    ("data-element", terminal["element_name"]),
                    ("data-terminal", terminal["terminal_name"]),
                ),
                collision_priority=1,
                candidates=_stripboard_terminal_label_candidates(x, y),
            )
        )

    for marker in _stripboard_overlay_node_markers(schema, assignment):
        if not marker["label"]:
            continue
        x, y = marker["position"]
        labels.append(
            _StripboardOverlayLabel(
                class_name="overlay-node-label",
                text=marker["label"],
                x=x + 0.18,
                y=y - 0.16,
                font_size=STRIPBOARD_OVERLAY_NODE_LABEL_SIZE,
                font_weight="700",
                text_anchor="start",
                rotation_degrees=STRIPBOARD_OVERLAY_LABEL_ANGLE,
                data_attrs=(
                    ("data-net", marker["net_name"]),
                    ("data-node", marker["node_name"]),
                ),
                collision_priority=2,
                candidates=_stripboard_node_label_candidates(x, y),
            )
        )

    for element_overlay in _stripboard_overlay_elements(schema, assignment):
        center = element_overlay["center"]
        labels.append(
            _StripboardOverlayLabel(
                class_name="overlay-element-label",
                text=element_overlay["label"],
                x=center[0],
                y=center[1] - 0.18,
                font_size=STRIPBOARD_OVERLAY_ELEMENT_LABEL_SIZE,
                font_weight="700",
                text_anchor="middle",
                rotation_degrees=STRIPBOARD_OVERLAY_LABEL_ANGLE,
                data_attrs=(("data-element", element_overlay["name"]),),
                collision_priority=3,
                candidates=_stripboard_element_label_candidates(center),
            )
        )

    return _resolve_stripboard_overlay_label_xlisions(tuple(labels))


def _stripboard_terminal_label_candidates(x, y):
    return (
        _StripboardOverlayLabelCandidate(x + 0.155, y - 0.125, "middle", 0.0),
        _StripboardOverlayLabelCandidate(x - 0.155, y - 0.125, "middle", 0.0),
        _StripboardOverlayLabelCandidate(x + 0.155, y + 0.230, "middle", 0.0),
        _StripboardOverlayLabelCandidate(x - 0.155, y + 0.230, "middle", 0.0),
        _StripboardOverlayLabelCandidate(x, y - 0.310, "middle", 0.0),
        _StripboardOverlayLabelCandidate(x, y + 0.360, "middle", 0.0),
    )


def _stripboard_node_label_candidates(x, y):
    angle = STRIPBOARD_OVERLAY_LABEL_ANGLE
    return (
        _StripboardOverlayLabelCandidate(x + 0.18, y - 0.16, "start", angle),
        _StripboardOverlayLabelCandidate(x + 0.18, y - 0.38, "start", angle),
        _StripboardOverlayLabelCandidate(x + 0.18, y + 0.12, "start", angle),
        _StripboardOverlayLabelCandidate(x - 0.18, y - 0.16, "end", angle),
        _StripboardOverlayLabelCandidate(x - 0.18, y - 0.38, "end", angle),
        _StripboardOverlayLabelCandidate(x + 0.42, y - 0.24, "start", angle),
        _StripboardOverlayLabelCandidate(x - 0.42, y - 0.24, "end", angle),
    )


def _stripboard_element_label_candidates(center):
    x, y = center
    angle = STRIPBOARD_OVERLAY_LABEL_ANGLE
    offsets = (
        (0.00, -0.18),
        (0.00, -0.44),
        (0.00, 0.14),
        (-0.36, -0.24),
        (0.36, -0.24),
        (-0.58, 0.08),
        (0.58, 0.08),
        (0.00, -0.70),
        (0.00, 0.40),
        (-0.82, -0.06),
        (0.82, -0.06),
        (0.00, -0.96),
        (0.00, 0.72),
        (0.00, 1.00),
        (-1.10, -0.32),
        (1.10, -0.32),
        (-1.10, 0.28),
        (1.10, 0.28),
        (-1.35, -0.60),
        (1.35, -0.60),
        (-1.35, 0.58),
        (1.35, 0.58),
    )
    return tuple(
        _StripboardOverlayLabelCandidate(x + dx, y + dy, "middle", angle)
        for dx, dy in offsets
    )


def _resolve_stripboard_overlay_label_xlisions(labels):
    occupied_rectangles = []
    resolved_by_index = {}
    for index, label in sorted(
        enumerate(labels),
        key=lambda item: (item[1].collision_priority, item[0]),
    ):
        placed_label, bbox = _select_stripboard_overlay_label_candidate(
            label,
            occupied_rectangles,
        )
        occupied_rectangles.append(bbox)
        resolved_by_index[index] = replace(placed_label, bbox=bbox)
    return tuple(resolved_by_index[index] for index in range(len(labels)))


def _select_stripboard_overlay_label_candidate(label, occupied_rectangles):
    candidates = label.candidates or (
        _StripboardOverlayLabelCandidate(
            label.x,
            label.y,
            label.text_anchor,
            label.rotation_degrees,
        ),
    )
    best_candidate = candidates[0]
    best_bbox = _stripboard_overlay_label_bbox(label, best_candidate)
    best_score = _stripboard_overlay_label_xlision_score(
        best_bbox,
        occupied_rectangles,
    )

    for candidate in candidates:
        bbox = _stripboard_overlay_label_bbox(label, candidate)
        score = _stripboard_overlay_label_xlision_score(bbox, occupied_rectangles)
        if score == 0:
            return _stripboard_label_with_candidate(label, candidate), bbox
        if score < best_score:
            best_candidate = candidate
            best_bbox = bbox
            best_score = score

    return _stripboard_label_with_candidate(label, best_candidate), best_bbox


def _stripboard_label_with_candidate(label, candidate):
    return replace(
        label,
        x=candidate.x,
        y=candidate.y,
        text_anchor=candidate.text_anchor,
        rotation_degrees=candidate.rotation_degrees,
    )


def _stripboard_overlay_label_bbox(label, candidate):
    return _estimate_stripboard_text_bbox(
        label.text,
        x=candidate.x,
        y=candidate.y,
        font_size=label.font_size,
        text_anchor=candidate.text_anchor,
        rotation_degrees=candidate.rotation_degrees,
    )


def _stripboard_overlay_label_xlision_score(bbox, occupied_rectangles):
    return sum(
        1
        for rectangle in occupied_rectangles
        if _stripboard_rectangles_overlap(
            bbox,
            rectangle,
            padding=STRIPBOARD_OVERLAY_LABEL_COLLISION_PADDING,
        )
    )


def _estimate_stripboard_text_bbox(
    content,
    *,
    x,
    y,
    font_size,
    text_anchor,
    rotation_degrees=0.0,
):
    width = max(len(str(content)), 1) * font_size * 0.62
    ascent = font_size * 0.82
    descent = font_size * 0.28

    if text_anchor in ("start", "left"):
        left = x
        right = x + width
    elif text_anchor in ("end", "right"):
        left = x - width
        right = x
    else:
        left = x - (width / 2.0)
        right = x + (width / 2.0)

    top = y - ascent
    bottom = y + descent
    corners = (
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
    )
    if rotation_degrees:
        corners = tuple(
            _rotate_around(corner, rotation_degrees, (x, y)) for corner in corners
        )

    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _stripboard_rectangles_overlap(left, right, *, padding=0.0):
    return not (
        left[2] + padding <= right[0]
        or right[2] + padding <= left[0]
        or left[3] + padding <= right[1]
        or right[3] + padding <= left[1]
    )


def _svg_stripboard_overlay_label(label):
    data_attrs = "".join(
        f' {name}="{_svg_attr(value)}"' for name, value in label.data_attrs
    )
    transform = ""
    if label.rotation_degrees:
        transform = (
            f' transform="rotate({label.rotation_degrees:.1f} '
            f'{label.x:.3f} {label.y:.3f})"'
        )
    return (
        f'  <text class="{label.class_name}"{data_attrs} '
        f'x="{label.x:.3f}" y="{label.y:.3f}" '
        f'font-size="{label.font_size:.3f}" '
        f'font-weight="{_svg_attr(label.font_weight)}" '
        f'text-anchor="{_svg_attr(label.text_anchor)}" '
        f'fill="{STRIPBOARD_OVERLAY_TEXT_FILL}" '
        f'stroke="{STRIPBOARD_OVERLAY_TEXT_HALO}" stroke-width="0.075" '
        f'paint-order="stroke"{transform}>'
        f"{_svg_text(label.text)}</text>"
    )


def _draw_stripboard_overlay_label_png(image, label, label_margin, scale):
    _draw_png_text_rotated(
        image,
        (label.x + label_margin, label.y),
        label.text,
        font=_overlay_png_font(scale, label.font_size),
        scale=scale,
        fill=STRIPBOARD_OVERLAY_TEXT_FILL,
        angle=label.rotation_degrees,
        anchor=label.text_anchor,
    )


def _stripboard_overlay_node_markers(schema, assignment):
    node_views_by_name = _node_views_by_name(schema.node_views)
    node_points = _schema_node_points(schema, node_views_by_name)
    markers = []
    for node_view in schema.node_views:
        if node_view.net.name not in assignment.net_y:
            continue
        if not _is_stripboard_physical_node_view(node_view):
            continue
        point = node_points.get(node_view.name, (node_view.position,))[0]
        markers.append(
            {
                "node_name": node_view.name,
                "net_name": node_view.net.name,
                "net_kind": node_view.net.kind,
                "label": node_view.label,
                "position": _stripboard_marker_position(
                    _stripboard_node_marker_key(node_view.name),
                    point,
                    node_view.net.name,
                    assignment,
                ),
            }
        )
    return markers


def _stripboard_overlay_terminals(schema, assignment):
    terminals = []
    for element in schema.elements:
        for terminal_name, net_name in element.terminal_nets.items():
            if net_name not in assignment.net_y:
                continue
            terminals.append(
                {
                    "element_name": element.name,
                    "terminal_name": terminal_name,
                    "net_name": net_name,
                    "label": _stripboard_terminal_overlay_label(
                        element,
                        terminal_name,
                    ),
                    "position": _stripboard_marker_position(
                        _stripboard_terminal_marker_key(element.name, terminal_name),
                        element.anchor_position(terminal_name),
                        net_name,
                        assignment,
                    ),
                }
            )
    return terminals


def _stripboard_terminal_overlay_label(element, terminal_name):
    return _element_spec(element).terminal_labels.get(terminal_name, "")


def _stripboard_overlay_elements(schema, assignment):
    overlays = []
    for element in schema.elements:
        terminal_holes = []
        for terminal_name, net_name in element.terminal_nets.items():
            if net_name not in assignment.net_y:
                continue
            marker_key = _stripboard_terminal_marker_key(element.name, terminal_name)
            x = assignment.marker_x_maps.get(marker_key)
            if x is None:
                x = _snap_schema_x_to_x(
                    element.anchor_position(terminal_name)[0],
                    net_name,
                    assignment,
                    assignment.x_pitch,
                )
            terminal_holes.append((x, assignment.net_y[net_name]))
        if not terminal_holes:
            continue
        label = (
            element.name if element.value is None else f"{element.name} {element.value}"
        )
        segments = tuple(
            (
                _stripboard_hole_position(assignment.stripboard, start),
                _stripboard_hole_position(assignment.stripboard, end),
            )
            for start, end in _stripboard_element_body_segments_from_terminal_holes(
                terminal_holes,
            )
        )
        if len(terminal_holes) == 1:
            center = _stripboard_hole_position(assignment.stripboard, terminal_holes[0])
        elif len(terminal_holes) == 2:
            center = _average_points(
                tuple(
                    _stripboard_hole_position(assignment.stripboard, hole)
                    for hole in terminal_holes
                )
            )
        else:
            center = _stripboard_hole_position(
                assignment.stripboard, _stripboard_terminal_center_hole(terminal_holes)
            )
        overlays.append(
            {
                "name": element.name,
                "label": label,
                "segments": segments,
                "center": center,
            }
        )
    return overlays


def _stripboard_hole_position(stripboard, hole):
    x, y = hole
    return (
        STRIPBOARD_BOARD_MARGIN + x,
        _stripboard_y_center(stripboard, y),
    )


def _stripboard_marker_position(marker_key, point, net_name, assignment):
    x = assignment.marker_x_maps.get(marker_key)
    if x is None:
        return _snap_schema_point_to_stripboard(
            point,
            net_name,
            assignment,
            assignment.x_pitch,
        )
    y = assignment.net_y[net_name]
    return (STRIPBOARD_BOARD_MARGIN + x, _stripboard_y_center(assignment.stripboard, y))


def _snap_schema_point_to_stripboard(point, net_name, assignment, x_pitch):
    x = _snap_schema_x_to_x(point[0], net_name, assignment, x_pitch)
    y = assignment.net_y[net_name]
    return (STRIPBOARD_BOARD_MARGIN + x, _stripboard_y_center(assignment.stripboard, y))


def _snap_schema_x_to_x(x, net_name, assignment, x_pitch):
    source_x = int(round(x / x_pitch))
    if abs(float(x_pitch) - assignment.x_pitch) < EPS:
        net_x_map = assignment.net_x_maps.get(net_name, {})
        x = net_x_map.get(source_x)
        if x is not None:
            return x
        x = assignment.x_map.get(source_x)
        if x is not None:
            return x
    x = source_x + assignment.x_offset
    return int(_clamp(x, 0, assignment.stripboard.width_pitches - 1))


def _height_ordered_stripboard_marker_xs(
    schema,
    assignment,
    use_component_blockers,
    strict,
):
    cut_positions = {(cut.x, cut.y) for cut in assignment.cuts}
    blocker_positions = set()
    blocker_keys = set()
    blockers = []
    marker_x_maps = {}
    used_positions = set()
    body_segments = []

    for item in _stripboard_placement_items(schema, assignment):
        if item["kind"] == "loose":
            entry = item["entries"][0]
            x = _place_loose_stripboard_marker(
                assignment,
                entry,
                used_positions,
                cut_positions,
                blocker_positions,
                strict=strict,
            )
            marker_x_maps[entry["key"]] = x
            used_positions.add((x, entry["y"]))
            continue

        placed_xs, item_blockers, item_segments = _place_stripboard_element_item(
            assignment,
            item,
            used_positions,
            cut_positions,
            blocker_positions,
            body_segments,
            use_component_blockers=use_component_blockers,
            strict=strict,
        )
        for entry in item["entries"]:
            x = placed_xs[entry["key"]]
            marker_x_maps[entry["key"]] = x
            used_positions.add((x, entry["y"]))
        body_segments.extend(item_segments)
        if not use_component_blockers:
            continue
        for blocker in item_blockers:
            blocker_key = (blocker.x, blocker.y, blocker.element_name)
            if blocker_key in blocker_keys:
                continue
            blocker_keys.add(blocker_key)
            blocker_positions.add((blocker.x, blocker.y))
            blockers.append(blocker)

    return marker_x_maps, tuple(
        sorted(
            blockers,
            key=lambda blocker: (blocker.x, blocker.y, blocker.element_name),
        )
    )


def _stripboard_placement_items(schema, assignment):
    marker_entries = _stripboard_assignment_marker_entries(assignment)
    entries_by_key = {entry["key"]: entry for entry in marker_entries}
    terminal_marker_keys = set()
    items = []

    for element in schema.elements:
        element_entries = []
        for terminal_name in element.terminal_nets:
            key = _stripboard_terminal_marker_key(element.name, terminal_name)
            entry = entries_by_key.get(key)
            if entry is None:
                continue
            terminal_marker_keys.add(key)
            element_entries.append(entry)
        if not element_entries:
            continue
        ys = [entry["y"] for entry in element_entries]
        xs = [entry["x"] for entry in element_entries]
        items.append(
            {
                "kind": "element",
                "name": str(element.name),
                "entries": tuple(element_entries),
                "vertical_span": max(ys) - min(ys),
                "terminal_count": len(element_entries),
                "horizontal_span": max(xs) - min(xs),
                "source_left": min(xs),
                "type_rank": 1,
            }
        )

    for entry in marker_entries:
        if entry["key"] in terminal_marker_keys:
            continue
        items.append(
            {
                "kind": "loose",
                "name": _stripboard_marker_key_label(entry["key"]),
                "entries": (entry,),
                "vertical_span": 0,
                "terminal_count": 1,
                "horizontal_span": 0,
                "source_left": entry["x"],
                "type_rank": 0,
            }
        )

    return tuple(
        sorted(
            items,
            key=lambda item: (
                item["type_rank"],
                item["vertical_span"],
                item["terminal_count"],
                item["horizontal_span"],
                item["source_left"],
                item["name"],
            ),
        )
    )


def _place_loose_stripboard_marker(
    assignment,
    entry,
    used_positions,
    cut_positions,
    blocker_positions,
    strict,
):
    y = entry["y"]
    start_x, end_x = _stripboard_marker_allowed_span(assignment, entry)
    for x in range(start_x, end_x + 1):
        if _stripboard_hole_available(
            x,
            y,
            used_positions,
            cut_positions,
            blocker_positions,
        ):
            return x

    if not strict:
        fallback_x = _non_strict_fallback_marker_x(
            entry,
            start_x,
            end_x,
            used_positions,
            cut_positions,
        )
        if fallback_x is not None:
            return fallback_x

    raise ValueError(
        "No legal stripboard hole remains for "
        f"marker {entry['key']!r} on net {entry['net_name']!r} "
        f"at y {y}."
    )


def _place_stripboard_element_item(
    assignment,
    item,
    used_positions,
    cut_positions,
    blocker_positions,
    body_segments,
    use_component_blockers,
    strict,
):
    placement = _best_stripboard_element_placement(
        assignment,
        item,
        used_positions,
        cut_positions,
        blocker_positions,
        body_segments,
        use_component_blockers=use_component_blockers,
        reject_segment_intersections=strict,
    )
    if placement is None and not strict:
        placement = _best_stripboard_element_placement(
            assignment,
            item,
            used_positions,
            cut_positions,
            blocker_positions,
            body_segments,
            use_component_blockers=use_component_blockers,
            enforce_new_blockers=False,
            reject_segment_intersections=False,
        )
    if placement is None and not strict:
        placement = _best_stripboard_element_placement(
            assignment,
            item,
            used_positions,
            cut_positions,
            set(),
            (),
            use_component_blockers=False,
            enforce_new_blockers=False,
            reject_segment_intersections=False,
        )
    if placement is None:
        marker_names = ", ".join(
            _stripboard_marker_key_label(entry["key"]) for entry in item["entries"]
        )
        raise ValueError(
            "No legal stripboard hole remains for "
            f"element {item['name']!r} terminals: {marker_names}."
        )
    return placement


def _best_stripboard_element_placement(
    assignment,
    item,
    used_positions,
    cut_positions,
    blocker_positions,
    body_segments,
    use_component_blockers,
    enforce_new_blockers=True,
    reject_segment_intersections=True,
):
    entries = item["entries"]
    x_ranges = [
        range(*_stripboard_marker_allowed_span_as_stop(assignment, entry))
        for entry in entries
    ]
    best_score = None
    best_xs = None
    best_blockers = None
    best_segments = None

    for xs in product(*x_ranges):
        positions = tuple((x, entry["y"]) for entry, x in zip(entries, xs))
        if len(set(positions)) != len(positions):
            continue
        if any(position in used_positions for position in positions):
            continue
        if any(position in cut_positions for position in positions):
            continue
        if any(position in blocker_positions for position in positions):
            continue

        segments = _stripboard_element_body_segments_from_terminal_holes(positions)
        if reject_segment_intersections and _stripboard_segments_intersect_any(
            segments,
            body_segments,
        ):
            continue

        blockers = ()
        if use_component_blockers:
            blockers = _stripboard_element_blockers_from_terminal_holes(
                item["name"],
                positions,
            )
            if enforce_new_blockers:
                blocker_set = {(blocker.x, blocker.y) for blocker in blockers}
                if blocker_set & used_positions:
                    continue
                if blocker_set & blocker_positions:
                    continue

        score = (
            max(xs) - min(xs),
            _stripboard_terminal_cluster_score(xs),
            min(xs),
            sum(abs(x - entry["x"]) for entry, x in zip(entries, xs)),
            xs,
        )
        if best_score is None or score < best_score:
            best_score = score
            best_xs = xs
            best_blockers = blockers
            best_segments = segments

    if best_xs is None:
        return None
    return (
        {entry["key"]: x for entry, x in zip(entries, best_xs)},
        best_blockers,
        best_segments,
    )


def _stripboard_marker_allowed_span_as_stop(assignment, entry):
    start_x, end_x = _stripboard_marker_allowed_span(assignment, entry)
    return start_x, end_x + 1


def _stripboard_hole_available(
    x,
    y,
    used_positions,
    cut_positions,
    blocker_positions,
):
    position = (x, y)
    return (
        position not in used_positions
        and position not in cut_positions
        and position not in blocker_positions
    )


def _stripboard_marker_key_label(marker_key):
    return ":".join(str(part) for part in marker_key)


def _stripboard_terminal_cluster_score(xs):
    center = _median(xs)
    return sum(abs(x - center) for x in xs)


def _stripboard_element_body_segments_from_terminal_holes(terminal_holes):
    if len(terminal_holes) < 2:
        return ()

    terminal_holes = tuple(terminal_holes)
    if len(terminal_holes) == 2:
        return ((terminal_holes[0], terminal_holes[1]),)

    center = _stripboard_terminal_center_hole(terminal_holes)
    return tuple(
        (terminal_hole, center)
        for terminal_hole in terminal_holes
        if terminal_hole != center
    )


def _stripboard_terminal_center_hole(terminal_holes):
    xs = [x for x, _y in terminal_holes]
    ys = [y for _x, y in terminal_holes]
    return (
        int(round(sum(xs) / len(xs))),
        int(round(sum(ys) / len(ys))),
    )


def _stripboard_element_blockers_from_terminal_holes(element_name, terminal_holes):
    terminal_holes = tuple(terminal_holes)
    if len(terminal_holes) < 2:
        return ()

    terminal_hole_set = set(terminal_holes)
    blocker_holes = set()
    for segment in _stripboard_element_body_segments_from_terminal_holes(
        terminal_holes,
    ):
        for hole in _stripboard_supercover_line_holes(*segment):
            if hole in terminal_hole_set:
                continue
            blocker_holes.add(hole)

    return tuple(
        StripboardBlocker(x=x, y=y, element_name=element_name)
        for x, y in sorted(blocker_holes)
    )


def _stripboard_supercover_line_holes(start, end):
    start_x, start_y = start
    end_x, end_y = end
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    steps = max(abs(delta_y), abs(delta_x))
    if steps == 0:
        return (start,)

    holes = []
    seen = set()
    samples = steps * 4
    for index in range(samples + 1):
        fraction = index / samples
        x = int(round(start_x + delta_x * fraction))
        y = int(round(start_y + delta_y * fraction))
        hole = (x, y)
        if hole in seen:
            continue
        seen.add(hole)
        holes.append(hole)
    return tuple(holes)


def _stripboard_segments_intersect_any(segments, existing_segments):
    for segment in segments:
        for existing_segment in existing_segments:
            if _stripboard_segments_intersect(segment, existing_segment):
                return True
    return False


def _stripboard_segments_intersect(segment_a, segment_b):
    a_start, a_end = segment_a
    b_start, b_end = segment_b
    a1 = _stripboard_hole_xy(a_start)
    a2 = _stripboard_hole_xy(a_end)
    b1 = _stripboard_hole_xy(b_start)
    b2 = _stripboard_hole_xy(b_end)

    orientations = (
        _point_orientation(a1, a2, b1),
        _point_orientation(a1, a2, b2),
        _point_orientation(b1, b2, a1),
        _point_orientation(b1, b2, a2),
    )
    o1, o2, o3, o4 = orientations
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _point_on_segment(a1, b1, a2):
        return True
    if o2 == 0 and _point_on_segment(a1, b2, a2):
        return True
    if o3 == 0 and _point_on_segment(b1, a1, b2):
        return True
    if o4 == 0 and _point_on_segment(b1, a2, b2):
        return True
    return False


def _stripboard_hole_xy(hole):
    return hole


def _point_orientation(first, second, third):
    value = (second[1] - first[1]) * (third[0] - second[0]) - (second[0] - first[0]) * (
        third[1] - second[1]
    )
    if value == 0:
        return 0
    return 1 if value > 0 else 2


def _point_on_segment(first, point, second):
    return min(first[0], second[0]) <= point[0] <= max(first[0], second[0]) and min(
        first[1], second[1]
    ) <= point[1] <= max(first[1], second[1])


def _stripboard_component_blockers(schema, assignment):
    blocker_keys = set()
    blockers = []
    for element in schema.elements:
        terminal_holes = []
        for terminal_name, net_name in element.terminal_nets.items():
            if net_name not in assignment.net_y:
                continue
            marker_key = _stripboard_terminal_marker_key(element.name, terminal_name)
            x = assignment.marker_x_maps.get(marker_key)
            if x is None:
                continue
            terminal_holes.append((x, assignment.net_y[net_name]))

        for blocker in _stripboard_element_blockers_from_terminal_holes(
            element.name,
            terminal_holes,
        ):
            blocker_key = (blocker.x, blocker.y, blocker.element_name)
            if blocker_key in blocker_keys:
                continue
            blocker_keys.add(blocker_key)
            blockers.append(blocker)

    return tuple(
        sorted(
            blockers,
            key=lambda blocker: (blocker.x, blocker.y, blocker.element_name),
        )
    )


def _left_compacted_marker_x_maps(assignment, blockers, strict=True):
    blocker_positions = {(blocker.x, blocker.y) for blocker in blockers}
    cut_positions = {(cut.x, cut.y) for cut in assignment.cuts}
    used_by_y = {}
    marker_x_maps = {}

    marker_entries = sorted(
        _stripboard_assignment_marker_entries(assignment),
        key=lambda entry: (entry["y"], entry["x"], entry["key"]),
    )
    for entry in marker_entries:
        y = entry["y"]
        start_x, end_x = _stripboard_marker_allowed_span(assignment, entry)
        used = used_by_y.setdefault(y, set())
        for x in range(start_x, end_x + 1):
            position = (x, y)
            if position in used:
                continue
            if position in cut_positions:
                continue
            if position in blocker_positions:
                continue
            marker_x_maps[entry["key"]] = x
            used.add(position)
            break
        else:
            if not strict:
                fallback_x = _non_strict_fallback_marker_x(
                    entry,
                    start_x,
                    end_x,
                    used,
                    cut_positions,
                )
                if fallback_x is not None:
                    marker_x_maps[entry["key"]] = fallback_x
                    used.add((fallback_x, y))
                    continue
            raise ValueError(
                "No legal stripboard hole remains for "
                f"marker {entry['key']!r} on net {entry['net_name']!r} "
                f"at y {y}."
            )

    return marker_x_maps


def _non_strict_fallback_marker_x(entry, start_x, end_x, used, cut_positions):
    preferred = entry["x"]
    candidates = [preferred, *range(start_x, end_x + 1)]
    seen = set()
    for x in candidates:
        if x in seen:
            continue
        seen.add(x)
        if x < start_x or x > end_x:
            continue
        position = (x, entry["y"])
        if position in used or position in cut_positions:
            continue
        return x
    return None


def _stripboard_assignment_marker_entries(assignment):
    entries = []
    markers_by_net = _stripboard_markers_by_net(
        assignment.net_visualizations,
        assignment.x_pitch,
    )
    for net_name, markers in markers_by_net.items():
        if net_name not in assignment.net_y:
            continue
        y = assignment.net_y[net_name]
        for marker_key, source_x in markers:
            x = assignment.marker_x_maps.get(marker_key)
            if x is None:
                x = _snap_source_x_to_stripboard(
                    source_x,
                    net_name,
                    assignment,
                )
            entries.append(
                {
                    "key": marker_key,
                    "net_name": net_name,
                    "y": y,
                    "x": x,
                    "source_x": source_x,
                }
            )
    return entries


def _snap_source_x_to_stripboard(source_x, net_name, assignment):
    net_x_map = assignment.net_x_maps.get(net_name, {})
    x = net_x_map.get(source_x)
    if x is not None:
        return x
    x = assignment.x_map.get(source_x)
    if x is not None:
        return x
    return int(
        _clamp(
            source_x + assignment.x_offset,
            0,
            assignment.stripboard.width_pitches - 1,
        )
    )


def _stripboard_marker_allowed_span(assignment, entry):
    active_start = assignment.left_margin_pitches
    active_end = (
        assignment.stripboard.width_pitches - assignment.right_margin_pitches - 1
    )
    active_end = max(active_start, active_end)
    for run in assignment.net_runs:
        if run.net_name != entry["net_name"]:
            continue
        if (
            not run.compacted
            and run.start_x == 0
            and run.end_x == assignment.stripboard.width_pitches - 1
        ):
            return active_start, active_end
        return run.start_x, run.end_x
    return active_start, active_end


def _net_x_maps_from_marker_xs(assignment, marker_x_maps):
    net_x_maps = {}
    for entry in _stripboard_assignment_marker_entries(assignment):
        x = marker_x_maps.get(entry["key"])
        if x is None:
            continue
        net_map = net_x_maps.setdefault(entry["net_name"], {})
        source_x = entry["source_x"]
        existing = net_map.get(source_x)
        if existing is None or x < existing:
            net_map[source_x] = x
    return net_x_maps


def _trim_stripboard_assignment_width(assignment):
    old_width = assignment.stripboard.width_pitches
    rightmost = max(
        [
            assignment.left_margin_pitches,
            *assignment.marker_x_maps.values(),
            *[cut.x for cut in assignment.cuts],
            *[blocker.x for blocker in assignment.blockers],
            *[
                run.end_x
                for run in assignment.net_runs
                if run.compacted or run.start_x != 0 or run.end_x != old_width - 1
            ],
        ]
    )
    new_width = max(
        rightmost + 1 + assignment.right_margin_pitches,
        assignment.left_margin_pitches + assignment.right_margin_pitches + 1,
    )
    if new_width >= old_width:
        return assignment

    net_runs = tuple(
        (
            replace(run, end_x=new_width - 1)
            if (not run.compacted and run.start_x == 0 and run.end_x == old_width - 1)
            else run
        )
        for run in assignment.net_runs
    )
    x_map = {
        source_x: min(x, new_width - 1) for source_x, x in assignment.x_map.items()
    }
    net_x_maps = {
        net_name: {source_x: min(x, new_width - 1) for source_x, x in net_x_map.items()}
        for net_name, net_x_map in assignment.net_x_maps.items()
    }
    return replace(
        assignment,
        stripboard=create_stripboard(
            new_width,
            assignment.stripboard.height_pitches,
            strip_direction=assignment.stripboard.strip_direction,
            pitch_mm=assignment.stripboard.pitch_mm,
        ),
        net_runs=net_runs,
        x_map=x_map,
        net_x_maps=net_x_maps,
    )


def _pack_sparse_stripboard_runs(
    net_names,
    source_xs_by_net,
    markers_by_net,
    x_map,
    active_start,
    active_end,
    min_run_holes,
):
    active_width = active_end - active_start + 1
    ys = []
    track_runs = []
    track_cuts = []
    track_local_points = []
    cursor = active_start

    for net_name in sorted(
        net_names,
        key=lambda name: _sparse_stripboard_run_sort_key(
            name,
            source_xs_by_net,
            markers_by_net,
        ),
    ):
        source_xs = source_xs_by_net[net_name]
        markers = markers_by_net.get(net_name, ())
        marker_count = len(markers)
        is_local_point = marker_count == 1
        item_length = 1 if is_local_point else max(min_run_holes, marker_count)
        if item_length > active_width:
            raise ValueError(
                f"Net {net_name!r} needs {item_length} holes, "
                f"but the active strip width is {active_width}."
            )

        cut_x = cursor if track_runs and not is_local_point else None
        min_start_x = cursor + 1 if cut_x is not None else cursor
        start_x = max(
            min_start_x,
            _preferred_sparse_run_start(
                net_name,
                item_length,
                source_xs_by_net,
                markers_by_net,
                x_map,
                active_start,
                active_end,
            ),
        )
        end_x = start_x + item_length - 1
        if end_x > active_end:
            ys.append((track_runs, tuple(track_cuts), track_local_points))
            track_runs = []
            track_cuts = []
            track_local_points = []
            cursor = active_start
            cut_x = None
            min_start_x = cursor
            start_x = max(
                min_start_x,
                _preferred_sparse_run_start(
                    net_name,
                    item_length,
                    source_xs_by_net,
                    markers_by_net,
                    x_map,
                    active_start,
                    active_end,
                ),
            )
            end_x = start_x + item_length - 1

        if cut_x is not None:
            track_cuts.append(StripboardCut(x=cut_x, y=0))
        if start_x > min_start_x:
            track_cuts.append(StripboardCut(x=start_x - 1, y=0))

        if is_local_point:
            track_local_points.append(
                StripboardLocalPoint(
                    net_name=net_name,
                    y=0,
                    x=start_x,
                    source_x=markers[0][1],
                )
            )
        else:
            track_runs.append(
                StripboardNetRun(
                    net_name=net_name,
                    y=0,
                    start_x=start_x,
                    end_x=end_x,
                    source_xs=source_xs,
                    compacted=True,
                )
            )
        cursor = end_x + 1

    if track_runs or track_local_points:
        ys.append((track_runs, tuple(track_cuts), track_local_points))

    return ys


def _preferred_sparse_run_start(
    net_name,
    item_length,
    source_xs_by_net,
    markers_by_net,
    x_map,
    active_start,
    active_end,
):
    source_xs = tuple(source_xs_by_net.get(net_name, ()))
    markers = tuple(markers_by_net.get(net_name, ()))
    marker_xs = tuple(x for _marker_key, x in markers)
    xs = marker_xs or source_xs
    if not xs:
        return active_start
    mapped_xs = tuple(x_map.get(x, x) for x in xs)
    preferred_center = _median(mapped_xs)
    start_x = int(round(preferred_center - (item_length - 1) / 2))
    return int(_clamp(start_x, active_start, active_end - item_length + 1))


def _sparse_stripboard_run_sort_key(net_name, source_xs_by_net, markers_by_net):
    source_xs = tuple(source_xs_by_net.get(net_name, ()))
    markers = tuple(markers_by_net.get(net_name, ()))
    marker_xs = tuple(x for _marker_key, x in markers)
    xs = marker_xs or source_xs
    if not xs:
        return (0, net_name)
    return (_median(xs), net_name)


def _run_x_map(run):
    source_xs = tuple(run.source_xs)
    if not source_xs:
        return {}
    run_length = run.end_x - run.start_x + 1
    if len(source_xs) == 1:
        return {source_xs[0]: run.start_x + run_length // 2}
    step = (run_length - 1) / (len(source_xs) - 1)
    return {
        source_x: run.start_x + int(round(index * step))
        for index, source_x in enumerate(source_xs)
    }


def _spread_marker_x_map(markers, start_x, end_x):
    markers = tuple(markers)
    if not markers:
        return {}
    available_xs = end_x - start_x + 1
    if len(markers) > available_xs:
        raise ValueError(
            f"Need {len(markers)} unique holes but only {available_xs} "
            "stripboard xs are available."
        )
    if len(markers) == 1:
        return {markers[0][0]: start_x + available_xs // 2}

    step = (available_xs - 1) / (len(markers) - 1)
    return {
        marker_key: start_x + int(round(index * step))
        for index, (marker_key, _source_x) in enumerate(markers)
    }


def _unique_marker_x_map(markers, source_x_map, start_x, end_x):
    marker_map = {}
    used_xs = set()
    for marker_key, source_x in markers:
        preferred = source_x_map.get(source_x)
        if preferred is None:
            preferred = source_x
        preferred = int(_clamp(preferred, start_x, end_x))
        x = preferred
        if x in used_xs:
            x = _nearest_unused_x(preferred, used_xs, start_x, end_x)
        marker_map[marker_key] = x
        used_xs.add(x)
    return marker_map


def _nearest_unused_x(preferred, used_xs, start_x, end_x):
    for distance in range(end_x - start_x + 1):
        left = preferred - distance
        if left >= start_x and left not in used_xs:
            return left
        right = preferred + distance
        if right <= end_x and right not in used_xs:
            return right
    raise ValueError("Need more unique stripboard holes than the y has available xs.")


def _stripboard_markers_by_net(net_visualizations, x_pitch):
    return {
        visualization.net_name: tuple(
            sorted(
                _stripboard_markers_for_visualization(visualization, x_pitch),
                key=lambda marker: (marker[1], marker[0]),
            )
        )
        for visualization in net_visualizations
    }


def _stripboard_markers_for_visualization(visualization, x_pitch):
    for node_view in visualization.node_views:
        if not _is_stripboard_physical_node_view(node_view):
            continue
        yield (
            _stripboard_node_marker_key(node_view.name),
            int(round(node_view.position[0] / x_pitch)),
        )
    for terminal in visualization.terminal_points:
        yield (
            _stripboard_terminal_marker_key(
                terminal.element_name,
                terminal.terminal_name,
            ),
            int(round(terminal.position[0] / x_pitch)),
        )


def _stripboard_node_marker_key(node_name):
    return ("node", str(node_name))


def _is_stripboard_physical_node_view(node_view):
    return node_view.kind not in STRIPBOARD_NON_PHYSICAL_NODE_KINDS


def _stripboard_terminal_marker_key(element_name, terminal_name):
    return ("terminal", str(element_name), str(terminal_name))


def _source_xs_for_visualization(visualization, x_pitch):
    return tuple(
        sorted(
            {
                int(round(point[0] / x_pitch))
                for point in _schema_net_visualization_points((visualization,))
            }
        )
    )


def _schema_net_visualization_points(net_visualizations):
    for visualization in net_visualizations:
        for node_view in visualization.node_views:
            yield node_view.position
        for terminal in visualization.terminal_points:
            yield terminal.position


def _stripboard_y_net_name(assignment, y):
    runs = _stripboard_track_runs(assignment, y)
    if len(runs) == 1:
        return runs[0].net_name
    return ""


def _svg_attr(value):
    return html.escape(str(value), quote=True)


def _svg_text(value):
    return html.escape(str(value), quote=False)


def _px_rect(x, y, width, height, scale):
    return (
        int(round(x * scale)),
        int(round(y * scale)),
        int(round((x + width) * scale)),
        int(round((y + height) * scale)),
    )


def _px_point(point, scale):
    return (int(round(point[0] * scale)), int(round(point[1] * scale)))


def _px_stroke(scale):
    return max(1, int(round(STRIPBOARD_STROKE_WIDTH * scale)))


def _px_overlay_stroke(scale):
    return max(1, int(round(STRIPBOARD_OVERLAY_STROKE_WIDTH * scale)))


def _draw_px_circle(draw, center, radius, scale, fill):
    draw.ellipse(
        _px_rect(
            center[0] - radius,
            center[1] - radius,
            radius * 2,
            radius * 2,
            scale,
        ),
        fill=fill,
    )


def _draw_png_text_centered(draw, center, text, font, scale, fill):
    x, y = _px_point(center, scale)
    if hasattr(draw, "textbbox"):
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
    else:
        width, height = draw.textsize(text, font=font)
    draw.text((x - width // 2, y - height // 2), text, fill=fill, font=font)


def _draw_png_text_rotated(
    image,
    anchor_point,
    text,
    font,
    scale,
    fill,
    angle,
    anchor="center",
):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return

    measure = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    measure_draw = ImageDraw.Draw(measure)
    if hasattr(measure_draw, "textbbox"):
        box = measure_draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
    else:
        width, height = measure_draw.textsize(text, font=font)
    padding = max(3, int(round(0.10 * scale)))
    text_image = Image.new(
        "RGBA",
        (width + padding * 2, height + padding * 2),
        (255, 255, 255, 0),
    )
    text_draw = ImageDraw.Draw(text_image)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                text_draw.text(
                    (padding + dx, padding + dy),
                    text,
                    fill=STRIPBOARD_OVERLAY_TEXT_HALO,
                    font=font,
                )
    text_draw.text((padding, padding), text, fill=fill, font=font)
    resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC")
    rotated = text_image.rotate(angle, expand=True, resample=resampling)

    x, y = _px_point(anchor_point, scale)
    if anchor in ("left", "start"):
        paste_at = (x, y - rotated.height // 2)
    elif anchor in ("right", "end"):
        paste_at = (x - rotated.width, y - rotated.height // 2)
    else:
        paste_at = (x - rotated.width // 2, y - rotated.height // 2)
    image.paste(rotated, paste_at, rotated)


def _overlay_png_font(scale, size_units):
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    size_px = max(10, int(round(size_units * scale)))
    for font_name in (
        "DejaVuSans-Bold.ttf",
        "Arial Bold.ttf",
        "Arial.ttf",
    ):
        try:
            return ImageFont.truetype(font_name, size_px)
        except OSError:
            pass
    return ImageFont.load_default()


def _validate_positive_integer(value, name):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be a positive integer.")
    if value <= 0:
        raise ValueError(f"{name} must be positive.")


def _validate_nonnegative_integer(value, name):
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be a non-negative integer.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")


def _validate_render_scale(scale):
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        raise TypeError("scale must be a positive number.")
    if scale <= 0:
        raise ValueError("scale must be positive.")
    return float(scale)


def _create_wire_from_element_args(name, nodes, terminal_nodes):
    if nodes and terminal_nodes:
        raise TypeError("Use either positional nodes or named wire endpoints.")
    if nodes:
        if len(nodes) != 2:
            raise TypeError("Wire expects two positional endpoint views.")
        return create_wire(nodes[0], nodes[1], name=name)
    provided = set(terminal_nodes)
    if provided != {"start", "end"}:
        raise TypeError("Wire expects start and end endpoint views.")
    return create_wire(terminal_nodes["start"], terminal_nodes["end"], name=name)


def _coerce_net(net, default_name):
    if net is None:
        return create_net(default_name)
    if isinstance(net, Net):
        return net
    if isinstance(net, str):
        return create_net(net)
    raise TypeError("net must be a Net, a net name string, or None.")


def _normalize_net_kind(kind):
    if kind is None:
        return DEFAULT_NET_KIND
    kind = str(kind).strip()
    return kind or DEFAULT_NET_KIND


def _merge_same_name_nets(existing, candidate):
    if existing.kind == candidate.kind:
        return existing
    if existing.kind == DEFAULT_NET_KIND:
        return candidate
    if candidate.kind == DEFAULT_NET_KIND:
        return existing
    raise ValueError(
        f"Net {existing.name!r} has conflicting kinds: "
        f"{existing.kind!r} and {candidate.kind!r}."
    )


def _kind_color_map(kind_color_map=None):
    color_map = dict(DEFAULT_KIND_COLOR_MAP)
    if kind_color_map:
        color_map.update(
            {str(kind): str(color) for kind, color in kind_color_map.items()}
        )
    return color_map


def kind_color(kind, kind_color_map=None, *, fallback=None):
    """Return a display color for a non-default net kind.

    The default kind intentionally returns ``fallback`` so old diagrams remain
    visually unchanged until a net opts into a semantic kind.
    """

    kind = _normalize_net_kind(kind)
    if kind == DEFAULT_NET_KIND:
        return fallback
    color_map = _kind_color_map(kind_color_map)
    return color_map.get(kind, color_map[DEFAULT_NET_KIND])


def net_color(net, kind_color_map=None, *, fallback=None):
    return kind_color(net.kind, kind_color_map, fallback=fallback)


def _net_colors_by_name(schema, kind_color_map=None):
    return {
        net.name: net_color(net, kind_color_map)
        for net in _nets_by_name(schema.node_views).values()
    }


def _alignment_delta(part, to, alignment, axes=None, stack_gap=0):
    if axes is not None and alignment is not Alignment.CENTER:
        raise ValueError("Axis-restricted alignment is only supported for CENTER.")

    use_padded_boxes = _uses_padded_alignment_boxes(alignment)
    moving_box = _get_bounding_box(part, padded=use_padded_boxes)
    target_box = _get_bounding_box(to, padded=use_padded_boxes)
    moving_center = _box_center(moving_box)
    target_center = _box_center(target_box)
    moving_width = moving_box[1][0] - moving_box[0][0]
    moving_height = moving_box[1][1] - moving_box[0][1]

    if alignment is Alignment.CENTER:
        dx = target_center[0] - moving_center[0]
        dy = target_center[1] - moving_center[1]
    elif alignment is Alignment.LEFT:
        dx, dy = target_box[0][0] - moving_box[0][0], 0.0
    elif alignment is Alignment.RIGHT:
        dx, dy = target_box[1][0] - moving_box[1][0], 0.0
    elif alignment is Alignment.TOP:
        dx, dy = 0.0, target_box[1][1] - moving_box[1][1]
    elif alignment is Alignment.BOTTOM:
        dx, dy = 0.0, target_box[0][1] - moving_box[0][1]
    elif alignment is Alignment.TOP_CENTER:
        dx, dy = 0.0, target_center[1] - moving_box[1][1]
    elif alignment is Alignment.BOTTOM_CENTER:
        dx, dy = 0.0, target_center[1] - moving_box[0][1]
    elif alignment is Alignment.LEFT_CENTER:
        dx, dy = target_center[0] - moving_box[0][0], 0.0
    elif alignment is Alignment.RIGHT_CENTER:
        dx, dy = target_center[0] - moving_box[1][0], 0.0
    elif alignment is Alignment.STACK_LEFT:
        dx, dy = target_box[0][0] - moving_box[0][0] - moving_width - stack_gap, 0.0
    elif alignment is Alignment.STACK_RIGHT:
        dx, dy = target_box[1][0] - moving_box[1][0] + moving_width + stack_gap, 0.0
    elif alignment is Alignment.STACK_TOP:
        dx, dy = 0.0, target_box[1][1] - moving_box[1][1] + moving_height + stack_gap
    elif alignment is Alignment.STACK_BOTTOM:
        dx, dy = 0.0, target_box[0][1] - moving_box[0][1] - moving_height - stack_gap
    else:
        raise ValueError(f"Unknown alignment: {alignment}")

    if axes is None:
        return dx, dy
    return (dx if "x" in axes else 0.0, dy if "y" in axes else 0.0)


def _uses_padded_alignment_boxes(alignment):
    return alignment in {
        Alignment.STACK_LEFT,
        Alignment.STACK_RIGHT,
        Alignment.STACK_TOP,
        Alignment.STACK_BOTTOM,
    }


def _translate_in_place(obj, vector):
    if isinstance(obj, NodeView):
        obj.position = _add_points(obj.position, vector)
        obj.placement_explicit = True
    elif isinstance(obj, Element):
        obj.position = _add_points(obj.position, vector)
    elif isinstance(obj, Schema):
        obj.node_views = [translate(*vector)(node) for node in obj.node_views]
        obj.elements = [translate(*vector)(element) for element in obj.elements]
    else:
        raise TypeError(f"Cannot translate {type(obj).__name__}")


def _rotate_in_place(obj, angle, center):
    if isinstance(obj, NodeView):
        if center is not None:
            obj.position = _rotate_around(obj.position, angle, _point(center))
            obj.placement_explicit = True
    elif isinstance(obj, Element):
        if center is not None:
            obj.position = _rotate_around(obj.position, angle, _point(center))
        obj.angle += angle
    elif isinstance(obj, Schema):
        obj.node_views = [rotate(angle, center=center)(node) for node in obj.node_views]
        obj.elements = [
            rotate(angle, center=center)(element) for element in obj.elements
        ]
    else:
        raise TypeError(f"Cannot rotate {type(obj).__name__}")


def _schema_node_points(schema, node_views_by_name):
    terminal_points_by_node = {}
    used_node_names = set()

    for wire in schema.wires:
        for view_name in (wire.start_view, wire.end_view):
            used_node_names.add(view_name)
            node_view = node_views_by_name[view_name]
            terminal_points_by_node.setdefault(view_name, []).append(node_view.position)

    for element in schema.elements:
        for anchor_name, view_name in element.terminal_views.items():
            used_node_names.add(view_name)
            terminal_points_by_node.setdefault(view_name, []).append(
                element.anchor_position(anchor_name)
            )

    return {
        name: (
            _resolved_node_position(node_view, terminal_points_by_node[name]),
            node_view,
            len(terminal_points_by_node[name]),
        )
        for name, node_view in node_views_by_name.items()
        if name in used_node_names
    }


def _resolved_node_position(node_view, terminal_points):
    if _is_rail(node_view):
        return node_view.position
    if node_view.placement_explicit:
        return node_view.position
    if len(terminal_points) > 2:
        return _median_point(terminal_points)
    return _average_points(terminal_points)


def _should_render_node(node_view, terminal_count):
    if _is_rail(node_view):
        return bool(node_view.label) or node_view.node_type is Ground
    if node_view.node_type is Ground:
        return True
    if node_view.label:
        return True
    return terminal_count > 2


def _validate_schema_items(node_views, elements, wires):
    for node_view in node_views:
        if not isinstance(node_view, NodeView):
            raise TypeError(
                "Schema node_views must be NodeView objects, "
                f"got {type(node_view).__name__}."
            )
    node_views_by_name = _node_views_by_name(node_views)
    nets_by_name = _nets_by_name(node_views)

    for element in elements:
        if not isinstance(element, Element):
            raise TypeError(
                f"Schema elements must be Element objects, got {type(element).__name__}."
            )
        for terminal, view_name in element.terminal_views.items():
            node_view = _require_view(node_views_by_name, view_name, element.name)
            expected_net = element.terminal_nets[terminal]
            if node_view.net.name != expected_net:
                raise ValueError(
                    f"Element {element.name!r} terminal {terminal!r} refers to "
                    f"view {view_name!r} as net {expected_net!r}, but the schema "
                    f"view is on net {node_view.net.name!r}."
                )

    for wire in wires:
        if not isinstance(wire, WireSegment):
            raise TypeError(
                f"Schema wires must be WireSegment objects, got {type(wire).__name__}."
            )
        start = _require_view(node_views_by_name, wire.start_view, wire.name or "wire")
        end = _require_view(node_views_by_name, wire.end_view, wire.name or "wire")
        if start.net.name != end.net.name:
            raise ValueError(
                f"Wire {wire.name!r} endpoints are on different nets: "
                f"{start.net.name!r} and {end.net.name!r}."
            )
        if wire.net_name != start.net.name:
            raise ValueError(
                f"Wire {wire.name!r} was created for net {wire.net_name!r}, "
                f"but its schema endpoints are on {start.net.name!r}."
            )

    return list(nets_by_name.values())


def _require_view(node_views_by_name, view_name, owner_name):
    try:
        return node_views_by_name[view_name]
    except KeyError as error:
        raise ValueError(
            f"{owner_name!r} refers to node view {view_name!r}, "
            "but that view is missing from the schema."
        ) from error


def _node_views_by_name(node_views):
    node_views_by_name = {}
    for node_view in node_views:
        if node_view.name in node_views_by_name:
            raise ValueError(f"Duplicate node view name: {node_view.name!r}")
        node_views_by_name[node_view.name] = node_view
    return node_views_by_name


def _nets_by_name(node_views):
    nets_by_name = {}
    for node_view in node_views:
        existing = nets_by_name.get(node_view.net.name)
        if existing is None:
            nets_by_name[node_view.net.name] = node_view.net
            continue
        nets_by_name[node_view.net.name] = _merge_same_name_nets(
            existing,
            node_view.net,
        )
    return nets_by_name


def _schemdraw_element(element):
    spec = _element_spec(element)
    placed = spec.schemdraw_factory()
    if spec.positional_terminals == ("start", "end"):
        return placed.endpoints(element.start.point(), element.end.point())
    return placed.theta(element.angle).anchor("center").at(element.position)


def _is_rail(node_view):
    return node_view.rail_direction is not None


def _wire_endpoints(wire, node_points, node_views_by_name):
    start_view = node_views_by_name[wire.start_view]
    end_view = node_views_by_name[wire.end_view]
    start_point = _node_connection_point(
        start_view,
        node_points[start_view.name][0],
        node_points[end_view.name][0],
    )
    end_point = _node_connection_point(
        end_view,
        node_points[end_view.name][0],
        start_point,
    )
    return start_point, end_point


def _record_wire_rail_taps(wire, node_views_by_name, rail_taps, start, end):
    start_view = node_views_by_name[wire.start_view]
    end_view = node_views_by_name[wire.end_view]
    if _is_rail(start_view):
        rail_taps[start_view.name].append(start)
    if _is_rail(end_view):
        rail_taps[end_view.name].append(end)


def _node_connection_point(node_view, resolved_point, terminal_point):
    if not _is_rail(node_view):
        return resolved_point
    return _project_point_to_rail(node_view, terminal_point)


def _project_point_to_rail(node_view, point):
    start, end = _rail_endpoints(node_view)
    if node_view.rail_direction is Direction.VERTICAL:
        return (
            start[0],
            _clamp(point[1], min(start[1], end[1]), max(start[1], end[1])),
        )
    return (_clamp(point[0], min(start[0], end[0]), max(start[0], end[0])), start[1])


def _rail_endpoints(node_view):
    x, y = node_view.position
    length = float(node_view.rail_length)
    anchor = node_view.rail_anchor

    if node_view.rail_direction is Direction.HORIZONTAL:
        if anchor is Alignment.LEFT:
            return (x, y), (x + length, y)
        if anchor is Alignment.RIGHT:
            return (x - length, y), (x, y)
        return (x - length / 2.0, y), (x + length / 2.0, y)

    if anchor is Alignment.TOP:
        return (x, y), (x, y - length)
    if anchor is Alignment.BOTTOM:
        return (x, y + length), (x, y)
    return (x, y + length / 2.0), (x, y - length / 2.0)


def _add_wire(drawing, start, end, direct=False, color=None):
    if _same_point(start, end):
        return

    def add_line(line_start, line_end):
        line = elm.Line().endpoints(line_start, line_end)
        if color:
            line = line.color(color)
        drawing.add(line)

    if direct:
        add_line(start, end)
        return
    corner = (start[0], end[1])
    if _same_point(start, corner) or _same_point(corner, end):
        add_line(start, end)
        return
    add_line(start, corner)
    add_line(corner, end)


def _prefers_direct_terminal_wire(element):
    return not _is_axis_aligned(element.angle)


def _is_axis_aligned(angle):
    return min(abs(angle % 90.0), abs(90.0 - (angle % 90.0))) < EPS


def _validate_terminal_views(element_type, terminal_nodes):
    spec = _spec_for_type(element_type)
    provided = set(terminal_nodes)
    expected = set(spec.terminals)
    missing = expected - provided
    unexpected = provided - expected
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unexpected:
            details.append(f"unexpected {sorted(unexpected)}")
        raise TypeError(f"{element_type.name} terminal mismatch: {', '.join(details)}")
    for terminal, node_view in terminal_nodes.items():
        if not isinstance(node_view, NodeView):
            raise TypeError(f"Terminal {terminal!r} must connect to a NodeView.")
    return {terminal: terminal_nodes[terminal] for terminal in spec.terminals}


def _get_bounding_box(obj, padded=True):
    if isinstance(obj, (Anchor, ReferencePoint)):
        return obj.get_bounding_box()
    if isinstance(obj, Element):
        if padded:
            return obj.get_bounding_box()
        return _element_visual_bounding_box(obj)
    if isinstance(obj, Schema) and not padded:
        return _schema_visual_bounding_box(obj)
    if isinstance(obj, (NodeView, Schema)):
        return obj.get_bounding_box()
    if obj is None:
        return [[0.0, 0.0], [0.0, 0.0]]
    raise TypeError(f"Cannot get bounding box of {type(obj).__name__}")


def _element_label_position(element):
    box = _element_visual_bounding_box(element)
    center = _box_center(box)
    width = box[1][0] - box[0][0]
    height = box[1][1] - box[0][1]
    loc = element.label_loc
    if loc == "auto":
        loc = "top" if width > height else "right"

    gap = LABEL_GAP
    if loc == "left":
        return (box[0][0] - gap, center[1])
    if loc == "right":
        return (box[1][0] + gap, center[1])
    if loc == "top":
        return (center[0], box[1][1] + gap)
    if loc == "bottom":
        return (center[0], box[0][1] - gap)
    raise ValueError(f"Unknown label_loc: {element.label_loc!r}")


def _label_loc_from_alignment(alignment):
    mapping = {
        Alignment.LEFT: "left",
        Alignment.RIGHT: "right",
        Alignment.TOP: "top",
        Alignment.BOTTOM: "bottom",
    }
    try:
        return mapping[alignment]
    except KeyError as error:
        raise ValueError(
            "Label alignment must be LEFT, RIGHT, TOP, or BOTTOM."
        ) from error


def _element_visual_bounding_box(element):
    corners = _box_corners(_element_spec(element).local_bbox)
    points = [
        _add_points(element.position, _rotate_point(corner, element.angle))
        for corner in corners
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [[min(xs), min(ys)], [max(xs), max(ys)]]


def _schema_visual_bounding_box(schema):
    node_views_by_name = _node_views_by_name(schema.node_views)
    boxes = [
        *[_element_visual_bounding_box(element) for element in schema.elements],
        *[node.get_bounding_box() for node in schema.node_views],
        *[_wire_bounding_box(wire, node_views_by_name) for wire in schema.wires],
    ]
    if not boxes:
        return [[0.0, 0.0], [0.0, 0.0]]
    return [
        [min(box[0][0] for box in boxes), min(box[0][1] for box in boxes)],
        [max(box[1][0] for box in boxes), max(box[1][1] for box in boxes)],
    ]


def _wire_bounding_box(wire, node_views_by_name):
    start = node_views_by_name[wire.start_view].get_bounding_box()
    end = node_views_by_name[wire.end_view].get_bounding_box()
    return [
        [min(start[0][0], end[0][0]), min(start[0][1], end[0][1])],
        [max(start[1][0], end[1][0]), max(start[1][1], end[1][1])],
    ]


def _element_spec(element):
    return _spec_for_type(element.element_type)


def _spec_for_type(element_type):
    try:
        return ELEMENT_SPECS[element_type]
    except KeyError as error:
        raise ValueError(f"Unsupported element type: {element_type}") from error


def _box_corners(box):
    return [
        (box[0][0], box[0][1]),
        (box[0][0], box[1][1]),
        (box[1][0], box[0][1]),
        (box[1][0], box[1][1]),
    ]


def _padded_box(box, padding):
    return [
        [box[0][0] - padding, box[0][1] - padding],
        [box[1][0] + padding, box[1][1] + padding],
    ]


def _box_center(box):
    return ((box[0][0] + box[1][0]) / 2.0, (box[0][1] + box[1][1]) / 2.0)


def _aligned_point(obj, alignment):
    box = _get_bounding_box(obj, padded=False)
    center = _box_center(box)
    if alignment is Alignment.CENTER:
        return center
    if alignment in (Alignment.LEFT, Alignment.LEFT_CENTER):
        return (box[0][0], center[1])
    if alignment in (Alignment.RIGHT, Alignment.RIGHT_CENTER):
        return (box[1][0], center[1])
    if alignment in (Alignment.TOP, Alignment.TOP_CENTER):
        return (center[0], box[1][1])
    if alignment in (Alignment.BOTTOM, Alignment.BOTTOM_CENTER):
        return (center[0], box[0][1])
    raise ValueError(f"Unsupported point alignment: {alignment}")


def _point(value):
    return (float(value[0]), float(value[1]))


def _add_points(a, b):
    return (float(a[0]) + float(b[0]), float(a[1]) + float(b[1]))


def _offset_point(point, dx, dy):
    return (float(point[0]) + float(dx), float(point[1]) + float(dy))


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _unique_points(points):
    unique = []
    for point in points:
        if not any(_same_point(point, existing) for existing in unique):
            unique.append(point)
    return unique


def _strip_trailing_whitespace(path):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")


def _rotate_point(point, angle):
    radians = math.radians(angle)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        point[0] * cosine - point[1] * sine,
        point[0] * sine + point[1] * cosine,
    )


def _rotate_around(point, angle, center):
    shifted = (point[0] - center[0], point[1] - center[1])
    rotated = _rotate_point(shifted, angle)
    return _add_points(center, rotated)


def _average_points(points):
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _median_point(points):
    return (
        _median(point[0] for point in points),
        _median(point[1] for point in points),
    )


def _median(values):
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def _same_point(a, b):
    return abs(a[0] - b[0]) < EPS and abs(a[1] - b[1]) < EPS
