import pytest

from examples.high_side_switch_v3 import create_high_side_switch
from examples.integration.tb6600_stripboard_interface import (
    create_schema_for_tb6600_interface,
)
from examples.voltage_divider import create_voltage_divider
from mege_circuits.simple import (
    Footprint,
    Jumper,
    PhysicalLayout,
    PlacedPin,
    circuit_from_schema,
    create_manual_stripboard_layout,
    create_stripboard,
    default_footprints,
    footprint_for_component,
    placed_component_pins,
    render_stripboard_layout,
)


def test_default_footprints_cover_current_example_components():
    footprints = default_footprints()
    schemas = (
        create_voltage_divider(),
        create_high_side_switch(),
        create_schema_for_tb6600_interface(),
    )

    for schema in schemas:
        circuit = circuit_from_schema(schema)
        for component in circuit.components:
            footprint = footprint_for_component(component, footprints)
            assert component.kind in footprint.component_kinds
            assert set(footprint.pins) == {
                terminal.name for terminal in component.terminals
            }


def test_create_manual_stripboard_layout_enumerates_physical_pins():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 4),
        footprints=default_footprints(),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
        cuts=((0, 4), (2, 4)),
        jumpers=(Jumper(start=(0, 3), end=(2, 0), net_name="midpoint"),),
    )
    pins = placed_component_pins(layout, circuit)

    assert isinstance(layout, PhysicalLayout)
    assert all(isinstance(pin, PlacedPin) for pin in pins)
    assert {
        (pin.refdes, pin.terminal_name): (pin.row, pin.col, pin.net_name)
        for pin in pins
    } == {
        ("R1", "start"): (0, 0, "vcc"),
        ("R1", "end"): (0, 3, "midpoint"),
        ("R2", "start"): (2, 0, "midpoint"),
        ("R2", "end"): (2, 3, "gnd"),
    }
    assert {
        (blocker.row, blocker.col, blocker.element_name) for blocker in layout.blockers
    } == {
        (0, 1, "R1"),
        (0, 2, "R1"),
        (2, 1, "R2"),
        (2, 2, "R2"),
    }


def test_manual_layout_rotates_footprint_pins_on_grid():
    circuit = circuit_from_schema(create_voltage_divider())
    footprints = (
        Footprint(
            name="vertical_resistor",
            component_kinds=("resistor",),
            pins={"start": (0, 0), "end": (0, 2)},
            allowed_rotations=(0, 90),
        ),
    )

    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 8),
        footprints=footprints,
        placements={
            "R1": ("vertical_resistor", (5, 5), 90),
            "R2": ("vertical_resistor", (0, 0), 0),
        },
    )
    pins = {
        (pin.refdes, pin.terminal_name): pin.hole
        for pin in placed_component_pins(layout, circuit)
    }

    assert pins[("R1", "start")] == (5, 5)
    assert pins[("R1", "end")] == (7, 5)
    assert pins[("R2", "end")] == (0, 2)


def test_render_stripboard_layout_writes_svg_and_png(tmp_path):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 4),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
        cuts=((0, 4),),
        jumpers=(((0, 3), (2, 0), "midpoint"),),
    )
    svg_path = tmp_path / "manual_layout.svg"
    png_path = tmp_path / "manual_layout.png"

    render_stripboard_layout(layout, circuit, file=svg_path)
    render_stripboard_layout(layout, circuit, file=png_path)

    svg = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert 'class="layout-pin"' in svg
    assert 'class="layout-jumper"' in svg
    assert 'class="layout-blocker"' in svg
    assert 'data-element="R1"' in svg
    assert 'data-terminal="start"' in svg
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_manual_layout_rejects_component_pins_outside_board():
    circuit = circuit_from_schema(create_voltage_divider())

    with pytest.raises(ValueError, match="outside board"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            placements={
                "R1": ((0, 6), 0),
                "R2": ((2, 0), 0),
            },
        )


def test_manual_layout_rejects_cut_on_component_pin():
    circuit = circuit_from_schema(create_voltage_divider())

    with pytest.raises(ValueError, match="cut hole"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            placements={
                "R1": ((0, 0), 0),
                "R2": ((2, 0), 0),
            },
            cuts=((0, 0),),
        )


def test_manual_layout_rejects_duplicate_pin_holes():
    circuit = circuit_from_schema(create_voltage_divider())

    with pytest.raises(ValueError, match="Multiple component pins share hole"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            placements={
                "R1": ((0, 0), 0),
                "R2": ((0, 0), 0),
            },
        )


def test_manual_layout_rejects_footprint_terminal_mismatch():
    circuit = circuit_from_schema(create_voltage_divider())
    bad_footprint = Footprint(
        name="bad_resistor",
        component_kinds=("resistor",),
        pins={"start": (0, 0)},
    )

    with pytest.raises(ValueError, match="does not match"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            footprints=(bad_footprint,),
            placements={
                "R1": ("bad_resistor", (0, 0), 0),
                "R2": ("bad_resistor", (2, 0), 0),
            },
        )
