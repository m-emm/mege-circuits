# Alignment-Based Schemdraw Concept

## Situation

Schemdraw produces very nice schematic output, but its native placement model is
hard to keep under control once a drawing stops being a short linear circuit.
The official placement model is cursor-like: a drawing has a current position
and direction, and many element calls implicitly advance or modify that state.
That is convenient for tiny sketches, but it mixes three separate things:

- the circuit graph,
- the visual layout,
- the final Schemdraw backend calls.

The goal here is to graft a small ShellForgePy-style DSL on top of Schemdraw:
first define the circuit, then place immutable-ish objects with explicit
alignment operations, then let a renderer generate the Schemdraw calls.

Reference: Schemdraw placement documentation:
https://schemdraw.readthedocs.io/en/stable/usage/placement.html

## Core Direction

The design should copy the successful ShellForgePy semantics as closely as
possible:

```python
thing = create_some_thing()
thing = align(thing, other_thing, Alignment.CENTER)
thing = align(thing, other_thing, Alignment.STACK_BOTTOM)
thing = rotate(90)(thing)

result = merge(thing, other_thing)
```

No in-place layout mutation should be part of the public API. Objects are not
technically frozen or complexly immutable, but user code should treat them as
values. Transformations return moved or rotated copies. This is the core
debugging advantage:

- one line creates a new placement,
- previous values remain valid,
- subcircuits can be turned into schemas and aligned later,
- changing one alignment line changes one returned object,
- there is no hidden global cursor and no hidden layout state.

For circuit schematics, we do not fuse solids. Instead we merge schematic
objects and subcircuits. Merging preserves the circuit graph and combines the
visual objects that will later be rendered.

## Terminology

Use **node** in the public API:

```python
gnd = create_node(Ground, "gnd")
vcc = create_node(Dot, "vcc")
midpoint = create_node(Dot, "MP")
```

The word **net** is standard EDA/netlist/SPICE terminology for an electrical
node, so it may appear in internals, export formats, or documentation about
netlists. But for this DSL, `create_node(...)` is clearer and should be
the user-facing concept.

## Non-Goals For The First Prototype

- No global constraint solver.
- No automatic placement of components.
- No full PCB-style autorouter.
- No user-facing wire DSL unless a real need appears.
- No in-place `align(...)`, `rotate(...)`, or `translate(...)`.
- No dependence on Schemdraw's drawing cursor for user layout code.

Automatic connection drawing is allowed, but it must be deterministic and based
on the graph plus already placed objects. It must not move elements.

## Architecture Overview

The DSL can live under:

```text
examples/
```

Suggested split:

```text
mege_circuits/
    simple.py             # import surface for design scripts
    dsl.py                # current compact implementation module
    graph.py              # Node, CircuitElement, node/terminal graph helpers
    geometry.py           # plain point/bounding-box helpers
    alignment.py          # Alignment enum, translate, rotate, align
    elements.py           # create_element and optional thin element helpers
    node_visuals.py       # create_node, create_rail, optional ground helpers
    schematic.py          # SchematicGroup, create_schema, merge
    render.py             # automatic connection materialization and Schemdraw export
    examples/
        voltage_divider.py
        motor_power_switch.py
```

The layers:

```text
Circuit graph
    Nodes and Schemdraw-named elements connected by terminals.

Value-like layout objects
    Elements, nodes, rails, grounds, and schematic groups with placement data
    and terminals.

Pure transformations
    translate(...)(obj), rotate(...)(obj), align(obj_or_anchor, target, ...).

Connection materialization
    Render-time generation of lines, dots, and rail taps from graph connectivity.

Schemdraw backend
    Absolute Schemdraw calls, SVG/PDF/PNG export.
```

## Public Import Surface

ShellForgePy's `simple.py` is a major usability win. This project should copy
that pattern. A design script should start like this:

```python
from mege_circuits.simple import *
```

and then have everything needed for normal work:

- `create_node`
- `create_element`
- `create_schema`
- `merge`
- `align`
- `translate`
- `rotate`
- `Alignment`
- `Direction`
- `render_schemdraw`
- supported DSL type names such as `Dot`, `Ground`, `Resistor`

