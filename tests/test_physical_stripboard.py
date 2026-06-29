import json

import pytest

import mege_circuits.physical as physical
from examples.high_side_switch_v3 import create_high_side_switch
from examples.integration.tb6600_stripboard_interface import (
    create_schema_for_tb6600_interface,
)
from examples.integration.tb6600_stripboard_layout import (
    create_tb6600_verified_stripboard_plan,
    render_tb6600_stripboard_build,
)
from examples.voltage_divider import create_voltage_divider
from mege_circuits.simple import (
    Circuit,
    Component,
    Footprint,
    Jumper,
    PhysicalLayout,
    PhysicalNetlist,
    PhysicalVerificationReport,
    PlacedComponent,
    PlacedConnector,
    PlacedPin,
    StripboardBlocker,
    StripboardBuildOutputs,
    StripboardCut,
    StripboardRoutingHints,
    Terminal,
    circuit_from_schema,
    create_manual_stripboard_layout,
    create_net,
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
    write_stripboard_build_json,
    write_stripboard_build_outputs,
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


def test_staggered_to92_footprint_rotates_and_labels_terminal_holes(tmp_path):
    circuit = Circuit(
        name="staggered_bjt",
        components=(
            Component(
                "Q1",
                "bjt_npn",
                "BC337",
                (
                    Terminal("collector", "collector"),
                    Terminal("base", "base"),
                    Terminal("emitter", "emitter"),
                ),
            ),
        ),
        nets=(create_net("collector"), create_net("base"), create_net("emitter")),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 6),
        placements={"Q1": ("to92_cbe_staggered_013", (1, 4), 90)},
    )
    pins = {
        pin.terminal_name: pin.hole for pin in placed_component_pins(layout, circuit)
    }
    svg_path = tmp_path / "staggered_q1.svg"

    render_stripboard_layout(layout, circuit, file=svg_path)
    svg = svg_path.read_text(encoding="utf-8")

    assert pins == {"collector": (1, 4), "base": (2, 4), "emitter": (4, 4)}
    assert svg.count('class="layout-terminal-hole-label"') == 3
    assert 'data-terminal="collector" data-row="1" data-col="4"' in svg
    assert 'data-terminal="base" data-row="2" data-col="4"' in svg
    assert 'data-terminal="emitter" data-row="4" data-col="4"' in svg


def test_render_stripboard_layout_writes_svg_and_png(tmp_path):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 4),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
        cuts=((0, 1),),
        jumpers=(((0, 4), (2, 4), "midpoint"),),
    )
    svg_path = tmp_path / "manual_layout.svg"
    png_path = tmp_path / "manual_layout.png"

    render_stripboard_layout(layout, circuit, file=svg_path)
    render_stripboard_layout(layout, circuit, file=png_path)

    svg = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert 'class="layout-pin"' in svg
    assert 'class="layout-jumper"' in svg
    assert 'class="layout-blocker"' not in svg
    assert svg.count('class="layout-terminal-hole-label"') == 0
    assert 'class="layout-pin-label"' not in svg
    assert 'data-element="R1"' in svg
    assert 'data-terminal="start"' in svg
    assert 'class="layout-jumper-endpoint"' in svg
    assert svg.index('class="layout-component"') < svg.index(
        'class="layout-component-body-label"'
    )
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    annotated_path = tmp_path / "manual_layout_annotated.svg"
    render_stripboard_layout(layout, circuit, file=annotated_path, detail="annotated")
    annotated_svg = annotated_path.read_text(encoding="utf-8")
    assert 'class="layout-blocker"' in annotated_svg
    assert 'class="layout-terminal-hole-label"' not in annotated_svg


