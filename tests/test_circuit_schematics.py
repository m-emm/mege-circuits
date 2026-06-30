import pytest

import mege_circuits.dsl as circuit_dsl
from examples.high_side_switch_v3 import create_high_side_switch
from examples.integration import tb6600_stripboard_interface as tb6600_interface
from examples.integration.tb6600_stripboard_interface import (
    SCHEMATIC_ARTIFACT_STEM,
    create_schema_for_tb6600_interface,
    prepare_tb6600_artifact_outputs,
    render_tb6600_schematic,
)
from examples.integration.tb6600_stripboard_layout import (
    STRIPBOARD_ARTIFACT_STEM,
    render_tb6600_stripboard_build,
)
from examples.voltage_divider import create_voltage_divider
from mege_circuits.simple import (
    Alignment,
    BjtNpn,
    Circuit,
    Component,
    Direction,
    Dot,
    ERCIssue,
    ERCReport,
    Ground,
    Resistor,
    Stripboard,
    StripboardBlocker,
    StripboardCut,
    Terminal,
    Wire,
    Zener,
    align,
    assign_schema_nets_to_stripboard,
    check_schema_erc,
    circuit_from_schema,
    compact_sparse_stripboard_rows,
    compact_stripboard_connections_left,
    create_element,
    create_net,
    create_node,
    create_rail,
    create_schema,
    create_stripboard,
    create_wire,
    export_netlist,
    get_schema_net_visualizations,
    permute_stripboard_rows_for_element_span,
    point_at,
    render_schemdraw,
    render_stripboard,
    render_stripboard_overlay,
    rotate,
    snap_schema_to_stripboard,
    translate,
)


def test_voltage_divider_schema_has_expected_shape():
    schema = create_voltage_divider()

    assert [node.name for node in schema.node_views] == ["vcc", "midpoint", "gnd"]
    assert [net.name for net in schema.nets] == ["vcc", "midpoint", "gnd"]
    assert [element.name for element in schema.elements] == ["R1", "R2"]
    assert schema.elements[0].terminal_views["start"] == "vcc"
    assert schema.elements[0].terminal_views["end"] == "midpoint"
    assert schema.elements[0].terminal_nets["start"] == "vcc"
    assert schema.elements[0].terminal_nets["end"] == "midpoint"


def test_circuit_from_schema_exports_voltage_divider_netlist():
    schema = create_voltage_divider()

    circuit = circuit_from_schema(schema, name="voltage_divider")
    netlist = export_netlist(circuit)
    report = check_schema_erc(schema)

    assert isinstance(circuit, Circuit)
    assert all(isinstance(component, Component) for component in circuit.components)
    assert all(
        isinstance(terminal, Terminal)
        for component in circuit.components
        for terminal in component.terminals
    )
    assert isinstance(report, ERCReport)
    assert report.ok
    assert {issue.code for issue in report.warnings} == {"single_terminal_net"}
    assert netlist == {
        "name": "voltage_divider",
        "nets": ("gnd", "midpoint", "vcc"),
        "components": {
            "R1": {
                "kind": "resistor",
                "value": "10K",
                "terminals": {"end": "midpoint", "start": "vcc"},
            },
            "R2": {
                "kind": "resistor",
                "value": "20K",
                "terminals": {"end": "gnd", "start": "midpoint"},
            },
        },
    }


def test_semantic_netlist_ignores_drawing_positions():
    schema = create_voltage_divider()
    moved_schema = create_schema(
        [translate(20, 10)(node) for node in schema.node_views],
        [translate(-8, 7)(element) for element in schema.elements],
        schema.wires,
    )

    assert export_netlist(circuit_from_schema(schema)) == export_netlist(
        circuit_from_schema(moved_schema)
    )


def test_circuit_from_high_side_switch_schema_exports_semantic_components():
    circuit = circuit_from_schema(create_high_side_switch(), name="high_side_switch")
    netlist = export_netlist(circuit)

    assert netlist["name"] == "high_side_switch"
    assert set(netlist["components"]) == {
        "D1",
        "F1",
        "Q1",
        "Q2",
        "R1",
        "R2",
        "R3",
        "R4",
    }
    assert netlist["components"]["Q1"] == {
        "kind": "pmos",
        "value": "IRF5210",
        "terminals": {
            "drain": "vmot",
            "gate": "gate",
            "source": "after_fuse",
        },
    }
    assert netlist["components"]["Q2"]["terminals"] == {
        "base": "base_drive",
        "collector": "q2_collector",
        "emitter": "gnd",
    }


def test_circuit_from_tb6600_schema_exports_expected_semantic_shape():
    circuit = circuit_from_schema(
        create_schema_for_tb6600_interface(),
        name="tb6600_interface",
    )
    netlist = export_netlist(circuit)

    assert netlist["name"] == "tb6600_interface"
    assert len(netlist["nets"]) == 12
    assert set(netlist["components"]) == {
        "C1",
        "Q1",
        "Q2",
        "Q3",
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "R7",
        "R8",
    }
    assert netlist["components"]["Q1"]["terminals"] == {
        "base": "step_base",
        "collector": "step_pul_minus",
        "emitter": "gnd",
    }
    assert netlist["components"]["R5"]["terminals"] == {
        "end": "ena_plus",
        "start": "v24",
    }


def test_circuit_from_schema_raises_on_duplicate_refdes():
    a = create_node(Dot, "a")
    b = create_node(Dot, "b")
    r1 = create_element(Resistor, "Rdup", "1k", a, b)
    r2 = create_element(Resistor, "Rdup", "2k", b, a)
    schema = create_schema([a, b], [r1, r2])

    report = check_schema_erc(schema)

    assert [issue.code for issue in report.errors] == ["duplicate_refdes"]
    with pytest.raises(ValueError, match="duplicate_refdes"):
        circuit_from_schema(schema)


def test_check_schema_erc_reports_malformed_schema_errors():
    a_net = create_net("a")
    b_net = create_net("b")
    a = create_node(Dot, "same", net=a_net)
    duplicate_a = create_node(Dot, "same", net=a_net)
    b = create_node(Dot, "b", net=b_net)
    resistor = create_element(Resistor, "Rbad", "1k", a, b)
    resistor.terminal_views = {"start": "same", "extra": "b"}
    resistor.terminal_nets = {"start": "a", "extra": "missing", "ghost": "missing"}
    wire = circuit_dsl.WireSegment(
        start_view="same",
        end_view="b",
        net_name="a",
        name="bad_wire",
    )
    schema = circuit_dsl.Schema(
        nets=[a_net, b_net],
        node_views=[a, duplicate_a, b],
        elements=[resistor],
        wires=[wire],
    )

    report = check_schema_erc(schema)

    assert isinstance(report.errors[0], ERCIssue)
    assert {
        "duplicate_node_view",
        "missing_terminal",
        "unknown_terminal",
        "terminal_metadata_mismatch",
        "unknown_net",
        "wire_net_mismatch",
    }.issubset({issue.code for issue in report.errors})


def test_align_returns_placed_copy_without_mutating_original():
    vcc = create_node(Dot, "vcc", label="+5V")
    midpoint = create_node(Dot, "midpoint", label="OUT")
    resistor = create_element(Resistor, "R1", "10K", vcc, midpoint)

    placed = align(resistor, vcc, Alignment.STACK_BOTTOM)

    assert resistor.position == (0.0, 0.0)
    assert placed.position != resistor.position


def test_render_schemdraw_writes_svg(tmp_path):
    schema = create_voltage_divider()
    outfile = tmp_path / "voltage_divider.svg"

    render_schemdraw(schema, file=outfile)

    assert outfile.exists()
    assert "<svg" in outfile.read_text(encoding="utf-8")


