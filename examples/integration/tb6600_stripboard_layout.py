"""Render the verified TB6600 stripboard build artifacts."""

import logging
import shutil
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

_logger = logging.getLogger(__name__)

try:
    from examples.integration.tb6600_stripboard_interface import (
        create_tb6600_artifact_staging_dir,
        create_schema_for_tb6600_interface,
        prepare_tb6600_artifact_outputs_for_run,
        publish_tb6600_staged_artifacts,
    )
except ModuleNotFoundError:
    from tb6600_stripboard_interface import (
        create_tb6600_artifact_staging_dir,
        create_schema_for_tb6600_interface,
        prepare_tb6600_artifact_outputs_for_run,
        publish_tb6600_staged_artifacts,
    )


DEFAULT_OUTPUT_DIR = Path(__file__).with_name("diagrams")
STRIPBOARD_ARTIFACT_STEM = "pico_tb6600_stripboard_interface_stripboard"
OBSOLETE_STRIPBOARD_ARTIFACT_STEMS = (
    "pico_tb6600_stripboard_interface_stripboard_projection",
)
TB6600_PRIORITY_ELEMENTS = ("Q1", "Q2", "Q3")


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


def render_tb6600_stripboard_projection(output_dir=None, stem=STRIPBOARD_ARTIFACT_STEM):
    if output_dir is None:
        raise ValueError(
            "Legacy stripboard projection rendering requires an explicit output_dir; "
            "the integration diagrams directory is reserved for verified build outputs."
        )
    output_dir = Path(output_dir)
    run_id, staging_dir = create_tb6600_artifact_staging_dir(output_dir, stem)
    svg_file, png_file = prepare_tb6600_artifact_outputs_for_run(
        staging_dir,
        stem,
        run_id,
    )
    try:
        schema, assignment = create_stripboard_projection()
        for output_file in (svg_file, png_file):
            render_stripboard_overlay(
                assignment.stripboard,
                assignment,
                schema,
                file=output_file,
            )
            _logger.info("Wrote %s", output_file)
        final_svg, final_png = publish_tb6600_staged_artifacts(
            output_dir,
            (svg_file, png_file),
            staging_dir=staging_dir,
            prune_stems=(stem,),
        )
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return final_svg, final_png


def create_tb6600_verified_stripboard_plan():
    schema = create_schema_for_tb6600_interface()
    circuit = circuit_from_schema(schema, name="pico_tb6600_stripboard_interface")
    hints = stripboard_hints_from_schema(
        schema,
        priority_element_names=TB6600_PRIORITY_ELEMENTS,
    )
    board = create_stripboard(
        hints.board_width_pitches,
        hints.board_height_pitches,
    )
    layout, report = plan_stripboard(
        circuit,
        board=board,
        hints=hints,
    )
    if not report.ok:
        raise RuntimeError(report.summary())
    return schema, circuit, layout, report


def render_tb6600_stripboard_build(output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    _schema, circuit, layout, report = create_tb6600_verified_stripboard_plan()
    run_id, staging_dir = create_tb6600_artifact_staging_dir(
        output_dir, STRIPBOARD_ARTIFACT_STEM
    )
    try:
        staged_outputs = write_stripboard_build_outputs(
            layout,
            circuit,
            output_dir=staging_dir,
            stem=STRIPBOARD_ARTIFACT_STEM,
            run_id=run_id,
            report=report,
        )
        for artifact in staged_outputs.as_tuple():
            _logger.debug("Wrote %s", artifact)
        final_artifacts = publish_tb6600_staged_artifacts(
            output_dir,
            staged_outputs.as_tuple(),
            staging_dir=staging_dir,
            prune_stems=(STRIPBOARD_ARTIFACT_STEM,),
            obsolete_stems=OBSOLETE_STRIPBOARD_ARTIFACT_STEMS,
        )
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return type(staged_outputs)(*final_artifacts)


def main():
    render_tb6600_stripboard_build()


if __name__ == "__main__":
    main()
