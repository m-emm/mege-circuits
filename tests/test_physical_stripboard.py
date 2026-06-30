import json
import logging

import pytest

import mege_circuits.physical as physical
from examples.high_side_switch_v3 import create_high_side_switch
from examples.integration import tb6600_stripboard_layout as tb6600_layout
from examples.integration.tb6600_stripboard_interface import (
    create_schema_for_tb6600_interface,
)
from examples.integration.tb6600_stripboard_layout import (
    OBSOLETE_STRIPBOARD_ARTIFACT_STEMS,
    STRIPBOARD_ARTIFACT_STEM,
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
    render_stripboard_bottom,
    render_stripboard_layout,
    render_stripboard_layout_print_pdf,
    score_stripboard_layout,
    stripboard_hints_from_schema,
    verify_stripboard_layout,
    write_stripboard_build_checklist,
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
    values_svg_path = tmp_path / "manual_layout_values.svg"
    values_png_path = tmp_path / "manual_layout_values.png"

    render_stripboard_layout(layout, circuit, file=svg_path)
    render_stripboard_layout(layout, circuit, file=png_path)
    render_stripboard_layout(
        layout,
        circuit,
        file=values_svg_path,
        component_labels="refdes_value",
    )
    render_stripboard_layout(
        layout,
        circuit,
        file=values_png_path,
        component_labels="refdes_value",
    )

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
    assert ">R1</text>" in svg
    assert ">R1 10K</text>" not in svg
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    values_svg = values_svg_path.read_text(encoding="utf-8")
    assert ">R1 10K</text>" in values_svg
    assert ">R2 20K</text>" in values_svg
    assert 'class="layout-component-body"' not in values_svg
    assert 'data-element="R1" data-value="10K" data-label="R1 10K"' in values_svg
    assert values_png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(ValueError, match="component_labels"):
        render_stripboard_layout(
            layout,
            circuit,
            file=tmp_path / "bad_label_mode.svg",
            component_labels="values",
        )

    annotated_path = tmp_path / "manual_layout_annotated.svg"
    render_stripboard_layout(layout, circuit, file=annotated_path, detail="annotated")
    annotated_svg = annotated_path.read_text(encoding="utf-8")
    assert 'class="layout-blocker"' in annotated_svg
    assert 'class="layout-terminal-hole-label"' not in annotated_svg


def test_render_stripboard_layout_print_pdf_is_true_scale(tmp_path):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 4),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
        cuts=((0, 1),),
    )
    pdf_path = tmp_path / "manual_layout_a4.pdf"

    render_stripboard_layout_print_pdf(layout, circuit, file=pdf_path)

    pdf = pdf_path.read_bytes()
    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" not in pdf
    sheet_svg, geometry = physical._stripboard_print_svg_sheet(
        layout,
        circuit,
        detail="assembly",
        component_labels="refdes",
    )
    assert geometry["orientation"] == "portrait"
    assert geometry["board_width_mm"] == pytest.approx(8 * 2.54)
    assert geometry["board_height_mm"] == pytest.approx(4 * 2.54)
    assert geometry["pitch_mm"] == pytest.approx(2.54)
    assert 'width="210mm" height="297mm"' in sheet_svg
    assert 'class="stripboard-print-source"' in sheet_svg
    assert "Print at 100% / actual size" in sheet_svg
    assert "50 mm calibration" in sheet_svg
    source_view_box = geometry["source_view_box"]
    assert geometry["source_width_mm"] == pytest.approx(
        source_view_box[2] * geometry["pitch_mm"]
    )
    assert geometry["source_height_mm"] == pytest.approx(
        source_view_box[3] * geometry["pitch_mm"]
    )
    assert geometry["source_width_mm"] >= geometry["board_width_mm"]
    assert geometry["source_height_mm"] >= geometry["board_height_mm"]

    large_layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(120, 8),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
    )
    with pytest.raises(ValueError, match="does not fit on A4 at 1:1 scale"):
        render_stripboard_layout_print_pdf(
            large_layout,
            circuit,
            file=tmp_path / "too_large.pdf",
        )


