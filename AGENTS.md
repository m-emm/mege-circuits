# Agent Orientation

This repository (`mege-circuits`) hosts an alignment-first Python DSL for small
circuit schematics and diagnostic stripboard projection previews. It grew out of
the Ender 3 V3 KE IDEX wiring work and is now a standalone package for reusable
schematic drawing, stripboard visualization, and experiments toward verified
hand-buildable electronics layouts.

## Code Style

- The codebase targets Python 3.11 and 3.12. Follow the existing conventions:
  Black (line length 88), isort, and flake8 are the canonical local checks.
- Prefer descriptive names over comments. Add docstrings for public DSL
  functions, render entry points, and transitional APIs where the behavior could
  be mistaken for something more complete than it is.
- Keep the implementation dependency-light. Schemdraw, matplotlib, and Pillow
  are rendering dependencies; future routing, netlist, and verification layers
  should not be entangled with renderer internals.
- Use concrete absolute imports inside this repository. Import the real module
  that defines the symbol, for example `from mege_circuits.dsl import ...`.
- Do not use relative imports inside this repository.
- Do not use `__init__.py` files to create broad package-level shortcut APIs.
  Keep `mege_circuits.simple` as the only convenience facade for the public API.
- Keep the three truths separate:
  - semantic circuit truth: nets, components, terminals, values;
  - physical stripboard truth: holes, strips, cuts, jumpers, footprints;
  - presentation truth: schematic drawings and human-facing SVG/PNG previews.

## Testing

- Prefer proper pytest tests under `tests/`; avoid ad-hoc debug scripts.
- Run `python -m pytest` from the repo root before sending behavioral changes.
- Run `./precommit.sh` before committing. It is intentionally fast: it formats
  Python files and runs focused flake8 checks, but it does not run the full test
  suite.
- When changing render behavior, inspect the generated integration diagrams in
  `examples/integration/diagrams/` after running the relevant example or test.
  This directory is gitignored.
- Generated SVG/PNG paths use timestamped filenames plus stable symlinks. When
  sharing image references in Codex chat, prefer the timestamped files because
  stable image paths can be cached by the editor/chat integration.

## Repository Layout

- `src/mege_circuits/`
  - `dsl.py`: core alignment-first schematic DSL, stripboard projection model,
    renderers, and current projection heuristics.
  - `simple.py`: convenience facade for scripts and examples.
- `examples/`
  - small schematic examples and the TB6600 integration projection.
  - generated SVG/PNG files are reproducible and ignored.
- `examples/integration/diagrams/`
  - generated current-state schematic and stripboard projection artifacts.
  - ignored as a directory; examples/tests recreate it when needed.
- `docs/`
  - `dsl-guide.md`: user-facing DSL and projection guide.
  - `alignment-based-schemdraw.md`: design notes for the alignment DSL.
  - `blueprint.md`: evolution plan toward netlist-driven verified stripboard
    planning.
- `tests/`
  - pytest coverage for the DSL, renderers, projection heuristics, and the
    TB6600 integration artifacts.

## Environment Notes

- Do not create a virtual environment in this repository. Use the pyenv-managed
  Python environment selected by the local `.python-version` file.
- Install/update development dependencies in that pyenv environment with
  `pip install -e ".[testing]"`.
- The package runtime depends on Schemdraw, matplotlib, and Pillow.
- `precommit.sh` is a convenience script, not a replacement for CI or pytest.

## Common Tasks

- Run tests: `python -m pytest`
- Run fast precommit checks: `./precommit.sh`
- Render the voltage divider example: `python examples/voltage_divider.py`
- Render a blank stripboard: `python examples/stripboard_blank.py`
- Render the TB6600 schematic and projection:
  - `python examples/integration/tb6600_stripboard_interface.py`
  - `python examples/integration/tb6600_stripboard_layout.py`


## Integration Points

- This package is consumed by Ender 3 V3 KE IDEX wiring work. Keep the TB6600
  example and generated integration artifacts useful for review.
- The DSL intentionally feels similar to ShellForgePy scripts: create values,
  transform copies with `align`, `translate`, and `rotate`, then render.
- `mege_circuits.simple` is the public import surface. Surface new public DSL or
  rendering helpers there deliberately, and avoid leaking private helpers unless
  they are intended for scripts.

Keep this guide current as `mege-circuits` evolves from diagnostic projection
toward verified stripboard planning.
