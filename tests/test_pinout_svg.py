import math
import re
from xml.etree import ElementTree as ET

import pytest

from mege_circuits.pinout.config import PinoutBox, load_pinout_config
from mege_circuits.pinout.discrete import generate_discrete_top_svg
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


def test_generate_routed_svg_draws_and_mirrors_shared_boxes():
    pin_positions = {
        "LEFT": (0.0, 0.0),
        "RIGHT": (1.0, 0.0),
    }
    box = PinoutBox(
        id="driver",
        label="TMC5160T Plus\n64 x 57 mm",
        top_left=(4.0, 3.0),
        size_pitches=(64 / 2.54, 57 / 2.54),
    )

    top_svg = generate_routed_svg(
        pin_positions,
        [],
        {},
        boxes=(box,),
        flip_x=False,
    )
    bottom_svg = generate_routed_svg(
        pin_positions,
        [],
        {},
        boxes=(box,),
        flip_x=True,
    )
    top_root = ET.fromstring(top_svg)
    bottom_root = ET.fromstring(bottom_svg)
    top_box = top_root.find(f"{SVG_NAMESPACE}rect[@class='pinout-box']")
    bottom_box = bottom_root.find(f"{SVG_NAMESPACE}rect[@class='pinout-box']")

    assert top_box is not None
    assert bottom_box is not None
    assert float(top_box.attrib["width"]) == pytest.approx((64 / 2.54) * 40)
    assert float(top_box.attrib["height"]) == pytest.approx((57 / 2.54) * 40)
    assert float(top_box.attrib["x"]) != float(bottom_box.attrib["x"])
    assert top_svg.count('data-box="driver"') == 3
    assert "TMC5160T Plus" in top_svg
    assert "64 x 57 mm" in bottom_svg


def test_generate_discrete_top_svg_draws_components_without_wiring(tmp_path):
    config_path = tmp_path / "discrete.yaml"
    config_path.write_text(
        """
metadata:
  version_label: test placement
boxes:
  - id: driver
    label: Driver outline
    top_left: [7, 3]
    size_pitches: [2, 2]
pin_sets:
  - id: left
    prefix: A
    origin: [0, 2]
    direction: down
    discrete_pin_numbers: {start: 1, step: 1}
    pins: ["01", "02", "03"]
  - id: right
    prefix: A
    origin: [3, 2]
    direction: down
    discrete_pin_numbers: {start: 6, step: -1}
    pins: ["06", "05", "04"]
wires:
  - from: A01
    to: A06
component_placements:
  - ref: R1
    kind: resistor
    value: 10k
    terminals: {start: A01, end: A06}
  - ref: DZ1
    kind: zener
    value: 3V3
    terminals: {anode: A05, cathode: A02}
  - ref: Q1
    kind: bjt_pnp
    value: BC327 PNP
    terminals: {collector: A03, base: A04, emitter: A05}
discrete_view:
  title: Placement test
  notes: K is the cathode band.
  groups:
    - id: socket
      label: Socket A
      pin_sets: [left, right]
  anchor_labels: {A01: pin 1}
""".strip(),
        encoding="utf-8",
    )

    # Q1 intentionally cannot share A05 with DZ1; use a second project with
    # distinct pins after first proving the placement validator does its job.
    with pytest.raises(ValueError, match="occupied by both"):
        load_pinout_config(config_path)

    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace(
            "terminals: {collector: A03, base: A04, emitter: A05}",
            "terminals: {collector: B01, base: B02, emitter: B03}",
        )
        .replace(
            "wires:\n  - from: A01",
            "pins:\n  B01: [5, 2]\n  B02: [5, 1]\n  B03: [5, 0]\nwires:\n  - from: A01",
        ),
        encoding="utf-8",
    )
    project = load_pinout_config(config_path)
    svg_content = generate_discrete_top_svg(project)
    root = ET.fromstring(svg_content)

    assert 'class="discrete-background"' in svg_content
    assert 'class="pinout-box"' in svg_content
    assert 'data-box="driver"' in svg_content
    assert 'data-component="R1"' in svg_content
    assert 'data-component="DZ1"' in svg_content
    assert 'data-component="Q1"' in svg_content
    assert 'class="cathode-band"' in svg_content
    assert 'class="transistor-terminal-label"' in svg_content
    assert 'class="discrete-pin-group"' in svg_content
    assert 'data-pin="A01"' in svg_content
    assert "Placement test" in svg_content
    assert "K is the cathode band." in svg_content
    assert not root.findall(f"{SVG_NAMESPACE}polyline[@class='wire']")

    pin_positions = {
        node.attrib["data-pin"]: (
            float(node.attrib["cx"]),
            float(node.attrib["cy"]),
        )
        for node in root.iter(f"{SVG_NAMESPACE}circle")
        if node.attrib.get("class") == "discrete-pin"
    }
    cathode_band = next(
        node
        for node in root.iter(f"{SVG_NAMESPACE}line")
        if node.attrib.get("class") == "cathode-band"
        and node.attrib.get("data-component") == "DZ1"
    )
    band_center = (
        (float(cathode_band.attrib["x1"]) + float(cathode_band.attrib["x2"])) / 2.0,
        (float(cathode_band.attrib["y1"]) + float(cathode_band.attrib["y2"])) / 2.0,
    )
    assert math.dist(band_center, pin_positions["A02"]) < math.dist(
        band_center, pin_positions["A05"]
    )

    polarity_labels = {
        node.attrib["data-terminal"]: (
            node.text,
            (float(node.attrib["x"]), float(node.attrib["y"])),
        )
        for node in root.iter(f"{SVG_NAMESPACE}text")
        if node.attrib.get("class") == "polarity-label"
        and node.attrib.get("data-component") == "DZ1"
    }
    assert polarity_labels["anode"][0] == "A"
    assert polarity_labels["cathode"][0] == "K"
    assert math.dist(polarity_labels["anode"][1], pin_positions["A05"]) < math.dist(
        polarity_labels["anode"][1], pin_positions["A02"]
    )
    assert math.dist(polarity_labels["cathode"][1], pin_positions["A02"]) < math.dist(
        polarity_labels["cathode"][1], pin_positions["A05"]
    )
