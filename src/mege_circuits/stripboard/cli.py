"""CLI for dumping and rendering human-editable stripboard YAML layouts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from mege_circuits.circuit import circuit_from_schema
from mege_circuits.dsl import Schema, create_stripboard
from mege_circuits.physical import (
    plan_stripboard,
    stripboard_hints_from_schema,
    verify_stripboard_layout,
)
from mege_circuits.stripboard.config import (
    _import_source_factory,
    render_stripboard_layout_config,
    write_stripboard_layout_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mege-circuits-stripboard",
        description="Dump or render visible-terminal stripboard YAML layouts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dump_parser = subparsers.add_parser(
        "dump",
        help="Plan a source schematic and dump a hand-editable stripboard YAML file.",
    )
    dump_parser.add_argument("factory", help="Source factory: module:function")
    dump_parser.add_argument("-o", "--output", required=True, help="Output YAML path.")
    dump_parser.add_argument(
        "--basename",
        default=None,
        help="Output artifact basename stored in YAML.",
    )
    dump_parser.add_argument(
        "--circuit-name",
        default=None,
        help="Circuit name override for netlist fingerprinting.",
    )
    dump_parser.add_argument(
        "--priority-elements",
        default="",
        help="Comma-separated priority refdeses for planner hints.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Verify and render a hand-edited stripboard YAML file.",
    )
    render_parser.add_argument("config", help="Path to stripboard YAML/JSON config.")
    render_parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Output directory for generated artifacts.",
    )
    render_parser.add_argument(
        "--basename",
        default=None,
        help="Filename prefix override.",
    )
    render_parser.add_argument(
        "--allow-source-drift",
        action="store_true",
        help="Allow source fingerprint mismatch while loading YAML.",
    )
    render_parser.add_argument(
        "--full-build",
        action="store_true",
        help="Write the full build artifact set instead of only top SVG/PNG.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dump":
        output = _dump_command(args)
        print(output)
        return 0
    if args.command == "render":
        outputs = render_stripboard_layout_config(
            args.config,
            output_dir=args.output_dir,
            basename=args.basename,
            allow_source_drift=args.allow_source_drift,
            full_build=args.full_build,
        )
        for output in outputs:
            print(output)
        return 0

    parser.error(f"Unknown command {args.command!r}")
    return 2


def _dump_command(args) -> Path:
    factory = _import_source_factory(args.factory, base_dir=Path.cwd())
    schema = factory()
    if not isinstance(schema, Schema):
        raise TypeError("dump factory must return a mege_circuits.dsl.Schema object")
    circuit = circuit_from_schema(schema, name=args.circuit_name)
    priority_elements = _split_priority_elements(args.priority_elements)
    hints = stripboard_hints_from_schema(
        schema,
        priority_element_names=priority_elements,
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
    if layout is None or not report.ok:
        raise RuntimeError(report.summary())
    report = verify_stripboard_layout(layout, circuit)
    if not report.ok:
        raise RuntimeError(report.summary())
    return write_stripboard_layout_yaml(
        layout,
        circuit,
        args.output,
        source_factory=args.factory,
        basename=args.basename or circuit.name,
        priority_elements=priority_elements,
    )


def _split_priority_elements(raw_value: str):
    if not raw_value:
        return ()
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


if __name__ == "__main__":
    raise SystemExit(main())
