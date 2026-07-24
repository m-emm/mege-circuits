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


def _three_lead_nodes(root, component_ref):
    body = next(
        node
        for node in root.iter(f"{SVG_NAMESPACE}path")
        if node.attrib.get("class") == "to92-body"
        and node.attrib.get("data-component") == component_ref
    )
    flat_face = next(
        node
        for node in root.iter(f"{SVG_NAMESPACE}line")
        if node.attrib.get("class") == "to92-flat-face"
        and node.attrib.get("data-component") == component_ref
    )
    leads = {
        node.attrib["data-terminal"]: node
        for node in root.iter(f"{SVG_NAMESPACE}line")
        if node.attrib.get("class") == "to92-lead"
        and node.attrib.get("data-component") == component_ref
    }
    labels = {
        node.attrib["data-terminal"]: node
        for node in root.iter(f"{SVG_NAMESPACE}text")
        if node.attrib.get("class") == "to92-terminal-label"
        and node.attrib.get("data-component") == component_ref
    }
    return body, flat_face, leads, labels


def _pin_positions(root):
    return {
        node.attrib["data-pin"]: (
            float(node.attrib["cx"]),
            float(node.attrib["cy"]),
        )
        for node in root.iter(f"{SVG_NAMESPACE}circle")
        if node.attrib.get("class") == "discrete-pin"
    }


