from pathlib import Path

import pytest

from mege_circuits.pinout.config import PinoutDownholderKind, load_pinout_config


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


def test_load_pinout_config_normalizes_physical_components(tmp_path: Path):
    config_path = tmp_path / "physical_components.yaml"
    config_path.write_text(
        """
pin_sets:
  - id: adapter_j1
    prefix: J1_
    origin: [0, 0]
    direction: right
    pins: [EN, STEP]
  - id: adapter_j2
    prefix: J2_
    origin: [0, 2]
    direction: right
    pins: [VM, VIO]
  - id: adapter_top
    prefix: TOP_
    origin: [0, 4]
    direction: right
    pins: [DIAG0, DIAG1]
  - id: auxiliary_line
    prefix: AUX_
    origin: [15, 0]
    direction: up
    pins: [ONE, TWO]
boxes:
  - id: driver
    label: Driver
    top_left: [4, 5]
    size_pitches: [8, 6]
physical_components:
  - id: adapter
    label: StepStick adapter
    component_type: stepstick_adapter
    pin_sets: [adapter_j1, adapter_j2, adapter_top]
    downholder: perimeter_frame
  - id: auxiliary_line
    component_type: pin_line
    pin_sets: [auxiliary_line]
    downholder: pin_line_upholder
  - id: driver
    component_type: boxed_module
    pin_sets: []
    through_pin_sets: []
    box: driver
    downholder: none
wires:
  - from: J1_EN
    to: J1_STEP
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    adapter, auxiliary_line, driver = project.physical_components
    assert adapter.id == "adapter"
    assert adapter.label == "StepStick adapter"
    assert adapter.component_type == "stepstick_adapter"
    assert adapter.pin_sets == ("adapter_j1", "adapter_j2", "adapter_top")
    assert adapter.through_pin_sets == adapter.pin_sets
    assert adapter.downholder is PinoutDownholderKind.PERIMETER_FRAME
    assert adapter.box_id is None
    assert auxiliary_line.component_type == "pin_line"
    assert auxiliary_line.pin_sets == ("auxiliary_line",)
    assert auxiliary_line.downholder is PinoutDownholderKind.PIN_LINE_UPHOLDER
    assert driver.pin_sets == ()
    assert driver.through_pin_sets == ()
    assert driver.box_id == "driver"


def test_pinout_physical_component_types_are_exported_through_simple():
    from mege_circuits.simple import PinoutDownholderKind as ExportedDownholderKind
    from mege_circuits.simple import (
        PinoutPhysicalComponent as ExportedPhysicalComponent,
    )

    assert ExportedDownholderKind is PinoutDownholderKind
    assert ExportedPhysicalComponent.__name__ == "PinoutPhysicalComponent"


@pytest.mark.parametrize(
    "downholder_kind",
    (
        PinoutDownholderKind.PIN_LINE_CLAMP,
        PinoutDownholderKind.PIN_LINE_UPHOLDER,
    ),
)
def test_load_pinout_config_supports_both_pin_line_retention_kinds(
    tmp_path: Path,
    downholder_kind: PinoutDownholderKind,
):
    config_path = tmp_path / f"{downholder_kind.value}.yaml"
    config_path.write_text(
        f"""
pin_sets:
  - id: pin_line
    prefix: LINE_
    origin: [0, 0]
    direction: up
    pins: [ONE, TWO]
physical_components:
  - id: pin_line
    component_type: pin_line
    pin_sets: [pin_line]
    downholder: {downholder_kind.value}
wires:
  - from: LINE_ONE
    to: LINE_TWO
""".strip(),
        encoding="utf-8",
    )

    project = load_pinout_config(config_path)

    assert project.physical_components[0].downholder is downholder_kind


@pytest.mark.parametrize(
    ("physical_components_yaml", "message"),
    [
        (
            """
  - id: duplicate
    component_type: header
    pin_sets: [header_left]
    downholder: none
  - id: duplicate
    component_type: header
    pin_sets: [header_right]
    downholder: none
""",
            "Duplicate physical component id",
        ),
        (
            """
  - id: unknown-pin-set
    component_type: header
    pin_sets: [missing]
    downholder: none
""",
            "references unknown pin_sets",
        ),
        (
            """
  - id: first-owner
    component_type: header
    pin_sets: [header_left]
    downholder: none
  - id: second-owner
    component_type: header
    pin_sets: [header_left]
    downholder: none
""",
            "may belong to only one component",
        ),
        (
            """
  - id: invalid-through-set
    component_type: header
    pin_sets: [header_left]
    through_pin_sets: [header_right]
    downholder: none
""",
            "through_pin_sets must be a subset",
        ),
        (
            """
  - id: unknown-box
    component_type: boxed_module
    pin_sets: []
    box: missing
    downholder: none
""",
            "references unknown box",
        ),
        (
            """
  - id: unsupported-holder
    component_type: header
    pin_sets: [header_left]
    downholder: elastic_band
""",
            "downholder must be one of",
        ),
        (
            """
  - id: no-layout-source
    component_type: header
    pin_sets: []
    downholder: none
""",
            "requires at least one pin_set or a box",
        ),
        (
            """
  - id: no-component-type
    component_type: ""
    pin_sets: [header_left]
    downholder: none
""",
            "component_type is required",
        ),
        (
            """
  - id: mechanical-leak
    component_type: header
    pin_sets: [header_left]
    downholder: none
    thickness_mm: 3
""",
            "Unknown physical_components",
        ),
        (
            """
  - id: malformed-through-set
    component_type: header
    pin_sets: [header_left]
    through_pin_sets: header_left
    downholder: none
""",
            "through_pin_sets must be a list",
        ),
    ],
)
def test_load_pinout_config_rejects_invalid_physical_components(
    tmp_path: Path,
    physical_components_yaml: str,
    message: str,
):
    config_path = tmp_path / "invalid_physical_components.yaml"
    config_path.write_text(
        (
            """
pin_sets:
  - id: header_left
    prefix: LEFT_
    origin: [0, 0]
    direction: right
    pins: [A, B]
  - id: header_right
    prefix: RIGHT_
    origin: [0, 2]
    direction: right
    pins: [A, B]
boxes:
  - id: known
    label: Known box
    top_left: [4, 4]
    size_pitches: [2, 2]
physical_components:
"""
            + physical_components_yaml
            + """
wires:
  - from: LEFT_A
    to: LEFT_B
"""
        ).strip(),
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


@pytest.mark.parametrize(
    ("placement", "message"),
    [
        (
            """
  - ref: Q1
    kind: bjt_npn
    part: NOT_A_PART
    value: unknown
    terminals: {collector: P1, base: P2, emitter: P3}
""",
            "Unknown catalog part",
        ),
        (
            """
  - ref: Q1
    kind: bjt_npn
    part: BC337
    pinout_variant: not_a_variant
    value: BC337
    terminals: {collector: P1, base: P2, emitter: P3}
""",
            "Unknown pinout variant",
        ),
        (
            """
  - ref: Q1
    kind: bjt_npn
    part: BC327
    value: BC327
    terminals: {collector: P1, base: P2, emitter: P3}
""",
            "does not match catalog part",
        ),
        (
            """
  - ref: Q1
    kind: bjt_npn
    part: BD139
    value: BD139
    terminals: {collector: P1, base: P2, emitter: P3}
""",
            "currently supports TO-92",
        ),
        (
            """
  - ref: U3
    kind: voltage_regulator
    part: UTC_LP2950L_33_T92
    value: LP2950L-3.3
    terminals: {output: P1, ground: P2, emitter: P3}
""",
            "terminals for voltage_regulator must be exactly",
        ),
    ],
)
def test_load_pinout_config_rejects_invalid_catalog_backed_placements(
    tmp_path: Path,
    placement: str,
    message: str,
):
    config_path = tmp_path / "catalog_placement.yaml"
    config_path.write_text(
        (
            """
pins:
  P1: [0, 2]
  P2: [0, 1]
  P3: [0, 0]
wires:
  - from: P1
    to: P2
component_placements:
"""
            + placement
        ).strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_pinout_config(config_path)
