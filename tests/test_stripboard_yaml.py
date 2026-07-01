from pathlib import Path

import pytest
import yaml

from examples.voltage_divider import create_voltage_divider
from mege_circuits.simple import (
    PlacedConnector,
    circuit_fingerprint,
    circuit_from_schema,
    create_manual_stripboard_layout,
    create_stripboard,
    load_stripboard_layout_config,
    placed_component_pins,
    render_stripboard_layout_config,
    write_stripboard_layout_yaml,
)
from mege_circuits.stripboard.cli import main as stripboard_cli_main

VOLTAGE_DIVIDER_FACTORY = "examples.voltage_divider:create_voltage_divider"


def _divider_circuit():
    return circuit_from_schema(create_voltage_divider(), name="manual_divider")


def _connected_divider_layout():
    circuit = _divider_circuit()
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(9, 1),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((0, 5), 0),
        },
        cuts=((0, 1), (0, 7)),
    )
    return circuit, layout


def _write_connected_divider_yaml(path: Path, *, extra_data=None):
    circuit, layout = _connected_divider_layout()
    write_stripboard_layout_yaml(
        layout,
        circuit,
        path,
        source_factory=VOLTAGE_DIVIDER_FACTORY,
        basename="manual_divider",
    )
    if extra_data:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data.update(extra_data)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return circuit, layout


def test_stripboard_yaml_dump_uses_visible_terminal_coordinates(tmp_path):
    yaml_path = tmp_path / "divider.yaml"
    circuit, layout = _write_connected_divider_yaml(yaml_path)

    text = yaml_path.read_text(encoding="utf-8")
    assert "footprint" not in text
    assert "kind:" not in text
    assert "value:" not in text
    assert "terminals:" not in text
    assert "R1: [[0, 0], [0, 3]]" in text

    project = load_stripboard_layout_config(yaml_path)
    assert project.report.ok, project.report.summary()
    assert {
        (pin.refdes, pin.terminal_name): pin.hole
        for pin in placed_component_pins(project.layout, project.circuit)
    } == {
        (pin.refdes, pin.terminal_name): pin.hole
        for pin in placed_component_pins(layout, circuit)
    }


def test_stripboard_yaml_loads_directional_visible_terminal_labels(tmp_path):
    source_path = tmp_path / "bjt_source.py"
    source_path.write_text(
        "\n".join(
            [
                "import mege_circuits.simple as mc",
                "",
                "def create_schema():",
                "    c = mc.create_node(mc.Dot, 'collector', net=mc.create_net('collector'))",
                "    b = mc.create_node(mc.Dot, 'base', net=mc.create_net('base'))",
                "    e = mc.create_node(mc.Dot, 'emitter', net=mc.create_net('emitter'))",
                "    q = mc.create_element(mc.BjtNpn, 'Q1', 'BC337', base=b, collector=c, emitter=e)",
                "    return mc.create_schema([c, b, e], [q])",
                "",
            ]
        ),
        encoding="utf-8",
    )
    factory = f"{source_path}:create_schema"
    schema = load_stripboard_layout_config.__globals__["_import_source_factory"](
        factory,
        base_dir=tmp_path,
    )()
    circuit = circuit_from_schema(schema, name="bjt_fixture")
    yaml_path = tmp_path / "bjt.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                "basename: bjt_fixture",
                "source:",
                f"  factory: {factory}",
                "  circuit_name: bjt_fixture",
                f"  fingerprint: {circuit_fingerprint(circuit)}",
                "board: {size: [3, 3], pitch_mm: 2.54}",
                "components:",
                "  Q1: {c: [0, 0], b: [1, 0], e: [2, 0]}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    project = load_stripboard_layout_config(yaml_path)
    assert project.report.ok, project.report.summary()
    assert {
        pin.terminal_name: pin.hole
        for pin in placed_component_pins(project.layout, project.circuit)
    } == {"collector": (0, 0), "base": (1, 0), "emitter": (2, 0)}

    dumped_path = tmp_path / "bjt_dumped.yaml"
    write_stripboard_layout_yaml(
        project.layout,
        project.circuit,
        dumped_path,
        source_factory=factory,
        basename="bjt_fixture",
    )
    assert "Q1: {c: [0, 0], b: [1, 0], e: [2, 0]}" in dumped_path.read_text(
        encoding="utf-8"
    )