The lower-level modules can stay tidy internally, but normal design scripts
should not need a long import block.

`Dot`, `Ground`, and `Resistor` should not be Schemdraw classes in user code.
They should be backend-independent DSL constants, with Schemdraw classes used
only inside the renderer.

## Geometry Data

Do not introduce user-facing point, bounding-box, pose, or anchor classes.

For input data:

- points are lists, tuples, or NumPy arrays of length 2,
- bounding boxes use the ShellForgePy-style nested form
  `[[xmin, ymin], [xmax, ymax]]`,
- rotations and translations are stored inside schematic objects, but the user
  does not need to construct a pose object,
- terminals and anchors can be exposed as attributes such as `r1.start` or
  `q1.base`, but their implementation should stay an internal detail.

This keeps the DSL small and familiar. If helper classes are useful internally,
they should not leak into examples or concept-level API.

## Circuit Graph Model

### Nodes

A node is an electrical connection point that can connect any number of
terminals.

```python
gnd = create_node(Ground, "gnd")
vcc = create_node(Dot, "vcc", label="+5V")
midpoint = create_node(Dot, "MP")
output = create_node(Dot, "OUT")
```

Node data should stay small:

```python
Node(
    name="vcc",
    label="+5V",
    kind="power",
)
```

Useful metadata:

- `name`: stable identifier.
- `label`: optional display label.
- `kind`: optional hint such as `power`, `ground`, `signal`, `internal`.

The node does not choose its drawing position. A node can later be materialized
as a point, a rail, a ground symbol, or just an implicit connection.

The central constructor should be:

```python
node = create_node(node_type, name, label=None, kind=None, **kwargs)
```

For the first implementation slice, `node_type` should support only:

- `Dot`
- `Ground`

Later, rails can either become a third node type or stay as a wrapper:
`rail = create_rail(node, Direction.HORIZONTAL, length=...)`.

### Elements

Element names should follow Schemdraw names wherever possible. If Schemdraw has
`elm.Resistor`, the DSL should expose `Resistor` through `simple.py` and accept
it directly in `create_element(...)`, not invent a separate vocabulary that must
be looked up again. The exported `Resistor` itself should still be a DSL
constant, not `elm.Resistor`.

That means the user can search Schemdraw docs/classes for:

- what the symbol is called,
- what it looks like,
- which anchors/terminals it has.

Two examples:

```python
r1 = create_element(Resistor, "R1", "10K", vcc, midpoint)
r2 = create_element(Resistor, "R2", "20K", midpoint, gnd)
```

```python
q1 = create_element(
    BjtNpn,
    "Q1",
    "BC107B",
    base=midpoint,
    emitter=gnd,
    collector=output,
)
```

The terminal names should also match Schemdraw anchors where that is sensible,
but only when naming terminals adds clarity:

- two-terminal elements: pass nodes positionally in the common case,
- explicit two-terminal anchors such as `start` and `end` may still exist for
  direct alignment or advanced construction,
- BJT: `base`, `collector`, `emitter`,
- MOSFET: `gate`, `source`, `drain`,
- ICs: pin names following the Schemdraw `Ic` anchor names.

The generic fallback should be possible:

```python
r = create_element(
    Resistor,
    name="R1",
    value="10K",
    terminals={"start": vcc, "end": midpoint},
)
```

The central constructor should be:

```python
element = create_element(element_type, name, value=None, *nodes, **terminal_nodes)
```

For the first implementation slice, `element_type` should support only:

- `Resistor`

For `Resistor`, the first iteration should use `*nodes`:

```python
r1 = create_element(Resistor, "R1", "10K", vcc, midpoint)
```

Named helpers such as `create_Resistor(...)` or `create_BjtNpn(...)` can be
added later if they remain thin convenience wrappers. They are not needed for
the first slice.

### Graph Invariants

- Node names are unique within a schematic.
- Element names are unique within a schematic.
- Terminal names are unique within an element.
- Every element terminal connects to exactly one node.
- Multiple elements may connect the same pair of nodes.
- Lines are not part of the graph. Lines are generated from graph connectivity
  and layout during rendering.

