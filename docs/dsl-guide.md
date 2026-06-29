# Circuit Schematics

This package contains a small alignment-first DSL for drawing circuit
schematics with Schemdraw. It follows the same value-style layout feel as the
ShellForgePy geometry scripts in this repository: create nets, visual net
views, and elements; place the views and elements with `align`, `translate`,
and `rotate`; then render the resulting schema.

Use it for lightweight circuit diagrams, diagnostic stripboard projection
previews, and reusable electronics layout experiments. Connector pin maps and
harness views are out of scope for this package.

## Quick Start

```python
from pathlib import Path

from mege_circuits.simple import *


def create_voltage_divider():
    vcc_net = create_net("vcc")
    midpoint_net = create_net("midpoint")
    gnd_net = create_net("gnd")

    vcc = create_node(Dot, "vcc", net=vcc_net, label="+5V")
    midpoint = create_node(Dot, "midpoint", net=midpoint_net, label="OUT")
    gnd = create_node(Ground, "gnd", net=gnd_net)

    r1 = create_element(Resistor, "R1", "10K", vcc, midpoint)
    r2 = create_element(Resistor, "R2", "20K", midpoint, gnd)

    r1 = align(r1, vcc, Alignment.CENTER)
    r1 = align(r1, vcc, Alignment.STACK_BOTTOM)
    midpoint = align(midpoint, r1, Alignment.BOTTOM)

    r2 = align(r2, midpoint, Alignment.CENTER)
    r2 = align(r2, midpoint, Alignment.TOP)
    gnd = align(gnd, r2.end, Alignment.CENTER)
    gnd = align(gnd, r2, Alignment.BOTTOM)

    return create_schema([vcc, midpoint, gnd], [r1, r2])


schema = create_voltage_divider()
render_schemdraw(schema, file=Path("voltage_divider.svg"))
```

Use a `.png` filename instead of `.svg` to render a PNG preview:

```python
render_schemdraw(schema, file=Path("voltage_divider.png"))
```

## Semantic Netlist Export

A `Schema` can be lowered into a semantic `Circuit` and exported as a
deterministic structured netlist. This semantic model ignores drawing
coordinates and is the intended source for future stripboard planning work:

```python
schema = create_voltage_divider()

report = check_schema_erc(schema)
if not report.ok:
    raise ValueError(report.summary())

circuit = circuit_from_schema(schema, name="voltage_divider")
netlist = export_netlist(circuit)
```

The ERC report catches semantic errors such as duplicate component reference
designators, missing terminals, unknown nets, malformed wires, and unsupported
component types. Single-terminal nets are reported as warnings rather than
errors.

## Stripboard Renderer

The package also includes a small stripboard renderer for bare board
visualization. This is separate from schematic `Schema` rendering: it draws the
bare board, horizontal copper strips, and holes only. Components, strip cuts,
and net-aware placement are handled by the diagnostic overlay path below, not
by the bare board renderer.

```python
from pathlib import Path

from mege_circuits.simple import *


board = create_stripboard(24, 12)
render_stripboard(board, file=Path("stripboard.svg"))
render_stripboard(board, file=Path("stripboard.png"))
```

The first version renders horizontal stripboards. `strip_direction` is part of
the API shape for future vertical-strip support, but non-horizontal rendering
is not implemented yet.

## Schematic To Stripboard Projection

There is also a diagnostic bridge from a logical schematic to a stripboard
projection preview. This path is intentionally visualization-derived: it reads
the visible positions of every net in a `Schema`, sorts those nets by schematic
y coordinate, assigns one full horizontal strip to each net, then overlays
snapped node and terminal markers onto the hole grid. The board projection maps
the schematic top to the first stripboard row, so a bottom ground rail stays at
the bottom of the rendered stripboard. Horizontally, only columns with snapped
schematic node or terminal markers are kept; empty runs of holes between used
columns are removed.

Sparse rows can be compacted as a second pass. This keeps the initial
one-net-per-row assignment intact, then merges rows with few connections into
cut-separated runs on shared physical strips:

