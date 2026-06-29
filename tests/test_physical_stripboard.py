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
    PhysicalNetlist,
    PhysicalVerificationReport,
    PlacedComponent,
    PlacedPin,
    StripboardBlocker,
    StripboardCut,
    StripboardRoutingHints,
    circuit_from_schema,
    create_manual_stripboard_layout,
    create_stripboard,
    default_footprints,
    extract_physical_netlist,
    footprint_for_component,
    placed_component_pins,
    plan_stripboard,
    render_stripboard_layout,
    score_stripboard_layout,
    stripboard_hints_from_schema,
    verify_stripboard_layout,
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


def test_extract_physical_netlist_and_verification_pass_for_connected_layout():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 90),
            "R2": ((4, 2), 90),
        },
        jumpers=(((3, 0), (4, 2), "midpoint"),),
    )

    physical_netlist = extract_physical_netlist(layout, circuit)
    report = verify_stripboard_layout(layout, circuit)

    assert isinstance(physical_netlist, PhysicalNetlist)
    assert isinstance(report, PhysicalVerificationReport)
    assert report.ok
    assert report.physical_netlist == physical_netlist
    assert _conductors_by_net(physical_netlist)["midpoint"][0].net_names == (
        "midpoint",
    )
    assert len(_conductors_by_net(physical_netlist)["midpoint"]) == 1


def test_extract_physical_netlist_respects_strip_cuts():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((4, 2), 90),
        },
        cuts=((0, 1),),
        jumpers=(((0, 3), (4, 2), "midpoint"),),
    )

    report = verify_stripboard_layout(layout, circuit)

    assert report.ok
    assert _conductors_by_net(report.physical_netlist)["vcc"][0].net_names == ("vcc",)
    assert _conductors_by_net(report.physical_netlist)["midpoint"][0].net_names == (
        "midpoint",
    )


def test_plan_stripboard_routes_voltage_divider_with_verified_layout():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(5, 5),
    )

    assert layout is not None
    assert report.ok, report.summary()
    assert score_stripboard_layout(layout, circuit, report) == (0, 4, 2, 5, 4)
    assert [component.refdes for component in layout.placed_components] == ["R1", "R2"]
    assert {(cut.row, cut.col) for cut in layout.cuts} == {(3, 1), (4, 1)}


def test_plan_stripboard_uses_projection_hints_from_schema():
    schema = create_voltage_divider()
    circuit = circuit_from_schema(schema, name="manual_divider")
    hints = stripboard_hints_from_schema(schema)

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(8, 5),
        hints=hints,
    )

    assert isinstance(hints, StripboardRoutingHints)
    assert report.ok, report.summary()
    assert layout.placed_components[0].refdes == "R1"
    assert layout.placed_components[0].origin[1] == 2


def test_plan_stripboard_routes_high_side_switch_with_jumpers_and_cuts():
    circuit = circuit_from_schema(create_high_side_switch(), name="high_side_switch")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(8, 20),
    )

    assert layout is not None
    assert report.ok, report.summary()
    assert len(layout.placed_components) == len(circuit.components)
    assert len(layout.jumpers) == sum(
        len(component.terminals) for component in circuit.components
    )
    assert {
        pin.net_name
        for conductor in report.physical_netlist.conductors
        for pin in conductor.pins
    } == {net.name for net in circuit.nets}


def test_plan_stripboard_reports_failure_for_too_small_board():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(5, 4),
    )

    assert layout is None
    assert not report.ok
    assert report.errors[0].code == "routing_failed"
    assert "needs component row" in report.summary()


def test_verify_stripboard_layout_reports_open_circuit():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 90),
            "R2": ((4, 2), 90),
        },
    )

    report = verify_stripboard_layout(layout, circuit)

    assert not report.ok
    assert {issue.code for issue in report.errors} == {"open_circuit"}
    assert "midpoint" in report.summary()


def test_verify_stripboard_layout_reports_short_circuit():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((4, 2), 90),
        },
    )

    report = verify_stripboard_layout(layout, circuit)

    assert not report.ok
    assert "short_circuit" in {issue.code for issue in report.errors}
    assert any(
        conductor.net_names == ("midpoint", "vcc")
        for conductor in report.physical_netlist.conductors
    )


def test_verify_stripboard_layout_reports_drc_without_raising():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = PhysicalLayout(
        board=create_stripboard(4, 4),
        placed_components=(
            PlacedComponent("R1", "axial_2pin_span3", (0, 2), 0),
            PlacedComponent("R2", "axial_2pin_span3", (2, 0), 0),
        ),
        cuts=(StripboardCut(row=2, col=0),),
        jumpers=(Jumper(start=(0, 0), end=(9, 9), net_name="ghost"),),
        blockers=(),
        footprints=default_footprints(),
    )

    report = verify_stripboard_layout(layout, circuit)

    assert not report.ok
    assert report.physical_netlist is None
    assert {
        "component_outside_board",
        "pin_on_cut",
        "jumper_outside_board",
        "unknown_jumper_net",
    }.issubset({issue.code for issue in report.errors})
    with pytest.raises(ValueError, match="component_outside_board"):
        extract_physical_netlist(layout, circuit)


def test_verify_stripboard_layout_reports_pin_and_blocker_collisions():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = PhysicalLayout(
        board=create_stripboard(8, 4),
        placed_components=(
            PlacedComponent("R1", "axial_2pin_span3", (0, 0), 0),
            PlacedComponent("R2", "axial_2pin_span3", (0, 0), 0),
        ),
        cuts=(),
        jumpers=(),
        blockers=(StripboardBlocker(row=0, col=0, element_name="fixture"),),
        footprints=default_footprints(),
    )

    report = verify_stripboard_layout(layout, circuit)

    assert not report.ok
    assert {
        "pin_hole_collision",
        "blocker_pin_collision",
    }.issubset({issue.code for issue in report.errors})


def test_verify_stripboard_layout_reports_unassigned_footprint_terminal():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    bad_footprint = Footprint(
        name="bad_resistor",
        component_kinds=("resistor",),
        pins={"start": (0, 0)},
    )
    layout = PhysicalLayout(
        board=create_stripboard(8, 4),
        placed_components=(
            PlacedComponent("R1", "bad_resistor", (0, 0), 0),
            PlacedComponent("R2", "bad_resistor", (2, 0), 0),
        ),
        cuts=(),
        jumpers=(),
        blockers=(),
        footprints=(bad_footprint,),
    )

    report = verify_stripboard_layout(layout, circuit)

    assert not report.ok
    assert {issue.code for issue in report.errors} == {"unassigned_footprint_terminal"}


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


def _conductors_by_net(physical_netlist):
    conductors_by_net = {}
    for conductor in physical_netlist.conductors:
        for net_name in conductor.net_names:
            conductors_by_net.setdefault(net_name, []).append(conductor)
    return conductors_by_net


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