def test_render_stripboard_layout_elbows_same_row_jumpers_without_data_waypoints(
    tmp_path,
):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(12, 2),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((0, 8), 0),
        },
        cuts=((0, 2), (0, 5), (0, 10)),
        jumpers=(((0, 4), (0, 6), "midpoint"),),
    )
    report = verify_stripboard_layout(layout, circuit)
    assert report.ok, report.summary()

    svg_path = tmp_path / "same_row_jumper.svg"
    data_path = tmp_path / "same_row_jumper.json"
    render_stripboard_layout(layout, circuit, file=svg_path)
    write_stripboard_build_json(layout, circuit, report, file=data_path)

    svg = svg_path.read_text(encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    assert '<polyline class="layout-jumper" data-net="midpoint"' in svg
    assert 'data-shape="elbow"' in svg
    assert svg.count('class="layout-jumper-endpoint"') == 2
    points = svg.split('class="layout-jumper"', 1)[1].split('points="', 1)[1]
    assert len(points.split('"', 1)[0].split()) == 4
    assert data["layout"]["jumpers"] == [
        {"end": [0, 6], "net_name": "midpoint", "start": [0, 4]}
    ]
    assert "points" not in data["layout"]["jumpers"][0]
    assert "waypoints" not in data["layout"]["jumpers"][0]


def test_extract_physical_netlist_and_verification_pass_for_connected_layout():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 90),
            "R2": ((4, 2), 90),
        },
        jumpers=(((3, 1), (4, 1), "midpoint"),),
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
        jumpers=(((0, 4), (4, 1), "midpoint"),),
    )

    report = verify_stripboard_layout(layout, circuit)

    assert report.ok
    assert _conductors_by_net(report.physical_netlist)["vcc"][0].net_names == ("vcc",)
    assert _conductors_by_net(report.physical_netlist)["midpoint"][0].net_names == (
        "midpoint",
    )


def test_manual_layout_connectors_are_physical_pins_and_rendered(tmp_path):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 90),
            "R2": ((4, 2), 90),
        },
        jumpers=(((3, 1), (4, 1), "midpoint"),),
        connectors=(PlacedConnector("J_mid", "midpoint", (3, 2), "MID"),),
    )
    report = verify_stripboard_layout(layout, circuit)
    assert report.ok, report.summary()

    svg_path = tmp_path / "connector_layout.svg"
    data_path = tmp_path / "connector_layout.json"
    render_stripboard_layout(layout, circuit, file=svg_path)
    write_stripboard_build_json(layout, circuit, report, file=data_path)

    svg = svg_path.read_text(encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    midpoint_conductor = _conductors_by_net(report.physical_netlist)["midpoint"][0]

    assert any(
        (pin.refdes, pin.terminal_name) == ("J_mid", "pin")
        for pin in midpoint_conductor.pins
    )
    assert 'class="layout-connector"' in svg
    assert 'data-connector="J_mid"' in svg
    assert 'class="layout-connector-label"' in svg
    assert data["layout"]["connectors"] == [
        {
            "col": 2,
            "kind": "nail",
            "label": "MID",
            "name": "J_mid",
            "net_name": "midpoint",
            "row": 3,
        }
    ]


def test_left_compaction_moves_components_as_rigid_units_and_trims_board():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(10, 5),
        placements={
            "R1": ("axial_2pin_span3", (0, 5), 90),
            "R2": ("axial_2pin_span3", (1, 7), 90),
        },
        jumpers=(((3, 4), (1, 6), "midpoint"),),
    )

    compacted, report = physical._left_compact_stripboard_layout(layout, circuit)
    pins = {
        (pin.refdes, pin.terminal_name): pin.hole
        for pin in placed_component_pins(compacted, circuit)
    }
    blockers = {
        (blocker.row, blocker.col, blocker.element_name)
        for blocker in compacted.blockers
    }

    assert report.ok, report.summary()
    assert compacted.board.width_pitches == 4
    assert pins[("R1", "start")] == (0, 0)
    assert pins[("R1", "end")] == (3, 0)
    assert {(1, 0, "R1"), (2, 0, "R1")}.issubset(blockers)
    assert compacted.jumpers == (Jumper(start=(3, 2), end=(1, 2), net_name="midpoint"),)


