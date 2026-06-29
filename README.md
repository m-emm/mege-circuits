# mege-circuits

`mege-circuits` is an alignment-first Python DSL for drawing small circuit
schematics and projecting them onto stripboard-style physical layout previews.

It grew out of the Ender 3 V3 KE IDEX wiring work, but is now a standalone
project for reusable circuit drawing, stripboard visualization, and experiments
around hand-buildable electronics layouts.

Status: early open-source extraction. The public API is useful, tested, and
still expected to change as the stripboard planner matures.

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

Those scripts render both schematic and stripboard preview artifacts next to the
example by default. The test suite renders them into temporary directories.

## Documentation

- [DSL guide](docs/dsl-guide.md)
- [Alignment notes](docs/alignment-based-schemdraw.md)
- [Stripboard layout engine blueprint](docs/blueprint.md)

The blueprint is a draft expansion document and intentionally moved here mostly
as-is; it will be revised as the standalone project grows.

## Development

```bash
pip install -e ".[testing]"
python -m pytest
```

CI runs the test suite on Python 3.11 and 3.12.

## License

MIT. See [LICENSE.txt](LICENSE.txt).