## Canonical Orientation

Each element has a canonical initial orientation chosen by this DSL, not by
Schemdraw's cursor defaults.

Initial convention:

- two-terminal elements are vertical,
- `start` is at the top,
- `end` is at the bottom,
- NPN/PNP transistors have `base` on the left, `collector` at the top, and
  `emitter` at the bottom,
- MOSFETs have `gate` on the left, with `source` and `drain` vertically placed
  according to the symbol convention,
- rails are horizontal or vertical depending on the requested direction.

Rotation is a pure transformation, just like ShellForgePy:

```python
r1 = rotate(90)(r1)
q1 = rotate(270)(q1)
```

No `.orient(...)` method is needed for normal use. If a convenience method is
added later, it should still return a copy.

## Transformations

Transformations are functional. They return transformation functions that return
moved copies:

```python
r1 = translate(2.0, 0.0)(r1)
r1 = rotate(90)(r1)
```

Alignment is also pure:

```python
r1 = align(r1, vcc, Alignment.STACK_BOTTOM)
r1 = align(r1, midpoint, Alignment.CENTER, axes=["x"])
```

When the first argument is an anchor or terminal reference, `align(...)` returns
a moved copy of the owner of that reference:

```python
q1 = align(q1.base, midpoint, Alignment.CENTER)
q1 = align(q1.base, midpoint, Alignment.STACK_RIGHT, stack_gap=2.0)
```

This mirrors `aligned_from_follower(...)` in ShellForgePy, but keeps the call
site compact. The important rule:

```python
q1 = align(q1.base, midpoint, Alignment.CENTER)
```

returns a moved `q1`. It does not mutate the old `q1`, the `base` anchor, or
`midpoint`.

For repeated movement of a group, keep the lower-level translation API:

```python
move = align_translation(q1.base, midpoint, Alignment.STACK_RIGHT, stack_gap=2.0)
q1 = move(q1)
label = move(label)
```

## Alignment Values

Use a 2D version of the ShellForgePy vocabulary:

```python
class Alignment(Enum):
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()
    CENTER = auto()

    STACK_LEFT = auto()
    STACK_RIGHT = auto()
    STACK_TOP = auto()
    STACK_BOTTOM = auto()
```

Semantics:

- `CENTER`: align centers in both axes, unless `axes` restricts it.
- `LEFT`, `RIGHT`, `TOP`, `BOTTOM`: make corresponding box edges coincide.
- `STACK_*`: put the moving object outside the target in that direction.

For point-like nodes and terminals, `CENTER` means "same point". If both
references are points, `STACK_RIGHT` means "same y coordinate, shifted right by
`stack_gap`".

Axis restrictions should initially be supported only for `CENTER`:

```python
r1 = align(r1, midpoint, Alignment.CENTER, axes=["x"])
```

## Nodes As Visual Objects

A node starts as graph data:

```python
gnd = create_node(Ground, "gnd")
vcc = create_node(Dot, "vcc")
```

It can later be turned into a simple visual node object. The first iteration
should support only `Dot` and `Ground`. The next visual forms to add are:

- point node / dot node,
- horizontal or vertical rail,
- optional ground symbol wrapper.

Avoid a larger `BusGlyph`/`RailGlyph` hierarchy for now. A rail is enough.

### Point Nodes

A plain node can be positioned as a point:

```python
midpoint = align(midpoint, r1, Alignment.STACK_BOTTOM)
```

If it has multiple connections, the renderer can draw a junction dot at the
point. If it has only two connections, a dot is optional and can be omitted by
style.

### Rails

Rails are the one intentionally line-like node materialization:

```python
gnd = create_rail(gnd, Direction.HORIZONTAL, length=5.0)
vcc = create_rail(vcc, Direction.HORIZONTAL, length=5.0)

gnd = align(gnd, vcc, Alignment.STACK_BOTTOM, stack_gap=3.0)
```

A rail is still one node. It has a line segment for rendering and a bounding box
for alignment. Connected terminals project to the rail during rendering; the
renderer adds a dot/tap and an orthogonal connection line.

Rules:

- horizontal rail: terminals connect by vertical drops/rises where possible,
- vertical rail: terminals connect by horizontal runs where possible,
- the rail itself does not create multiple graph nodes,
- all connected terminals remain connected to the same node.

### Ground Symbols

Schemdraw 0.22 exposes `Ground`, `GroundSignal`, and `GroundChassis`, each with
a `lead` option. For the first iteration, ground should be just another node
type:

```python
gnd = create_node(Ground, "gnd")
gnd = align(gnd, r2.end, Alignment.CENTER)
gnd = align(gnd, r2, Alignment.STACK_BOTTOM)
```

This should not become a separate graph concept. It is just a way to draw a
node. Later, `GroundSignal` and `GroundChassis` can be accepted as additional
`node_type` values if they are useful.

## Automatic Connection Rendering

The user should usually not write wires. The graph already knows what is
connected. The layout already knows where terminals and nodes are. Rendering can
materialize the necessary lines.

Render-time connection algorithm:

1. For each node, collect all connected element terminals.
2. Also collect any visual materialization of the node: point, rail, or ground.
3. If two connected terminals occupy the same point, draw no line between them.
4. If exactly two terminals are connected and there is no explicit node visual,
   draw one deterministic connection line between them.
5. If a point node exists, connect every non-coincident terminal to that point.
6. If a rail exists, project each terminal onto the rail, draw a dot/tap there,
   then draw an orthogonal line from the terminal to the tap.
7. If a ground symbol exists, connect terminals to the ground symbol's connection
   anchor.
8. If a node has three or more terminals and no visual node/rail/ground, raise a
   validation error or warning. Explicit fanout should stay explicit.

The renderer can choose simple deterministic routing:

- same x or same y: direct line,
- terminal to horizontal rail: vertical line,
- terminal to vertical rail: horizontal line,
- terminal to point node: direct if axis-aligned, otherwise simple orthogonal
  route using a stable default order.

Manual route objects can be an escape hatch later, but they should not be the
core DSL. The first version should prove how far automatic line materialization
gets from the graph.

## Schema Creation And Merge

Like ShellForgePy assemblies, circuits should be composable.

```python
divider = create_schema([r1, r2])
amplifier = create_schema([q1])

schema = merge(divider, amplifier)
schema = align(schema, None, Alignment.CENTER)
```

`create_schema(...)` returns a schematic group with:

- child objects,
- a combined bounding box,
- graph membership,
- named children for access if useful.

Nodes referenced by elements are included automatically. Nodes that are not
connected to any element are ignored; they cannot affect the circuit or the
rendered result.

`merge(a, b)` combines two groups or objects. It should not mutate either input.

Node identity controls electrical identity:

- if two elements refer to the same `Node` object, they are electrically joined,
- if two separately created nodes have the same name, merging should reject the
  collision unless explicitly told they are the same node,
- if two node visuals represent the same node, validation should decide whether
  that is allowed or whether it makes the drawing ambiguous.

## Proposed User-Facing API Sketch

The first useful script should be a full stacked voltage divider, not a partial
framework demo. It should create outside terminals/nodes, create two resistors,
place them with `align(...)`, create the schema, and export SVG.

```python
from mege_circuits.simple import *


def create_voltage_divider():
    vcc = create_node(Dot, "vcc", label="+5V")
    midpoint = create_node(Dot, "midpoint", label="OUT")
    gnd = create_node(Ground, "gnd")

    r1 = create_element(Resistor, "R1", "10K", vcc, midpoint)
    r2 = create_element(Resistor, "R2", "20K", midpoint, gnd)

    r1 = align(r1, vcc, Alignment.CENTER)
    r1 = align(r1, vcc, Alignment.STACK_BOTTOM)

    midpoint = align(midpoint, r1, Alignment.BOTTOM)

    r2 = align(r2, midpoint, Alignment.CENTER)
    r2 = align(r2, midpoint, Alignment.TOP)

    gnd = align(gnd, r2.end, Alignment.CENTER)
    gnd = align(gnd, r2, Alignment.BOTTOM)

    return create_schema([r1, r2])


if __name__ == "__main__":
    schema = create_voltage_divider()
    render_schemdraw(schema, file="voltage_divider.svg")
```