def test_left_compaction_respects_locked_component_placements():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(10, 5),
        placements={
            "R1": ("axial_2pin_span3", (0, 5), 90),
            "R2": ("axial_2pin_span3", (1, 7), 90),
        },
        jumpers=(((3, 4), (1, 6), "midpoint"),),
    )

    compacted, report = physical._left_compact_stripboard_layout(
        layout,
        circuit,
        locked_refdeses=("R1",),
    )

    assert report.ok, report.summary()
    assert compacted.board.width_pitches == 7
    assert {
        component.refdes: component.origin for component in compacted.placed_components
    } == {"R1": (0, 5), "R2": (1, 0)}


def test_left_compaction_moves_connectors_left_without_losing_identity():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(10, 5),
        placements={
            "R1": ("axial_2pin_span3", (0, 5), 90),
            "R2": ("axial_2pin_span3", (1, 7), 90),
        },
        jumpers=(((3, 4), (1, 6), "midpoint"),),
        connectors=(("J_vcc", "vcc", (0, 8), "VCC"),),
    )

    compacted, report = physical._left_compact_stripboard_layout(layout, circuit)

    assert report.ok, report.summary()
    assert compacted.board.width_pitches == 4
    assert compacted.connectors == (PlacedConnector("J_vcc", "vcc", (0, 1), "VCC"),)


def test_left_compaction_moves_cuts_left_when_split_stays_verified():
    circuit = Circuit(
        name="cut_compaction",
        components=(
            Component(
                "R1",
                "resistor",
                "10K",
                (Terminal("start", "left"), Terminal("end", "right")),
            ),
        ),
        nets=(create_net("left"), create_net("right")),
    )
    footprints = (
        Footprint(
            name="wide_resistor",
            component_kinds=("resistor",),
            pins={"start": (0, 0), "end": (0, 8)},
            allowed_rotations=(0,),
        ),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(12, 1),
        footprints=footprints,
        placements={"R1": ("wide_resistor", (0, 0), 0)},
        cuts=((0, 7),),
    )

    compacted, report = physical._left_compact_stripboard_layout(layout, circuit)

    assert report.ok, report.summary()
    assert compacted.board.width_pitches == 10
    assert compacted.cuts == (StripboardCut(row=0, col=1),)


def test_left_compaction_keeps_jumper_endpoints_inside_cut_bounded_segment():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="jumper_segment",
        components=(
            Component("P1", "test_pin", None, (Terminal("pin", "n"),)),
            Component("P2", "test_pin", None, (Terminal("pin", "n"),)),
            Component("P3", "test_pin", None, (Terminal("pin", "other"),)),
            Component("P4", "test_pin", None, (Terminal("pin", "other"),)),
        ),
        nets=(create_net("n"), create_net("other")),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(10, 2),
        footprints=footprints,
        placements={
            "P1": ("test_pin", (0, 0), 0),
            "P2": ("test_pin", (1, 3), 0),
            "P3": ("test_pin", (1, 1), 0),
            "P4": ("test_pin", (1, 0), 0),
        },
        cuts=((1, 2),),
        jumpers=(((0, 1), (1, 5), "n"),),
    )

    compacted, report = physical._left_compact_stripboard_layout(layout, circuit)

    assert report.ok, report.summary()
    assert compacted.board.width_pitches == 6
    assert compacted.cuts == (StripboardCut(row=1, col=2),)
    assert compacted.jumpers == (Jumper(start=(0, 1), end=(1, 4), net_name="n"),)


def test_bridge_first_score_prefers_fewer_jumpers_over_narrower_width():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="bridge_score",
        components=(
            Component("P1", "test_pin", None, (Terminal("pin", "n"),)),
            Component("P2", "test_pin", None, (Terminal("pin", "n"),)),
        ),
        nets=(create_net("n"),),
    )
    narrower_with_jumper = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(3, 2),
        footprints=footprints,
        placements={
            "P1": ("test_pin", (0, 0), 0),
            "P2": ("test_pin", (1, 0), 0),
        },
        jumpers=(((0, 1), (1, 1), "n"),),
    )
    wider_without_jumper = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 2),
        footprints=footprints,
        placements={
            "P1": ("test_pin", (0, 3), 0),
            "P2": ("test_pin", (0, 4), 0),
        },
    )
    narrow_report = verify_stripboard_layout(narrower_with_jumper, circuit)
    wide_report = verify_stripboard_layout(wider_without_jumper, circuit)

    assert narrow_report.ok, narrow_report.summary()
    assert wide_report.ok, wide_report.summary()
    assert physical._routing_layout_score(
        wider_without_jumper,
        wide_report,
        physical._routing_zero_score(),
        circuit,
    ) < physical._routing_layout_score(
        narrower_with_jumper,
        narrow_report,
        physical._routing_zero_score(),
        circuit,
    )