```python
assignment = assign_schema_nets_to_stripboard(schema)
assignment = compact_sparse_stripboard_rows(
    assignment,
    min_run_holes=4,
    max_connections_per_sparse_net=3,
    schema=schema,
)
```

Passing `schema=` makes sparse compaction opportunistic: each candidate
short run is kept only if strict component placement still succeeds. Without a
schema, the pass performs the pure geometric compaction and treats all nets
with up to three markers as sparse.

After component placement, physical rows can be permuted without changing any
hole columns. This is useful when solderability matters more than preserving
the schematic-like row order:

```python
assignment = compact_stripboard_connections_left(schema, assignment, strict=True)
assignment = permute_stripboard_rows_for_element_span(
    schema,
    assignment,
    priority_element_names=("Q1", "Q2", "Q3"),
)
```

This is a visual layout aid, not an autorouter or verified manufacturing plan.
It can show diagnostic strip cuts for compacted runs, avoid many marker/body
collisions, and produce useful build-thinking previews, but it does not yet
place real component footprints, route jumpers, extract physical connectivity,
or prove the board matches the intended circuit netlist.

```python
schema = create_voltage_divider()
assignment = assign_schema_nets_to_stripboard(schema)

render_stripboard_overlay(
    assignment.stripboard,
    assignment,
    schema,
    file=Path("voltage_divider_stripboard.svg"),
)
render_stripboard_overlay(
    assignment.stripboard,
    assignment,
    schema,
    file=Path("voltage_divider_stripboard.png"),
)
```

Rails are visible materializations of normal nodes. They are useful when many
connections should visibly share one supply or ground rail:

```python
v5 = create_net("v5")

vcc = create_node(Dot, "vcc", net=v5, label="+5V", label_alignment=Alignment.LEFT)
vcc = translate(0, 4)(vcc)
vcc = create_rail(vcc, Direction.VERTICAL, 8, anchor=Alignment.TOP)

pul_plus = create_node(Dot, "pul_plus", net=v5, label="PUL+")
pul_plus = translate(4, 1)(pul_plus)

feed = create_wire(vcc, pul_plus)
```

Use `point_at(...)` when an alignment should target a specific edge or endpoint
of an object:

```python
gnd = create_node(Ground, "gnd", label="GND", label_alignment=Alignment.RIGHT)
gnd = create_rail(gnd, Direction.VERTICAL, 8, anchor=Alignment.BOTTOM)
gnd = align(point_at(gnd, Alignment.TOP), point_at(vcc, Alignment.TOP), Alignment.CENTER)
```

Run an example from the repository root:

```bash
./run.sh examples/voltage_divider.py
```

The helper runs the script with the repository `src/` directory on
`PYTHONPATH`, finds the generated SVG next to the example, and opens it.

## Concepts

- Nets are logical electrical connections created with `create_net`.
- Node views are placed visual representations of nets created with
  `create_node`. If `net=` is omitted, a same-named net is created implicitly.
- Use `label_alignment=Alignment.LEFT/RIGHT/TOP/BOTTOM` when creating labeled
  nodes whose labels should face a specific way.
- Rails are created from node views with `create_rail`; connected terminals
  project onto the visible rail and render tap dots.
- Use `point_at(obj, Alignment.TOP/RIGHT/...)` to align from a specific side or
  endpoint while moving the original object.
- Elements are connected to node views with `create_element`; internally they
  store terminal view names and net names, not copies of the placed views.
- `create_wire(...)` draws a direct conductor between two views of the same net.
- Layout is explicit and copy-returning: `align(...)`, `translate(...)`, and
  `rotate(...)` return placed copies.
- Schemas group node views, elements, inferred nets, and wires with
  `create_schema`.
- `render_schemdraw` turns the schema into a Schemdraw-backed SVG or PNG based
  on the output filename extension.

Supported node types are `Dot` and `Ground`. Supported element types are
`Wire`, `Resistor`, `Fuse`, `Capacitor`, `PMos`, `BjtNpn`, and `Zener`.

See `ALIGNMENT_BASED_SCHEMDRAW.md` for the design notes behind the DSL.