def test_generate_discrete_top_svg_orients_numbered_to92_from_pin1_to_pin3(
    tmp_path,
):
    config_path = tmp_path / "to92.yaml"
    config_path.write_text(
        """
basename: to92
pin_sets:
  - id: regulator
    prefix: U3_
    origin: [0, 2]
    direction: down
    pins: [OUT, GND, IN]
pins:
  GND_BUS: [3, 1]
wires:
  - from: U3_GND
    to: GND_BUS
component_placements:
  - ref: U3
    kind: to92
    value: LP2950L-3.3
    terminals: {pin1: U3_OUT, pin2: U3_GND, pin3: U3_IN}
discrete_view:
  title: TO-92 placement test
  groups:
    - id: regulator
      label: Regulator
      pin_sets: [regulator]
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)
    svg_content = generate_discrete_top_svg(project)
    root = ET.fromstring(svg_content)
    body, flat_face, leads, labels = _three_lead_nodes(root, "U3")
    pins = _pin_positions(root)

    assert 'data-component="U3"' in svg_content
    assert 'class="to92-body"' in svg_content
    assert 'class="to92-terminal-label"' in svg_content
    assert "LP2950L-3.3" in svg_content
    assert float(body.attrib["data-body-min-x"]) > pins["U3_OUT"][0]
    assert float(flat_face.attrib["x1"]) == pytest.approx(float(flat_face.attrib["x2"]))
    assert float(flat_face.attrib["x1"]) < float(body.attrib["data-body-max-x"])
    assert {terminal: label.text for terminal, label in labels.items()} == {
        "pin1": "1",
        "pin2": "2",
        "pin3": "3",
    }
    for terminal, pin_name in {
        "pin1": "U3_OUT",
        "pin2": "U3_GND",
        "pin3": "U3_IN",
    }.items():
        assert (
            float(leads[terminal].attrib["x1"]),
            float(leads[terminal].attrib["y1"]),
        ) == pytest.approx(pins[pin_name])


def test_reversing_numbered_to92_pin_order_mirrors_the_body(tmp_path):
    config_path = tmp_path / "reversed_to92.yaml"
    config_path.write_text(
        """
basename: reversed_to92
pins:
  TOP: [0, 2]
  MIDDLE: [0, 1]
  BOTTOM: [0, 0]
wires:
  - from: TOP
    to: MIDDLE
component_placements:
  - ref: Q1
    kind: to92
    value: unknown
    terminals: {pin1: BOTTOM, pin2: MIDDLE, pin3: TOP}
""".strip(),
        encoding="utf-8",
    )

    root = ET.fromstring(generate_discrete_top_svg(load_pinout_config(config_path)))
    body, flat_face, _, _ = _three_lead_nodes(root, "Q1")
    pins = _pin_positions(root)

    assert float(body.attrib["data-body-max-x"]) < pins["TOP"][0]
    assert float(flat_face.attrib["x1"]) == pytest.approx(float(flat_face.attrib["x2"]))
    assert float(flat_face.attrib["x1"]) > float(body.attrib["data-body-min-x"])


def test_horizontal_to92_row_rotates_flat_face_and_body(tmp_path):
    config_path = tmp_path / "horizontal_to92.yaml"
    config_path.write_text(
        """
basename: horizontal_to92
pins:
  LEFT: [0, 0]
  MIDDLE: [1, 0]
  RIGHT: [2, 0]
wires:
  - from: LEFT
    to: MIDDLE
component_placements:
  - ref: Q1
    kind: to92
    value: unknown
    terminals: {pin1: LEFT, pin2: MIDDLE, pin3: RIGHT}
""".strip(),
        encoding="utf-8",
    )

    root = ET.fromstring(generate_discrete_top_svg(load_pinout_config(config_path)))
    body, flat_face, _, _ = _three_lead_nodes(root, "Q1")
    pins = _pin_positions(root)

    assert float(body.attrib["data-body-max-y"]) < pins["LEFT"][1]
    assert float(flat_face.attrib["y1"]) == pytest.approx(float(flat_face.attrib["y2"]))
    assert float(flat_face.attrib["y1"]) > float(body.attrib["data-body-min-y"])


def test_catalog_backed_npn_variant_changes_package_orientation_not_semantics(
    tmp_path,
):
    config_template = """
basename: npn
pins:
  COLLECTOR: [0, 2]
  BASE: [0, 1]
  EMITTER: [0, 0]
wires:
  - from: COLLECTOR
    to: BASE
component_placements:
  - ref: Q1
    kind: bjt_npn
    part: BC337
{variant_line}
    value: BC337
    terminals: {{collector: COLLECTOR, base: BASE, emitter: EMITTER}}
"""
    bodies = {}
    for variant in ("cbe", "ebc"):
        config_path = tmp_path / f"npn_{variant}.yaml"
        config_path.write_text(
            config_template.format(
                variant_line=("    pinout_variant: ebc" if variant == "ebc" else "")
            ).strip(),
            encoding="utf-8",
        )
        root = ET.fromstring(generate_discrete_top_svg(load_pinout_config(config_path)))
        body, _, leads, labels = _three_lead_nodes(root, "Q1")
        pins = _pin_positions(root)
        bodies[variant] = body

        assert {terminal: label.text for terminal, label in labels.items()} == {
            "collector": "C",
            "base": "B",
            "emitter": "E",
        }
        for terminal, pin_name in {
            "collector": "COLLECTOR",
            "base": "BASE",
            "emitter": "EMITTER",
        }.items():
            assert (
                float(leads[terminal].attrib["x1"]),
                float(leads[terminal].attrib["y1"]),
            ) == pytest.approx(pins[pin_name])

    pin_x = _pin_positions(
        ET.fromstring(
            generate_discrete_top_svg(load_pinout_config(tmp_path / "npn_cbe.yaml"))
        )
    )["COLLECTOR"][0]
    assert float(bodies["cbe"].attrib["data-body-min-x"]) > pin_x
    assert float(bodies["ebc"].attrib["data-body-max-x"]) < pin_x


def test_catalog_backed_regulator_uses_semantic_labels_and_utc_pinout(tmp_path):
    config_path = tmp_path / "regulator.yaml"
    config_path.write_text(
        """
basename: regulator
pins:
  OUT: [0, 2]
  GND: [0, 1]
  IN: [0, 0]
wires:
  - from: OUT
    to: GND
component_placements:
  - ref: U3
    kind: voltage_regulator
    part: UTC_LP2950L_33_T92
    value: LP2950L-3.3
    terminals: {output: OUT, ground: GND, input: IN}
""".strip(),
        encoding="utf-8",
    )

    root = ET.fromstring(generate_discrete_top_svg(load_pinout_config(config_path)))
    body, _, leads, labels = _three_lead_nodes(root, "U3")
    pins = _pin_positions(root)

    assert body.attrib["data-part"] == "UTC_LP2950L_33_T92"
    assert float(body.attrib["data-body-min-x"]) > pins["OUT"][0]
    assert {terminal: label.text for terminal, label in labels.items()} == {
        "output": "OUT",
        "ground": "GND",
        "input": "IN",
    }
    for terminal, pin_name in {
        "output": "OUT",
        "ground": "GND",
        "input": "IN",
    }.items():
        assert (
            float(leads[terminal].attrib["x1"]),
            float(leads[terminal].attrib["y1"]),
        ) == pytest.approx(pins[pin_name])


def test_three_lead_renderer_rejects_non_collinear_positions(tmp_path):
    config_path = tmp_path / "non_collinear_to92.yaml"
    config_path.write_text(
        """
basename: non_collinear_to92
pins:
  P1: [0, 2]
  P2: [1, 1]
  P3: [0, 0]
wires:
  - from: P1
    to: P2
component_placements:
  - ref: Q1
    kind: to92
    value: unknown
    terminals: {pin1: P1, pin2: P2, pin3: P3}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be collinear"):
        generate_discrete_top_svg(load_pinout_config(config_path))