def test_render_schemdraw_writes_png(tmp_path):
    schema = create_voltage_divider()
    outfile = tmp_path / "voltage_divider.png"

    render_schemdraw(schema, file=outfile)

    assert outfile.exists()
    assert outfile.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.slow
def test_tb6600_integration_examples_render_stable_artifacts(tb6600_verified_plan):
    schematic_svg, schematic_png = render_tb6600_schematic()
    stripboard_outputs = render_tb6600_stripboard_build(
        verified_plan=tb6600_verified_plan
    )
    stripboard_svg = stripboard_outputs.top_svg
    stripboard_png = stripboard_outputs.top_png
    stripboard_values_svg = stripboard_outputs.top_values_svg
    stripboard_values_png = stripboard_outputs.top_values_png
    stripboard_a4_pdf = stripboard_outputs.top_a4_pdf
    stripboard_values_a4_pdf = stripboard_outputs.top_values_a4_pdf

    assert "<svg" in schematic_svg.read_text(encoding="utf-8")
    assert schematic_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "<svg" in stripboard_svg.read_text(encoding="utf-8")
    assert stripboard_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "Q1 BC337" in stripboard_values_svg.read_text(encoding="utf-8")
    assert stripboard_values_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert stripboard_a4_pdf.read_bytes().startswith(b"%PDF")
    assert stripboard_values_a4_pdf.read_bytes().startswith(b"%PDF")
    assert b"/Subtype /Image" not in stripboard_a4_pdf.read_bytes()
    assert b"/Subtype /Image" not in stripboard_values_a4_pdf.read_bytes()
    assert schematic_svg.parent == stripboard_svg.parent
    assert schematic_svg.parent.name == "diagrams"
    assert schematic_svg.stem.startswith(f"{SCHEMATIC_ARTIFACT_STEM}__")
    assert schematic_png.stem.startswith(f"{SCHEMATIC_ARTIFACT_STEM}__")
    assert stripboard_svg.stem.startswith(f"{STRIPBOARD_ARTIFACT_STEM}__")
    assert stripboard_png.stem.startswith(f"{STRIPBOARD_ARTIFACT_STEM}__")
    assert stripboard_values_svg.stem.startswith(f"{STRIPBOARD_ARTIFACT_STEM}_values__")
    assert stripboard_values_png.stem.startswith(f"{STRIPBOARD_ARTIFACT_STEM}_values__")
    assert stripboard_a4_pdf.stem.startswith(f"{STRIPBOARD_ARTIFACT_STEM}_a4__")
    assert stripboard_values_a4_pdf.stem.startswith(
        f"{STRIPBOARD_ARTIFACT_STEM}_values_a4__"
    )
    _assert_latest_artifact_link(
        schematic_svg.parent / f"{SCHEMATIC_ARTIFACT_STEM}.svg",
        schematic_svg,
    )
    _assert_latest_artifact_link(
        schematic_png.parent / f"{SCHEMATIC_ARTIFACT_STEM}.png",
        schematic_png,
    )
    _assert_latest_artifact_link(
        stripboard_svg.parent / f"{STRIPBOARD_ARTIFACT_STEM}.svg",
        stripboard_svg,
    )
    _assert_latest_artifact_link(
        stripboard_png.parent / f"{STRIPBOARD_ARTIFACT_STEM}.png",
        stripboard_png,
    )
    _assert_latest_artifact_link(
        stripboard_values_svg.parent / f"{STRIPBOARD_ARTIFACT_STEM}_values.svg",
        stripboard_values_svg,
    )
    _assert_latest_artifact_link(
        stripboard_values_png.parent / f"{STRIPBOARD_ARTIFACT_STEM}_values.png",
        stripboard_values_png,
    )
    _assert_latest_artifact_link(
        stripboard_a4_pdf.parent / f"{STRIPBOARD_ARTIFACT_STEM}_a4.pdf",
        stripboard_a4_pdf,
    )
    _assert_latest_artifact_link(
        stripboard_values_a4_pdf.parent / f"{STRIPBOARD_ARTIFACT_STEM}_values_a4.pdf",
        stripboard_values_a4_pdf,
    )
    assert not tuple(stripboard_svg.parent.glob("*projection*"))


def test_prepare_tb6600_artifact_outputs_preserves_existing_files(tmp_path):
    old_svg = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}__old.svg"
    latest_svg = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}.svg"
    old_svg.write_text("old svg", encoding="utf-8")
    latest_svg.write_text("latest svg", encoding="utf-8")

    svg_file, png_file = prepare_tb6600_artifact_outputs(
        tmp_path, SCHEMATIC_ARTIFACT_STEM
    )

    assert old_svg.read_text(encoding="utf-8") == "old svg"
    assert latest_svg.read_text(encoding="utf-8") == "latest svg"
    assert svg_file.parent == tmp_path
    assert png_file.parent == tmp_path
    assert svg_file.stem.startswith(f"{SCHEMATIC_ARTIFACT_STEM}__")
    assert png_file.stem.startswith(f"{SCHEMATIC_ARTIFACT_STEM}__")


def test_tb6600_schematic_failure_preserves_existing_artifacts(tmp_path, monkeypatch):
    old_svg = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}__old.svg"
    old_png = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}__old.png"
    latest_svg = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}.svg"
    latest_png = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}.png"
    old_svg.write_text("old svg", encoding="utf-8")
    old_png.write_bytes(b"old png")
    latest_svg.write_text("latest svg", encoding="utf-8")
    latest_png.write_bytes(b"latest png")

    def failing_render(_schema, file, show=False):
        assert show is False
        file.write_text("partial new artifact", encoding="utf-8")
        raise RuntimeError("schematic render failed")

    monkeypatch.setattr(tb6600_interface, "render_schemdraw", failing_render)

    with pytest.raises(RuntimeError, match="schematic render failed"):
        tb6600_interface.render_tb6600_schematic(tmp_path)

    assert old_svg.read_text(encoding="utf-8") == "old svg"
    assert old_png.read_bytes() == b"old png"
    assert latest_svg.read_text(encoding="utf-8") == "latest svg"
    assert latest_png.read_bytes() == b"latest png"
    assert not tuple(tmp_path.glob(".tmp_*"))
    assert tuple(tmp_path.glob(f"{SCHEMATIC_ARTIFACT_STEM}__*.svg")) == (old_svg,)
    assert tuple(tmp_path.glob(f"{SCHEMATIC_ARTIFACT_STEM}__*.png")) == (old_png,)


def test_tb6600_schematic_success_prunes_after_publish(tmp_path, monkeypatch):
    old_svg = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}__old.svg"
    old_png = tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}__old.png"
    old_svg.write_text("old svg", encoding="utf-8")
    old_png.write_bytes(b"old png")

    def fake_render(_schema, file, show=False):
        assert show is False
        if file.suffix == ".png":
            file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        else:
            file.write_text("<svg></svg>", encoding="utf-8")

    monkeypatch.setattr(tb6600_interface, "render_schemdraw", fake_render)

    svg_file, png_file = tb6600_interface.render_tb6600_schematic(tmp_path)

    assert svg_file.exists()
    assert png_file.exists()
    assert not old_svg.exists()
    assert not old_png.exists()
    assert not tuple(tmp_path.glob(".tmp_*"))
    _assert_latest_artifact_link(
        tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}.svg",
        svg_file,
    )
    _assert_latest_artifact_link(
        tmp_path / f"{SCHEMATIC_ARTIFACT_STEM}.png",
        png_file,
    )


def _assert_latest_artifact_link(latest, artifact):
    assert latest.exists()
    if latest.is_symlink():
        assert latest.resolve() == artifact.resolve()
    else:
        assert latest.read_bytes() == artifact.read_bytes()