def test_render_stripboard_layout_print_pdf_requires_rsvg_convert(
    tmp_path,
    monkeypatch,
):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(8, 4),
        placements={
            "R1": ((0, 0), 0),
            "R2": ((2, 0), 0),
        },
    )
    monkeypatch.setattr(physical.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="rsvg-convert is required"):
        render_stripboard_layout_print_pdf(
            layout,
            circuit,
            file=tmp_path / "manual_layout_a4.pdf",
        )


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
            "color": "#2563eb",
            "kind": "nail",
            "label": "MID",
            "name": "J_mid",
            "net_kind": "default",
            "net_name": "midpoint",
            "row": 3,
        }
    ]


def test_stripboard_connectors_inherit_net_kind_color(tmp_path):
    circuit = Circuit(
        name="connector_color",
        components=(),
        nets=(create_net("vcc", kind="power"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(3, 1),
        connectors=(("J_vcc", "vcc", (0, 0), "VCC"),),
    )
    report = verify_stripboard_layout(layout, circuit)
    assert report.ok, report.summary()

    svg_path = tmp_path / "connector_color.svg"
    bottom_path = tmp_path / "connector_color_bottom.svg"
    data_path = tmp_path / "connector_color.json"
    checklist_path = tmp_path / "connector_color.md"
    render_stripboard_layout(layout, circuit, file=svg_path)
    render_stripboard_bottom(layout, circuit, file=bottom_path)
    write_stripboard_build_json(layout, circuit, report, file=data_path)
    write_stripboard_build_checklist(layout, circuit, report, file=checklist_path)

    svg = svg_path.read_text(encoding="utf-8")
    bottom_svg = bottom_path.read_text(encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    checklist = checklist_path.read_text(encoding="utf-8")
    assert 'class="layout-connector"' in svg
    assert 'data-net-kind="power"' in svg
    assert 'data-color="red"' in svg
    assert 'fill="red"' in svg
    assert 'class="bottom-connector"' in bottom_svg
    assert 'data-net-kind="power"' in bottom_svg
    assert data["circuit"]["net_kinds"] == {"vcc": "power"}
    assert data["layout"]["connectors"][0]["net_kind"] == "power"
    assert data["layout"]["connectors"][0]["color"] == "red"
    assert "kind `power`, color `red`" in checklist


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


def test_stripboard_density_metrics_count_unique_occupied_and_empty_holes():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="density_metrics",
        components=(
            Component("P1", "test_pin", None, (Terminal("pin", "n"),)),
            Component("P2", "test_pin", None, (Terminal("pin", "n"),)),
        ),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 3),
        footprints=footprints,
        placements={
            "P1": ("test_pin", (0, 0), 0),
            "P2": ("test_pin", (1, 1), 0),
        },
        cuts=((0, 3),),
        jumpers=(((0, 4), (1, 4), "n"),),
        connectors=(("J_n", "n", (0, 2), "N"),),
        blockers=(StripboardBlocker(row=1, col=2, element_name="keepout"),),
    )

    metrics = physical._stripboard_density_metrics(layout, circuit)

    assert metrics.total_holes == 15
    assert metrics.component_pin_holes == 2
    assert metrics.connector_holes == 1
    assert metrics.cut_holes == 1
    assert metrics.blocker_holes == 1
    assert metrics.jumper_endpoint_holes == 2
    assert metrics.occupied_holes == 7
    assert metrics.empty_holes == 8
    assert metrics.empty_ratio == pytest.approx(8 / 15)


def test_optimizer_absorbs_connector_only_bridge_into_target_conductor():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="connector_bridge",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 2),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 0), 0)},
        jumpers=(((1, 1), (0, 1), "n"),),
        connectors=(("J_n", "n", (1, 0), "N"),),
    )

    optimized, report, changed = physical._absorb_connector_only_jumpers(
        layout,
        circuit,
    )

    assert changed
    assert report.ok, report.summary()
    assert optimized.jumpers == ()
    assert optimized.connectors == (PlacedConnector("J_n", "n", (0, 1), "N"),)


