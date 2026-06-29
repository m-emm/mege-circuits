# mege-circuits

`mege-circuits` is an alignment-first Python DSL for drawing small circuit
schematics and projecting them onto diagnostic stripboard-style layout previews.

It grew out of the Ender 3 V3 KE IDEX wiring work, but is now a standalone
project for reusable circuit drawing, stripboard visualization, and experiments
around hand-buildable electronics layouts.

Status: early open-source extraction. The schematic API and current
schematic-to-stripboard projection are useful and tested, but the projection is
not yet a verified stripboard router or manufacturing plan.

## Install

```bash
git clone git@github.com:m-emm/mege-circuits.git
cd mege-circuits
pip install -e ".[testing]"
```

## Quick Start

```python
from pathlib import Path

from mege_circuits.simple import *


vcc_net = create_net("vcc")
out_net = create_net("out")
gnd_net = create_net("gnd")

vcc = create_node(Dot, "vcc", net=vcc_net, label="+5V")
out = create_node(Dot, "out", net=out_net, label="OUT")
gnd = create_node(Ground, "gnd", net=gnd_net)

r1 = create_element(Resistor, "R1", "10K", vcc, out)
r2 = create_element(Resistor, "R2", "20K", out, gnd)

r1 = align(r1, vcc, Alignment.STACK_BOTTOM)
out = align(out, r1, Alignment.BOTTOM)
r2 = align(r2, out, Alignment.STACK_BOTTOM)
gnd = align(gnd, r2.end, Alignment.CENTER)

schema = create_schema([vcc, out, gnd], [r1, r2])
render_schemdraw(schema, file=Path("voltage_divider.svg"))
```

Use a `.png` filename to render a PNG preview.

## Examples

Run the small schematic examples from the repository root:

```bash
python examples/voltage_divider.py
python examples/stripboard_blank.py
```

The main real-world integration example is the Pico-to-TB6600 stripboard
interface:

```bash
python examples/integration/tb6600_stripboard_interface.py
python examples/integration/tb6600_stripboard_layout.py
```

Those scripts render both schematic and diagnostic stripboard projection
artifacts next to the example by default. The test suite renders them into
`examples/integration/diagrams/` as gitignored SVG/PNG files so the latest
integration output is easy to inspect after changes. Each render uses a unique
timestamped filename to avoid local preview caches; stable filenames in that
directory are symlinks to the newest generated artifacts.

## Documentation

- [DSL guide](docs/dsl-guide.md)
- [Alignment notes](docs/alignment-based-schemdraw.md)
- [Stripboard planning blueprint](docs/blueprint.md)

The blueprint describes how the current projection path should evolve into a
netlist-driven, verified stripboard planner while keeping the visualization
engine.

## Development

```bash
pip install -e ".[testing]"
python -m pytest
```

Slow integration and optimizer regressions are skipped by default. Run them
explicitly when changing the stripboard router or generated TB6600 artifacts:

```bash
python -m pytest --runslow
python -m pytest --runslow -m slow
```

CI runs the test suite on Python 3.11 and 3.12.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