def test_wire_element_renders_without_a_label(tmp_path):
    v5 = create_net("v5")
    vcc = create_node(Dot, "vcc", net=v5, label="+5V")
    pul_plus = create_node(Dot, "pul_plus", net=v5, label="PUL+")
    pul_plus = translate(4, 0)(pul_plus)
    feed = create_wire(vcc, pul_plus)
    schema = create_schema([vcc, pul_plus], [feed])
    outfile = tmp_path / "wire.svg"

    assert feed.position == (0.0, 0.0)
    assert schema.wires == [feed]
    assert schema.get_bounding_box() == [[0.0, 0.0], [4.0, 0.0]]

    render_schemdraw(schema, file=outfile)

    svg = outfile.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "PUL+" in svg
    assert ">W<" not in svg


def test_create_element_wire_compatibility_path():
    v5 = create_net("v5")
    rail = create_node(Dot, "rail", net=v5)
    terminal = create_node(Dot, "terminal", net=v5)

    wire = create_element(Wire, "", None, rail, terminal)

    assert wire.start_view == "rail"
    assert wire.end_view == "terminal"
    assert wire.net_name == "v5"


def test_create_node_accepts_label_alignment():
    vcc = create_node(Dot, "vcc", label="+5V", label_alignment=Alignment.LEFT)

    assert vcc.label_loc == "left"


def test_vertical_rail_bounding_box_and_alignment():
    rail = create_node(Dot, "rail")
    rail = translate(2, 3)(rail)
    rail = create_rail(rail, Direction.VERTICAL, 6, anchor=Alignment.TOP)

    marker = create_node(Dot, "marker")
    marker = align(marker, rail, Alignment.BOTTOM)

    assert rail.get_bounding_box() == [[2.0, -3.0], [2.0, 3.0]]
    assert marker.position == (0.0, -3.0)


def test_point_at_returns_rail_endpoint_points():
    rail = create_node(Dot, "rail")
    rail = translate(2, 3)(rail)
    rail = create_rail(rail, Direction.VERTICAL, 6, anchor=Alignment.TOP)

    assert point_at(rail, Alignment.TOP).position == (2.0, 3.0)
    assert point_at(rail, Alignment.BOTTOM).position == (2.0, -3.0)


def test_align_can_move_owner_by_reference_point():
    start = create_node(Dot, "start")
    end = create_node(Dot, "end")
    end = translate(4, 0)(end)
    resistor = create_element(Resistor, "R1", "1k", start, end)
    resistor = rotate(90)(resistor)

    placed = align(point_at(resistor, Alignment.RIGHT), end, Alignment.CENTER)

    assert point_at(placed, Alignment.RIGHT).position == end.position


def test_point_at_anchor_keeps_anchor_point_and_moves_owner():
    start = create_node(Dot, "start")
    end = create_node(Dot, "end")
    target = translate(4, 0)(create_node(Dot, "target"))
    resistor = create_element(Resistor, "R1", "1k", start, end)
    resistor = rotate(90)(resistor)

    placed = align(point_at(resistor.end, Alignment.CENTER), target, Alignment.CENTER)

    assert placed.end.position == target.position


def test_render_schemdraw_writes_rail_and_tap(tmp_path):
    v5 = create_net("v5")
    rail = create_node(Dot, "rail", net=v5, label="+5V", label_alignment=Alignment.LEFT)
    rail = translate(0, 4)(rail)
    rail = create_rail(rail, Direction.VERTICAL, 8, anchor=Alignment.TOP)

    tap = create_node(Dot, "tap", net=v5, label="PUL+")
    tap = translate(4, 1)(tap)

    feed = create_wire(rail, tap)
    schema = create_schema([rail, tap], [feed])
    outfile = tmp_path / "rail.svg"

    render_schemdraw(schema, file=outfile)

    svg = outfile.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "+5V" in svg
    assert "PUL+" in svg


def test_element_stores_terminal_view_names_and_net_names_not_view_objects():
    signal = create_net("signal")
    ground = create_net("ground")
    sig_view = create_node(Dot, "sig_view", net=signal)
    gnd_view = create_node(Ground, "gnd_view", net=ground)

    resistor = create_element(Resistor, "R1", "1k", sig_view, gnd_view)

    assert resistor.terminal_views == {"start": "sig_view", "end": "gnd_view"}
    assert resistor.terminal_nets == {"start": "signal", "end": "ground"}


def test_moving_node_view_after_element_creation_keeps_connectivity():
    signal = create_net("signal")
    ground = create_net("ground")
    sig_view = create_node(Dot, "sig_view", net=signal)
    gnd_view = create_node(Ground, "gnd_view", net=ground)
    resistor = create_element(Resistor, "R1", "1k", sig_view, gnd_view)

    sig_view = translate(4, 0)(sig_view)
    schema = create_schema([sig_view, gnd_view], [resistor])

    assert resistor.terminal_views["start"] == "sig_view"
    assert resistor.terminal_nets["start"] == "signal"
    assert schema.node_views[0].position == (4.0, 0.0)


def test_multiple_node_views_can_represent_the_same_net():
    v5 = create_net("v5")
    rail = create_node(Dot, "v5_rail", net=v5)
    terminal = create_node(Dot, "pul_plus", net=v5)

    schema = create_schema([rail, terminal], [])

    assert [net.name for net in schema.nets] == ["v5"]


def test_create_wire_requires_same_net_views():
    v5 = create_net("v5")
    gnd = create_net("gnd")
    rail = create_node(Dot, "v5_rail", net=v5)
    terminal = create_node(Dot, "pul_plus", net=v5)
    ground = create_node(Ground, "gnd", net=gnd)

    assert create_wire(rail, terminal).net_name == "v5"
    try:
        create_wire(rail, ground)
    except ValueError as error:
        assert "same net" in str(error)
    else:
        raise AssertionError("wires should not connect different nets")


def test_create_schema_rejects_duplicate_node_names():
    node_a = create_node(Dot, "same")
    node_b = create_node(Dot, "same")

    try:
        create_schema([node_a, node_b], [])
    except ValueError as error:
        assert "Duplicate node view name" in str(error)
    else:
        raise AssertionError("duplicate node view names should be rejected")


def _create_stripboard_mapping_schema():
    top_net = create_net("top")
    middle_net = create_net("middle")
    low_net = create_net("low")

    top = create_node(Dot, "top", net=top_net, label="TOP")
    middle = translate(2, -2)(create_node(Dot, "middle", net=middle_net))
    low = translate(4, -4)(create_node(Dot, "low", net=low_net, label="LOW"))

    r1 = translate(0, -1)(create_element(Resistor, "R1", "1k", top, middle))
    r2 = translate(4, -3)(create_element(Resistor, "R2", "2k", middle, low))

    return create_schema([top, middle, low], [r1, r2])


def _create_sparse_stripboard_schema():
    dense_net = create_net("dense")
    sparse_a_net = create_net("sparse_a")
    sparse_b_net = create_net("sparse_b")
    sparse_c_net = create_net("sparse_c")

    dense_nodes = [
        translate(column, 0)(create_node(Dot, f"dense_{column}", net=dense_net))
        for column in range(10)
    ]
    sparse_a_nodes = [
        translate(column, -2)(
            create_node(Dot, f"sparse_a_{column}", net=sparse_a_net, label="A")
        )
        for column in (0, 1)
    ]
    sparse_b_nodes = [
        translate(column, -4)(
            create_node(Dot, f"sparse_b_{column}", net=sparse_b_net, label="B")
        )
        for column in (4, 5)
    ]
    sparse_c = translate(8, -6)(
        create_node(Dot, "sparse_c", net=sparse_c_net, label="C")
    )

    return create_schema([*dense_nodes, *sparse_a_nodes, *sparse_b_nodes, sparse_c], [])