def test_stripboard_yaml_added_cut_can_break_original_net(tmp_path):
    yaml_path = tmp_path / "divider_open.yaml"
    _write_connected_divider_yaml(yaml_path)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["cuts"].append([0, 4])
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    project = load_stripboard_layout_config(yaml_path)

    assert not project.report.ok
    assert "open_circuit" in {issue.code for issue in project.report.errors}


def test_stripboard_yaml_added_jumper_can_short_original_nets(tmp_path):
    yaml_path = tmp_path / "divider_short.yaml"
    _write_connected_divider_yaml(yaml_path)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["board"] = {"size": [11, 1], "pitch_mm": 2.54}
    data["components"] = {
        "R1": [[0, 0], [0, 4]],
        "R2": [[0, 6], [0, 10]],
    }
    data["cuts"] = [[0, 2], [0, 8]]
    data["jumpers"] = [{"from": [0, 1], "to": [0, 9], "color": "#00b894"}]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    project = load_stripboard_layout_config(yaml_path)

    assert not project.report.ok
    assert "short_circuit" in {issue.code for issue in project.report.errors}


def test_stripboard_yaml_visual_pins_and_connectors_are_not_semantic(tmp_path):
    yaml_path = tmp_path / "divider_visual.yaml"
    _write_connected_divider_yaml(yaml_path)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["pins"] = {"probe": {"at": [0, 2], "label": "PROBE", "type": "aux"}}
    data["connectors"] = [
        {"name": "aux_mid", "at": [0, 6], "net": "midpoint", "label": "AUX"}
    ]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    project = load_stripboard_layout_config(yaml_path)

    assert project.report.ok, project.report.summary()
    connector_pins = {
        pin.refdes
        for conductor in project.report.physical_netlist.conductors
        for pin in conductor.pins
    }
    assert "probe" not in connector_pins
    assert "aux_mid" not in connector_pins
    assert any(
        connector
        == PlacedConnector(
            "aux_mid",
            "midpoint",
            (0, 6),
            "AUX",
            verify=False,
        )
        for connector in project.layout.connectors
    )

    output_paths = render_stripboard_layout_config(yaml_path, output_dir=tmp_path)
    svg = output_paths[0].read_text(encoding="utf-8")
    assert 'data-connector="probe"' in svg
    assert 'data-connector="aux_mid"' in svg


def test_stripboard_yaml_source_fingerprint_drift_is_explicit(tmp_path):
    yaml_path = tmp_path / "divider_drift.yaml"
    _write_connected_divider_yaml(yaml_path)
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["source"]["fingerprint"] = "sha256:not-current"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Source fingerprint mismatch"):
        load_stripboard_layout_config(yaml_path)

    project = load_stripboard_layout_config(yaml_path, allow_source_drift=True)
    assert project.expected_fingerprint == "sha256:not-current"


def test_stripboard_cli_dump_and_render(tmp_path):
    yaml_path = tmp_path / "cli_divider.yaml"
    assert (
        stripboard_cli_main(
            [
                "dump",
                VOLTAGE_DIVIDER_FACTORY,
                "-o",
                str(yaml_path),
                "--basename",
                "cli_divider",
                "--circuit-name",
                "manual_divider",
            ]
        )
        == 0
    )
    text = yaml_path.read_text(encoding="utf-8")
    assert "footprint" not in text
    assert "kind:" not in text

    output_dir = tmp_path / "out"
    assert stripboard_cli_main(["render", str(yaml_path), "-o", str(output_dir)]) == 0
    assert (output_dir / "cli_divider.svg").exists()
    assert (output_dir / "cli_divider.png").read_bytes().startswith(b"\x89PNG")
