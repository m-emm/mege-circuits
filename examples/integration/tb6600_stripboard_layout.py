"""Render a first stripboard-row projection of the TB6600 interface schematic."""

from pathlib import Path

from mege_circuits.simple import (
    assign_schema_nets_to_stripboard,
    compact_sparse_stripboard_rows,
    compact_stripboard_connections_left,
    permute_stripboard_rows_for_element_span,
    render_stripboard_overlay,
)
try:
    from examples.integration.tb6600_stripboard_interface import (
        create_schema_for_tb6600_interface,
    )
except ModuleNotFoundError:
    from tb6600_stripboard_interface import create_schema_for_tb6600_interface


DEFAULT_OUTPUT_DIR = Path(__file__).with_name("diagrams")


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
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_file = output_dir / "pico_tb6600_stripboard_interface_stripboard.svg"
    png_file = output_dir / "pico_tb6600_stripboard_interface_stripboard.png"
    schema, assignment = create_stripboard_projection()
    for output_file in (svg_file, png_file):
        render_stripboard_overlay(
            assignment.stripboard,
            assignment,
            schema,
            file=output_file,
        )
        print(f"Wrote {output_file}")
    return svg_file, png_file


def main():
    render_tb6600_stripboard_projection()


if __name__ == "__main__":
    main()