def test_shake_orders_prioritize_bridge_net_transistor_and_neighbors():
    circuit = Circuit(
        name="shake_order",
        components=(
            Component(
                "Q1",
                "bjt_npn",
                "BC337",
                (
                    Terminal("collector", "n"),
                    Terminal("base", "base"),
                    Terminal("emitter", "gnd"),
                ),
            ),
            Component(
                "R1",
                "resistor",
                "10K",
                (Terminal("start", "n"), Terminal("end", "vcc")),
            ),
            Component(
                "R2",
                "resistor",
                "10K",
                (Terminal("start", "base"), Terminal("end", "gpio")),
            ),
        ),
        nets=(
            create_net("base"),
            create_net("gpio"),
            create_net("gnd"),
            create_net("n"),
            create_net("vcc"),
        ),
    )
    hints = StripboardRoutingHints(
        component_order=("R1", "R2", "Q1"),
        component_columns={"R1": 1, "R2": 2, "Q1": 3},
    )
    layout = PhysicalLayout(
        board=create_stripboard(4, 4),
        placed_components=(),
        cuts=(),
        jumpers=(Jumper(start=(0, 0), end=(1, 0), net_name="n"),),
        footprints=default_footprints(),
    )

    orders = physical._routing_shake_orders_from_layout(circuit, hints, layout)

    assert orders
    assert orders[0][0] == "Q1"
    assert orders[0].index("R1") < orders[0].index("R2")


def test_plan_stripboard_routes_voltage_divider_with_verified_layout():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(5, 5),
    )

    assert layout is not None
    assert report.ok, report.summary()
    assert layout.board.width_pitches == 3
    assert score_stripboard_layout(layout, circuit, report) == (0, 0, 0, 3, 2)
    assert [component.refdes for component in layout.placed_components] == ["R1", "R2"]
    assert layout.cuts == ()


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
    assert hints.board_width_pitches == 5
    assert hints.board_height_pitches == 3
    assert hints.component_terminal_holes[("R1", "start")] == (0, 2)
    assert hints.component_terminal_holes[("R2", "end")] == (2, 3)
    assert report.ok, report.summary()
    pins = {
        (pin.refdes, pin.terminal_name): pin.hole
        for pin in placed_component_pins(layout, circuit)
    }
    assert layout.board.width_pitches < 8
    assert (
        pins[("R1", "start")][0] == hints.component_terminal_holes[("R1", "start")][0]
    )
    assert pins[("R2", "end")][0] == hints.component_terminal_holes[("R2", "end")][0]


def test_plan_stripboard_routes_high_side_switch_with_jumpers_and_cuts():
    circuit = circuit_from_schema(create_high_side_switch(), name="high_side_switch")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(16, 20),
    )

    assert layout is not None
    assert report.ok, report.summary()
    assert len(layout.placed_components) == len(circuit.components)
    assert len(layout.jumpers) < sum(
        len(component.terminals) for component in circuit.components
    )
    _assert_jumper_endpoints_are_dedicated(layout, circuit)
    assert {
        pin.net_name
        for conductor in report.physical_netlist.conductors
        for pin in conductor.pins
    } == {net.name for net in circuit.nets}


def test_render_stripboard_layout_labels_only_directional_terminals(tmp_path):
    circuit = circuit_from_schema(create_high_side_switch(), name="high_side_switch")
    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(16, 20),
    )
    assert report.ok, report.summary()

    svg_path = tmp_path / "high_side.svg"
    render_stripboard_layout(layout, circuit, file=svg_path)
    svg = svg_path.read_text(encoding="utf-8")
    directional_pins = _directional_pins(layout, circuit)

    assert svg.count('class="layout-terminal-hole-label"') == len(directional_pins)
    assert 'data-element="Q1"' in svg
    assert 'data-terminal="gate"' in svg
    assert 'data-element="D1"' in svg
    assert 'data-element="R1"' in svg
    assert (
        'class="layout-terminal-hole-label" data-net="gate" data-element="R1"'
        not in svg
    )


