"""Render the diagnostic stripboard projection of the TB6600 interface."""

from pathlib import Path

from mege_circuits.simple import (
    assign_schema_nets_to_stripboard,
    circuit_from_schema,
    compact_sparse_stripboard_rows,
    compact_stripboard_connections_left,
    create_stripboard,
    permute_stripboard_rows_for_element_span,
    plan_stripboard,
    render_stripboard_overlay,
    stripboard_hints_from_schema,
    write_stripboard_build_outputs,
)

try:
    from examples.integration.tb6600_stripboard_interface import (
        create_schema_for_tb6600_interface,
        prepare_tb6600_artifact_outputs,
        publish_tb6600_latest_artifact_links,
    )
except ModuleNotFoundError:
    from tb6600_stripboard_interface import (
        create_schema_for_tb6600_interface,
        prepare_tb6600_artifact_outputs,
        publish_tb6600_latest_artifact_links,
    )


DEFAULT_OUTPUT_DIR = Path(__file__).with_name("diagrams")
STRIPBOARD_ARTIFACT_STEM = "pico_tb6600_stripboard_interface_stripboard"
TB6600_BUILD_BOARD_WIDTH = 8
TB6600_BUILD_BOARD_EXTRA_ROWS = 2


def create_stripboard_projection():
    schema = create_schema_for_tb6600_interface()
    assignment = assign_schema_nets_to_stripboard(schema)
    assignment = compact_sparse_stripboard_rows(assignment, schema=schema)
    assignment = compact_stripboard_connections_left(schema, assignment, strict=True)
    assignment = permute_stripboard_rows_for_element_span(
        schema,
        assignment,
        priority_element_names=("Q1", "Q2", "Q3"),
    )
    return schema, assignment


def render_tb6600_stripboard_projection(output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    svg_file, png_file = prepare_tb6600_artifact_outputs(
        output_dir,
        STRIPBOARD_ARTIFACT_STEM,
    )
    schema, assignment = create_stripboard_projection()
    for output_file in (svg_file, png_file):
        render_stripboard_overlay(
            assignment.stripboard,
            assignment,
            schema,
            file=output_file,
        )
        print(f"Wrote {output_file}")
    publish_tb6600_latest_artifact_links(svg_file, png_file)
    return svg_file, png_file


def create_tb6600_verified_stripboard_plan():
    schema = create_schema_for_tb6600_interface()
    circuit = circuit_from_schema(schema, name="pico_tb6600_stripboard_interface")
    board = create_stripboard(
        TB6600_BUILD_BOARD_WIDTH,
        len(circuit.nets) + len(circuit.components) + TB6600_BUILD_BOARD_EXTRA_ROWS,
    )
    layout, report = plan_stripboard(
        circuit,
        board=board,
        hints=stripboard_hints_from_schema(schema),
    )
    if not report.ok:
        raise RuntimeError(report.summary())
    return schema, circuit, layout, report


def render_tb6600_stripboard_build(output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    _clear_tb6600_build_artifacts(output_dir, STRIPBOARD_ARTIFACT_STEM)
    _schema, circuit, layout, report = create_tb6600_verified_stripboard_plan()
    run_id = prepare_tb6600_artifact_outputs(
        output_dir,
        STRIPBOARD_ARTIFACT_STEM,
    )[
        0
    ].stem.split("__", 1)[1]
    outputs = write_stripboard_build_outputs(
        layout,
        circuit,
        output_dir=output_dir,
        stem=STRIPBOARD_ARTIFACT_STEM,
        run_id=run_id,
        report=report,
    )
    for artifact in outputs.as_tuple():
        print(f"Wrote {artifact}")
    publish_tb6600_latest_artifact_links(*outputs.as_tuple())
    return outputs


def _clear_tb6600_build_artifacts(output_dir, stem):
    output_dir.mkdir(parents=True, exist_ok=True)
    stems = (
        stem,
        f"{stem}_bottom",
        f"{stem}_debug",
        f"{stem}_checklist",
        f"{stem}_data",
    )
    for artifact_stem in stems:
        for suffix in (".svg", ".png", ".md", ".json"):
            latest = output_dir / f"{artifact_stem}{suffix}"
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            for old_artifact in output_dir.glob(f"{artifact_stem}__*{suffix}"):
                old_artifact.unlink()


def main():
    render_tb6600_stripboard_build()


if __name__ == "__main__":
    main()