def test_optimizer_keeps_fixed_connector_only_bridge():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="fixed_connector_bridge",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    fixed_jumper = Jumper(start=(1, 1), end=(0, 1), net_name="n")
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 2),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 0), 0)},
        jumpers=(fixed_jumper,),
        connectors=(("J_n", "n", (1, 0), "N"),),
    )

    optimized, report, changed = physical._absorb_connector_only_jumpers(
        layout,
        circuit,
        fixed_jumper_keys=frozenset((physical._jumper_identity_key(fixed_jumper),)),
    )

    assert not changed
    assert report.ok, report.summary()
    assert optimized.jumpers == (fixed_jumper,)
    assert optimized.connectors == (PlacedConnector("J_n", "n", (1, 0), "N"),)


def test_right_relax_moves_connector_to_rightmost_empty_hole_before_cut():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="right_relax_connector",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(6, 1),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 2), 0)},
        cuts=((0, 4),),
        connectors=(("J_n", "n", (0, 0), "N"),),
        blockers=(StripboardBlocker(row=0, col=1, element_name="keepout"),),
    )

    optimized, report, changed = physical._right_relax_flexible_terminals(
        layout,
        circuit,
    )

    assert changed
    assert report.ok, report.summary()
    assert optimized.connectors == (PlacedConnector("J_n", "n", (0, 3), "N"),)


def test_optimizer_prunes_redundant_cut_next_to_empty_tail():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="redundant_cut",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 1),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 0), 0)},
        cuts=((0, 2),),
    )

    optimized, report, changed = physical._prune_redundant_cuts(layout, circuit)

    assert changed
    assert report.ok, report.summary()
    assert optimized.cuts == ()


def test_optimizer_keeps_cut_when_removal_would_short_nets():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="required_cut",
        components=(
            Component("P1", "test_pin", None, (Terminal("pin", "left"),)),
            Component("P2", "test_pin", None, (Terminal("pin", "right"),)),
        ),
        nets=(create_net("left"), create_net("right")),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 1),
        footprints=footprints,
        placements={
            "P1": ("test_pin", (0, 0), 0),
            "P2": ("test_pin", (0, 4), 0),
        },
        cuts=((0, 2),),
    )

    optimized, report, changed = physical._prune_redundant_cuts(layout, circuit)

    assert not changed
    assert report.ok, report.summary()
    assert optimized.cuts == (StripboardCut(row=0, col=2),)


def test_optimizer_preserves_fixed_redundant_cut():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="fixed_redundant_cut",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(5, 1),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 0), 0)},
        cuts=((0, 2),),
    )

    optimized, report, changed = physical._prune_redundant_cuts(
        layout,
        circuit,
        fixed_cuts=frozenset(((0, 2),)),
    )

    assert not changed
    assert report.ok, report.summary()
    assert optimized.cuts == (StripboardCut(row=0, col=2),)


def test_down_compaction_moves_verified_point_units_down():
    footprints = (
        Footprint(
            name="test_pin",
            component_kinds=("test_pin",),
            pins={"pin": (0, 0)},
            allowed_rotations=(0,),
        ),
    )
    circuit = Circuit(
        name="down_compaction",
        components=(Component("P1", "test_pin", None, (Terminal("pin", "n"),)),),
        nets=(create_net("n"),),
    )
    layout = create_manual_stripboard_layout(
        circuit,
        board=create_stripboard(4, 3),
        footprints=footprints,
        placements={"P1": ("test_pin", (0, 0), 0)},
        cuts=((0, 3),),
    )

    optimized, report, changed = physical._down_compact_stripboard_layout(
        layout,
        circuit,
    )

    assert changed
    assert report.ok, report.summary()
    assert optimized.placed_components == (PlacedComponent("P1", "test_pin", (2, 0)),)
    assert optimized.cuts == (StripboardCut(row=2, col=3),)


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