def test_plan_stripboard_reports_failure_for_too_small_board():
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    layout, report = plan_stripboard(
        circuit,
        board=create_stripboard(1, 1),
    )

    assert layout is None
    assert not report.ok
    assert report.errors[0].code == "routing_failed"
    assert "No legal placement candidates" in report.summary()


def test_write_stripboard_build_outputs_writes_build_artifacts(tmp_path):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 8),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((4, 2), 90),
        },
        cuts=((0, 1),),
        jumpers=(((0, 4), (4, 1), "midpoint"),),
    )
    report = verify_stripboard_layout(layout, circuit)
    assert report.ok, report.summary()

    outputs = write_stripboard_build_outputs(
        layout,
        circuit,
        output_dir=tmp_path,
        stem="manual_divider_build",
        report=report,
        run_id="test",
    )

    assert isinstance(outputs, StripboardBuildOutputs)
    assert all(path.exists() for path in outputs.as_tuple())
    assert 'class="layout-pin"' in outputs.top_svg.read_text(encoding="utf-8")
    assert 'class="bottom-strip-cut"' in outputs.bottom_svg.read_text(encoding="utf-8")
    assert 'class="debug-conductor-hole"' in outputs.debug_svg.read_text(
        encoding="utf-8"
    )
    assert "## Top Jumpers" in outputs.checklist_md.read_text(encoding="utf-8")
    data = json.loads(outputs.data_json.read_text(encoding="utf-8"))
    assert data["verification"]["ok"] is True
    assert data["layout"]["board"] == {
        "height_pitches": 8,
        "pitch_mm": 2.54,
        "strip_direction": "horizontal",
        "width_pitches": 5,
    }


def test_tb6600_verified_stripboard_layout_is_readable_and_labeled(tmp_path):
    _schema, circuit, layout, report = create_tb6600_verified_stripboard_plan()

    assert report.ok, report.summary()
    assert layout.board.width_pitches <= 14
    assert layout.board.height_pitches == 9
    assert len(layout.cuts) <= 5
    assert len(layout.jumpers) <= 2
    assert physical._left_compaction_cut_blocker_collisions(layout) == frozenset()
    assert all(jumper.net_name != "ena_plus" for jumper in layout.jumpers)
    _assert_jumper_endpoints_are_dedicated(layout, circuit)
    assert any(
        component.refdes == "Q3"
        and component.footprint_name == "to92_cbe_staggered_013"
        for component in layout.placed_components
    )
    assert any(
        connector.name == "STEP_minus"
        and connector.label == "PUL-"
        and connector.net_name == "step_pul_minus"
        for connector in layout.connectors
    )
    assert any(
        {(pin.refdes, pin.terminal_name) for pin in conductor.pins}.issuperset(
            {("Q1", "collector"), ("STEP_minus", "pin")}
        )
        for conductor in report.physical_netlist.conductors
    )
    assert any(
        {(pin.refdes, pin.terminal_name) for pin in conductor.pins}.issuperset(
            {
                ("Q3", "collector"),
                ("R5", "end"),
                ("R6", "end"),
                ("ena_plus", "pin"),
            }
        )
        for conductor in report.physical_netlist.conductors
    )

    svg_path = tmp_path / "tb6600.svg"
    render_stripboard_layout(layout, circuit, file=svg_path)
    svg = svg_path.read_text(encoding="utf-8")
    directional_pins = _directional_pins(layout, circuit)

    assert svg.count('class="layout-terminal-hole-label"') == len(directional_pins)
    assert 'class="layout-pin-label"' not in svg
    assert 'class="layout-jumper-endpoint"' in svg
    assert 'class="layout-component-body"' in svg
    assert svg.index('class="layout-component"') < svg.index(
        'class="layout-component-body-label"'
    )
    assert 'data-element="Q1"' in svg
    assert 'data-terminal="emitter"' in svg
    assert 'class="layout-connector"' in svg
    assert 'data-connector="STEP_minus"' in svg
    assert ">PUL-</text>" in svg
    assert (
        'class="layout-terminal-hole-label" data-net="step_base" data-element="R1"'
        not in svg
    )