def _create_three_marker_sparse_stripboard_schema():
    four_marker_net = create_net("four_marker")
    three_marker_net = create_net("three_marker")
    two_marker_net = create_net("two_marker")

    four_marker_nodes = [
        translate(column, 0)(
            create_node(Dot, f"four_marker_{column}", net=four_marker_net)
        )
        for column in (0, 2, 4, 6)
    ]
    three_marker_nodes = [
        translate(column, -2)(
            create_node(Dot, f"three_marker_{column}", net=three_marker_net)
        )
        for column in (1, 3, 5)
    ]
    two_marker_nodes = [
        translate(column, -4)(
            create_node(Dot, f"two_marker_{column}", net=two_marker_net)
        )
        for column in (7, 8)
    ]

    return create_schema(
        [*four_marker_nodes, *three_marker_nodes, *two_marker_nodes],
        [],
    )


def _create_duplicate_marker_stripboard_schema():
    dense_net = create_net("dense")
    shared_net = create_net("shared")
    other_net = create_net("other")

    dense_nodes = [
        translate(column, 0)(create_node(Dot, f"dense_dup_{column}", net=dense_net))
        for column in range(6)
    ]
    shared = translate(2, -2)(
        create_node(Dot, "shared_node", net=shared_net, label="shared")
    )
    other = translate(4, -4)(
        create_node(Dot, "other_node", net=other_net, label="other")
    )
    resistor = translate(2, -3)(create_element(Resistor, "Rdup", "1k", shared, other))

    return create_schema([*dense_nodes, shared, other], [resistor])


def _create_nonphysical_junction_stripboard_schema():
    net = create_net("signal")
    other_net = create_net("other")
    signal = create_node(Dot, "signal", net=net, label="signal")
    helper = translate(9, 0)(
        create_node(Dot, "helper", net=net, kind="schematic_junction")
    )
    other = translate(2, -2)(create_node(Dot, "other", net=other_net, label="other"))
    resistor = translate(1, -1)(
        create_element(Resistor, "Rhelper", "1k", signal, other)
    )

    return create_schema([signal, helper, other], [resistor])


def _create_vertical_blocker_schema(middle_x=8, resistor_x=1):
    top_net = create_net("top")
    middle_net = create_net("middle")
    bottom_net = create_net("bottom")

    top = create_node(Dot, "top_block", net=top_net, kind="schematic_junction")
    middle = translate(middle_x, -2)(
        create_node(Dot, "middle_block", net=middle_net, label="middle")
    )
    bottom = translate(0, -4)(
        create_node(Dot, "bottom_block", net=bottom_net, kind="schematic_junction")
    )
    resistor = translate(resistor_x, -2)(
        create_element(Resistor, "Rblock", "1k", top, bottom)
    )

    return create_schema([top, middle, bottom], [resistor])


def _create_transistor_blocker_schema():
    collector_net = create_net("collector")
    dummy_1_net = create_net("dummy_1")
    base_net = create_net("base")
    dummy_2_net = create_net("dummy_2")
    emitter_net = create_net("emitter")

    collector = translate(0, 0)(
        create_node(Dot, "collector_pad", net=collector_net, kind="schematic_junction")
    )
    dummy_1 = translate(8, -2)(
        create_node(Dot, "dummy_1", net=dummy_1_net, label="dummy 1")
    )
    base = translate(-2, -4)(
        create_node(Dot, "base_pad", net=base_net, kind="schematic_junction")
    )
    dummy_2 = translate(9, -6)(
        create_node(Dot, "dummy_2", net=dummy_2_net, label="dummy 2")
    )
    emitter = translate(0, -8)(
        create_node(Dot, "emitter_pad", net=emitter_net, kind="schematic_junction")
    )
    transistor = create_element(
        BjtNpn,
        "Qblock",
        "BC337",
        base=base,
        collector=collector,
        emitter=emitter,
    )

    return create_schema([collector, dummy_1, base, dummy_2, emitter], [transistor])


def _create_short_and_tall_element_schema():
    top_net = create_net("top")
    middle_net = create_net("middle")
    bottom_net = create_net("bottom")

    top = create_node(Dot, "top_span", net=top_net, kind="schematic_junction")
    middle = translate(0, -2)(
        create_node(Dot, "middle_span", net=middle_net, kind="schematic_junction")
    )
    bottom = translate(0, -4)(
        create_node(Dot, "bottom_span", net=bottom_net, kind="schematic_junction")
    )
    short = translate(1, -1)(create_element(Resistor, "Rshort", "1k", top, middle))
    tall = translate(5, -2)(create_element(Resistor, "Rtall", "1k", top, bottom))

    return create_schema([top, middle, bottom], [short, tall])


def _create_same_row_element_schema():
    net = create_net("same_row")

    left = create_node(Dot, "same_row_left", net=net, kind="schematic_junction")
    right = translate(4, 0)(
        create_node(Dot, "same_row_right", net=net, kind="schematic_junction")
    )
    resistor = translate(2, 0)(create_element(Resistor, "Rsame_row", "0R", left, right))

    return create_schema([left, right], [resistor])


def _load_tb6600_schema_factory():
    return create_schema_for_tb6600_interface


def _terminal_holes_by_element(schema, assignment):
    holes_by_element = {}
    for element in schema.elements:
        terminal_holes = []
        for terminal_name, net_name in element.terminal_nets.items():
            key = ("terminal", element.name, terminal_name)
            if key not in assignment.marker_column_maps:
                continue
            if net_name not in assignment.net_rows:
                continue
            terminal_holes.append(
                (
                    terminal_name,
                    assignment.net_rows[net_name],
                    assignment.marker_column_maps[key],
                )
            )
        if terminal_holes:
            holes_by_element[element.name] = tuple(terminal_holes)
    return holes_by_element


def _marker_positions_by_key(assignment):
    marker_rows = {}
    for visualization in assignment.net_visualizations:
        row = assignment.net_rows[visualization.net_name]
        for node_view in visualization.node_views:
            key = ("node", node_view.name)
            if key in assignment.marker_column_maps:
                marker_rows[key] = row
        for terminal in visualization.terminal_points:
            key = ("terminal", terminal.element_name, terminal.terminal_name)
            if key in assignment.marker_column_maps:
                marker_rows[key] = row
    return {
        key: (row, assignment.marker_column_maps[key])
        for key, row in marker_rows.items()
    }


def _create_tb6600_strict_assignment():
    schema = _load_tb6600_schema_factory()()
    assignment = assign_schema_nets_to_stripboard(schema)
    assignment = compact_sparse_stripboard_rows(assignment, schema=schema)
    assignment = compact_stripboard_connections_left(schema, assignment, strict=True)
    return schema, assignment


def _create_tb6600_permuted_assignment():
    schema, assignment = _create_tb6600_strict_assignment()
    assignment = permute_stripboard_rows_for_element_span(
        schema,
        assignment,
        priority_element_names=("Q1", "Q2", "Q3"),
    )
    return schema, assignment


def _terminal_row_span(holes):
    rows = [row for _terminal_name, row, _column in holes]
    return max(rows) - min(rows)


def _assert_no_label_bbox_overlaps(labels):
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            assert not circuit_dsl._stripboard_rectangles_overlap(
                left.bbox,
                right.bbox,
                padding=circuit_dsl.STRIPBOARD_OVERLAY_LABEL_COLLISION_PADDING,
            ), (left.text, right.text, left.bbox, right.bbox)


def test_get_schema_net_visualizations_sorts_nets_by_representative_y():
    schema = _create_stripboard_mapping_schema()

    visualizations = get_schema_net_visualizations(schema)

    assert [visualization.net_name for visualization in visualizations] == [
        "low",
        "middle",
        "top",
    ]
    middle = visualizations[1]
    assert [node.name for node in middle.node_views] == ["middle"]
    assert {
        (terminal.element_name, terminal.terminal_name)
        for terminal in middle.terminal_points
    } == {("R1", "end"), ("R2", "start")}
    assert middle.representative_y == pytest.approx(-2.0)