Important points in this sketch:

- The import is compact because `simple.py` exposes the normal design surface.
- Nodes are created first.
- Elements connect to nodes at creation time.
- Layout is a sequence of pure `align(...)` calls.
- Nodes used by elements are included in the schema automatically.
- Unused nodes are ignored.
- There is no user-facing wire list.
- The renderer adds the lines from graph connectivity.

Later, the same generic style should work for more Schemdraw element types:

```python
z1 = create_element(
    Zener,
    name="D1",
    value="12V",
    terminals={"start": gate, "end": vcc},
)

z1 = rotate(180)(z1)
z1 = align(z1, r1, Alignment.STACK_LEFT, stack_gap=0.8)
```

## Backend Strategy

The Schemdraw backend should receive an already placed schematic group. It then
emits absolute Schemdraw calls.

For two-terminal elements, rendering can usually use endpoints:

```python
elm.Resistor().endpoints(r1.start.point(), r1.end.point()).label("R1\n10K")
```

For multi-terminal elements, use a stable Schemdraw anchor:

```python
elm.BjtNpn().anchor("base").at(q1.base.point()).label("Q1\nBC107B")
```

For rails and generated connections:

```python
elm.Line().endpoints(a, b)
elm.Dot().at(tap)
elm.Ground().at(anchor)
```

The renderer may use Schemdraw methods internally, but user code should not
depend on `d.here`, `hold()`, or implicit cursor placement.

## Validation

Validation should be opinionated because this DSL is meant to prevent layout
surprises.

Graph validation:

- duplicate node names,
- duplicate element names,
- unknown terminal names,
- terminals connected to missing nodes,
- element wrapper terminal names that do not match the known Schemdraw anchors,
- accidental same-name nodes during merge.

Layout validation:

- objects still at the origin unless marked as intentionally unplaced,
- fanout nodes with no point/rail/ground visual,
- generated connection lines whose route would be ambiguous,
- multiple visual materializations of one node,
- overlapping element bounding boxes, warning-only at first.

Render validation:

- all element anchors needed by the backend exist,
- generated lines have finite endpoints,
- every graph terminal is represented by a rendered symbol anchor,
- SVG export succeeds.

Useful debug output:

```python
schema.dump_nodes()
schema.dump_elements()
schema.render_debug_svg("debug.svg", show_bboxes=True, show_anchor_names=True)
```

## Testing Concept

Transformation tests:

- `translate(...)(obj)` returns a moved copy and leaves the original unchanged.
- `rotate(90)(obj)` rotates anchors and bounding boxes around the object center.
- `CENTER` aligns two boxes.
- `CENTER` aligns two point nodes.
- `STACK_BOTTOM` with two points shifts exactly by `stack_gap`.
- `align(q1.base, midpoint, ...)` returns a moved `q1`.
- `align_translation(...)` can move a group consistently.

Graph tests:

- voltage divider node graph.
- BJT with `base`, `collector`, `emitter`.
- MOSFET with `gate`, `source`, `drain`.
- multiple elements between the same two nodes.
- duplicate node names rejected on merge.

Connection generation tests:

- two terminals on one node generate one line.
- terminal to horizontal rail generates one vertical line plus dot.
- terminal to vertical rail generates one horizontal line plus dot.
- three terminals without a visual node produce a validation error.
- ground symbol connects through its anchor.

Backend tests:

- minimal voltage divider exports SVG.
- transistor example exports SVG.
- high-side PMOS/NPN switch exports SVG.
- rendering the same schematic twice is stable.

## Implementation Iterations

### Iteration 1: Minimal Resistor Voltage Divider

Implement:

- a minimal `simple.py`
- one minimal implementation module behind it; the earlier module split can wait
- plain point helpers accepting tuples, lists, or NumPy arrays of length 2
- plain bounding-box helpers using `[[xmin, ymin], [xmax, ymax]]`
- `Alignment`
- `translate`
- `rotate`
- `align_translation`
- `align`
- `create_node(node_type, ...)`
- `create_element(element_type, ...)`
- only these node types:
  - `Dot`
  - `Ground`
- only this element type:
  - `Resistor`