def test_tb6600_build_outputs_include_only_verified_artifacts(tmp_path):
    outputs = render_tb6600_stripboard_build(tmp_path)

    assert all(path.exists() for path in outputs.as_tuple())
    assert (
        outputs.top_svg.read_text(encoding="utf-8").count(
            'class="layout-terminal-hole-label"'
        )
        == 9
    )
    assert 'class="layout-jumper-endpoint"' in outputs.top_svg.read_text(
        encoding="utf-8"
    )
    assert 'data-connector="STEP_minus"' in outputs.top_svg.read_text(encoding="utf-8")
    assert 'class="bottom-connector"' in outputs.bottom_svg.read_text(encoding="utf-8")
    assert "## External Connectors" in outputs.checklist_md.read_text(encoding="utf-8")
    data = json.loads(outputs.data_json.read_text(encoding="utf-8"))
    top_svg = outputs.top_svg.read_text(encoding="utf-8")
    assert data["layout"]["board"]["width_pitches"] <= 14
    assert data["layout"]["board"]["height_pitches"] == 9
    assert len(data["layout"]["cuts"]) <= 5
    assert len(data["layout"]["jumpers"]) <= 2
    assert all(jumper["net_name"] != "ena_plus" for jumper in data["layout"]["jumpers"])
    assert top_svg.count('class="layout-jumper-endpoint"') == 2 * len(
        data["layout"]["jumpers"]
    )
    assert any(
        connector["name"] == "STEP_minus"
        and connector["label"] == "PUL-"
        and connector["net_name"] == "step_pul_minus"
        for connector in data["layout"]["connectors"]
    )
    assert not tuple(tmp_path.glob("*projection*"))


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
        jumpers=(Jumper(start=(2, 0), end=(9, 9), net_name="ghost"),),
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
        "jumper_on_component_pin",
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


def _directional_pins(layout, circuit):
    directional_refdeses = {
        component.refdes
        for component in circuit.components
        if component.kind in {"bjt_npn", "pmos", "zener"}
    }
    return tuple(
        pin
        for pin in placed_component_pins(layout, circuit)
        if pin.refdes in directional_refdeses
    )


def _assert_jumper_endpoints_are_dedicated(layout, circuit):
    pin_holes = {pin.hole for pin in placed_component_pins(layout, circuit)}
    connector_holes = {connector.hole for connector in layout.connectors}
    cut_holes = {(cut.row, cut.col) for cut in layout.cuts}
    blocker_holes = {(blocker.row, blocker.col) for blocker in layout.blockers}
    used_jumper_holes = set()
    for jumper in layout.jumpers:
        for hole in (jumper.start, jumper.end):
            assert hole not in pin_holes
            assert hole not in connector_holes
            assert hole not in cut_holes
            assert hole not in blocker_holes
            assert hole not in used_jumper_holes
            used_jumper_holes.add(hole)


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


def test_manual_layout_rejects_jumper_endpoint_on_component_pin():
    circuit = circuit_from_schema(create_voltage_divider())

    with pytest.raises(ValueError, match="shares component pin"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            placements={
                "R1": ((0, 0), 0),
                "R2": ((2, 0), 0),
            },
            jumpers=(((0, 3), (2, 4), "midpoint"),),
        )


def test_manual_layout_rejects_connector_on_component_pin():
    circuit = circuit_from_schema(create_voltage_divider())

    with pytest.raises(ValueError, match="Multiple physical terminals share hole"):
        create_manual_stripboard_layout(
            circuit,
            board=create_stripboard(8, 4),
            placements={
                "R1": ((0, 0), 0),
                "R2": ((2, 0), 0),
            },
            connectors=(("J1", "vcc", (0, 0), "VCC"),),
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