def test_get_schema_net_visualizations_includes_unconnected_views():
    loose_net = create_net("loose")
    loose = translate(3, 2)(create_node(Dot, "loose", net=loose_net))
    schema = create_schema([loose], [])

    visualizations = get_schema_net_visualizations(schema)

    assert [visualization.net_name for visualization in visualizations] == ["loose"]
    assert visualizations[0].node_views[0].position == (3.0, 2.0)
    assert visualizations[0].terminal_points == ()


def test_assign_schema_nets_to_stripboard_uses_one_row_per_net():
    schema = _create_stripboard_mapping_schema()

    assignment = assign_schema_nets_to_stripboard(schema)

    assert assignment.stripboard.height_pitches == 3
    assert assignment.net_rows == {"top": 0, "middle": 1, "low": 2}
    assert [
        visualization.net_name for visualization in assignment.net_visualizations
    ] == ["top", "middle", "low"]
    assert assignment.used_source_columns == (0, 2, 4)
    assert assignment.column_map == {0: 1, 2: 2, 4: 3}
    assert assignment.stripboard.width_pitches == 5


def test_compact_sparse_stripboard_rows_merges_only_sparse_rows():
    schema = _create_sparse_stripboard_schema()
    assignment = assign_schema_nets_to_stripboard(schema)

    compacted = compact_sparse_stripboard_rows(assignment)

    assert assignment.stripboard.height_pitches == 4
    assert compacted.stripboard.height_pitches == 2
    assert compacted.stripboard.width_pitches == assignment.stripboard.width_pitches
    assert compacted.net_rows == {
        "dense": 0,
        "sparse_a": 1,
        "sparse_b": 1,
        "sparse_c": 1,
    }

    dense_run = next(run for run in compacted.net_runs if run.net_name == "dense")
    assert dense_run.compacted is False
    assert dense_run.start_col == 0
    assert dense_run.end_col == compacted.stripboard.width_pitches - 1

    sparse_runs = [run for run in compacted.net_runs if run.compacted]
    assert [
        (run.net_name, run.row, run.start_col, run.end_col) for run in sparse_runs
    ] == [
        ("sparse_a", 1, 1, 4),
        ("sparse_b", 1, 6, 9),
    ]
    assert len(compacted.local_points) == 1
    assert (
        compacted.local_points[0].net_name,
        compacted.local_points[0].row,
        compacted.local_points[0].col,
    ) == ("sparse_c", 1, 10)
    assert len(compacted.cuts) == 1
    assert (compacted.cuts[0].row, compacted.cuts[0].col) == (1, 5)


def test_compact_sparse_stripboard_rows_compacts_three_marker_nets_by_default():
    schema = _create_three_marker_sparse_stripboard_schema()
    assignment = assign_schema_nets_to_stripboard(schema)

    compacted = compact_sparse_stripboard_rows(assignment)

    four_marker_run = next(
        run for run in compacted.net_runs if run.net_name == "four_marker"
    )
    three_marker_run = next(
        run for run in compacted.net_runs if run.net_name == "three_marker"
    )
    two_marker_run = next(
        run for run in compacted.net_runs if run.net_name == "two_marker"
    )

    assert four_marker_run.compacted is False
    assert four_marker_run.start_col == 0
    assert four_marker_run.end_col == compacted.stripboard.width_pitches - 1

    assert three_marker_run.compacted is True
    assert three_marker_run.end_col - three_marker_run.start_col + 1 == 4
    assert compacted.net_column_maps["three_marker"] == {
        1: three_marker_run.start_col,
        3: three_marker_run.start_col + 2,
        5: three_marker_run.end_col,
    }

    assert two_marker_run.compacted is True
    if two_marker_run.row == three_marker_run.row:
        assert two_marker_run.start_col == three_marker_run.end_col + 2
        assert (
            StripboardCut(
                row=three_marker_run.row,
                col=three_marker_run.end_col + 1,
            )
            in compacted.cuts
        )
    else:
        assert two_marker_run.row > three_marker_run.row


def test_compacted_sparse_rows_snap_markers_inside_runs_not_cuts():
    schema = _create_sparse_stripboard_schema()
    assignment = compact_sparse_stripboard_rows(
        assign_schema_nets_to_stripboard(schema)
    )

    assert assignment.net_column_maps["sparse_a"] == {0: 1, 1: 4}
    assert assignment.net_column_maps["sparse_b"] == {4: 6, 5: 9}
    assert assignment.net_column_maps["sparse_c"] == {8: 10}

    snapped = snap_schema_to_stripboard(schema, assignment)
    positions = {node.name: node.position for node in snapped.node_views}

    assert positions["sparse_a_0"] == pytest.approx((1.5, 1.5))
    assert positions["sparse_a_1"] == pytest.approx((4.5, 1.5))
    assert positions["sparse_b_4"] == pytest.approx((6.5, 1.5))
    assert positions["sparse_b_5"] == pytest.approx((9.5, 1.5))
    assert positions["sparse_c"] == pytest.approx((10.5, 1.5))
    assert all(
        abs(position[0] - 5.5) > 1e-9 or abs(position[1] - 1.5) > 1e-9
        for position in positions.values()
    )


def test_compacted_sparse_rows_give_duplicate_markers_separate_holes():
    schema = _create_duplicate_marker_stripboard_schema()
    assignment = compact_sparse_stripboard_rows(
        assign_schema_nets_to_stripboard(schema)
    )

    shared_keys = [
        ("node", "shared_node"),
        ("terminal", "Rdup", "start"),
    ]
    shared_columns = [assignment.marker_column_maps[key] for key in shared_keys]
    assert len(set(shared_columns)) == len(shared_columns)

    marker_rows = {}
    for visualization in assignment.net_visualizations:
        row = assignment.net_rows[visualization.net_name]
        for node_view in visualization.node_views:
            marker_rows[("node", node_view.name)] = row
        for terminal in visualization.terminal_points:
            marker_rows[("terminal", terminal.element_name, terminal.terminal_name)] = (
                row
            )

    occupied_holes = [
        (assignment.marker_column_maps[key], marker_rows[key]) for key in marker_rows
    ]
    assert len(occupied_holes) == len(set(occupied_holes))


def test_stripboard_assignment_ignores_nonphysical_schematic_junctions(tmp_path):
    schema = _create_nonphysical_junction_stripboard_schema()
    assignment = assign_schema_nets_to_stripboard(schema)

    assert ("node", "helper") not in assignment.marker_column_maps
    assert 9 not in assignment.used_source_columns

    outfile = tmp_path / "overlay.svg"
    render_stripboard_overlay(assignment.stripboard, assignment, schema, file=outfile)

    svg = outfile.read_text(encoding="utf-8")
    assert 'data-node="helper"' not in svg


def test_left_compaction_uses_component_blockers():
    schema = _create_vertical_blocker_schema(middle_x=8)
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
        strict=False,
    )

    assert assignment.marker_column_maps[("node", "middle_block")] == 1
    blocker = StripboardBlocker(row=1, col=2, element_name="Rblock")
    assert blocker in assignment.blockers

    blocker_positions = {(blocker.row, blocker.col) for blocker in assignment.blockers}
    marker_rows = {}
    for visualization in assignment.net_visualizations:
        row = assignment.net_rows[visualization.net_name]
        for node_view in visualization.node_views:
            marker_rows[("node", node_view.name)] = row
        for terminal in visualization.terminal_points:
            marker_rows[("terminal", terminal.element_name, terminal.terminal_name)] = (
                row
            )

    marker_positions = {
        (row, assignment.marker_column_maps[key])
        for key, row in marker_rows.items()
        if key in assignment.marker_column_maps
    }
    assert marker_positions.isdisjoint(blocker_positions)


