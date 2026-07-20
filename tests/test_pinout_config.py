from pathlib import Path

import pytest

from mege_circuits.pinout.config import load_pinout_config


def test_load_pinout_config_rejects_duplicate_pin_coordinates(tmp_path: Path):
    config_path = tmp_path / "duplicate_coords.yaml"
    config_path.write_text(
        """
basename: duplicate_coords
pin_sets:
  - prefix: LEFT_
    origin: [0, 0]
    direction: right
    pins: [A, B]
  - prefix: RIGHT_
    origin: [1, 0]
    direction: left
    pins: [C, D]
wires:
  - from: LEFT_A
    to: RIGHT_C
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate pin coordinates detected"):
        load_pinout_config(config_path)


def test_load_pinout_config_accepts_distinct_pin_coordinates(tmp_path: Path):
    config_path = tmp_path / "distinct_coords.yaml"
    config_path.write_text(
        """
basename: distinct_coords
pin_sets:
  - prefix: LEFT_
    origin: [0, 0]
    direction: right
    pins: [A, B]
pins:
  EXTRA: [3, 2]
wires:
  - from: LEFT_A
    to: EXTRA
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert project.pin_positions["LEFT_A"] == (0.0, 0.0)
    assert project.pin_positions["LEFT_B"] == (1.0, 0.0)
    assert project.pin_positions["EXTRA"] == (3.0, 2.0)


def test_load_pinout_config_accepts_scalar_svg_margin(tmp_path: Path):
    config_path = tmp_path / "scalar_margin.yaml"
    config_path.write_text(
        """
metadata:
  svg_margins_px: 32
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
wires:
  - from: LEFT
    to: RIGHT
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert project.svg_margins_px == (32.0, 32.0, 32.0, 32.0)


def test_load_pinout_config_accepts_per_side_svg_margins(tmp_path: Path):
    config_path = tmp_path / "per_side_margins.yaml"
    config_path.write_text(
        """
metadata:
  svg_margins_px:
    left: 10
    right: 20
    top: 30
    bottom: 40
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
wires:
  - from: LEFT
    to: RIGHT
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert project.svg_margins_px == (10.0, 20.0, 30.0, 40.0)


def test_load_pinout_config_normalizes_discrete_placements_and_groups(
    tmp_path: Path,
):
    config_path = tmp_path / "discrete.yaml"
    config_path.write_text(
        """
pin_sets:
  - id: socket_left
    prefix: A
    origin: [0, 1]
    direction: down
    discrete_pin_numbers: {start: 1, step: 1}
    pins: [01_LEFT, 02_LEFT]
  - id: socket_right
    prefix: A
    origin: [3, 1]
    direction: down
    discrete_pin_numbers: {start: 4, step: -1}
    pins: [04_RIGHT, 03_RIGHT]
wires:
  - from: A01_LEFT
    to: A04_RIGHT
component_placements:
  - ref: R1
    kind: resistor
    value: 10k
    terminals: {start: A01_LEFT, end: A04_RIGHT}
  - ref: D1
    kind: diode
    value: 1N4148
    terminals: {anode: A02_LEFT, cathode: A03_RIGHT}
discrete_view:
  title: Assembly side
  notes: Insert components, then flip the board.
  groups:
    - id: socket_a
      label: Socket A
      pin_sets: [socket_left, socket_right]
  anchor_labels:
    A01_LEFT: pin 1
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert project.pin_sets == {
        "socket_left": ("A01_LEFT", "A02_LEFT"),
        "socket_right": ("A04_RIGHT", "A03_RIGHT"),
    }
    assert project.discrete_pin_numbers == {
        "A01_LEFT": "1",
        "A02_LEFT": "2",
        "A04_RIGHT": "4",
        "A03_RIGHT": "3",
    }
    assert [component.ref for component in project.component_placements] == [
        "R1",
        "D1",
    ]
    assert project.discrete_view is not None
    assert project.discrete_view.groups[0].pin_sets == (
        "socket_left",
        "socket_right",
    )
    assert project.discrete_view.anchor_labels == {"A01_LEFT": "pin 1"}


def test_load_pinout_config_normalizes_shared_boxes(tmp_path: Path):
    config_path = tmp_path / "box.yaml"
    config_path.write_text(
        """
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
boxes:
  - id: driver
    label: |
      TMC5160T Plus
      64 x 57 mm
    top_left: [4, 3]
    size_pitches: [25.1968503937, 22.4409448819]
wires:
  - from: LEFT
    to: RIGHT
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert len(project.boxes) == 1
    assert project.boxes[0].id == "driver"
    assert project.boxes[0].label == "TMC5160T Plus\n64 x 57 mm"
    assert project.boxes[0].top_left == (4.0, 3.0)
    assert project.boxes[0].size_pitches == pytest.approx((64 / 2.54, 57 / 2.54))


@pytest.mark.parametrize(
    ("box_yaml", "message"),
    [
        (
            "{id: driver, label: Driver, top_left: [0, 0], " "size_pitches: [0, 2]}",
            "size_pitches values must be > 0",
        ),
        (
            "{id: driver, label: Driver, top_left: [0, 0], " "size_pitches: [.nan, 2]}",
            "coordinates and size must be finite",
        ),
        (
            "{id: driver, label: Driver, top_left: [0, 0], "
            "size_pitches: [2, 2], color: red}",
            "Unknown boxes",
        ),
    ],
)
def test_load_pinout_config_rejects_invalid_shared_boxes(
    tmp_path: Path,
    box_yaml: str,
    message: str,
):
    config_path = tmp_path / "invalid_box.yaml"
    config_path.write_text(
        f"""
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
boxes:
  - {box_yaml}
wires:
  - from: LEFT
    to: RIGHT
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_pinout_config(config_path)


@pytest.mark.parametrize(
    ("extra_yaml", "message"),
    [
        (
            """
  - ref: R2
    kind: resistor
    value: 22k
    terminals: {start: LEFT, end: EXTRA}
""",
            "unknown pins",
        ),
        (
            """
  - ref: R2
    kind: resistor
    value: 22k
    terminals: {start: LEFT, end: RIGHT}
""",
            "occupied by both",
        ),
    ],
)
def test_load_pinout_config_rejects_invalid_discrete_placements(
    tmp_path: Path,
    extra_yaml: str,
    message: str,
):
    config_path = tmp_path / "invalid_discrete.yaml"
    config_path.write_text(
        (
            """
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
wires:
  - from: LEFT
    to: RIGHT
component_placements:
  - ref: R1
    kind: resistor
    value: 10k
    terminals: {start: LEFT, end: RIGHT}
"""
            + extra_yaml
        ).strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_pinout_config(config_path)
