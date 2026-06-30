from pathlib import Path

from mege_circuits.pinout.cli import main
from mege_circuits.pinout.config import load_pinout_config
from mege_circuits.pinout.routing import (
    analyze_connection_violations,
    route_problematic_connections,
)


def test_pinout_routing_adds_waypoint_for_blocked_connection():
    pin_positions = {
        "LEFT": (0.0, 0.0),
        "MIDDLE": (1.0, 0.0),
        "RIGHT": (2.0, 0.0),
    }
    connections = [{"from": "LEFT", "to": "RIGHT", "type": "data"}]

    score, violations = analyze_connection_violations(pin_positions, connections[0])
    waypoint_solutions = route_problematic_connections(pin_positions, connections)

    assert score == 1
    assert violations[0]["pin"] == "MIDDLE"
    assert set(waypoint_solutions) == {0}
    assert waypoint_solutions[0]["waypoint"] not in pin_positions.values()


def test_pinout_cli_renders_top_and_bottom_svgs(tmp_path: Path):
    config_path = tmp_path / "pinout.yaml"
    output_dir = tmp_path / "out"
    config_path.write_text(
        """
basename: cli_pinout
pins:
  LEFT: [0, 0]
  RIGHT: [1, 0]
wires:
  - from: LEFT
    to: RIGHT
    type: data
""".strip(),
        encoding="utf-8",
    )

    assert main([str(config_path), "-o", str(output_dir)]) == 0

    top_svg = output_dir / "cli_pinout_top.svg"
    bottom_svg = output_dir / "cli_pinout_bottom.svg"
    assert top_svg.exists()
    assert bottom_svg.exists()
    assert "Top View" in top_svg.read_text(encoding="utf-8")
    assert "Underside View" in bottom_svg.read_text(encoding="utf-8")


def test_pinout_demo_config_loads():
    project = load_pinout_config(
        "examples/pinout/demo_pico_w_btt_tmc2226_single_driver.yaml"
    )

    assert project.basename == "demo_pico_w_btt_tmc2226_single_driver"
    assert "PICO_GPIO_2" in project.pin_positions
    assert any(
        connection["from"] == "PICO_GPIO_2" for connection in project.connections
    )