def test_left_compaction_places_loose_markers_before_elements():
    schema = _create_vertical_blocker_schema(middle_x=8)
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )

    assert assignment.marker_column_maps[("node", "middle_block")] == 1
    assert (1, 1) not in {(blocker.row, blocker.col) for blocker in assignment.blockers}


def test_left_compaction_places_short_span_elements_before_tall_ones():
    schema = _create_short_and_tall_element_schema()
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )

    short_columns = {
        assignment.marker_column_maps[("terminal", "Rshort", "start")],
        assignment.marker_column_maps[("terminal", "Rshort", "end")],
    }
    tall_columns = {
        assignment.marker_column_maps[("terminal", "Rtall", "start")],
        assignment.marker_column_maps[("terminal", "Rtall", "end")],
    }
    assert short_columns == {1}
    assert min(tall_columns) > 1


def test_left_compaction_places_element_terminals_atomically_and_compactly():
    schema = _create_vertical_blocker_schema(middle_x=8)
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )

    assert assignment.marker_column_maps[("terminal", "Rblock", "start")] == 2
    assert assignment.marker_column_maps[("terminal", "Rblock", "end")] == 2


def test_left_compaction_keeps_same_row_element_terminals_distinct():
    schema = _create_same_row_element_schema()
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )

    start_col = assignment.marker_column_maps[("terminal", "Rsame_row", "start")]
    end_col = assignment.marker_column_maps[("terminal", "Rsame_row", "end")]
    assert start_col != end_col
    assert {start_col, end_col} == {1, 2}


def test_left_compaction_allows_different_row_element_terminals_to_align():
    schema = _create_duplicate_marker_stripboard_schema()
    assignment = compact_stripboard_connections_left(
        schema,
        compact_sparse_stripboard_rows(assign_schema_nets_to_stripboard(schema)),
        trim_board=False,
    )

    start_col = assignment.marker_column_maps[("terminal", "Rdup", "start")]
    end_col = assignment.marker_column_maps[("terminal", "Rdup", "end")]
    assert start_col == end_col


def test_stripboard_body_blockers_follow_vertical_horizontal_and_diagonal_paths():
    vertical = circuit_dsl._stripboard_element_blockers_from_terminal_holes(
        "Rvertical",
        ((0, 2), (3, 2)),
    )
    horizontal = circuit_dsl._stripboard_element_blockers_from_terminal_holes(
        "Rhorizontal",
        ((2, 1), (2, 4)),
    )
    diagonal = circuit_dsl._stripboard_element_blockers_from_terminal_holes(
        "Rdiagonal",
        ((0, 0), (2, 2)),
    )

    assert {(blocker.row, blocker.col) for blocker in vertical} == {
        (1, 2),
        (2, 2),
    }
    assert {(blocker.row, blocker.col) for blocker in horizontal} == {
        (2, 2),
        (2, 3),
    }
    diagonal_positions = {(blocker.row, blocker.col) for blocker in diagonal}
    assert (1, 1) in diagonal_positions
    assert (0, 0) not in diagonal_positions
    assert (2, 2) not in diagonal_positions


def test_stripboard_body_blockers_for_multi_terminal_star_paths():
    blockers = circuit_dsl._stripboard_element_blockers_from_terminal_holes(
        "Qstar",
        ((0, 0), (2, 2), (4, 0)),
    )

    blocker_positions = {(blocker.row, blocker.col) for blocker in blockers}
    assert (2, 1) in blocker_positions
    assert (0, 0) not in blocker_positions
    assert (2, 2) not in blocker_positions
    assert (4, 0) not in blocker_positions


def test_left_compaction_prefers_compact_element_span_over_left_edge():
    schema, assignment = _create_tb6600_strict_assignment()
    holes = _terminal_holes_by_element(schema, assignment)

    for element_name in ("Q1", "Q2", "R1", "R2", "R3", "R4", "R7", "R8"):
        columns = [column for _terminal_name, _row, column in holes[element_name]]
        assert max(columns) - min(columns) == 0
    q3_columns = [column for _terminal_name, _row, column in holes["Q3"]]
    assert max(q3_columns) - min(q3_columns) <= 5


def test_tb6600_strict_stripboard_projection_has_no_duplicate_marker_holes():
    _schema, assignment = _create_tb6600_strict_assignment()
    marker_positions = _marker_positions_by_key(assignment)

    assert len(marker_positions.values()) == len(set(marker_positions.values()))


def test_tb6600_strict_stripboard_projection_has_no_terminal_on_body_blocker():
    _schema, assignment = _create_tb6600_strict_assignment()
    marker_positions = _marker_positions_by_key(assignment)
    terminal_positions = {
        position for key, position in marker_positions.items() if key[0] == "terminal"
    }
    blocker_positions = {(blocker.row, blocker.col) for blocker in assignment.blockers}

    assert terminal_positions.isdisjoint(blocker_positions)


def test_tb6600_body_paths_do_not_cross_other_terminal_holes_or_bodies():
    schema, assignment = _create_tb6600_strict_assignment()
    holes_by_element = _terminal_holes_by_element(schema, assignment)
    terminal_positions = {
        (row, column)
        for terminal_holes in holes_by_element.values()
        for _terminal_name, row, column in terminal_holes
    }
    seen_segments = []

    for element_name, terminal_holes in holes_by_element.items():
        element_terminal_positions = {
            (row, column) for _terminal_name, row, column in terminal_holes
        }
        blockers = circuit_dsl._stripboard_element_blockers_from_terminal_holes(
            element_name,
            tuple((row, column) for _terminal_name, row, column in terminal_holes),
        )
        blocker_positions = {(blocker.row, blocker.col) for blocker in blockers}
        assert blocker_positions.isdisjoint(
            terminal_positions - element_terminal_positions
        )

        segments = circuit_dsl._stripboard_element_body_segments_from_terminal_holes(
            tuple((row, column) for _terminal_name, row, column in terminal_holes),
        )
        assert not circuit_dsl._stripboard_segments_intersect_any(
            segments,
            seen_segments,
        )
        seen_segments.extend(segments)


def _row_groups(assignment):
    groups = {}
    for net_name, row in assignment.net_rows.items():
        groups.setdefault(row, set()).add(net_name)
    return tuple(frozenset(net_names) for _row, net_names in sorted(groups.items()))


def _row_remap_from_net_groups(before, after):
    row_remap = {}
    for before_row in range(before.stripboard.height_pitches):
        net_names = [
            net_name for net_name, row in before.net_rows.items() if row == before_row
        ]
        if not net_names:
            row_remap[before_row] = before_row
            continue
        new_rows = {after.net_rows[net_name] for net_name in net_names}
        assert len(new_rows) == 1
        row_remap[before_row] = next(iter(new_rows))
    return row_remap


def test_permute_stripboard_rows_reduces_tb6600_priority_transistor_spans():
    schema, strict_assignment = _create_tb6600_strict_assignment()
    permuted = permute_stripboard_rows_for_element_span(
        schema,
        strict_assignment,
        priority_element_names=("Q1", "Q2", "Q3"),
    )

    strict_holes = _terminal_holes_by_element(schema, strict_assignment)
    permuted_holes = _terminal_holes_by_element(schema, permuted)

    assert (
        max(
            _terminal_row_span(strict_holes[element_name])
            for element_name in ("Q1", "Q2", "Q3")
        )
        > 3
    )
    assert {
        element_name: _terminal_row_span(permuted_holes[element_name])
        for element_name in ("Q1", "Q2", "Q3")
    } == {"Q1": 3, "Q2": 2, "Q3": 3}