def test_plan_stripboard_logs_progress(caplog):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    with caplog.at_level(logging.INFO, logger="mege_circuits.physical"):
        layout, report = plan_stripboard(
            circuit,
            board=create_stripboard(5, 5),
        )

    assert report.ok, report.summary()
    assert layout is not None
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "Planning stripboard layout circuit=manual_divider" in messages
    assert "Placed component 1/2 refdes=R1" in messages
    assert "Finished component placement states=" in messages
    assert "Finished stripboard planning circuit=manual_divider" in messages


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


def test_plan_stripboard_logs_jumper_endpoint_selection(caplog):
    circuit = circuit_from_schema(create_high_side_switch(), name="high_side_switch")

    with caplog.at_level(logging.DEBUG, logger="mege_circuits.physical"):
        layout, report = plan_stripboard(
            circuit,
            board=create_stripboard(16, 20),
        )

    assert report.ok, report.summary()
    assert layout.jumpers
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "Routing connectivity jumpers" in messages
    assert "Selected jumper endpoints net=" in messages


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


def test_plan_stripboard_logs_failure_for_too_small_board(caplog):
    circuit = circuit_from_schema(create_voltage_divider(), name="manual_divider")

    with caplog.at_level(logging.INFO, logger="mege_circuits.physical"):
        layout, report = plan_stripboard(
            circuit,
            board=create_stripboard(1, 1),
        )

    assert layout is None
    assert not report.ok
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "No legal placement candidates refdes=R1" in messages
    assert "Stripboard planning failed circuit=manual_divider" in messages


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
    assert ">R1 10K</text>" in outputs.top_values_svg.read_text(encoding="utf-8")
    assert 'class="layout-component-body"' not in outputs.top_values_svg.read_text(
        encoding="utf-8"
    )
    assert outputs.top_values_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert outputs.top_a4_pdf.read_bytes().startswith(b"%PDF")
    assert outputs.top_values_a4_pdf.read_bytes().startswith(b"%PDF")
    assert b"/Subtype /Image" not in outputs.top_a4_pdf.read_bytes()
    assert b"/Subtype /Image" not in outputs.top_values_a4_pdf.read_bytes()
    assert 'class="bottom-strip-cut"' in outputs.bottom_svg.read_text(encoding="utf-8")
    assert 'class="debug-conductor-hole"' in outputs.debug_svg.read_text(
        encoding="utf-8"
    )
    assert "## Top Jumpers" in outputs.checklist_md.read_text(encoding="utf-8")
    assert "Empty holes:" in outputs.checklist_md.read_text(encoding="utf-8")
    data = json.loads(outputs.data_json.read_text(encoding="utf-8"))
    assert data["verification"]["ok"] is True
    assert data["layout"]["board"] == {
        "height_pitches": 8,
        "pitch_mm": 2.54,
        "strip_direction": "horizontal",
        "width_pitches": 5,
    }
    assert data["layout"]["metrics"]["total_holes"] == 40
    assert data["layout"]["metrics"]["empty_holes"] >= 0


@pytest.mark.slow
def test_tb6600_verified_stripboard_layout_is_readable_and_labeled(
    tmp_path,
    tb6600_verified_plan,
    tb6600_verified_plan_stats,
):
    _schema, circuit, layout, report = tb6600_verified_plan

    assert report.ok, report.summary()
    planning_stats = tb6600_verified_plan_stats
    assert planning_stats is not None
    assert planning_stats.verified_candidates > planning_stats.optimized_candidates
    assert (
        planning_stats.optimized_candidates
        <= physical._routing_optimization_candidate_limit()
    )
    assert planning_stats.verified_candidates >= 2 * planning_stats.optimized_candidates
    assert layout.board.width_pitches <= 14
    assert layout.board.height_pitches == 9
    assert len(layout.cuts) <= 4
    assert len(layout.jumpers) <= 1
    assert physical._left_compaction_cut_blocker_collisions(layout) == frozenset()
    assert all(jumper.net_name != "ena_plus" for jumper in layout.jumpers)
    assert all(jumper.net_name != "step_pul_minus" for jumper in layout.jumpers)
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


