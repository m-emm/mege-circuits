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