def test_permute_stripboard_rows_preserves_columns_and_shared_row_groups():
    schema, strict_assignment = _create_tb6600_strict_assignment()
    permuted = permute_stripboard_rows_for_element_span(schema, strict_assignment)

    assert permuted.marker_column_maps == strict_assignment.marker_column_maps
    assert permuted.net_column_maps == strict_assignment.net_column_maps
    assert set(_row_groups(permuted)) == set(_row_groups(strict_assignment))
    assert any(len(group) > 1 for group in _row_groups(permuted))
    assert permuted.net_rows != strict_assignment.net_rows


def test_permute_stripboard_rows_remaps_artifacts_consistently():
    schema, strict_assignment = _create_tb6600_strict_assignment()
    permuted = permute_stripboard_rows_for_element_span(schema, strict_assignment)
    row_remap = _row_remap_from_net_groups(strict_assignment, permuted)

    assert {
        (run.net_name, row_remap[run.row], run.start_col, run.end_col, run.compacted)
        for run in strict_assignment.net_runs
    } == {
        (run.net_name, run.row, run.start_col, run.end_col, run.compacted)
        for run in permuted.net_runs
    }
    assert {(row_remap[cut.row], cut.col) for cut in strict_assignment.cuts} == {
        (cut.row, cut.col) for cut in permuted.cuts
    }
    assert {
        (
            local_point.net_name,
            row_remap[local_point.row],
            local_point.col,
            local_point.source_column,
        )
        for local_point in strict_assignment.local_points
    } == {
        (
            local_point.net_name,
            local_point.row,
            local_point.col,
            local_point.source_column,
        )
        for local_point in permuted.local_points
    }
    assert {
        (row_remap[blocker.row], blocker.col, blocker.element_name)
        for blocker in strict_assignment.blockers
    } == {
        (blocker.row, blocker.col, blocker.element_name)
        for blocker in permuted.blockers
    }


def test_permute_stripboard_rows_is_deterministic():
    schema, strict_assignment = _create_tb6600_strict_assignment()

    first = permute_stripboard_rows_for_element_span(schema, strict_assignment)
    second = permute_stripboard_rows_for_element_span(schema, strict_assignment)

    assert first.net_rows == second.net_rows
    assert first.net_runs == second.net_runs
    assert first.cuts == second.cuts
    assert first.blockers == second.blockers


def test_tb6600_permuted_projection_has_no_duplicate_marker_holes_or_terminals_on_blockers():
    _schema, assignment = _create_tb6600_permuted_assignment()
    marker_positions = _marker_positions_by_key(assignment)
    terminal_positions = {
        position for key, position in marker_positions.items() if key[0] == "terminal"
    }
    blocker_positions = {(blocker.row, blocker.col) for blocker in assignment.blockers}

    assert len(marker_positions.values()) == len(set(marker_positions.values()))
    assert terminal_positions.isdisjoint(blocker_positions)


def test_left_compaction_allows_all_element_types_to_block_holes():
    schema = _create_transistor_blocker_schema()
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )

    assert any(blocker.element_name == "Qblock" for blocker in assignment.blockers)


def test_left_compaction_raises_when_blockers_leave_no_hole():
    schema = _create_vertical_blocker_schema(middle_x=0, resistor_x=0)

    with pytest.raises(ValueError, match="No legal stripboard hole remains"):
        compact_stripboard_connections_left(
            schema,
            assign_schema_nets_to_stripboard(schema),
            trim_board=False,
        )


def test_left_compaction_trims_board_but_keeps_blocker_extent():
    schema = _create_vertical_blocker_schema(middle_x=8)
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
    )

    rightmost_blocker = max(blocker.col for blocker in assignment.blockers)
    assert assignment.stripboard.width_pitches >= (
        rightmost_blocker + 1 + assignment.right_margin_pitches
    )
    for run in assignment.net_runs:
        if not run.compacted and run.start_col == 0:
            assert run.end_col == assignment.stripboard.width_pitches - 1


def test_snap_schema_to_stripboard_moves_node_views_onto_rows():
    schema = _create_stripboard_mapping_schema()
    assignment = assign_schema_nets_to_stripboard(schema)

    snapped = snap_schema_to_stripboard(schema, assignment)

    for node_view in snapped.node_views:
        expected_row = assignment.net_rows[node_view.net.name]
        assert node_view.position[1] == pytest.approx(0.5 + expected_row)
        assert (node_view.position[0] - 0.5).is_integer()


def test_render_stripboard_overlay_writes_svg(tmp_path):
    schema = _create_stripboard_mapping_schema()
    assignment = assign_schema_nets_to_stripboard(schema)
    outfile = tmp_path / "overlay.svg"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    svg = outfile.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert 'class="copper-strip"' in svg
    assert 'class="hole"' in svg
    assert 'class="overlay-net-label"' in svg
    assert 'class="overlay-node"' in svg
    assert ">top</text>" in svg


def test_render_compacted_stripboard_overlay_writes_cuts_and_run_blocks(tmp_path):
    schema = _create_sparse_stripboard_schema()
    assignment = compact_sparse_stripboard_rows(
        assign_schema_nets_to_stripboard(schema)
    )
    outfile = tmp_path / "compacted_overlay.svg"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    svg = outfile.read_text(encoding="utf-8")
    assert 'class="strip-cut"' in svg
    assert 'class="strip-run-block"' in svg
    assert 'class="overlay-net-run-label"' not in svg
    assert 'class="overlay-local-point-label"' not in svg
    assert ">sparse_a</text>" not in svg
    assert ">sparse_c</text>" not in svg


def test_render_stripboard_overlay_labels_transistor_terminals(tmp_path):
    collector = create_node(Dot, "collector", net=create_net("collector"))
    base = translate(1, -1)(create_node(Dot, "base", net=create_net("base")))
    emitter = translate(2, -2)(create_node(Dot, "emitter", net=create_net("emitter")))
    transistor = create_element(
        BjtNpn,
        "Qtest",
        "BC337",
        base=base,
        collector=collector,
        emitter=emitter,
    )
    schema = create_schema([collector, base, emitter], [transistor])
    assignment = assign_schema_nets_to_stripboard(schema)
    outfile = tmp_path / "transistor_terminal_labels.svg"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    terminal_label_lines = [
        line
        for line in outfile.read_text(encoding="utf-8").splitlines()
        if 'class="overlay-terminal-label"' in line
    ]
    assert len(terminal_label_lines) == 3
    assert any(
        'data-terminal="base"' in line and ">B</text>" in line
        for line in terminal_label_lines
    )
    assert any(
        'data-terminal="collector"' in line and ">C</text>" in line
        for line in terminal_label_lines
    )
    assert any(
        'data-terminal="emitter"' in line and ">E</text>" in line
        for line in terminal_label_lines
    )


def test_render_stripboard_overlay_labels_zener_terminals(tmp_path):
    anode = create_node(Dot, "anode", net=create_net("anode"))
    cathode = translate(0, -1)(create_node(Dot, "cathode", net=create_net("cathode")))
    zener = create_element(Zener, "Dtest", "5V1", anode, cathode)
    schema = create_schema([anode, cathode], [zener])
    assignment = assign_schema_nets_to_stripboard(schema)
    outfile = tmp_path / "zener_terminal_labels.svg"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    terminal_label_lines = [
        line
        for line in outfile.read_text(encoding="utf-8").splitlines()
        if 'class="overlay-terminal-label"' in line
    ]
    assert len(terminal_label_lines) == 2
    assert any(
        'data-terminal="start"' in line and ">A</text>" in line
        for line in terminal_label_lines
    )
    assert any(
        'data-terminal="end"' in line and ">K</text>" in line
        for line in terminal_label_lines
    )


