"""CLI for generating top/bottom pinout SVG diagrams from config files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .config import PinoutBox, load_pinout_config
from .discrete import generate_discrete_top_svg
from .routing import route_problematic_connections
from .svg import SvgMarginsPx, generate_routed_svg, write_svg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mege-circuits-pinout",
        description=(
            "Generate pinout SVG diagrams (top, optional discrete top, and "
            "underside views) from YAML/JSON config."
        ),
    )
    parser.add_argument("config", help="Path to pinout config (.yaml/.yml/.json)")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Output directory for generated SVGs (default: current directory).",
    )
    parser.add_argument(
        "--basename",
        default=None,
        help="Filename prefix override (default: config basename field or 'pinout').",
    )
    parser.add_argument(
        "--top-only",
        action="store_true",
        help="Generate only top view SVG.",
    )
    parser.add_argument(
        "--bottom-only",
        action="store_true",
        help="Generate only underside view SVG.",
    )
    parser.add_argument(
        "--no-routing",
        action="store_true",
        help="Disable waypoint routing and render all wires as direct lines.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print routing details.",
    )
    return parser


def _write_view(
    *,
    output_dir: Path,
    basename: str,
    suffix: str,
    pin_positions: dict[str, tuple[float, float]],
    connections: list[dict[str, object]],
    waypoint_solutions: dict[int, dict[str, object]],
    color_map: dict[str, str],
    version_label: str | None,
    notes_text: str | None,
    svg_margins_px: SvgMarginsPx,
    boxes: tuple[PinoutBox, ...],
    flip_x: bool,
) -> Path:
    svg_content = generate_routed_svg(
        pin_positions,
        connections,
        waypoint_solutions,
        boxes=boxes,
        flip_x=flip_x,
        version_label=version_label,
        notes_text=notes_text,
        color_map=color_map,
        svg_margins_px=svg_margins_px,
    )
    return write_svg(svg_content, output_dir / f"{basename}_{suffix}.svg")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.top_only and args.bottom_only:
        parser.error("--top-only and --bottom-only are mutually exclusive")

    project = load_pinout_config(args.config)
    output_dir = Path(args.output_dir)
    basename = args.basename or project.basename

    waypoint_solutions: dict[int, dict[str, object]] = {}
    if not args.no_routing:
        waypoint_solutions = route_problematic_connections(
            project.pin_positions,
            project.connections,
            verbose=args.verbose,
        )

    output_paths: list[Path] = []
    if not args.bottom_only:
        output_paths.append(
            _write_view(
                output_dir=output_dir,
                basename=basename,
                suffix="top",
                pin_positions=project.pin_positions,
                connections=project.connections,
                waypoint_solutions=waypoint_solutions,
                color_map=project.color_map,
                version_label=project.version_label,
                notes_text=project.notes_text,
                svg_margins_px=project.svg_margins_px,
                boxes=project.boxes,
                flip_x=False,
            )
        )
        if project.component_placements:
            output_paths.append(
                write_svg(
                    generate_discrete_top_svg(project),
                    output_dir / f"{basename}_top_discrete.svg",
                )
            )

    if not args.top_only:
        output_paths.append(
            _write_view(
                output_dir=output_dir,
                basename=basename,
                suffix="bottom",
                pin_positions=project.pin_positions,
                connections=project.connections,
                waypoint_solutions=waypoint_solutions,
                color_map=project.color_map,
                version_label=project.version_label,
                notes_text=project.notes_text,
                svg_margins_px=project.svg_margins_px,
                boxes=project.boxes,
                flip_x=True,
            )
        )

    for path in output_paths:
        print(path)
    print(f"routed_connections={len(waypoint_solutions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