- automatic connection rendering for the simple vertical chain
- SVG export from the design script

Deliverable: one runnable Python design file, probably
`examples/voltage_divider.py`, that does the whole stack:

```python
from mege_circuits.simple import *


def main():
    vcc = create_node(Dot, "vcc", label="+5V")
    midpoint = create_node(Dot, "midpoint", label="OUT")
    gnd = create_node(Ground, "gnd")

    r1 = create_element(Resistor, "R1", "10K", vcc, midpoint)
    r2 = create_element(Resistor, "R2", "20K", midpoint, gnd)

    r1 = align(r1, vcc, Alignment.CENTER)
    r1 = align(r1, vcc, Alignment.STACK_BOTTOM)
    midpoint = align(midpoint, r1, Alignment.BOTTOM)

    r2 = align(r2, midpoint, Alignment.CENTER)
    r2 = align(r2, midpoint, Alignment.TOP)
    gnd = align(gnd, r2.end, Alignment.CENTER)
    gnd = align(gnd, r2, Alignment.BOTTOM)

    schema = create_schema([r1, r2])
    render_schemdraw(schema, file="voltage_divider.svg")


if __name__ == "__main__":
    main()
```

This first iteration is intentionally narrow. It should prove the important
rhythm before adding more symbols.

### Iteration 2: Tests And Copy Semantics

Add tests for:

- `translate(...)(obj)` returns a moved copy and leaves the original unchanged,
- `rotate(90)(obj)` returns a rotated copy,
- `align(...)` returns a moved copy,
- points can be tuples, lists, or NumPy arrays,
- bounding boxes use the nested ShellForgePy-style array form,
- the voltage divider SVG can be generated.

### Iteration 3: More Schemdraw Element Types

Add more `create_element(...)` support while keeping Schemdraw names:

- `Capacitor`
- `Zener`
- `Fuse`
- `BjtNpn`
- `PMos`

Deliverable: a transistor example that still reads like the voltage divider:
nodes first, elements second, pure alignment calls third.

### Iteration 4: Rails, Groups, And Merge

Implement:

- `create_rail`
- `create_schema`
- `merge`
- group-level bounding boxes and transformations.

Deliverable: create and align the voltage divider/transistor example.

### Iteration 5: Automatic Connection Materialization

Implement render-time generated lines for:

- two-terminal node connections,
- point-node fanout,
- horizontal rail taps,
- vertical rail taps,
- optional ground symbol anchors.

Deliverable: debug SVG showing generated wires, dots, anchors, and boxes.

### Iteration 6: Schemdraw Rendering

Implement:

- absolute rendering of Schemdraw elements,
- labels,
- generated `Line` and `Dot` calls,
- optional `Ground`, `GroundSignal`, and `GroundChassis`,
- SVG export.

Deliverable: clean Schemdraw SVG for the voltage divider/transistor example.

### Iteration 7: Motor Power Switch Regression

Rebuild a representative motor-power switch notebook as a regression example.

Success criteria:

- no user-facing `d.here`,
- no user-facing `hold()`,
- no hand-written wire list for ordinary node connections,
- components created using Schemdraw-derived names,
- layout reads like ShellForgePy:
  `thing = create_thing(); thing = align(thing, other, ...)`.

## Open Questions

- How should the generic `create_element(elm.SomeClass, ...)` discover anchors:
  from a hand-maintained catalog, from Schemdraw's `anchors` dictionary, or from
  both?
- What is the best default orthogonal route from terminal to point node when the
  points are not axis-aligned?
- Should stack distances be raw Schemdraw units only, or should helper constants
  like `RESISTOR_HEIGHT` make examples read as "three resistor heights"?
- Should `merge(...)` automatically coalesce same-name nodes when they are not
  the same object, or should it always require an explicit node alias operation?
- Is a manual route escape hatch needed immediately, or can the first slice
  stay graph-driven?

## Design Boundary

The short version:

```text
Create nodes first.
Create Schemdraw-named elements connected to those nodes.
Move copies with align/rotate/translate.
Merge into subcircuits.
Generate lines automatically from the graph.
Use Schemdraw only at the end.
```
