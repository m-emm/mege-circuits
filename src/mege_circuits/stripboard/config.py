"""Config loader and dumper for human-editable stripboard YAML layouts."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import mege_circuits.dsl as dsl
from mege_circuits.circuit import (
    Circuit,
    Component,
    circuit_from_schema,
    export_netlist,
)
from mege_circuits.dsl import Direction, Schema, create_stripboard
from mege_circuits.physical import (
    Footprint,
    Jumper,
    PhysicalLayout,
    PhysicalVerificationReport,
    PlacedComponent,
    PlacedConnector,
    create_manual_stripboard_layout,
    placed_component_pins,
    render_stripboard_layout,
    stripboard_hints_from_schema,
    verify_stripboard_layout,
    write_stripboard_build_outputs,
)

DEFAULT_STRIPBOARD_BASENAME = "stripboard"
COMPACT_TWO_TERMINAL_KINDS = frozenset(("capacitor", "fuse", "resistor"))
TERMINAL_ORDER_BY_KIND = {
    "capacitor": ("start", "end"),
    "fuse": ("start", "end"),
    "resistor": ("start", "end"),
    "zener": ("start", "end"),
    "bjt_npn": ("collector", "base", "emitter"),
    "pmos": ("gate", "drain", "source"),
}
VISIBLE_TERMINAL_ALIASES = {
    "bjt_npn": {
        "b": "base",
        "base": "base",
        "c": "collector",
        "collector": "collector",
        "e": "emitter",
        "emitter": "emitter",
    },
    "pmos": {
        "g": "gate",
        "gate": "gate",
        "d": "drain",
        "drain": "drain",
        "s": "source",
        "source": "source",
    },
    "zener": {
        "a": "start",
        "anode": "start",
        "start": "start",
        "k": "end",
        "cathode": "end",
        "end": "end",
    },
}
OUTPUT_TERMINAL_ALIASES = {
    "bjt_npn": (("c", "collector"), ("b", "base"), ("e", "emitter")),
    "pmos": (("g", "gate"), ("d", "drain"), ("s", "source")),
    "zener": (("a", "start"), ("k", "end")),
}


@dataclass(frozen=True)
class StripboardLayoutProject:
    """Normalized stripboard layout project loaded from YAML."""

    basename: str
    metadata: dict[str, Any]
    source: dict[str, Any]
    color_map: dict[str, str]
    circuit: Circuit
    layout: PhysicalLayout
    report: PhysicalVerificationReport
    fingerprint: str
    expected_fingerprint: str
    source_schema: Schema
    config_path: Path | None = None


class _FlowList(list):
    pass


class _FlowMap(dict):
    pass


class _StripboardYamlDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def _represent_flow_list(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def _represent_flow_map(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


_StripboardYamlDumper.add_representer(_FlowList, _represent_flow_list)
_StripboardYamlDumper.add_representer(_FlowMap, _represent_flow_map)


def circuit_fingerprint(circuit: Circuit) -> str:
    """Return a stable fingerprint for a circuit's canonical netlist."""

    payload = json.dumps(
        export_netlist(circuit),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_stripboard_layout_config(
    config_path: str | Path,
    *,
    allow_source_drift: bool = False,
) -> StripboardLayoutProject:
    """Load, validate, and verify a stripboard layout YAML or JSON file."""

    path = Path(config_path)
    data = _load_raw_config(path)
    return _project_from_data(
        data,
        config_path=path,
        allow_source_drift=allow_source_drift,
    )


def write_stripboard_layout_yaml(
    layout: PhysicalLayout,
    circuit: Circuit,
    file: str | Path,
    *,
    source_factory: str,
    basename: str | None = None,
    metadata: dict[str, Any] | None = None,
    color_map: dict[str, str] | None = None,
    priority_elements=(),
) -> Path:
    """Write a human-editable visible-terminal stripboard YAML file."""

    data = stripboard_layout_yaml_data(
        layout,
        circuit,
        source_factory=source_factory,
        basename=basename,
        metadata=metadata,
        color_map=color_map,
        priority_elements=priority_elements,
    )
    path = Path(file)
    path.write_text(_dump_stripboard_yaml(data), encoding="utf-8")
    return path


def stripboard_layout_yaml_data(
    layout: PhysicalLayout,
    circuit: Circuit,
    *,
    source_factory: str,
    basename: str | None = None,
    metadata: dict[str, Any] | None = None,
    color_map: dict[str, str] | None = None,
    priority_elements=(),
) -> dict[str, Any]:
    """Return visible-terminal YAML data for a verified physical layout."""

    if not isinstance(layout, PhysicalLayout):
        raise TypeError("layout must be a PhysicalLayout object.")
    if not isinstance(circuit, Circuit):
        raise TypeError("circuit must be a Circuit object.")

    source = {
        "factory": str(source_factory),
        "circuit_name": circuit.name,
        "fingerprint": circuit_fingerprint(circuit),
    }
    priority_elements = tuple(str(refdes) for refdes in priority_elements)
    if priority_elements:
        source["priority_elements"] = list(priority_elements)

    data: dict[str, Any] = {
        "basename": str(basename or circuit.name or DEFAULT_STRIPBOARD_BASENAME),
    }
    if metadata:
        data["metadata"] = dict(metadata)
    data["source"] = source
    if color_map:
        data["color_map"] = {str(key): str(value) for key, value in color_map.items()}
    data["board"] = _FlowMap(
        {
            "size": _FlowList(
                [layout.board.width_pitches, layout.board.height_pitches]
            ),
            "pitch_mm": layout.board.pitch_mm,
        }
    )
    data["components"] = _component_yaml_data(layout, circuit)
    data["cuts"] = [
        _FlowList([cut.x, cut.y])
        for cut in sorted(layout.cuts, key=lambda item: (item.x, item.y))
    ]
    semantic_connectors = []
    visual_pins = {}
    for connector in sorted(layout.connectors, key=lambda item: item.name):
        connector_data = _connector_yaml_data(connector, circuit)
        if connector.verify:
            semantic_connectors.append(_FlowMap(connector_data))
        else:
            visual_pins[connector.name] = _FlowMap(
                {key: value for key, value in connector_data.items() if key != "name"}
            )
    if semantic_connectors:
        data["connectors"] = semantic_connectors
    if visual_pins:
        data["pins"] = visual_pins
    data["jumpers"] = [_FlowMap(_jumper_yaml_data(jumper)) for jumper in layout.jumpers]
    return data


def render_stripboard_layout_config(
    config_path: str | Path,
    *,
    output_dir: str | Path,
    basename: str | None = None,
    allow_source_drift: bool = False,
    full_build: bool = False,
    scale: int = 32,
) -> tuple[Path, ...]:
    """Render a verified stripboard YAML config to output files."""

    project = load_stripboard_layout_config(
        config_path,
        allow_source_drift=allow_source_drift,
    )
    if not project.report.ok:
        raise ValueError(project.report.summary())

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = str(basename or project.basename)

    if full_build:
        return write_stripboard_build_outputs(
            project.layout,
            project.circuit,
            output_dir=output_dir,
            stem=stem,
            report=project.report,
            scale=scale,
            kind_color_map=project.color_map,
        ).as_tuple()

    svg_path = output_dir / f"{stem}.svg"
    png_path = output_dir / f"{stem}.png"
    render_stripboard_layout(
        project.layout,
        project.circuit,
        file=svg_path,
        scale=scale,
        kind_color_map=project.color_map,
    )
    render_stripboard_layout(
        project.layout,
        project.circuit,
        file=png_path,
        scale=scale,
        kind_color_map=project.color_map,
    )
    return svg_path, png_path


def _load_raw_config(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw_text)
    else:
        data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got: {type(data).__name__}")
    return data


def _project_from_data(
    data: dict[str, Any],
    *,
    config_path: Path | None,
    allow_source_drift: bool,
) -> StripboardLayoutProject:
    source = _load_source_mapping(data.get("source"))
    schema, circuit = _source_schema_and_circuit(source, config_path)
    expected_fingerprint = str(source["fingerprint"])
    fingerprint = circuit_fingerprint(circuit)
    if fingerprint != expected_fingerprint and not allow_source_drift:
        raise ValueError(
            "Source fingerprint mismatch: YAML expects "
            f"{expected_fingerprint}, current source is {fingerprint}."
        )

    layout = _layout_from_yaml_data(data, schema, circuit)
    report = verify_stripboard_layout(layout, circuit)
    metadata = data.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a mapping")
    color_map = _load_color_map(data.get("color_map"))
    return StripboardLayoutProject(
        basename=str(data.get("basename", circuit.name or DEFAULT_STRIPBOARD_BASENAME)),
        metadata=dict(metadata),
        source=source,
        color_map=color_map,
        circuit=circuit,
        layout=layout,
        report=report,
        fingerprint=fingerprint,
        expected_fingerprint=expected_fingerprint,
        source_schema=schema,
        config_path=config_path,
    )


def _load_source_mapping(raw_source: Any) -> dict[str, Any]:
    if not isinstance(raw_source, dict):
        raise ValueError("source must be a mapping")
    factory = raw_source.get("factory")
    fingerprint = raw_source.get("fingerprint")
    if not factory:
        raise ValueError("source.factory is required")
    if not fingerprint:
        raise ValueError("source.fingerprint is required")
    source = dict(raw_source)
    source["factory"] = str(factory)
    source["fingerprint"] = str(fingerprint)
    if "priority_elements" in source and source["priority_elements"] is not None:
        if not isinstance(source["priority_elements"], list):
            raise ValueError("source.priority_elements must be a list")
        source["priority_elements"] = [
            str(refdes) for refdes in source["priority_elements"]
        ]
    return source


def _source_schema_and_circuit(
    source: dict[str, Any],
    config_path: Path | None,
) -> tuple[Schema, Circuit]:
    factory = _import_source_factory(
        source["factory"],
        base_dir=None if config_path is None else config_path.parent,
    )
    schema = factory()
    if not isinstance(schema, Schema):
        raise TypeError("source.factory must return a mege_circuits.dsl.Schema object")
    circuit = circuit_from_schema(
        schema,
        name=source.get("circuit_name"),
    )
    return schema, circuit


def _import_source_factory(factory_spec: str, *, base_dir: Path | None):
    if ":" not in factory_spec:
        raise ValueError(
            "source.factory must be 'module:function' or 'path.py:function'"
        )
    module_spec, function_name = factory_spec.rsplit(":", 1)
    if not module_spec or not function_name:
        raise ValueError(
            "source.factory must be 'module:function' or 'path.py:function'"
        )

    module = _import_source_module(module_spec, base_dir=base_dir)
    factory = getattr(module, function_name, None)
    if factory is None or not callable(factory):
        raise ValueError(f"source.factory function {function_name!r} was not found")
    return factory


def _import_source_module(module_spec: str, *, base_dir: Path | None):
    path_like = module_spec.endswith(".py") or "/" in module_spec
    if path_like:
        path = Path(module_spec)
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        path = path.resolve()
        if not path.exists():
            raise ValueError(f"source.factory module file does not exist: {path}")
        module_name = f"_mege_circuits_stripboard_source_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot import source factory module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    inserted_path = None
    if base_dir is not None:
        inserted_path = str(base_dir)
        if inserted_path not in sys.path:
            sys.path.insert(0, inserted_path)
    try:
        return importlib.import_module(module_spec)
    finally:
        if inserted_path is not None and sys.path and sys.path[0] == inserted_path:
            sys.path.pop(0)


def _load_color_map(raw_color_map: Any) -> dict[str, str]:
    color_map = dict(dsl.DEFAULT_KIND_COLOR_MAP)
    if raw_color_map is None:
        return color_map
    if not isinstance(raw_color_map, dict):
        raise ValueError("color_map must be a mapping")
    color_map.update({str(key): str(value) for key, value in raw_color_map.items()})
    return color_map


def _layout_from_yaml_data(data: dict[str, Any], schema: Schema, circuit: Circuit):
    board = _load_board(data.get("board"))
    components_by_refdes = {
        component.refdes: component for component in circuit.components
    }
    footprints, placements = _load_component_placements(
        data.get("components"),
        components_by_refdes,
    )
    cuts = tuple(_as_grid_point(cut, context="cuts[]") for cut in data.get("cuts", ()))
    hints = stripboard_hints_from_schema(
        schema,
        priority_element_names=tuple(
            data.get("source", {}).get("priority_elements", ())
        ),
    )
    connectors = _load_connectors(data, circuit, hints)
    jumpers = _load_jumpers(data.get("jumpers", ()), circuit)
    return create_manual_stripboard_layout(
        circuit,
        board=board,
        footprints=footprints,
        placements=placements,
        cuts=cuts,
        jumpers=jumpers,
        connectors=connectors,
    )


def _load_board(raw_board: Any):
    if not isinstance(raw_board, dict):
        raise ValueError("board must be a mapping")
    size = raw_board.get("size")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise ValueError("board.size must be [width, height]")
    width = _as_int(size[0], context="board.size[0]")
    height = _as_int(size[1], context="board.size[1]")
    pitch_mm = float(raw_board.get("pitch_mm", 2.54))
    direction = str(raw_board.get("strip_direction", "horizontal")).lower()
    if direction != "horizontal":
        raise ValueError("Only horizontal stripboards are supported")
    return create_stripboard(
        width,
        height,
        strip_direction=Direction.HORIZONTAL,
        pitch_mm=pitch_mm,
    )


def _load_component_placements(raw_components: Any, components_by_refdes):
    if not isinstance(raw_components, dict):
        raise ValueError("components must be a mapping of refdes to coordinates")
    expected = set(components_by_refdes)
    actual = {str(refdes) for refdes in raw_components}
    if actual != expected:
        missing = tuple(sorted(expected - actual))
        unexpected = tuple(sorted(actual - expected))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unknown {unexpected}")
        raise ValueError(
            f"components must cover source components: {', '.join(details)}"
        )

    footprints = []
    placements = {}
    for refdes, raw_placement in raw_components.items():
        refdes = str(refdes)
        component = components_by_refdes[refdes]
        terminal_holes = _component_terminal_holes_from_yaml(component, raw_placement)
        footprint_name = f"yaml_{refdes}"
        origin = terminal_holes[_component_terminal_order(component)[0]]
        pins = {
            terminal_name: (
                hole[0] - origin[0],
                hole[1] - origin[1],
            )
            for terminal_name, hole in terminal_holes.items()
        }
        footprints.append(
            Footprint(
                name=footprint_name,
                component_kinds=(component.kind,),
                pins=pins,
                allowed_rotations=(0,),
            )
        )
        placements[refdes] = PlacedComponent(
            refdes=refdes,
            footprint_name=footprint_name,
            origin=origin,
            rotation=0,
        )
    return tuple(footprints), placements


def _component_terminal_holes_from_yaml(component: Component, raw_placement: Any):
    terminal_order = _component_terminal_order(component)
    if isinstance(raw_placement, list):
        if not _component_uses_compact_yaml(component):
            raise ValueError(
                f"Component {component.refdes!r} must use a terminal-label mapping."
            )
        if len(raw_placement) != len(terminal_order):
            raise ValueError(
                f"Component {component.refdes!r} needs {len(terminal_order)} holes."
            )
        return {
            terminal_name: _as_grid_point(
                raw_placement[index],
                context=f"components.{component.refdes}[{index}]",
            )
            for index, terminal_name in enumerate(terminal_order)
        }

    if not isinstance(raw_placement, dict):
        raise ValueError(
            f"components.{component.refdes} must be a coordinate list or mapping"
        )
    terminal_holes = {}
    alias_map = _terminal_aliases(component)
    for raw_key, raw_hole in raw_placement.items():
        terminal_name = alias_map.get(str(raw_key).lower(), str(raw_key))
        if terminal_name in terminal_holes:
            raise ValueError(
                f"Component {component.refdes!r} defines terminal "
                f"{terminal_name!r} more than once."
            )
        terminal_holes[terminal_name] = _as_grid_point(
            raw_hole,
            context=f"components.{component.refdes}.{raw_key}",
        )
    expected = set(terminal_order)
    actual = set(terminal_holes)
    if actual != expected:
        missing = tuple(sorted(expected - actual))
        unexpected = tuple(sorted(actual - expected))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unknown {unexpected}")
        raise ValueError(
            f"Component {component.refdes!r} terminal labels are incomplete: "
            f"{', '.join(details)}."
        )
    return terminal_holes


def _component_uses_compact_yaml(component: Component):
    return (
        component.kind in COMPACT_TWO_TERMINAL_KINDS and len(component.terminals) == 2
    )


def _component_terminal_order(component: Component):
    available = {terminal.name for terminal in component.terminals}
    preferred = tuple(
        terminal
        for terminal in TERMINAL_ORDER_BY_KIND.get(component.kind, ())
        if terminal in available
    )
    rest = tuple(sorted(available - set(preferred)))
    return (*preferred, *rest)


def _terminal_aliases(component: Component):
    aliases = dict(VISIBLE_TERMINAL_ALIASES.get(component.kind, {}))
    for terminal in component.terminals:
        aliases.setdefault(terminal.name.lower(), terminal.name)
    return aliases


def _load_connectors(data: dict[str, Any], circuit: Circuit, hints):
    source_net_names = dict(hints.connector_net_names)
    source_labels = dict(hints.connector_labels)
    source_net_kinds = dict(hints.connector_net_kinds)
    connectors = []
    for index, raw_connector in enumerate(data.get("connectors", ()) or ()):
        if not isinstance(raw_connector, dict):
            raise ValueError(f"connectors[{index}] must be a mapping")
        name = str(raw_connector.get("name", ""))
        if not name:
            raise ValueError(f"connectors[{index}].name is required")
        is_source = name in source_net_names
        verify = bool(raw_connector.get("verify", is_source))
        net_name = str(raw_connector.get("net", source_net_names.get(name, "")))
        net_kind = _connector_kind_from_yaml(
            raw_connector,
            fallback=source_net_kinds.get(name, dsl.DEFAULT_NET_KIND),
        )
        connectors.append(
            PlacedConnector(
                name=name,
                net_name=net_name,
                hole=_as_grid_point(
                    raw_connector.get("at"), context=f"connectors[{index}].at"
                ),
                label=raw_connector.get("label", source_labels.get(name, name)),
                kind=str(raw_connector.get("kind", "nail")),
                net_kind=net_kind,
                verify=verify,
                color=raw_connector.get("color"),
            )
        )
    raw_pins = data.get("pins", {}) or {}
    if not isinstance(raw_pins, dict):
        raise ValueError("pins must be a mapping of name to visual pin data")
    for name, raw_pin in raw_pins.items():
        if isinstance(raw_pin, (list, tuple)):
            raw_pin = {"at": raw_pin}
        if not isinstance(raw_pin, dict):
            raise ValueError(f"pins.{name} must be a mapping or [x, y]")
        connectors.append(
            PlacedConnector(
                name=str(name),
                net_name=str(raw_pin.get("net", "")),
                hole=_as_grid_point(raw_pin.get("at"), context=f"pins.{name}.at"),
                label=raw_pin.get("label", str(name)),
                kind=str(raw_pin.get("kind", "pin")),
                net_kind=_connector_kind_from_yaml(raw_pin),
                verify=bool(raw_pin.get("verify", False)),
                color=raw_pin.get("color"),
            )
        )

    return tuple(connectors)


def _connector_kind_from_yaml(raw_data: dict[str, Any], *, fallback=None):
    value = raw_data.get("type", raw_data.get("net_kind", fallback))
    if value is None:
        return dsl.DEFAULT_NET_KIND
    return str(value)


def _load_jumpers(raw_jumpers: Any, circuit: Circuit):
    if raw_jumpers is None:
        return ()
    if not isinstance(raw_jumpers, (list, tuple)):
        raise ValueError("jumpers must be a list")
    net_names = {net.name for net in circuit.nets}
    jumpers = []
    for index, raw_jumper in enumerate(raw_jumpers):
        if not isinstance(raw_jumper, dict):
            raise ValueError(f"jumpers[{index}] must be a mapping")
        net_name = str(raw_jumper.get("net", ""))
        verify_net = bool(raw_jumper.get("verify", net_name in net_names))
        jumpers.append(
            Jumper(
                start=_as_grid_point(
                    raw_jumper.get("from"), context=f"jumpers[{index}].from"
                ),
                end=_as_grid_point(
                    raw_jumper.get("to"), context=f"jumpers[{index}].to"
                ),
                net_name=net_name,
                kind=str(
                    raw_jumper.get("type", raw_jumper.get("kind", dsl.DEFAULT_NET_KIND))
                ),
                color=raw_jumper.get("color"),
                verify_net=verify_net,
            )
        )
    return tuple(jumpers)


def _component_yaml_data(layout: PhysicalLayout, circuit: Circuit):
    pins_by_refdes = {}
    for pin in placed_component_pins(layout, circuit):
        pins_by_refdes.setdefault(pin.refdes, {})[pin.terminal_name] = pin.hole

    components = {}
    for component in sorted(circuit.components, key=lambda item: item.refdes):
        terminal_order = _component_terminal_order(component)
        terminal_holes = pins_by_refdes[component.refdes]
        if _component_uses_compact_yaml(component):
            components[component.refdes] = _FlowList(
                [
                    _FlowList(list(terminal_holes[terminal_name]))
                    for terminal_name in terminal_order
                ]
            )
            continue

        items = _output_terminal_aliases(component, terminal_order)
        components[component.refdes] = _FlowMap(
            {
                alias: _FlowList(list(terminal_holes[terminal_name]))
                for alias, terminal_name in items
            }
        )
    return components


def _output_terminal_aliases(component: Component, terminal_order):
    aliases = OUTPUT_TERMINAL_ALIASES.get(component.kind)
    if aliases is None:
        return tuple((terminal_name, terminal_name) for terminal_name in terminal_order)
    available = set(terminal_order)
    return tuple(item for item in aliases if item[1] in available)


def _connector_yaml_data(connector: PlacedConnector, circuit: Circuit):
    data: dict[str, Any] = {
        "name": connector.name,
        "at": _FlowList(list(connector.hole)),
    }
    if connector.net_name:
        data["net"] = connector.net_name
    if connector.label is not None:
        data["label"] = connector.label
    net_kind = _connector_display_kind(connector, circuit)
    if net_kind != dsl.DEFAULT_NET_KIND:
        data["type"] = net_kind
    if connector.color is not None:
        data["color"] = connector.color
    if not connector.verify:
        data["verify"] = False
    return data


def _connector_display_kind(connector: PlacedConnector, circuit: Circuit):
    if connector.net_kind != dsl.DEFAULT_NET_KIND:
        return connector.net_kind
    for net in circuit.nets:
        if net.name == connector.net_name:
            return net.kind
    return dsl.DEFAULT_NET_KIND


def _jumper_yaml_data(jumper: Jumper):
    data: dict[str, Any] = {
        "from": _FlowList(list(jumper.start)),
        "to": _FlowList(list(jumper.end)),
    }
    if jumper.net_name:
        data["net"] = jumper.net_name
    if jumper.kind != dsl.DEFAULT_NET_KIND:
        data["type"] = jumper.kind
    if jumper.color is not None:
        data["color"] = jumper.color
    if not jumper.verify_net:
        data["verify"] = False
    return data


def _dump_stripboard_yaml(data: dict[str, Any]):
    text = yaml.dump(
        data,
        Dumper=_StripboardYamlDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
    )
    coordinate_note = (
        "################\n"
        "# Note on the coordinate system:\n"
        "# The origin (0,0) is at the bottom-left corner\n"
        "# coordinates are [ X, Y ]\n"
        "# X increasing to the right\n"
        "# Y increasing upwards\n"
        "# ##############\n"
    )
    text = text.replace("\nboard:", f"\n{coordinate_note}board:", 1)
    return text + "\n"


def _as_grid_point(value: Any, *, context: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{context} must be [x, y], got: {value!r}")
    return (
        _as_int(value[0], context=f"{context}[0]"),
        _as_int(value[1], context=f"{context}[1]"),
    )


def _as_int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value
