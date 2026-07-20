"""Component-side placement rendering for pinout projects."""

from __future__ import annotations

import math
from xml.etree import ElementTree as ET

from mege_circuits.pinout.config import (
    DiscreteComponentPlacement,
    PinoutProject,
)
from mege_circuits.pinout.svg import (
    _calculate_bounds,
    _circle_bbox,
    _draw_pinout_boxes,
    _estimate_text_bbox,
    _line_bbox,
    _SvgBounds,
    _transform_positions_for_view,
)

GRID_SIZE = 40
PIN_RADIUS = 6
PIN_STROKE_WIDTH = 1.0
COMPONENT_STROKE = "#111827"
COMPONENT_LEAD_STROKE = "#374151"
GROUP_STROKE = "#94a3b8"
GROUP_FILL = "#f8fafc"


def _add_text(
    parent: ET.Element,
    bounds: _SvgBounds,
    content: str,
    *,
    x: float,
    y: float,
    font_size: float,
    text_anchor: str = "middle",
    fill: str = "#111827",
    font_weight: str | None = None,
    class_name: str | None = None,
    data_attrs: dict[str, str] | None = None,
) -> ET.Element:
    attrs = {
        "x": f"{x:g}",
        "y": f"{y:g}",
        "font-size": f"{font_size:g}px",
        "font-family": "sans-serif",
        "text-anchor": text_anchor,
        "fill": fill,
    }
    if font_weight is not None:
        attrs["font-weight"] = font_weight
    if class_name is not None:
        attrs["class"] = class_name
    if data_attrs:
        attrs.update(data_attrs)
    node = ET.SubElement(parent, "text", attrs)
    node.text = content
    bounds.add_rect(
        _estimate_text_bbox(
            content,
            x=x,
            y=y,
            font_size=font_size,
            text_anchor=text_anchor,
        )
    )
    return node


def _add_line(
    parent: ET.Element,
    bounds: _SvgBounds,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    class_name: str,
    data_attrs: dict[str, str],
    stroke: str = COMPONENT_LEAD_STROKE,
    stroke_width: float = 2.0,
) -> ET.Element:
    bounds.add_rect(_line_bbox(*start, *end, stroke_width=stroke_width))
    return ET.SubElement(
        parent,
        "line",
        {
            "class": class_name,
            **data_attrs,
            "x1": f"{start[0]:g}",
            "y1": f"{start[1]:g}",
            "x2": f"{end[0]:g}",
            "y2": f"{end[1]:g}",
            "stroke": stroke,
            "stroke-width": f"{stroke_width:g}",
            "stroke-linecap": "round",
        },
    )


def _component_attrs(component: DiscreteComponentPlacement) -> dict[str, str]:
    return {
        "data-component": component.ref,
        "data-kind": component.kind,
        "data-value": component.value,
    }


def _component_group(
    root: ET.Element,
    component: DiscreteComponentPlacement,
) -> ET.Element:
    return ET.SubElement(
        root,
        "g",
        {
            "class": "discrete-component",
            **_component_attrs(component),
        },
    )


def _two_terminal_geometry(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    body_length: float,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    float,
]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        raise ValueError("Discrete component terminals must not share a position")
    unit_x = dx / distance
    unit_y = dy / distance
    center = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    half_length = min(body_length / 2.0, max(6.0, distance / 2.0 - 10.0))
    body_start = (
        center[0] - unit_x * half_length,
        center[1] - unit_y * half_length,
    )
    body_end = (
        center[0] + unit_x * half_length,
        center[1] + unit_y * half_length,
    )
    return center, body_start, body_end, math.degrees(math.atan2(dy, dx))


def _draw_component_caption(
    group: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    center: tuple[float, float],
) -> None:
    _add_text(
        group,
        bounds,
        component.ref,
        x=center[0],
        y=center[1] + 3,
        font_size=9,
        fill="#111827",
        font_weight="700",
        class_name="discrete-component-ref",
        data_attrs=_component_attrs(component),
    )
    _add_text(
        group,
        bounds,
        component.value,
        x=center[0],
        y=center[1] + 18,
        font_size=8,
        fill="#374151",
        class_name="discrete-component-value",
        data_attrs=_component_attrs(component),
    )