def test_render_stripboard_overlay_does_not_label_passive_terminals(tmp_path):
    left = create_node(Dot, "left", net=create_net("left"))
    right = translate(0, -1)(create_node(Dot, "right", net=create_net("right")))
    resistor = create_element(Resistor, "Rtest", "1k", left, right)
    schema = create_schema([left, right], [resistor])
    assignment = assign_schema_nets_to_stripboard(schema)
    outfile = tmp_path / "passive_terminal_labels.svg"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    svg = outfile.read_text(encoding="utf-8")
    assert 'class="overlay-terminal"' in svg
    assert 'class="overlay-terminal-label"' not in svg


def test_stripboard_label_collision_resolver_moves_overlapping_label():
    fixed = circuit_dsl._StripboardOverlayLabel(
        class_name="fixed",
        text="fixed",
        x=0.0,
        y=0.0,
        font_size=0.25,
        font_weight="700",
        text_anchor="start",
        collision_priority=0,
    )
    movable = circuit_dsl._StripboardOverlayLabel(
        class_name="movable",
        text="movable",
        x=0.0,
        y=0.0,
        font_size=0.25,
        font_weight="700",
        text_anchor="start",
        collision_priority=1,
        candidates=(
            circuit_dsl._StripboardOverlayLabelCandidate(0.0, 0.0, "start", 0.0),
            circuit_dsl._StripboardOverlayLabelCandidate(0.0, 0.7, "start", 0.0),
        ),
    )

    resolved = circuit_dsl._resolve_stripboard_overlay_label_collisions(
        (fixed, movable)
    )

    assert (resolved[1].x, resolved[1].y) == (0.0, 0.7)
    _assert_no_label_bbox_overlaps(resolved)


def test_stripboard_label_collision_resolver_preserves_clear_preferred_position():
    first = circuit_dsl._StripboardOverlayLabel(
        class_name="first",
        text="left",
        x=0.0,
        y=0.0,
        font_size=0.20,
        font_weight="700",
        text_anchor="start",
        collision_priority=0,
    )
    second = circuit_dsl._StripboardOverlayLabel(
        class_name="second",
        text="right",
        x=2.0,
        y=0.0,
        font_size=0.20,
        font_weight="700",
        text_anchor="start",
        collision_priority=1,
        candidates=(
            circuit_dsl._StripboardOverlayLabelCandidate(2.0, 0.0, "start", 0.0),
            circuit_dsl._StripboardOverlayLabelCandidate(2.0, 0.6, "start", 0.0),
        ),
    )

    resolved = circuit_dsl._resolve_stripboard_overlay_label_collisions((first, second))

    assert (resolved[1].x, resolved[1].y) == (2.0, 0.0)
    _assert_no_label_bbox_overlaps(resolved)


def test_stripboard_label_collision_resolver_moves_lower_priority_element_label():
    element = circuit_dsl._StripboardOverlayLabel(
        class_name="overlay-element-label",
        text="Q3 BC337",
        x=0.0,
        y=0.0,
        font_size=0.20,
        font_weight="700",
        text_anchor="middle",
        collision_priority=3,
        candidates=(
            circuit_dsl._StripboardOverlayLabelCandidate(0.0, 0.0, "middle", 0.0),
            circuit_dsl._StripboardOverlayLabelCandidate(0.0, 0.7, "middle", 0.0),
        ),
    )
    terminal = circuit_dsl._StripboardOverlayLabel(
        class_name="overlay-terminal-label",
        text="B",
        x=0.0,
        y=0.0,
        font_size=0.20,
        font_weight="800",
        text_anchor="middle",
        collision_priority=1,
    )

    resolved = circuit_dsl._resolve_stripboard_overlay_label_collisions(
        (element, terminal)
    )

    assert (resolved[1].x, resolved[1].y) == (0.0, 0.0)
    assert (resolved[0].x, resolved[0].y) == (0.0, 0.7)
    _assert_no_label_bbox_overlaps(resolved)


def test_tb6600_permuted_stripboard_overlay_labels_do_not_overlap():
    schema, assignment = _create_tb6600_permuted_assignment()
    labels = circuit_dsl._placed_stripboard_overlay_labels(
        assignment.stripboard,
        assignment,
        schema,
    )
    main_labels = tuple(
        label
        for label in labels
        if label.class_name
        in {
            "overlay-element-label",
            "overlay-net-label",
            "overlay-node-label",
            "overlay-terminal-label",
        }
    )

    _assert_no_label_bbox_overlaps(main_labels)


def test_render_stripboard_overlay_omits_internal_blockers(tmp_path):
    schema = _create_vertical_blocker_schema(middle_x=8)
    assignment = compact_stripboard_connections_left(
        schema,
        assign_schema_nets_to_stripboard(schema),
        trim_board=False,
    )
    svg_outfile = tmp_path / "blockers.svg"
    png_outfile = tmp_path / "blockers.png"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=svg_outfile,
    )
    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=png_outfile,
    )

    svg = svg_outfile.read_text(encoding="utf-8")
    assert any(blocker.element_name == "Rblock" for blocker in assignment.blockers)
    assert 'class="stripboard-blocker"' not in svg
    assert png_outfile.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_render_stripboard_overlay_writes_png(tmp_path):
    schema = _create_stripboard_mapping_schema()
    assignment = assign_schema_nets_to_stripboard(schema)
    outfile = tmp_path / "overlay.png"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    assert outfile.exists()
    assert outfile.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_render_compacted_stripboard_overlay_writes_png(tmp_path):
    schema = _create_sparse_stripboard_schema()
    assignment = compact_sparse_stripboard_rows(
        assign_schema_nets_to_stripboard(schema)
    )
    outfile = tmp_path / "compacted_overlay.png"

    render_stripboard_overlay(
        assignment.stripboard,
        assignment,
        schema,
        file=outfile,
    )

    assert outfile.exists()
    assert outfile.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_create_stripboard_has_expected_defaults():
    board = create_stripboard(24, 12)

    assert isinstance(board, Stripboard)
    assert board.width_pitches == 24
    assert board.height_pitches == 12
    assert board.strip_direction is Direction.HORIZONTAL
    assert board.pitch_mm == 2.54


def test_create_stripboard_rejects_invalid_dimensions():
    invalid_sizes = [
        (0, 2),
        (-1, 2),
        (2, 0),
        (2, -1),
        (1.5, 2),
        (True, 2),
        (2, "3"),
    ]

    for width, height in invalid_sizes:
        with pytest.raises((TypeError, ValueError)):
            create_stripboard(width, height)


def test_create_stripboard_rejects_invalid_pitch():
    with pytest.raises((TypeError, ValueError)):
        create_stripboard(4, 3, pitch_mm=0)

    with pytest.raises((TypeError, ValueError)):
        create_stripboard(4, 3, pitch_mm="2.54")


def test_render_stripboard_writes_svg(tmp_path):
    board = create_stripboard(4, 3)
    outfile = tmp_path / "stripboard.svg"

    render_stripboard(board, file=outfile)

    svg = outfile.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert svg.count('class="copper-strip"') == 3
    assert svg.count('class="hole"') == 12


def test_render_stripboard_writes_png(tmp_path):
    board = create_stripboard(4, 3)
    outfile = tmp_path / "stripboard.png"

    render_stripboard(board, file=outfile)

    assert outfile.exists()
    assert outfile.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_render_stripboard_rejects_unsupported_suffix(tmp_path):
    board = create_stripboard(4, 3)

    with pytest.raises(ValueError, match="\\.svg or \\.png"):
        render_stripboard(board, file=tmp_path / "stripboard.pdf")


def test_render_stripboard_vertical_direction_is_not_implemented(tmp_path):
    board = create_stripboard(4, 3, strip_direction=Direction.VERTICAL)

    with pytest.raises(NotImplementedError, match="horizontal"):
        render_stripboard(board, file=tmp_path / "stripboard.svg")
