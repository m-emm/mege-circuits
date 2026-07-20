"""SVG rendering for pinout diagrams."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from mege_circuits.pinout.config import PinoutBox

DEFAULT_COLOR_MAP = {
    "power": "red",
    "hazard_power": "#8b4513",
    "lv_power": "grey",
    "ground": "black",
    "clock": "blue",
    "data": "gold",
    "default": "gray",
}

DEFAULT_SVG_MARGINS_PX = (20.0, 20.0, 20.0, 20.0)
SvgMarginsPx = tuple[float, float, float, float]


class _SvgBounds:
    def __init__(self) -> None:
        self.min_x = math.inf
        self.min_y = math.inf
        self.max_x = -math.inf
        self.max_y = -math.inf

    def add_rect(self, rect: tuple[float, float, float, float]) -> None:
        self.min_x = min(self.min_x, rect[0])
        self.min_y = min(self.min_y, rect[1])
        self.max_x = max(self.max_x, rect[2])
        self.max_y = max(self.max_y, rect[3])

    def viewbox(self, margins_px: SvgMarginsPx) -> tuple[int, int, int, int]:
        if not math.isfinite(self.min_x):
            return 0, 0, 0, 0

        margin_left, margin_right, margin_top, margin_bottom = margins_px
        min_x = math.floor(self.min_x - margin_left)
        min_y = math.floor(self.min_y - margin_top)
        max_x = math.ceil(self.max_x + margin_right)
        max_y = math.ceil(self.max_y + margin_bottom)
        return min_x, min_y, max_x - min_x, max_y - min_y


def _line_bbox(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke_width: float,
) -> tuple[float, float, float, float]:
    half_stroke = stroke_width / 2.0
    return (
        min(x1, x2) - half_stroke,
        min(y1, y2) - half_stroke,
        max(x1, x2) + half_stroke,
        max(y1, y2) + half_stroke,
    )


def _circle_bbox(
    cx: float,
    cy: float,
    *,
    radius: float,
    stroke_width: float,
) -> tuple[float, float, float, float]:
    extent = radius + (stroke_width / 2.0)
    return cx - extent, cy - extent, cx + extent, cy + extent


def _estimate_annotation_width_px(
    *,
    view_label: str,
    version_label: str | None,
    notes_text: str | None,
) -> int:
    line_specs = [(view_label, 16, 0.58)]
    if version_label:
        line_specs.append((version_label, 12, 0.56))
    if notes_text:
        line_specs.extend((line, 10, 0.54) for line in notes_text.splitlines())

    widest_line_px = max(
        int(len(line) * font_size * width_factor)
        for line, font_size, width_factor in line_specs
    )
    return widest_line_px + 24


def _calculate_bounds(
    pin_positions: dict[str, tuple[float, float]],
    waypoint_solutions: dict[int, dict[str, Any]] | None,
    boxes: tuple[PinoutBox, ...] = (),
) -> tuple[float, float, float, float]:
    coords = list(pin_positions.values())
    max_x = max(x for x, _ in coords)
    max_y = max(y for _, y in coords)
    min_x = min(x for x, _ in coords)
    min_y = min(y for _, y in coords)

    if waypoint_solutions:
        waypoint_coords = [sol["waypoint"] for sol in waypoint_solutions.values()]
        if waypoint_coords:
            max_x = max(max_x, max(x for x, _ in waypoint_coords))
            max_y = max(max_y, max(y for _, y in waypoint_coords))
            min_x = min(min_x, min(x for x, _ in waypoint_coords))
            min_y = min(min_y, min(y for _, y in waypoint_coords))

    for box in boxes:
        box_left, box_top = box.top_left
        box_width, box_height = box.size_pitches
        min_x = min(min_x, box_left)
        max_x = max(max_x, box_left + box_width)
        min_y = min(min_y, box_top - box_height)
        max_y = max(max_y, box_top)

    return min_x, min_y, max_x, max_y


def _transform_positions_for_view(
    pin_positions: dict[str, tuple[float, float]],
    waypoint_solutions: dict[int, dict[str, Any]] | None,
    *,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    flip_x: bool,
) -> tuple[dict[str, tuple[float, float]], dict[int, tuple[float, float]]]:
    transformed_pins: dict[str, tuple[float, float]] = {}
    for name, (x, y) in pin_positions.items():
        flipped_y = max_y - y + min_y
        transformed_x = max_x - x + min_x if flip_x else x
        transformed_pins[name] = (transformed_x, flipped_y)

    transformed_waypoints: dict[int, tuple[float, float]] = {}
    if waypoint_solutions:
        for conn_idx, solution in waypoint_solutions.items():
            wp_x, wp_y = solution["waypoint"]
            transformed_wp_y = max_y - wp_y + min_y
            transformed_wp_x = max_x - wp_x + min_x if flip_x else wp_x
            transformed_waypoints[conn_idx] = (transformed_wp_x, transformed_wp_y)

    return transformed_pins, transformed_waypoints


def _draw_pinout_boxes(
    root: ET.Element,
    svg_bounds: _SvgBounds,
    boxes: tuple[PinoutBox, ...],
    *,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    coord_shift_x: float,
    coord_shift_y: float,
    grid_size: float,
    flip_x: bool,
) -> None:
    for box in boxes:
        box_left, box_top = box.top_left
        box_width, box_height = box.size_pitches
        box_right = box_left + box_width
        box_bottom = box_top - box_height

        transformed_left = max_x - box_right + min_x if flip_x else box_left
        transformed_right = max_x - box_left + min_x if flip_x else box_right
        transformed_top = max_y - box_top + min_y
        transformed_bottom = max_y - box_bottom + min_y

        left = (transformed_left + coord_shift_x) * grid_size
        right = (transformed_right + coord_shift_x) * grid_size
        top = (transformed_top + coord_shift_y) * grid_size
        bottom = (transformed_bottom + coord_shift_y) * grid_size
        rect = (left, top, right, bottom)
        svg_bounds.add_rect(rect)
        ET.SubElement(
            root,
            "rect",
            {
                "class": "pinout-box",
                "data-box": box.id,
                "data-width-pitches": f"{box_width:.12g}",
                "data-height-pitches": f"{box_height:.12g}",
                "x": f"{left:.12g}",
                "y": f"{top:.12g}",
                "width": f"{right - left:.12g}",
                "height": f"{bottom - top:.12g}",
                "rx": "8",
                "fill": "#e2e8f0",
                "fill-opacity": "0.22",
                "stroke": "#475569",
                "stroke-width": "3",
            },
        )

        label_lines = box.label.splitlines()
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        first_y = center_y - ((len(label_lines) - 1) * 9.0)
        for line_index, line in enumerate(label_lines):
            label_y = first_y + line_index * 18.0
            svg_bounds.add_rect(
                _estimate_text_bbox(
                    line,
                    x=center_x,
                    y=label_y,
                    font_size=12.0,
                    text_anchor="middle",
                )
            )
            _add_text(
                root,
                line,
                x=f"{center_x:.12g}",
                y=f"{label_y:.12g}",
                **{
                    "class": "pinout-box-label",
                    "data-box": box.id,
                    "font-size": "12px",
                    "font-family": "sans-serif",
                    "font-weight": "bold" if line_index == 0 else "normal",
                    "text-anchor": "middle",
                    "fill": "#334155",
                },
            )


def _add_text(parent: ET.Element, content: str, **attrs: str) -> None:
    text_node = ET.SubElement(parent, "text", attrs)
    text_node.text = content


def _rotate_point(
    point_x: float,
    point_y: float,
    *,
    origin_x: float,
    origin_y: float,
    angle_degrees: float,
) -> tuple[float, float]:
    angle_radians = math.radians(angle_degrees)
    translated_x = point_x - origin_x
    translated_y = point_y - origin_y
    rotated_x = translated_x * math.cos(angle_radians) - translated_y * math.sin(
        angle_radians
    )
    rotated_y = translated_x * math.sin(angle_radians) + translated_y * math.cos(
        angle_radians
    )
    return rotated_x + origin_x, rotated_y + origin_y


def _estimate_text_bbox(
    content: str,
    *,
    x: float,
    y: float,
    font_size: float,
    text_anchor: str,
    rotation_degrees: float = 0.0,
) -> tuple[float, float, float, float]:
    width = max(len(content), 1) * font_size * 0.62
    ascent = font_size * 0.82
    descent = font_size * 0.28

    if text_anchor == "start":
        left = x
        right = x + width
    elif text_anchor == "end":
        left = x - width
        right = x
    else:
        left = x - (width / 2.0)
        right = x + (width / 2.0)

    top = y - ascent
    bottom = y + descent
    corners = [
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
    ]

    if rotation_degrees:
        corners = [
            _rotate_point(
                px, py, origin_x=x, origin_y=y, angle_degrees=rotation_degrees
            )
            for px, py in corners
        ]

    xs = [px for px, _ in corners]
    ys = [py for _, py in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _rectangles_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    padding: float = 0.0,
) -> bool:
    return not (
        left[2] + padding <= right[0]
        or right[2] + padding <= left[0]
        or left[3] + padding <= right[1]
        or right[3] + padding <= left[1]
    )


def _build_label_candidates(
    *,
    name: str,
    cx: int,
    cy: int,
    pin_radius: int,
    has_left_neighbor: bool,
    has_right_neighbor: bool,
    has_top_neighbor: bool,
    has_bottom_neighbor: bool,
    flip_x: bool,
) -> list[dict[str, str | float]]:
    candidates: list[dict[str, str | float]] = []

    is_horizontal_row = (
        (has_left_neighbor or has_right_neighbor)
        and not has_top_neighbor
        and not has_bottom_neighbor
    )

    if is_horizontal_row:
        primary_anchor = "start" if not flip_x else "end"
        primary_x = cx + pin_radius + 2 if not flip_x else cx - pin_radius - 2
        primary_angle = -45.0 if not flip_x else 45.0
        base_y = cy - pin_radius - 6
        for lift in (0, 12, 24, 36):
            candidates.append(
                {
                    "x": primary_x,
                    "y": base_y - lift,
                    "font_size": 11.0,
                    "text_anchor": primary_anchor,
                    "rotation_degrees": primary_angle,
                }
            )

        secondary_anchor = "end" if not flip_x else "start"
        secondary_x = cx - pin_radius - 2 if not flip_x else cx + pin_radius + 2
        secondary_angle = 45.0 if not flip_x else -45.0
        for lift in (0, 12):
            candidates.append(
                {
                    "x": secondary_x,
                    "y": base_y - lift,
                    "font_size": 11.0,
                    "text_anchor": secondary_anchor,
                    "rotation_degrees": secondary_angle,
                }
            )

    if not has_right_neighbor and not flip_x:
        candidates.append(
            {
                "x": cx + pin_radius + 5,
                "y": cy + 4,
                "font_size": 12.0,
                "text_anchor": "start",
                "rotation_degrees": 0.0,
            }
        )
    if not has_left_neighbor and flip_x:
        candidates.append(
            {
                "x": cx - pin_radius - 5,
                "y": cy + 4,
                "font_size": 12.0,
                "text_anchor": "end",
                "rotation_degrees": 0.0,
            }
        )
    if not has_left_neighbor:
        candidates.append(
            {
                "x": cx - pin_radius - 5,
                "y": cy + 4,
                "font_size": 12.0,
                "text_anchor": "end",
                "rotation_degrees": 0.0,
            }
        )
    if not has_top_neighbor:
        candidates.append(
            {
                "x": cx,
                "y": cy - pin_radius - 8,
                "font_size": 12.0,
                "text_anchor": "middle",
                "rotation_degrees": 0.0,
            }
        )
    if not has_bottom_neighbor:
        candidates.append(
            {
                "x": cx,
                "y": cy + pin_radius + 16,
                "font_size": 12.0,
                "text_anchor": "middle",
                "rotation_degrees": 0.0,
            }
        )

    for lift in (0, 10, 20):
        y_offset = cy - pin_radius - 8 - lift
        candidates.append(
            {
                "x": cx,
                "y": y_offset,
                "font_size": 11.0,
                "text_anchor": "middle",
                "rotation_degrees": -30.0 if not flip_x else 30.0,
            }
        )

    return candidates


def _select_label_candidate(
    *,
    name: str,
    candidates: list[dict[str, str | float]],
    occupied_rectangles: list[tuple[float, float, float, float]],
) -> tuple[dict[str, str | float], tuple[float, float, float, float]]:
    best_candidate = candidates[0]
    best_bbox = _estimate_text_bbox(
        name,
        x=float(best_candidate["x"]),
        y=float(best_candidate["y"]),
        font_size=float(best_candidate["font_size"]),
        text_anchor=str(best_candidate["text_anchor"]),
        rotation_degrees=float(best_candidate["rotation_degrees"]),
    )
    best_collision_score = sum(
        1
        for rectangle in occupied_rectangles
        if _rectangles_overlap(best_bbox, rectangle, padding=4.0)
    )

    for candidate in candidates:
        candidate_bbox = _estimate_text_bbox(
            name,
            x=float(candidate["x"]),
            y=float(candidate["y"]),
            font_size=float(candidate["font_size"]),
            text_anchor=str(candidate["text_anchor"]),
            rotation_degrees=float(candidate["rotation_degrees"]),
        )
        collision_score = sum(
            1
            for rectangle in occupied_rectangles
            if _rectangles_overlap(candidate_bbox, rectangle, padding=4.0)
        )
        if collision_score == 0:
            return candidate, candidate_bbox
        if collision_score < best_collision_score:
            best_candidate = candidate
            best_bbox = candidate_bbox
            best_collision_score = collision_score

    return best_candidate, best_bbox


def generate_routed_svg(
    pin_positions: dict[str, tuple[float, float]],
    connections: list[dict[str, Any]],
    waypoint_solutions: dict[int, dict[str, Any]] | None,
    *,
    boxes: tuple[PinoutBox, ...] = (),
    flip_x: bool = False,
    version_label: str | None = None,
    notes_text: str | None = None,
    color_map: dict[str, str] | None = None,
    svg_margins_px: SvgMarginsPx = DEFAULT_SVG_MARGINS_PX,
) -> str:
    """Generate SVG content for a routed pinout view."""
    if not pin_positions:
        raise ValueError("pin_positions must not be empty")

    merged_color_map = dict(DEFAULT_COLOR_MAP)
    if color_map:
        merged_color_map.update(color_map)

    min_x, min_y, max_x, max_y = _calculate_bounds(
        pin_positions, waypoint_solutions, boxes
    )
    actual_pin_positions, actual_waypoints = _transform_positions_for_view(
        pin_positions,
        waypoint_solutions,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        flip_x=flip_x,
    )

    view_label = "Underside View" if flip_x else "Top View"
    base_margin = 0.5
    annotation_width_px = _estimate_annotation_width_px(
        view_label=view_label,
        version_label=version_label,
        notes_text=notes_text,
    )
    margin_right = base_margin + 3.0 + (annotation_width_px / 40.0) + 0.75
    margin_top = base_margin + 0.5
    margin_left = base_margin + 1.0
    margin_bottom = base_margin
    coord_shift_x = margin_left - min_x
    coord_shift_y = margin_top - min_y

    grid_size = 40
    vb_x = 0
    vb_y = 0
    vb_w = int((max_x - min_x + margin_left + margin_right + 1) * grid_size)
    vb_h = int((max_y - min_y + margin_top + margin_bottom + 1) * grid_size)

    root = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"{vb_x} {vb_y} {vb_w} {vb_h}",
            "width": "100%",
            "height": "100%",
        },
    )
    svg_bounds = _SvgBounds()

    _draw_pinout_boxes(
        root,
        svg_bounds,
        boxes,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        coord_shift_x=coord_shift_x,
        coord_shift_y=coord_shift_y,
        grid_size=grid_size,
        flip_x=flip_x,
    )

    for i, connection in enumerate(connections):
        p1 = actual_pin_positions[connection["from"]]
        p2 = actual_pin_positions[connection["to"]]
        kind = str(connection.get("type", connection.get("kind", "default"))).strip()
        explicit_color = connection.get("color")
        color = str(
            explicit_color or merged_color_map.get(kind, merged_color_map["default"])
        )

        x1 = int((p1[0] + coord_shift_x) * grid_size)
        y1 = int((p1[1] + coord_shift_y) * grid_size)
        x2 = int((p2[0] + coord_shift_x) * grid_size)
        y2 = int((p2[1] + coord_shift_y) * grid_size)

        if i in actual_waypoints:
            wx = int((actual_waypoints[i][0] + coord_shift_x) * grid_size)
            wy = int((actual_waypoints[i][1] + coord_shift_y) * grid_size)
            svg_bounds.add_rect(_line_bbox(x1, y1, wx, wy, stroke_width=2.0))
            ET.SubElement(
                root,
                "line",
                {
                    "x1": str(x1),
                    "y1": str(y1),
                    "x2": str(wx),
                    "y2": str(wy),
                    "stroke": color,
                    "stroke-width": "2",
                },
            )
            svg_bounds.add_rect(_line_bbox(wx, wy, x2, y2, stroke_width=2.0))
            ET.SubElement(
                root,
                "line",
                {
                    "x1": str(wx),
                    "y1": str(wy),
                    "x2": str(x2),
                    "y2": str(y2),
                    "stroke": color,
                    "stroke-width": "2",
                },
            )
            svg_bounds.add_rect(_circle_bbox(wx, wy, radius=3.0, stroke_width=1.0))
            ET.SubElement(
                root,
                "circle",
                {
                    "cx": str(wx),
                    "cy": str(wy),
                    "r": "3",
                    "fill": color,
                    "stroke": "black",
                    "stroke-width": "1",
                },
            )
            continue

        svg_bounds.add_rect(_line_bbox(x1, y1, x2, y2, stroke_width=2.0))
        ET.SubElement(
            root,
            "line",
            {
                "x1": str(x1),
                "y1": str(y1),
                "x2": str(x2),
                "y2": str(y2),
                "stroke": color,
                "stroke-width": "2",
            },
        )

    pin_radius = 6
    pin_rectangles = []
    for x, y in actual_pin_positions.values():
        cx = int((x + coord_shift_x) * grid_size)
        cy = int((y + coord_shift_y) * grid_size)
        pin_rectangles.append(
            (
                cx - pin_radius - 2,
                cy - pin_radius - 2,
                cx + pin_radius + 2,
                cy + pin_radius + 2,
            )
        )

    placed_label_rectangles: list[tuple[float, float, float, float]] = []
    for name, (x, y) in actual_pin_positions.items():
        cx = int((x + coord_shift_x) * grid_size)
        cy = int((y + coord_shift_y) * grid_size)
        svg_bounds.add_rect(_circle_bbox(cx, cy, radius=pin_radius, stroke_width=1.0))
        ET.SubElement(
            root,
            "circle",
            {
                "cx": str(cx),
                "cy": str(cy),
                "r": str(pin_radius),
                "fill": "lightgray",
                "stroke": "black",
            },
        )

        has_right_neighbor = any(
            other != name and oy == y and 0 < ox - x <= 2
            for other, (ox, oy) in actual_pin_positions.items()
        )
        has_left_neighbor = any(
            other != name and oy == y and 0 < x - ox <= 2
            for other, (ox, oy) in actual_pin_positions.items()
        )
        has_top_neighbor = any(
            other != name and ox == x and 0 < oy - y <= 2
            for other, (ox, oy) in actual_pin_positions.items()
        )
        has_bottom_neighbor = any(
            other != name and ox == x and 0 < y - oy <= 2
            for other, (ox, oy) in actual_pin_positions.items()
        )

        label_candidates = _build_label_candidates(
            name=name,
            cx=cx,
            cy=cy,
            pin_radius=pin_radius,
            has_left_neighbor=has_left_neighbor,
            has_right_neighbor=has_right_neighbor,
            has_top_neighbor=has_top_neighbor,
            has_bottom_neighbor=has_bottom_neighbor,
            flip_x=flip_x,
        )
        label_candidate, label_bbox = _select_label_candidate(
            name=name,
            candidates=label_candidates,
            occupied_rectangles=[*pin_rectangles, *placed_label_rectangles],
        )

        label_attrs = {
            "font-size": f"{int(float(label_candidate['font_size']))}px",
            "font-family": "monospace",
            "text-anchor": str(label_candidate["text_anchor"]),
        }
        rotation_degrees = float(label_candidate["rotation_degrees"])
        label_x = float(label_candidate["x"])
        label_y = float(label_candidate["y"])
        if rotation_degrees:
            label_attrs["transform"] = (
                f"rotate({rotation_degrees:g},{label_x:g},{label_y:g})"
            )

        _add_text(
            root,
            name,
            x=f"{label_x:g}",
            y=f"{label_y:g}",
            **label_attrs,
        )
        placed_label_rectangles.append(label_bbox)
        svg_bounds.add_rect(label_bbox)

    label_x = vb_w - 20
    label_y = 30
    svg_bounds.add_rect(
        _estimate_text_bbox(
            view_label,
            x=label_x,
            y=label_y,
            font_size=16.0,
            text_anchor="end",
        )
    )
    _add_text(
        root,
        view_label,
        x=str(label_x),
        y=str(label_y),
        **{
            "font-size": "16px",
            "font-family": "sans-serif",
            "font-weight": "bold",
            "text-anchor": "end",
            "fill": "darkblue",
        },
    )

    if version_label:
        svg_bounds.add_rect(
            _estimate_text_bbox(
                version_label,
                x=label_x,
                y=label_y + 20,
                font_size=12.0,
                text_anchor="end",
            )
        )
        _add_text(
            root,
            version_label,
            x=str(label_x),
            y=str(label_y + 20),
            **{
                "font-size": "12px",
                "font-family": "sans-serif",
                "text-anchor": "end",
                "fill": "darkgreen",
            },
        )

    if notes_text:
        for i, line in enumerate(notes_text.splitlines()):
            svg_bounds.add_rect(
                _estimate_text_bbox(
                    line,
                    x=label_x,
                    y=label_y + 40 + i * 15,
                    font_size=10.0,
                    text_anchor="end",
                )
            )
            _add_text(
                root,
                line,
                x=str(label_x),
                y=str(label_y + 40 + i * 15),
                **{
                    "font-size": "10px",
                    "font-family": "sans-serif",
                    "text-anchor": "end",
                    "fill": "black",
                },
            )

    final_vb_x, final_vb_y, final_vb_w, final_vb_h = svg_bounds.viewbox(svg_margins_px)
    root.set("viewBox", f"{final_vb_x} {final_vb_y} {final_vb_w} {final_vb_h}")
    return ET.tostring(root, encoding="unicode")


def write_svg(svg_content: str, filename: str | Path) -> Path:
    """Write SVG content to disk."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg_content, encoding="utf-8")
    return path
