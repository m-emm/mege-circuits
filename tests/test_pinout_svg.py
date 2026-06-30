import re
from xml.etree import ElementTree as ET

from mege_circuits.pinout.svg import _estimate_text_bbox, generate_routed_svg

SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"


def _viewbox(svg_content: str) -> tuple[float, float, float, float]:
    root = ET.fromstring(svg_content)
    return tuple(float(value) for value in root.attrib["viewBox"].split())


def _viewbox_width(svg_content: str) -> int:
    return int(_viewbox(svg_content)[2])


def _text_bbox(node: ET.Element) -> tuple[float, float, float, float]:
    font_size = float(node.attrib["font-size"].removesuffix("px"))
    rotation_degrees = 0.0
    transform = node.attrib.get("transform", "")
    rotation_match = re.search(r"rotate\(([-0-9.]+),", transform)
    if rotation_match:
        rotation_degrees = float(rotation_match.group(1))

    return _estimate_text_bbox(
        node.text or "",
        x=float(node.attrib["x"]),
        y=float(node.attrib["y"]),
        font_size=font_size,
        text_anchor=node.attrib.get("text-anchor", "start"),
        rotation_degrees=rotation_degrees,
    )


def test_generate_routed_svg_reserves_right_margin_for_annotations():
    pin_positions = {
        "LEFT": (0.0, 0.0),
        "RIGHT": (6.0, 0.0),
    }
    connections = [{"from": "LEFT", "to": "RIGHT", "type": "data"}]

    svg_without_notes = generate_routed_svg(
        pin_positions,
        connections,
        {},
        flip_x=False,
    )
    svg_with_notes = generate_routed_svg(
        pin_positions,
        connections,
        {},
        flip_x=False,
        version_label="Example version label",
        notes_text="A much longer annotation line that needs reserved width.",
    )

    assert _viewbox_width(svg_with_notes) > _viewbox_width(svg_without_notes)
    assert "A much longer annotation line that needs reserved width." in svg_with_notes


def test_generate_routed_svg_rotates_labels_for_horizontal_pin_rows():
    pin_positions = {
        "MOSFET_GND": (0.0, 0.0),
        "MOSFET_IN": (1.0, 0.0),
        "MOSFET_TRIG_1": (2.0, 0.0),
        "MOSFET_TRIG_2": (3.0, 0.0),
    }

    svg_content = generate_routed_svg(
        pin_positions,
        [],
        {},
        flip_x=False,
    )

    root = ET.fromstring(svg_content)
    label_nodes = [
        node
        for node in root.findall(f"{SVG_NAMESPACE}text")
        if node.text in pin_positions
    ]
    label_y_positions = {node.attrib["y"] for node in label_nodes}

    assert 'transform="rotate(-45' in svg_content
    assert "MOSFET_TRIG_1" in svg_content
    assert "MOSFET_TRIG_2" in svg_content
    assert len(label_y_positions) > 1


def test_generate_routed_svg_auto_fits_left_edge_labels():
    pin_positions = {
        "VERY_LONG_LEFT_EDGE_LABEL_THAT_WOULD_CLIP": (0.0, 0.0),
    }

    svg_content = generate_routed_svg(
        pin_positions,
        [],
        {},
        flip_x=True,
        svg_margins_px=(20.0, 20.0, 20.0, 20.0),
    )

    root = ET.fromstring(svg_content)
    viewbox_x, viewbox_y, viewbox_width, viewbox_height = _viewbox(svg_content)
    viewbox_right = viewbox_x + viewbox_width
    viewbox_bottom = viewbox_y + viewbox_height

    assert viewbox_x < 0
    for node in root.findall(f"{SVG_NAMESPACE}text"):
        bbox = _text_bbox(node)
        assert bbox[0] >= viewbox_x
        assert bbox[1] >= viewbox_y
        assert bbox[2] <= viewbox_right
        assert bbox[3] <= viewbox_bottom