@pytest.mark.slow
def test_tb6600_build_outputs_include_only_verified_artifacts(
    tmp_path,
    caplog,
    tb6600_verified_plan,
):
    old_top_svg = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}__old.svg"
    old_top_png = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}__old.png"
    old_projection_svg = tmp_path / f"{OBSOLETE_STRIPBOARD_ARTIFACT_STEMS[0]}__old.svg"
    old_projection_latest = tmp_path / f"{OBSOLETE_STRIPBOARD_ARTIFACT_STEMS[0]}.svg"
    old_top_svg.write_text("old stripboard svg", encoding="utf-8")
    old_top_png.write_bytes(b"old stripboard png")
    old_projection_svg.write_text("old projection svg", encoding="utf-8")
    old_projection_latest.write_text("old projection latest", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        outputs = render_tb6600_stripboard_build(
            tmp_path,
            verified_plan=tb6600_verified_plan,
        )

    assert all(path.exists() for path in outputs.as_tuple())
    assert not old_top_svg.exists()
    assert not old_top_png.exists()
    assert not old_projection_svg.exists()
    assert not old_projection_latest.exists()
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}.svg",
        outputs.top_svg,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}.png",
        outputs.top_png,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}_values.svg",
        outputs.top_values_svg,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}_values.png",
        outputs.top_values_png,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}_a4.pdf",
        outputs.top_a4_pdf,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}_values_a4.pdf",
        outputs.top_values_a4_pdf,
    )
    assert outputs.top_a4_pdf.read_bytes().startswith(b"%PDF")
    assert outputs.top_values_a4_pdf.read_bytes().startswith(b"%PDF")
    assert b"/Subtype /Image" not in outputs.top_a4_pdf.read_bytes()
    assert b"/Subtype /Image" not in outputs.top_values_a4_pdf.read_bytes()
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
    values_svg = outputs.top_values_svg.read_text(encoding="utf-8")
    assert 'class="layout-component-body"' not in values_svg
    assert ">BC337</text>" not in values_svg
    for value in (
        "Q1 BC337",
        "Q2 BC337",
        "Q3 BC337",
        "C1 100nF",
        "R1 2k2",
        "R2 47k",
        "R5 4k7 0.25W",
    ):
        assert f">{value}</text>" in values_svg
    assert ">R1 2k2</text>" not in outputs.top_svg.read_text(encoding="utf-8")
    assert 'class="bottom-connector"' in outputs.bottom_svg.read_text(encoding="utf-8")
    assert "## External Connectors" in outputs.checklist_md.read_text(encoding="utf-8")
    data = json.loads(outputs.data_json.read_text(encoding="utf-8"))
    top_svg = outputs.top_svg.read_text(encoding="utf-8")
    assert data["circuit"]["net_kinds"]["v5"] == "power"
    assert data["circuit"]["net_kinds"]["v24"] == "hazard_power"
    assert data["circuit"]["net_kinds"]["gnd"] == "ground"
    assert data["circuit"]["net_kinds"]["step_pul_minus"] == "data"
    assert data["layout"]["board"]["width_pitches"] <= 14
    assert data["layout"]["board"]["height_pitches"] == 9
    assert len(data["layout"]["cuts"]) <= 4
    assert len(data["layout"]["jumpers"]) <= 1
    assert all(jumper["net_name"] != "ena_plus" for jumper in data["layout"]["jumpers"])
    assert all(
        jumper["net_name"] != "step_pul_minus" for jumper in data["layout"]["jumpers"]
    )
    assert data["layout"]["metrics"]["total_holes"] <= 126
    assert data["layout"]["metrics"]["empty_holes"] >= 0
    assert top_svg.count('class="layout-jumper-endpoint"') == 2 * len(
        data["layout"]["jumpers"]
    )
    assert any(
        connector["name"] == "STEP_minus"
        and connector["label"] == "PUL-"
        and connector["net_name"] == "step_pul_minus"
        and connector["net_kind"] == "data"
        and connector["color"] == "gold"
        for connector in data["layout"]["connectors"]
    )
    assert 'data-net="v5"' in top_svg
    assert 'data-net-kind="power"' in top_svg
    assert 'data-color="red"' in top_svg
    assert 'data-net="v24"' in top_svg
    assert 'data-net-kind="hazard_power"' in top_svg
    assert 'data-color="#8b4513"' in top_svg
    assert 'data-net-kind="ground"' in top_svg
    assert 'data-color="black"' in top_svg
    assert 'data-net-kind="data"' in top_svg
    assert 'data-color="gold"' in top_svg
    assert 'fill="#2563eb"' not in top_svg
    assert not tuple(tmp_path.glob("*projection*"))
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert (
        "Writing stripboard build outputs circuit=pico_tb6600_stripboard_interface"
        in messages
    )
    assert "Wrote stripboard build artifact" in messages
    assert "verification_ok=True" in messages