def _draw_resistor(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    start = positions[component.terminals["start"]]
    end = positions[component.terminals["end"]]
    center, body_start, body_end, angle = _two_terminal_geometry(
        start, end, body_length=54
    )
    group = _component_group(root, component)
    attrs = _component_attrs(component)
    _add_line(
        group, bounds, start, body_start, class_name="component-lead", data_attrs=attrs
    )
    _add_line(
        group, bounds, body_end, end, class_name="component-lead", data_attrs=attrs
    )
    body_width = math.dist(body_start, body_end)
    body_height = 16.0
    bounds.add_rect(
        (
            center[0] - body_width / 2.0 - 1,
            center[1] - body_height / 2.0 - 1,
            center[0] + body_width / 2.0 + 1,
            center[1] + body_height / 2.0 + 1,
        )
    )
    ET.SubElement(
        group,
        "rect",
        {
            "class": "resistor-body",
            **attrs,
            "x": f"{center[0] - body_width / 2.0:g}",
            "y": f"{center[1] - body_height / 2.0:g}",
            "width": f"{body_width:g}",
            "height": f"{body_height:g}",
            "rx": "4",
            "fill": "#f3d7a0",
            "stroke": COMPONENT_STROKE,
            "stroke-width": "2",
            "transform": f"rotate({angle:g} {center[0]:g} {center[1]:g})",
        },
    )
    _draw_component_caption(group, bounds, component, center)


def _draw_capacitor(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    start = positions[component.terminals["start"]]
    end = positions[component.terminals["end"]]
    center, body_start, body_end, angle = _two_terminal_geometry(
        start, end, body_length=26
    )
    group = _component_group(root, component)
    attrs = _component_attrs(component)
    _add_line(
        group, bounds, start, body_start, class_name="component-lead", data_attrs=attrs
    )
    _add_line(
        group, bounds, body_end, end, class_name="component-lead", data_attrs=attrs
    )
    body_width = math.dist(body_start, body_end)
    body_height = 20.0
    bounds.add_rect(
        (
            center[0] - body_width / 2.0 - 1,
            center[1] - body_height / 2.0 - 1,
            center[0] + body_width / 2.0 + 1,
            center[1] + body_height / 2.0 + 1,
        )
    )
    ET.SubElement(
        group,
        "rect",
        {
            "class": "capacitor-body",
            **attrs,
            "x": f"{center[0] - body_width / 2.0:g}",
            "y": f"{center[1] - body_height / 2.0:g}",
            "width": f"{body_width:g}",
            "height": f"{body_height:g}",
            "rx": "3",
            "fill": "#bfdbfe",
            "stroke": COMPONENT_STROKE,
            "stroke-width": "2",
            "transform": f"rotate({angle:g} {center[0]:g} {center[1]:g})",
        },
    )
    _draw_component_caption(group, bounds, component, center)


def _draw_diode(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    anode = positions[component.terminals["anode"]]
    cathode = positions[component.terminals["cathode"]]
    center, body_start, body_end, angle = _two_terminal_geometry(
        anode, cathode, body_length=46
    )
    group = _component_group(root, component)
    attrs = _component_attrs(component)
    _add_line(
        group, bounds, anode, body_start, class_name="component-lead", data_attrs=attrs
    )
    _add_line(
        group, bounds, body_end, cathode, class_name="component-lead", data_attrs=attrs
    )
    body_width = math.dist(body_start, body_end)
    body_height = 15.0
    bounds.add_rect(
        (
            center[0] - body_width / 2.0 - 2,
            center[1] - body_height / 2.0 - 2,
            center[0] + body_width / 2.0 + 2,
            center[1] + body_height / 2.0 + 2,
        )
    )
    symbol_group = ET.SubElement(
        group,
        "g",
        {
            "class": f"{component.kind}-body",
            **attrs,
            "transform": f"rotate({angle:g} {center[0]:g} {center[1]:g})",
        },
    )
    ET.SubElement(
        symbol_group,
        "rect",
        {
            "x": f"{center[0] - body_width / 2.0:g}",
            "y": f"{center[1] - body_height / 2.0:g}",
            "width": f"{body_width:g}",
            "height": f"{body_height:g}",
            "rx": "7",
            "fill": "#e5e7eb",
            "stroke": COMPONENT_STROKE,
            "stroke-width": "2",
        },
    )
    terminal_distance = math.dist(anode, cathode)
    unit_x = (cathode[0] - anode[0]) / terminal_distance
    unit_y = (cathode[1] - anode[1]) / terminal_distance
    perpendicular = (-unit_y, unit_x)
    band_center = (
        body_end[0] - unit_x * 9.0,
        body_end[1] - unit_y * 9.0,
    )
    half_band = body_height / 2.0
    band_start = (
        band_center[0] - perpendicular[0] * half_band,
        band_center[1] - perpendicular[1] * half_band,
    )
    band_end = (
        band_center[0] + perpendicular[0] * half_band,
        band_center[1] + perpendicular[1] * half_band,
    )
    _add_line(
        group,
        bounds,
        band_start,
        band_end,
        class_name="cathode-band",
        data_attrs={**attrs, "data-terminal": "cathode"},
        stroke="#111827",
        stroke_width=4.0,
    )
    if component.kind == "zener":
        for band_point, bend_direction in ((band_start, -1.0), (band_end, 1.0)):
            tip_end = (
                band_point[0] + unit_x * 5.0 + perpendicular[0] * bend_direction * 4.0,
                band_point[1] + unit_y * 5.0 + perpendicular[1] * bend_direction * 4.0,
            )
            _add_line(
                group,
                bounds,
                band_point,
                tip_end,
                class_name="zener-cathode-tip",
                data_attrs={**attrs, "data-terminal": "cathode"},
                stroke="#111827",
                stroke_width=2.0,
            )
    polarity_offset = 6.5
    anode_label = (
        center[0] - unit_x * polarity_offset,
        center[1] - unit_y * polarity_offset,
    )
    cathode_label = (
        center[0] + unit_x * polarity_offset,
        center[1] + unit_y * polarity_offset,
    )
    _add_text(
        group,
        bounds,
        "A",
        x=anode_label[0],
        y=anode_label[1] + 3,
        font_size=8,
        font_weight="700",
        class_name="polarity-label",
        data_attrs={**attrs, "data-terminal": "anode"},
    )
    _add_text(
        group,
        bounds,
        "K",
        x=cathode_label[0],
        y=cathode_label[1] + 3,
        font_size=8,
        font_weight="700",
        class_name="polarity-label",
        data_attrs={**attrs, "data-terminal": "cathode"},
    )
    _add_text(
        group,
        bounds,
        component.ref,
        x=center[0],
        y=center[1] - 11,
        font_size=8,
        font_weight="700",
        class_name="discrete-component-ref",
        data_attrs=attrs,
    )
    _add_text(
        group,
        bounds,
        component.value,
        x=center[0],
        y=center[1] + 14,
        font_size=8,
        fill="#374151",
        class_name="discrete-component-value",
        data_attrs=attrs,
    )


def _draw_bjt_pnp(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    terminal_positions = {
        name: positions[component.terminals[name]]
        for name in ("collector", "base", "emitter")
    }
    average_x = sum(point[0] for point in terminal_positions.values()) / 3.0
    average_y = sum(point[1] for point in terminal_positions.values()) / 3.0
    body_center = (average_x - 31.0, average_y)
    body_half_width = 24.0
    body_half_height = max(
        34.0,
        (
            max(point[1] for point in terminal_positions.values())
            - min(point[1] for point in terminal_positions.values())
        )
        / 2.0
        + 10.0,
    )
    group = _component_group(root, component)
    attrs = _component_attrs(component)
    flat_x = body_center[0] + body_half_width
    role_offsets = {"collector": -20.0, "base": 0.0, "emitter": 20.0}
    for role, pin_position in terminal_positions.items():
        body_point = (flat_x, body_center[1] + role_offsets[role])
        _add_line(
            group,
            bounds,
            pin_position,
            body_point,
            class_name="transistor-lead",
            data_attrs={**attrs, "data-terminal": role},
        )

    left_x = body_center[0] - body_half_width
    top_y = body_center[1] - body_half_height
    bottom_y = body_center[1] + body_half_height
    path_data = (
        f"M {flat_x:g} {top_y:g} "
        f"L {flat_x:g} {bottom_y:g} "
        f"A {body_half_width * 2:g} {body_half_height:g} 0 0 1 "
        f"{flat_x:g} {top_y:g} Z"
    )
    bounds.add_rect((left_x - 2, top_y - 2, flat_x + 2, bottom_y + 2))
    ET.SubElement(
        group,
        "path",
        {
            "class": "transistor-body",
            **attrs,
            "d": path_data,
            "fill": "#d1d5db",
            "stroke": COMPONENT_STROKE,
            "stroke-width": "2",
        },
    )
    for role, letter in (("collector", "C"), ("base", "B"), ("emitter", "E")):
        _add_text(
            group,
            bounds,
            letter,
            x=flat_x - 8,
            y=body_center[1] + role_offsets[role] + 3,
            font_size=9,
            text_anchor="end",
            font_weight="700",
            class_name="transistor-terminal-label",
            data_attrs={**attrs, "data-terminal": role},
        )
    _add_text(
        group,
        bounds,
        component.ref,
        x=body_center[0] - 2,
        y=body_center[1] - 4,
        font_size=10,
        font_weight="700",
        class_name="discrete-component-ref",
        data_attrs=attrs,
    )
    _add_text(
        group,
        bounds,
        component.value,
        x=body_center[0] - 2,
        y=body_center[1] + 10,
        font_size=8,
        class_name="discrete-component-value",
        data_attrs=attrs,
    )


def _draw_dip(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    terminal_positions = {
        int(number): positions[pin_name]
        for number, pin_name in component.terminals.items()
    }
    xs = [point[0] for point in terminal_positions.values()]
    ys = [point[1] for point in terminal_positions.values()]
    left = min(xs) + 12
    right = max(xs) - 12
    top = min(ys) - 10
    bottom = max(ys) + 10
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    group = _component_group(root, component)
    attrs = _component_attrs(component)
    bounds.add_rect((left - 2, top - 2, right + 2, bottom + 2))
    ET.SubElement(
        group,
        "rect",
        {
            "class": "dip-body",
            **attrs,
            "x": f"{left:g}",
            "y": f"{top:g}",
            "width": f"{right - left:g}",
            "height": f"{bottom - top:g}",
            "rx": "8",
            "fill": "#1f2937",
            "stroke": "#111827",
            "stroke-width": "2",
        },
    )
    ET.SubElement(
        group,
        "path",
        {
            "class": "dip-notch",
            **attrs,
            "d": (
                f"M {center_x - 10:g} {top:g} "
                f"Q {center_x:g} {top + 12:g} {center_x + 10:g} {top:g}"
            ),
            "fill": "none",
            "stroke": "#ffffff",
            "stroke-width": "2",
        },
    )
    pin_one = terminal_positions[1]
    marker_x = left + 10 if pin_one[0] == min(xs) else right - 10
    marker_y = top + 14
    bounds.add_rect(_circle_bbox(marker_x, marker_y, radius=3.5, stroke_width=0))
    ET.SubElement(
        group,
        "circle",
        {
            "class": "dip-pin-one-marker",
            **attrs,
            "cx": f"{marker_x:g}",
            "cy": f"{marker_y:g}",
            "r": "3.5",
            "fill": "#ffffff",
        },
    )
    for number, point in sorted(terminal_positions.items()):
        on_left = point[0] == min(xs)
        _add_text(
            group,
            bounds,
            str(number),
            x=left + 8 if on_left else right - 8,
            y=point[1] + 3,
            font_size=7,
            text_anchor="start" if on_left else "end",
            fill="#ffffff",
            font_weight="700",
            class_name="dip-pin-number",
            data_attrs={**attrs, "data-terminal": str(number)},
        )
    _add_text(
        group,
        bounds,
        component.ref,
        x=center_x,
        y=center_y - 3,
        font_size=12,
        fill="#ffffff",
        font_weight="700",
        class_name="discrete-component-ref",
        data_attrs=attrs,
    )
    _add_text(
        group,
        bounds,
        component.value,
        x=center_x,
        y=center_y + 13,
        font_size=8,
        fill="#ffffff",
        class_name="discrete-component-value",
        data_attrs=attrs,
    )


def _draw_component(
    root: ET.Element,
    bounds: _SvgBounds,
    component: DiscreteComponentPlacement,
    positions: dict[str, tuple[float, float]],
) -> None:
    if component.kind == "resistor":
        _draw_resistor(root, bounds, component, positions)
    elif component.kind == "capacitor":
        _draw_capacitor(root, bounds, component, positions)
    elif component.kind in {"diode", "zener"}:
        _draw_diode(root, bounds, component, positions)
    elif component.kind == "bjt_pnp":
        _draw_bjt_pnp(root, bounds, component, positions)
    elif component.kind == "dip":
        _draw_dip(root, bounds, component, positions)
    else:
        raise ValueError(f"Unsupported discrete component kind: {component.kind}")


def _component_terminal_labels(
    placements: tuple[DiscreteComponentPlacement, ...],
) -> dict[str, str]:
    labels = {}
    role_labels = {
        "anode": "A",
        "cathode": "K",
        "collector": "C",
        "base": "B",
        "emitter": "E",
    }
    for component in placements:
        if component.kind == "dip":
            continue
        for terminal, pin_name in component.terminals.items():
            if terminal in role_labels:
                labels.setdefault(pin_name, role_labels[terminal])
    return labels


def generate_discrete_top_svg(project: PinoutProject) -> str:
    """Generate a wire-free top view showing installed discrete components."""
    if not project.component_placements or project.discrete_view is None:
        raise ValueError(
            "A discrete top view requires component_placements and discrete_view"
        )
    pin_sets = project.pin_sets or {}
    pin_numbers = project.discrete_pin_numbers or {}
    view = project.discrete_view

    min_x, min_y, max_x, max_y = _calculate_bounds(
        project.pin_positions, None, project.boxes
    )
    transformed_positions, _ = _transform_positions_for_view(
        project.pin_positions,
        None,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        flip_x=False,
    )
    coord_shift_x = 1.0 - min_x
    coord_shift_y = 1.0 - min_y
    screen_positions = {
        name: (
            (position[0] + coord_shift_x) * GRID_SIZE,
            (position[1] + coord_shift_y) * GRID_SIZE,
        )
        for name, position in transformed_positions.items()
    }

    root = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": "0 0 1 1",
            "width": "100%",
            "height": "100%",
        },
    )
    background = ET.SubElement(
        root,
        "rect",
        {
            "class": "discrete-background",
            "fill": "#ffffff",
        },
    )
    bounds = _SvgBounds()

    _draw_pinout_boxes(
        root,
        bounds,
        project.boxes,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        coord_shift_x=coord_shift_x,
        coord_shift_y=coord_shift_y,
        grid_size=GRID_SIZE,
        flip_x=False,
    )

    for discrete_group in view.groups:
        group_pins = [
            pin_name
            for pin_set_name in discrete_group.pin_sets
            for pin_name in pin_sets[pin_set_name]
        ]
        xs = [screen_positions[pin_name][0] for pin_name in group_pins]
        ys = [screen_positions[pin_name][1] for pin_name in group_pins]
        padding_x = 18.0
        padding_y = 18.0
        left = min(xs) - padding_x
        top = min(ys) - padding_y
        right = max(xs) + padding_x
        bottom = max(ys) + padding_y
        bounds.add_rect((left, top, right, bottom))
        ET.SubElement(
            root,
            "rect",
            {
                "class": "discrete-pin-group",
                "data-group": discrete_group.id,
                "x": f"{left:g}",
                "y": f"{top:g}",
                "width": f"{right - left:g}",
                "height": f"{bottom - top:g}",
                "rx": "6",
                "fill": GROUP_FILL,
                "fill-opacity": "0.28",
                "stroke": GROUP_STROKE,
                "stroke-width": "1.5",
                "stroke-dasharray": "6 4",
            },
        )
        _add_text(
            root,
            bounds,
            discrete_group.label,
            x=left + 5,
            y=top - 6,
            font_size=11,
            text_anchor="start",
            fill="#475569",
            font_weight="700",
            class_name="discrete-group-label",
            data_attrs={"data-group": discrete_group.id},
        )

    for component in project.component_placements:
        _draw_component(root, bounds, component, screen_positions)

    for pin_name, (cx, cy) in screen_positions.items():
        bounds.add_rect(
            _circle_bbox(
                cx,
                cy,
                radius=PIN_RADIUS,
                stroke_width=PIN_STROKE_WIDTH,
            )
        )
        ET.SubElement(
            root,
            "circle",
            {
                "class": "discrete-pin",
                "data-pin": pin_name,
                "cx": f"{cx:g}",
                "cy": f"{cy:g}",
                "r": str(PIN_RADIUS),
                "fill": "#d1d5db",
                "stroke": "#111827",
                "stroke-width": f"{PIN_STROKE_WIDTH:g}",
            },
        )

    occupied_pins = {
        pin_name
        for component in project.component_placements
        for pin_name in component.terminals.values()
    }
    terminal_labels = _component_terminal_labels(project.component_placements)
    visible_labels = {}
    for pin_name in sorted(occupied_pins):
        if pin_name in pin_numbers:
            visible_labels[pin_name] = pin_numbers[pin_name]
        elif pin_name in terminal_labels:
            visible_labels[pin_name] = terminal_labels[pin_name]
    visible_labels.update(view.anchor_labels)
    for pin_name in sorted(visible_labels):
        label = visible_labels[pin_name]
        cx, cy = screen_positions[pin_name]
        _add_text(
            root,
            bounds,
            label,
            x=cx,
            y=cy - PIN_RADIUS - 4,
            font_size=8,
            fill="#111827",
            font_weight="700",
            class_name="discrete-pin-label",
            data_attrs={"data-pin": pin_name},
        )

    pin_xs = [point[0] for point in screen_positions.values()]
    pin_ys = [point[1] for point in screen_positions.values()]
    if project.boxes:
        layout_left = (min_x + coord_shift_x) * GRID_SIZE
        layout_top = (min_y + coord_shift_y) * GRID_SIZE
        layout_right = (max_x + coord_shift_x) * GRID_SIZE
        layout_bottom = (max_y + coord_shift_y) * GRID_SIZE
        title_x = (layout_left + layout_right) / 2.0
        title_y = layout_top - 54.0
    else:
        layout_left = min(pin_xs)
        layout_bottom = max(pin_ys)
        title_x = (min(pin_xs) + max(pin_xs)) / 2.0
        title_y = min(pin_ys) - 54.0
    _add_text(
        root,
        bounds,
        view.title,
        x=title_x,
        y=title_y,
        font_size=18,
        fill="#1e3a8a",
        font_weight="700",
        class_name="discrete-title",
    )
    if project.version_label:
        _add_text(
            root,
            bounds,
            project.version_label,
            x=title_x,
            y=title_y + 18,
            font_size=10,
            fill="#166534",
            class_name="discrete-version-label",
        )

    if view.notes_text:
        note_lines = view.notes_text.splitlines()
        note_x = layout_left
        note_y = layout_bottom + 55.0
        note_width = max(len(line) for line in note_lines) * 9 * 0.58 + 20
        note_height = len(note_lines) * 15 + 18
        note_rect = (
            note_x - 10,
            note_y - 17,
            note_x - 10 + note_width,
            note_y - 17 + note_height,
        )
        bounds.add_rect(note_rect)
        ET.SubElement(
            root,
            "rect",
            {
                "class": "discrete-notes-box",
                "x": f"{note_rect[0]:g}",
                "y": f"{note_rect[1]:g}",
                "width": f"{note_width:g}",
                "height": f"{note_height:g}",
                "rx": "5",
                "fill": "#ffffff",
                "stroke": "#94a3b8",
                "stroke-width": "1.5",
            },
        )
        for index, line in enumerate(note_lines):
            _add_text(
                root,
                bounds,
                line,
                x=note_x,
                y=note_y + index * 15,
                font_size=9,
                text_anchor="start",
                fill="#111827",
                class_name="discrete-note",
            )

    viewbox = bounds.viewbox(project.svg_margins_px)
    root.set("viewBox", " ".join(str(value) for value in viewbox))
    background.set("x", str(viewbox[0]))
    background.set("y", str(viewbox[1]))
    background.set("width", str(viewbox[2]))
    background.set("height", str(viewbox[3]))
    return ET.tostring(root, encoding="unicode")
