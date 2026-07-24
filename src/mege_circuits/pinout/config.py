"""Config loader for pinout diagrams."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .catalog import load_component_catalog
from .svg import DEFAULT_COLOR_MAP, DEFAULT_SVG_MARGINS_PX, SvgMarginsPx


@dataclass(frozen=True)
class DiscreteComponentPlacement:
    """One component installed between existing pinout contacts."""

    ref: str
    kind: str
    value: str
    terminals: dict[str, str]
    part: str | None = None
    pinout_variant: str | None = None


@dataclass(frozen=True)
class DiscretePinGroup:
    """Named collection of pin sets used to orient a discrete top view."""

    id: str
    label: str
    pin_sets: tuple[str, ...]


@dataclass(frozen=True)
class PinoutBox:
    """Shared physical outline drawn in every pinout view."""

    id: str
    label: str
    top_left: tuple[float, float]
    size_pitches: tuple[float, float]


class PinoutDownholderKind(str, Enum):
    """Semantic retention choice for one physical pinout component."""

    CORNER = "corner"
    CENTER_STRIP = "center_strip"
    PERIMETER_FRAME = "perimeter_frame"
    PIN_LINE_CLAMP = "pin_line_clamp"
    PIN_LINE_UPHOLDER = "pin_line_upholder"
    NONE = "none"


@dataclass(frozen=True)
class PinoutPhysicalComponent:
    """Pin-set ownership and retention semantics for one real component."""

    id: str
    component_type: str
    pin_sets: tuple[str, ...]
    through_pin_sets: tuple[str, ...]
    downholder: PinoutDownholderKind
    label: str | None = None
    box_id: str | None = None


@dataclass(frozen=True)
class DiscreteViewConfig:
    """Presentation settings for a component-placement top view."""

    title: str
    notes_text: str | None
    groups: tuple[DiscretePinGroup, ...]
    anchor_labels: dict[str, str]


@dataclass(frozen=True)
class PinoutProject:
    """Normalized pinout project loaded from config."""

    pin_positions: dict[str, tuple[float, float]]
    connections: list[dict[str, Any]]
    color_map: dict[str, str]
    basename: str
    version_label: str | None = None
    notes_text: str | None = None
    svg_margins_px: SvgMarginsPx = DEFAULT_SVG_MARGINS_PX
    pin_sets: dict[str, tuple[str, ...]] | None = None
    discrete_pin_numbers: dict[str, str] | None = None
    component_placements: tuple[DiscreteComponentPlacement, ...] = ()
    discrete_view: DiscreteViewConfig | None = None
    boxes: tuple[PinoutBox, ...] = ()
    physical_components: tuple[PinoutPhysicalComponent, ...] = ()


def _as_xy(value: Any, *, context: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{context} must be [x, y], got: {value!r}")
    return float(value[0]), float(value[1])


def _load_raw_config(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw_text)
    else:
        data = yaml.safe_load(raw_text)

    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got: {type(data).__name__}")
    return data


def _normalize_discrete_pin_numbers(
    raw_numbers: Any,
    *,
    pin_count: int,
    context: str,
) -> tuple[str, ...] | None:
    if raw_numbers is None:
        return None
    if not isinstance(raw_numbers, dict):
        raise ValueError(f"{context} must be a mapping with start/step keys")

    unknown_keys = sorted(set(raw_numbers) - {"start", "step"})
    if unknown_keys:
        raise ValueError(f"Unknown {context} keys: {unknown_keys}")
    if "start" not in raw_numbers:
        raise ValueError(f"{context}.start is required")

    start = raw_numbers["start"]
    step = raw_numbers.get("step", 1)
    if isinstance(start, bool) or not isinstance(start, int):
        raise ValueError(f"{context}.start must be an integer")
    if isinstance(step, bool) or not isinstance(step, int) or step == 0:
        raise ValueError(f"{context}.step must be a non-zero integer")
    return tuple(str(start + step * index) for index in range(pin_count))


def _expand_pin_sets(
    pin_sets: Any,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, tuple[str, ...]],
    dict[str, str],
]:
    if pin_sets is None:
        return {}, {}, {}
    if not isinstance(pin_sets, list):
        raise ValueError("pin_sets must be a list")

    generated: dict[str, tuple[float, float]] = {}
    named_pin_sets: dict[str, tuple[str, ...]] = {}
    discrete_pin_numbers: dict[str, str] = {}
    direction_vectors = {
        "up": (0.0, 1.0),
        "down": (0.0, -1.0),
        "right": (1.0, 0.0),
        "left": (-1.0, 0.0),
    }

    for idx, pin_set in enumerate(pin_sets):
        if not isinstance(pin_set, dict):
            raise ValueError(f"pin_sets[{idx}] must be a mapping")

        origin = _as_xy(pin_set.get("origin"), context=f"pin_sets[{idx}].origin")
        names = pin_set.get("pins", pin_set.get("names"))
        if not isinstance(names, list) or not names:
            raise ValueError(f"pin_sets[{idx}] requires non-empty pins/names list")

        pin_set_id_value = pin_set.get("id")
        pin_set_id = str(pin_set_id_value) if pin_set_id_value is not None else None
        if pin_set_id is not None:
            if not pin_set_id:
                raise ValueError(f"pin_sets[{idx}].id must not be empty")
            if pin_set_id in named_pin_sets:
                raise ValueError(f"Duplicate pin_sets id: {pin_set_id}")

        direction = str(pin_set.get("direction", "up")).lower()
        if direction not in direction_vectors:
            raise ValueError(
                f"pin_sets[{idx}].direction must be one of {list(direction_vectors)}"
            )

        step = float(pin_set.get("step", 1.0))
        if step <= 0:
            raise ValueError(f"pin_sets[{idx}].step must be > 0")

        prefix = str(pin_set.get("prefix", ""))
        number_labels = _normalize_discrete_pin_numbers(
            pin_set.get("discrete_pin_numbers"),
            pin_count=len(names),
            context=f"pin_sets[{idx}].discrete_pin_numbers",
        )
        dx, dy = direction_vectors[direction]
        generated_names = []
        for pos, name_value in enumerate(names):
            name = str(name_value)
            pin_name = f"{prefix}{name}" if prefix else name
            pin_pos = (origin[0] + dx * pos * step, origin[1] + dy * pos * step)
            if pin_name in generated:
                raise ValueError(f"Duplicate pin generated by pin_sets: {pin_name}")
            generated[pin_name] = pin_pos
            generated_names.append(pin_name)
            if number_labels is not None:
                discrete_pin_numbers[pin_name] = number_labels[pos]

        if pin_set_id is not None:
            named_pin_sets[pin_set_id] = tuple(generated_names)

    return generated, named_pin_sets, discrete_pin_numbers


def _load_explicit_pins(raw_pins: Any) -> dict[str, tuple[float, float]]:
    if raw_pins is None:
        return {}
    if not isinstance(raw_pins, dict):
        raise ValueError("pins must be a mapping of pin_name: [x, y]")

    pins: dict[str, tuple[float, float]] = {}
    for pin_name, raw_xy in raw_pins.items():
        pins[str(pin_name)] = _as_xy(raw_xy, context=f"pins.{pin_name}")
    return pins


def _raise_if_duplicate_pin_coordinates(
    pin_positions: dict[str, tuple[float, float]],
) -> None:
    coordinate_to_pins: dict[tuple[float, float], list[str]] = {}
    for pin_name, pin_position in pin_positions.items():
        coordinate_to_pins.setdefault(pin_position, []).append(pin_name)

    duplicate_coordinate_groups = [
        (coordinate, sorted(pin_names))
        for coordinate, pin_names in coordinate_to_pins.items()
        if len(pin_names) > 1
    ]
    if not duplicate_coordinate_groups:
        return

    duplicate_coordinate_groups.sort(key=lambda item: (item[0][0], item[0][1], item[1]))
    details = "; ".join(
        f"{coordinate}: {', '.join(pin_names)}"
        for coordinate, pin_names in duplicate_coordinate_groups
    )
    raise ValueError(f"Duplicate pin coordinates detected: {details}")


def _normalize_connections(raw_connections: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_connections, list) or not raw_connections:
        raise ValueError("wires/connections must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    for i, wire in enumerate(raw_connections):
        if not isinstance(wire, dict):
            raise ValueError(f"wire[{i}] must be a mapping")
        if "from" not in wire or "to" not in wire:
            raise ValueError(f"wire[{i}] must define 'from' and 'to'")

        normalized_wire: dict[str, Any] = {
            "from": str(wire["from"]),
            "to": str(wire["to"]),
            "type": str(wire.get("type", wire.get("kind", "default"))),
        }
        if "color" in wire and wire["color"] is not None:
            normalized_wire["color"] = str(wire["color"])

        normalized.append(normalized_wire)
    return normalized


_DISCRETE_TERMINALS_BY_KIND = {
    "resistor": frozenset(("start", "end")),
    "capacitor": frozenset(("start", "end")),
    "diode": frozenset(("anode", "cathode")),
    "zener": frozenset(("anode", "cathode")),
    "bjt_npn": frozenset(("collector", "base", "emitter")),
    "bjt_pnp": frozenset(("collector", "base", "emitter")),
    "voltage_regulator": frozenset(("input", "ground", "output")),
    "to92": frozenset(("pin1", "pin2", "pin3")),
}

_CATALOG_BACKED_DISCRETE_KINDS = frozenset(("bjt_npn", "voltage_regulator"))


def _normalize_component_placements(
    raw_placements: Any,
    *,
    pin_positions: dict[str, tuple[float, float]],
) -> tuple[DiscreteComponentPlacement, ...]:
    if raw_placements is None:
        return ()
    if not isinstance(raw_placements, list) or not raw_placements:
        raise ValueError("component_placements must be a non-empty list")

    placements = []
    refs = set()
    occupied_pins: dict[str, str] = {}
    component_catalog = load_component_catalog()
    for index, raw_placement in enumerate(raw_placements):
        context = f"component_placements[{index}]"
        if not isinstance(raw_placement, dict):
            raise ValueError(f"{context} must be a mapping")
        unknown_keys = sorted(
            set(raw_placement)
            - {"ref", "kind", "value", "terminals", "part", "pinout_variant"}
        )
        if unknown_keys:
            raise ValueError(f"Unknown {context} keys: {unknown_keys}")

        ref = str(raw_placement.get("ref", "")).strip()
        kind = str(raw_placement.get("kind", "")).strip().lower()
        value = str(raw_placement.get("value", "")).strip()
        raw_terminals = raw_placement.get("terminals")
        raw_part = raw_placement.get("part")
        part = str(raw_part).strip() if raw_part is not None else None
        raw_pinout_variant = raw_placement.get("pinout_variant")
        pinout_variant = (
            str(raw_pinout_variant).strip() if raw_pinout_variant is not None else None
        )
        if not ref:
            raise ValueError(f"{context}.ref is required")
        if ref in refs:
            raise ValueError(f"Duplicate component placement ref: {ref}")
        refs.add(ref)
        if kind not in {*_DISCRETE_TERMINALS_BY_KIND, "dip"}:
            raise ValueError(f"Unsupported discrete component kind: {kind!r}")
        if not value:
            raise ValueError(f"{context}.value is required")
        if not isinstance(raw_terminals, dict) or not raw_terminals:
            raise ValueError(f"{context}.terminals must be a non-empty mapping")
        if part == "":
            raise ValueError(f"{context}.part must not be empty")
        if pinout_variant == "":
            raise ValueError(f"{context}.pinout_variant must not be empty")
        if kind in _CATALOG_BACKED_DISCRETE_KINDS:
            if part is None:
                raise ValueError(f"{context}.part is required for {kind}")
            device = component_catalog.resolve_device(part)
            if device.kind != kind:
                raise ValueError(
                    f"{context}.kind {kind!r} does not match catalog part "
                    f"{device.id} kind {device.kind!r}"
                )
            if device.package != "TO-92":
                raise ValueError(
                    f"{context}.part {device.id} uses unsupported package "
                    f"{device.package!r}; catalog-backed {kind} rendering "
                    "currently supports TO-92"
                )
            device.resolve_pinout(pinout_variant)
            part = device.id
        elif part is not None or pinout_variant is not None:
            raise ValueError(
                f"{context}.part and pinout_variant are supported only for "
                f"{sorted(_CATALOG_BACKED_DISCRETE_KINDS)}"
            )

        terminals = {
            str(terminal_name): str(pin_name)
            for terminal_name, pin_name in raw_terminals.items()
        }
        if kind == "dip":
            try:
                terminal_numbers = sorted(int(name) for name in terminals)
            except ValueError as error:
                raise ValueError(
                    f"{context}.terminals for dip must use numeric pin names"
                ) from error
            expected_numbers = list(range(1, len(terminals) + 1))
            if (
                len(terminals) < 4
                or len(terminals) % 2
                or terminal_numbers != expected_numbers
            ):
                raise ValueError(
                    f"{context}.terminals for dip must be consecutive pins 1..N "
                    "with an even pin count of at least 4"
                )
        else:
            expected_terminals = _DISCRETE_TERMINALS_BY_KIND[kind]
            if set(terminals) != expected_terminals:
                raise ValueError(
                    f"{context}.terminals for {kind} must be exactly "
                    f"{sorted(expected_terminals)}"
                )

        unknown_pins = sorted(set(terminals.values()) - set(pin_positions))
        if unknown_pins:
            raise ValueError(f"{context} references unknown pins: {unknown_pins}")
        if len(set(terminals.values())) != len(terminals):
            raise ValueError(f"{context} maps more than one terminal to the same pin")
        for pin_name in terminals.values():
            if pin_name in occupied_pins:
                raise ValueError(
                    f"Pin {pin_name!r} is occupied by both "
                    f"{occupied_pins[pin_name]} and {ref}"
                )
            occupied_pins[pin_name] = ref

        placements.append(
            DiscreteComponentPlacement(
                ref=ref,
                kind=kind,
                value=value,
                terminals=terminals,
                part=part,
                pinout_variant=pinout_variant,
            )
        )
    return tuple(placements)


def _normalize_boxes(raw_boxes: Any) -> tuple[PinoutBox, ...]:
    if raw_boxes is None:
        return ()
    if not isinstance(raw_boxes, list) or not raw_boxes:
        raise ValueError("boxes must be a non-empty list")

    boxes = []
    box_ids = set()
    for index, raw_box in enumerate(raw_boxes):
        context = f"boxes[{index}]"
        if not isinstance(raw_box, dict):
            raise ValueError(f"{context} must be a mapping")
        unknown_keys = sorted(
            set(raw_box) - {"id", "label", "top_left", "size_pitches"}
        )
        if unknown_keys:
            raise ValueError(f"Unknown {context} keys: {unknown_keys}")

        box_id = str(raw_box.get("id", "")).strip()
        label = str(raw_box.get("label", "")).strip()
        if not box_id:
            raise ValueError(f"{context}.id is required")
        if box_id in box_ids:
            raise ValueError(f"Duplicate box id: {box_id}")
        box_ids.add(box_id)
        if not label:
            raise ValueError(f"{context}.label is required")

        top_left = _as_xy(raw_box.get("top_left"), context=f"{context}.top_left")
        size_pitches = _as_xy(
            raw_box.get("size_pitches"), context=f"{context}.size_pitches"
        )
        if not all(math.isfinite(value) for value in (*top_left, *size_pitches)):
            raise ValueError(f"{context} coordinates and size must be finite")
        if size_pitches[0] <= 0 or size_pitches[1] <= 0:
            raise ValueError(f"{context}.size_pitches values must be > 0")

        boxes.append(
            PinoutBox(
                id=box_id,
                label=label,
                top_left=top_left,
                size_pitches=size_pitches,
            )
        )
    return tuple(boxes)


def _normalize_physical_component_pin_sets(
    raw_pin_sets: Any,
    *,
    context: str,
) -> tuple[str, ...]:
    if not isinstance(raw_pin_sets, list):
        raise ValueError(f"{context} must be a list")

    pin_sets = tuple(str(pin_set).strip() for pin_set in raw_pin_sets)
    if any(not pin_set for pin_set in pin_sets):
        raise ValueError(f"{context} values must not be empty")
    if len(set(pin_sets)) != len(pin_sets):
        raise ValueError(f"{context} must not contain duplicates")
    return pin_sets


def _normalize_physical_components(
    raw_components: Any,
    *,
    pin_sets: dict[str, tuple[str, ...]],
    boxes: tuple[PinoutBox, ...],
) -> tuple[PinoutPhysicalComponent, ...]:
    if raw_components is None:
        return ()
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("physical_components must be a non-empty list")

    components = []
    component_ids = set()
    owned_pin_sets: dict[str, str] = {}
    box_ids = {box.id for box in boxes}
    allowed_keys = {
        "id",
        "label",
        "component_type",
        "pin_sets",
        "through_pin_sets",
        "downholder",
        "box",
    }

    for index, raw_component in enumerate(raw_components):
        context = f"physical_components[{index}]"
        if not isinstance(raw_component, dict):
            raise ValueError(f"{context} must be a mapping")

        unknown_keys = sorted(set(raw_component) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"Unknown {context} keys: {unknown_keys}")

        component_id = str(raw_component.get("id", "")).strip()
        if not component_id:
            raise ValueError(f"{context}.id is required")
        if component_id in component_ids:
            raise ValueError(f"Duplicate physical component id: {component_id}")
        component_ids.add(component_id)

        component_type = str(raw_component.get("component_type", "")).strip()
        if not component_type:
            raise ValueError(f"{context}.component_type is required")

        raw_label = raw_component.get("label")
        label = str(raw_label).strip() if raw_label is not None else None
        if label == "":
            raise ValueError(f"{context}.label must not be empty")

        component_pin_sets = _normalize_physical_component_pin_sets(
            raw_component.get("pin_sets", []),
            context=f"{context}.pin_sets",
        )
        unknown_pin_sets = sorted(set(component_pin_sets) - set(pin_sets))
        if unknown_pin_sets:
            raise ValueError(
                f"{context} references unknown pin_sets: {unknown_pin_sets}"
            )

        reused_pin_sets = sorted(set(component_pin_sets) & set(owned_pin_sets))
        if reused_pin_sets:
            ownership = ", ".join(
                f"{pin_set} ({owned_pin_sets[pin_set]})" for pin_set in reused_pin_sets
            )
            raise ValueError(
                f"Physical pin sets may belong to only one component: {ownership}"
            )
        for pin_set in component_pin_sets:
            owned_pin_sets[pin_set] = component_id

        if "through_pin_sets" in raw_component:
            through_pin_sets = _normalize_physical_component_pin_sets(
                raw_component["through_pin_sets"],
                context=f"{context}.through_pin_sets",
            )
        else:
            through_pin_sets = component_pin_sets
        non_component_through_pin_sets = sorted(
            set(through_pin_sets) - set(component_pin_sets)
        )
        if non_component_through_pin_sets:
            raise ValueError(
                f"{context}.through_pin_sets must be a subset of pin_sets: "
                f"{non_component_through_pin_sets}"
            )

        raw_box_id = raw_component.get("box")
        box_id = str(raw_box_id).strip() if raw_box_id is not None else None
        if box_id == "":
            raise ValueError(f"{context}.box must not be empty")
        if box_id is not None and box_id not in box_ids:
            raise ValueError(f"{context} references unknown box: {box_id}")
        if not component_pin_sets and box_id is None:
            raise ValueError(f"{context} requires at least one pin_set or a box")

        downholder_text = str(raw_component.get("downholder", "")).strip().lower()
        try:
            downholder = PinoutDownholderKind(downholder_text)
        except ValueError as error:
            allowed_downholders = [kind.value for kind in PinoutDownholderKind]
            raise ValueError(
                f"{context}.downholder must be one of {allowed_downholders}"
            ) from error

        components.append(
            PinoutPhysicalComponent(
                id=component_id,
                label=label,
                component_type=component_type,
                pin_sets=component_pin_sets,
                through_pin_sets=through_pin_sets,
                downholder=downholder,
                box_id=box_id,
            )
        )

    return tuple(components)


def _normalize_discrete_view(
    raw_view: Any,
    *,
    pin_positions: dict[str, tuple[float, float]],
    pin_sets: dict[str, tuple[str, ...]],
    has_component_placements: bool,
) -> DiscreteViewConfig | None:
    if raw_view is None:
        if has_component_placements:
            return DiscreteViewConfig(
                title="Discrete Component Placement — Top View",
                notes_text=None,
                groups=(),
                anchor_labels={},
            )
        return None
    if not has_component_placements:
        raise ValueError("discrete_view requires component_placements")
    if not isinstance(raw_view, dict):
        raise ValueError("discrete_view must be a mapping")

    title = str(
        raw_view.get("title", "Discrete Component Placement — Top View")
    ).strip()
    if not title:
        raise ValueError("discrete_view.title must not be empty")
    raw_notes = raw_view.get("notes")
    notes_text = str(raw_notes) if raw_notes is not None else None

    raw_groups = raw_view.get("groups", [])
    if not isinstance(raw_groups, list):
        raise ValueError("discrete_view.groups must be a list")
    groups = []
    group_ids = set()
    grouped_pin_sets = set()
    for index, raw_group in enumerate(raw_groups):
        context = f"discrete_view.groups[{index}]"
        if not isinstance(raw_group, dict):
            raise ValueError(f"{context} must be a mapping")
        group_id = str(raw_group.get("id", "")).strip()
        label = str(raw_group.get("label", "")).strip()
        raw_group_pin_sets = raw_group.get("pin_sets")
        if not group_id:
            raise ValueError(f"{context}.id is required")
        if group_id in group_ids:
            raise ValueError(f"Duplicate discrete group id: {group_id}")
        group_ids.add(group_id)
        if not label:
            raise ValueError(f"{context}.label is required")
        if not isinstance(raw_group_pin_sets, list) or not raw_group_pin_sets:
            raise ValueError(f"{context}.pin_sets must be a non-empty list")
        group_pin_sets = tuple(str(name) for name in raw_group_pin_sets)
        unknown_pin_sets = sorted(set(group_pin_sets) - set(pin_sets))
        if unknown_pin_sets:
            raise ValueError(
                f"{context} references unknown pin_sets: {unknown_pin_sets}"
            )
        reused_pin_sets = sorted(set(group_pin_sets) & grouped_pin_sets)
        if reused_pin_sets:
            raise ValueError(
                f"Pin sets may belong to only one discrete group: {reused_pin_sets}"
            )
        grouped_pin_sets.update(group_pin_sets)
        groups.append(
            DiscretePinGroup(
                id=group_id,
                label=label,
                pin_sets=group_pin_sets,
            )
        )

    raw_anchor_labels = raw_view.get("anchor_labels", {})
    if not isinstance(raw_anchor_labels, dict):
        raise ValueError("discrete_view.anchor_labels must be a mapping")
    anchor_labels = {
        str(pin_name): str(label) for pin_name, label in raw_anchor_labels.items()
    }
    unknown_anchors = sorted(set(anchor_labels) - set(pin_positions))
    if unknown_anchors:
        raise ValueError(
            f"discrete_view.anchor_labels references unknown pins: {unknown_anchors}"
        )
    if any(not label.strip() for label in anchor_labels.values()):
        raise ValueError("discrete_view.anchor_labels values must not be empty")

    return DiscreteViewConfig(
        title=title,
        notes_text=notes_text,
        groups=tuple(groups),
        anchor_labels=anchor_labels,
    )


def _as_non_negative_margin(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a non-negative number")

    margin = float(value)
    if margin < 0:
        raise ValueError(f"{context} must be >= 0")
    return margin


def _normalize_svg_margins_px(raw_margins: Any) -> SvgMarginsPx:
    if raw_margins is None:
        return DEFAULT_SVG_MARGINS_PX

    if isinstance(raw_margins, (int, float)) and not isinstance(raw_margins, bool):
        margin = _as_non_negative_margin(raw_margins, context="metadata.svg_margins_px")
        return margin, margin, margin, margin

    if not isinstance(raw_margins, dict):
        raise ValueError(
            "metadata.svg_margins_px must be a number or mapping with "
            "left/right/top/bottom keys"
        )

    allowed_keys = {"left", "right", "top", "bottom"}
    unknown_keys = sorted(
        str(key) for key in raw_margins if str(key) not in allowed_keys
    )
    if unknown_keys:
        raise ValueError(f"Unknown metadata.svg_margins_px keys: {unknown_keys}")

    values = {
        "left": DEFAULT_SVG_MARGINS_PX[0],
        "right": DEFAULT_SVG_MARGINS_PX[1],
        "top": DEFAULT_SVG_MARGINS_PX[2],
        "bottom": DEFAULT_SVG_MARGINS_PX[3],
    }
    for key, raw_value in raw_margins.items():
        key_text = str(key)
        values[key_text] = _as_non_negative_margin(
            raw_value, context=f"metadata.svg_margins_px.{key_text}"
        )

    return values["left"], values["right"], values["top"], values["bottom"]


def load_pinout_config(config_path: str | Path) -> PinoutProject:
    """Load and validate pinout config from YAML or JSON."""
    path = Path(config_path)
    data = _load_raw_config(path)

    pin_positions, pin_sets, discrete_pin_numbers = _expand_pin_sets(
        data.get("pin_sets")
    )
    explicit_pins = _load_explicit_pins(data.get("pins"))
    for pin_name in explicit_pins:
        if pin_name in pin_positions:
            raise ValueError(f"Duplicate pin '{pin_name}' from pin_sets and pins")
    pin_positions.update(explicit_pins)
    if not pin_positions:
        raise ValueError("Config must define at least one pin via pin_sets or pins")
    _raise_if_duplicate_pin_coordinates(pin_positions)

    raw_connections = data.get("wires", data.get("connections"))
    connections = _normalize_connections(raw_connections)
    unknown_pins = sorted(
        {
            endpoint
            for connection in connections
            for endpoint in (connection["from"], connection["to"])
            if endpoint not in pin_positions
        }
    )
    if unknown_pins:
        raise ValueError(f"Connections reference unknown pins: {unknown_pins}")

    boxes = _normalize_boxes(data.get("boxes"))
    physical_components = _normalize_physical_components(
        data.get("physical_components"),
        pin_sets=pin_sets,
        boxes=boxes,
    )
    component_placements = _normalize_component_placements(
        data.get("component_placements"),
        pin_positions=pin_positions,
    )
    discrete_view = _normalize_discrete_view(
        data.get("discrete_view"),
        pin_positions=pin_positions,
        pin_sets=pin_sets,
        has_component_placements=bool(component_placements),
    )
    color_map = dict(DEFAULT_COLOR_MAP)
    raw_color_map = data.get("color_map", {})
    if raw_color_map:
        if not isinstance(raw_color_map, dict):
            raise ValueError("color_map must be a mapping")
        color_map.update({str(k): str(v) for k, v in raw_color_map.items()})

    metadata = data.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a mapping")

    basename = str(data.get("basename", metadata.get("basename", "pinout")))
    version_label = data.get("version_label", metadata.get("version_label"))
    notes_text = data.get("notes_text", metadata.get("notes"))
    svg_margins_px = _normalize_svg_margins_px(metadata.get("svg_margins_px"))

    return PinoutProject(
        pin_positions=pin_positions,
        connections=connections,
        color_map=color_map,
        basename=basename,
        version_label=str(version_label) if version_label is not None else None,
        notes_text=str(notes_text) if notes_text is not None else None,
        svg_margins_px=svg_margins_px,
        pin_sets=pin_sets,
        discrete_pin_numbers=discrete_pin_numbers,
        component_placements=component_placements,
        discrete_view=discrete_view,
        boxes=boxes,
        physical_components=physical_components,
    )