def test_tb6600_stripboard_failure_preserves_existing_artifacts(tmp_path, monkeypatch):
    old_top_svg = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}__old.svg"
    old_top_png = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}__old.png"
    latest_top_svg = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}.svg"
    latest_top_png = tmp_path / f"{STRIPBOARD_ARTIFACT_STEM}.png"
    old_projection_svg = tmp_path / f"{OBSOLETE_STRIPBOARD_ARTIFACT_STEMS[0]}__old.svg"
    old_projection_latest = tmp_path / f"{OBSOLETE_STRIPBOARD_ARTIFACT_STEMS[0]}.svg"
    old_top_svg.write_text("old stripboard svg", encoding="utf-8")
    old_top_png.write_bytes(b"old stripboard png")
    latest_top_svg.write_text("latest stripboard svg", encoding="utf-8")
    latest_top_png.write_bytes(b"latest stripboard png")
    old_projection_svg.write_text("old projection svg", encoding="utf-8")
    old_projection_latest.write_text("old projection latest", encoding="utf-8")

    def fake_plan():
        return None, object(), object(), object()

    def failing_write(*_args, output_dir, stem, run_id, **_kwargs):
        partial = output_dir / f"{stem}__{run_id}.svg"
        partial.write_text("partial new stripboard", encoding="utf-8")
        raise RuntimeError("stripboard write failed")

    monkeypatch.setattr(
        tb6600_layout, "create_tb6600_verified_stripboard_plan", fake_plan
    )
    monkeypatch.setattr(tb6600_layout, "write_stripboard_build_outputs", failing_write)

    with pytest.raises(RuntimeError, match="stripboard write failed"):
        tb6600_layout.render_tb6600_stripboard_build(tmp_path)

    assert old_top_svg.read_text(encoding="utf-8") == "old stripboard svg"
    assert old_top_png.read_bytes() == b"old stripboard png"
    assert latest_top_svg.read_text(encoding="utf-8") == "latest stripboard svg"
    assert latest_top_png.read_bytes() == b"latest stripboard png"
    assert old_projection_svg.read_text(encoding="utf-8") == "old projection svg"
    assert old_projection_latest.read_text(encoding="utf-8") == "old projection latest"
    assert not tuple(tmp_path.glob(".tmp_*"))
    assert tuple(tmp_path.glob(f"{STRIPBOARD_ARTIFACT_STEM}__*.svg")) == (old_top_svg,)
    assert tuple(tmp_path.glob(f"{STRIPBOARD_ARTIFACT_STEM}__*.png")) == (old_top_png,)


def _assert_latest_artifact_link(latest, artifact):
    assert latest.exists()
    if latest.is_symlink():
        assert latest.resolve() == artifact.resolve()
    else:
        assert latest.read_bytes() == artifact.read_bytes()


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
