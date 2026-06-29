# mege-circuits: Stripboard Planning Blueprint

Status: evolution blueprint  
Target project: `mege-circuits`  
Primary goal: evolve the current schematic-to-stripboard projection into a
verified stripboard planner without losing the already useful visualization
engine.

`mege-circuits` is not starting from zero. The current code already has a good
alignment-first schematic DSL, a Schemdraw renderer, a bare stripboard renderer,
and a surprisingly capable diagnostic stripboard overlay. What is still
half-baked is the electrical planning model underneath the stripboard view:
today's layout is derived from schematic drawing positions and row compaction,
not from an explicit circuit netlist routed onto a physical board.

This document describes how to move from the current implementation to the
cleaner target:

```text
alignment-first schematic DSL
    -> canonical circuit netlist
    -> footprinted stripboard problem
    -> placement and stripboard routing
    -> physical netlist extraction and verification
    -> solder-ready SVG/PNG views and build checklist
```

The visual output remains a first-class product. The goal is not to replace the
renderer with a PCB toolchain; it is to feed that renderer better, verified
physical data.

## Current Reality

The public API is concentrated in `mege_circuits.simple`, which re-exports the
objects and functions implemented in `src/mege_circuits/dsl.py`.

Today the useful schematic model is:

```text
Net
NodeView
Element
WireSegment
Schema
```

Important current behavior:

```text
- `create_net` creates logical nets.
- `create_node` creates placed visual views of nets.
- `create_rail` turns a node view into a visible rail.
- `create_element` creates components whose terminals store both view names
  and net names.
- `create_wire` draws explicit same-net visual conductors.
- `create_schema` validates node views, elements, wires, and inferred nets.
- `render_schemdraw` renders the schematic with Schemdraw.
```

The current stripboard model is a projection/visualization model:

```text
Stripboard
SchemaNetVisualization
SchemaTerminalVisualization
StripboardNetAssignment
StripboardNetRun
StripboardCut
StripboardLocalPoint
StripboardBlocker
```

The current stripboard workflow, as used by
`examples/integration/tb6600_stripboard_layout.py`, is:

```python
schema = create_schema_for_tb6600_interface()
assignment = assign_schema_nets_to_stripboard(schema)
assignment = compact_sparse_stripboard_rows(assignment, schema=schema)
assignment = compact_stripboard_connections_left(schema, assignment, strict=True)
assignment = permute_stripboard_rows_for_element_span(
    schema,
    assignment,
    priority_element_names=("Q1", "Q2", "Q3"),
)
render_stripboard_overlay(assignment.stripboard, assignment, schema, file=...)
```

That workflow is useful and tested. It can:

```text
- group schematic markers by net,
- assign nets to stripboard rows,
- compact sparse nets into cut-separated runs,
- place terminal and node markers on distinct holes,
- avoid component-body blockers,
- reduce important component row spans by permuting rows,
- render SVG and PNG stripboard overlays,
- render cuts, run blocks, terminal dots, node dots, element body segments,
  net labels, component labels, and terminal labels,
- avoid many label collisions.
```

What it does not yet do:

```text
- export a canonical semantic circuit netlist,
- assign real through-hole footprints,
- represent component pins as footprinted physical pins,
- route nets over actual strip segments and jumpers,
- extract the physical conductor graph from the planned board,
- prove that the physical layout matches the intended circuit,
- produce authoritative solder-side cut and jumper instructions.
```

So the current stripboard output should be described as a projection preview,
not as a verified manufacturing plan.

## Design Principles

### Preserve The Three Truths

The project should keep three different kinds of truth separate:

```text
Semantic truth:
    The intended circuit: components, terminals, nets, values, labels.

Physical truth:
    The buildable stripboard implementation: holes, strips, cuts, jumpers,
    component pins, blockers, and solder points.

Presentation truth:
    Human-facing schematic and stripboard drawings.
```

The long-term invariant is:

```text
extract_physical_netlist(layout) == export_circuit_netlist(circuit)
```

The router may be heuristic. The verifier must be independent and strict.

### Keep The Existing DSL As The Authoring Layer

The alignment-first DSL is valuable. Users should still write circuits using
`create_net`, `create_node`, `create_element`, `align`, `translate`, `rotate`,
`create_schema`, and `render_schemdraw`.

The change is that `Schema` should lower into an explicit `Circuit` or
`Netlist` before stripboard planning begins. Schematic coordinates may become
placement hints, but they must not be the electrical source of truth for the
router.

### Keep The Visualization Engine

The current stripboard renderer is worth keeping. Its strengths are exactly the
parts that remain useful after routing improves:

```text
- clean board, strip, and hole rendering,
- SVG data attributes for inspection,
- top-side schematic overlays,
- compact run and cut visualization,
- component body segment drawing,
- terminal and node labels,
- collision-aware label placement,
- PNG fallback through Pillow.
```

The renderer should be refactored toward a stable render input model, not thrown
away. Existing `StripboardNetAssignment` rendering can remain as a legacy or
diagnostic adapter while the future `PhysicalLayout` renderer comes online.

### Grid First, Millimetres Late

All stripboard planning should use integer grid coordinates:

```text
row = 0 at the top of the rendered top view
col = 0 at the left of the rendered top view
pitch = 2.54 mm by default
horizontal stripboard = copper strips run along rows
```

Only renderers and exporters should convert grid coordinates into SVG units,
pixels, or millimetres.

### Make Verification Boring Before Routing Gets Clever

Routing can begin simple:

```text
- one-sided stripboard,
- horizontal copper strips,
- cuts at holes,
- top-side insulated jumpers,
- through-hole component pins,
- no diagonal bare-wire electrical interaction,
- no arbitrary PCB-like copper.
```

The physical extraction and verification model should be correct before the
router becomes ambitious.

## Target Internal Model

The current `Schema` should remain a presentation-friendly authoring object.
The planner should add a canonical semantic model beside it.

### Semantic Model

Recommended starting objects:

```python
@dataclass(frozen=True)
class Circuit:
    name: str
    components: tuple[Component, ...]
    nets: tuple[Net, ...]


@dataclass(frozen=True)
class Component:
    refdes: str
    kind: str
    value: str | None
    terminals: tuple[Terminal, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Terminal:
    name: str
    net_name: str
```

This model can be produced from today's `Schema` without changing user code:

```text
Schema.elements -> Component records
Element.name -> refdes
Element.element_type -> kind
Element.value -> value
Element.terminal_nets -> terminals
Schema.nets -> nets
NodeView labels and positions -> optional presentation/placement hints
WireSegment -> validation and presentation, not extra electrical truth
```

`NodeView.kind in {"schematic_junction", "layout"}` is already treated as
non-physical by the projection code. That distinction should carry forward:
visual helper nodes may affect schematic drawing or placement hints, but they
should not become physical connector pads unless explicitly requested.

### Footprint Model

The next model layer maps semantic terminals onto relative stripboard holes:

```python
@dataclass(frozen=True)
class Footprint:
    name: str
    component_kinds: tuple[str, ...]
    pins: Mapping[str, tuple[int, int]]
    allowed_rotations: tuple[int, ...] = (0, 180)
    blockers: tuple[tuple[int, int], ...] = ()
```

Initial footprints should cover the existing element types:

```text
Resistor / Fuse / Zener:
    two through-hole pins, variable span

Capacitor:
    two through-hole pins, common 2.54 mm or 5.08 mm span

BjtNpn:
    TO-92 variants such as CBE and EBC

PMos:
    common TO-220 / TO-92-ish variants as needed by examples

Terminal or connector nodes:
    explicit pads or pin-header footprints, introduced when needed
```

### Physical Stripboard Model

The verified planner should operate on a physical layout model that is richer
than `StripboardNetAssignment`:

```python
@dataclass(frozen=True)
class PhysicalLayout:
    board: Stripboard
    placed_components: tuple[PlacedComponent, ...]
    cuts: tuple[Cut, ...]
    jumpers: tuple[Jumper, ...]
    blockers: tuple[Blocker, ...] = ()
    annotations: tuple[Annotation, ...] = ()


@dataclass(frozen=True)
class PlacedComponent:
    refdes: str
    footprint_name: str
    origin: tuple[int, int]
    rotation: int


@dataclass(frozen=True)
class Cut:
    row: int
    col: int


@dataclass(frozen=True)
class Jumper:
    start: tuple[int, int]
    end: tuple[int, int]
    net_name: str
```

The existing `Stripboard`, `StripboardCut`, and `StripboardBlocker` concepts
can either be reused directly or migrated to these names gradually. The key is
that the new layout model represents real physical pins and conductors, not
only schematic markers snapped onto rows.

## Evolution Path

### Phase 0: Name The Current Feature Honestly

Keep the current projection workflow working and tested. Document it as:

```text
schematic-to-stripboard projection
diagnostic stripboard overlay
visual placement aid
```

Avoid presenting it as an autorouter or verified layout generator. This reduces
confusion while preserving the value of the tool.

Good near-term cleanup:

```text
- keep `assign_schema_nets_to_stripboard` as the legacy projection entry point,
- keep `render_stripboard_overlay` compatible with `StripboardNetAssignment`,
- add comments/docstrings that the assignment is visualization-derived,
- keep all existing TB6600 projection tests as regression tests.
```

### Phase 1: Export The Semantic Netlist From Schema

Add a small semantic layer and a lowering function:

```python
circuit = circuit_from_schema(schema)
netlist = export_netlist(circuit)
```

This should be easy because `Element` already stores `terminal_nets`. The first
implementation should avoid clever inference and simply normalize what the DSL
already knows.

Checks to add:

```text
- duplicate component reference designators,
- duplicate node view names,
- duplicate or missing terminal names,
- terminals assigned to unknown nets,
- wires connecting different nets,
- components with unsupported element types,
- floating single-terminal nets reported as warnings, not fatal errors.
```

Tests should prove that moving a schematic element with `align` or `translate`
does not change the exported semantic netlist.

### Phase 2: Introduce Footprints And Manual Physical Layouts

Before routing, support manual placement against the semantic netlist:

```python
circuit = circuit_from_schema(schema)
layout = create_manual_stripboard_layout(
    circuit,
    board=create_stripboard(24, 12),
    footprints=default_footprints(),
    placements={...},
    cuts=(...),
    jumpers=(...),
)
```

The important deliverable is not a convenient placement API yet. It is the
ability to represent physical pins, cuts, jumpers, and blockers independently
of schematic drawing coordinates.

The renderer should gain an adapter:

```python
render_stripboard_layout(layout, circuit, file=...)
```

Internally, this can reuse the existing SVG/PNG primitives and label placement
machinery. `render_stripboard_overlay(...)` should continue to work for
`StripboardNetAssignment`.

### Phase 3: Extract And Verify The Physical Netlist

Build a conductor graph from the physical layout:

```text
1. Create one graph node for every hole.
2. Connect adjacent holes along each copper strip unless a cut breaks the path.
3. Connect jumper endpoints.
4. Attach placed component pins to their holes and semantic nets.
5. Compute connected components of the conductor graph.
6. Report shorts when one physical connected component contains multiple
   semantic nets.
7. Report opens when one semantic net appears in multiple physical connected
   components.
8. Run DRC checks for impossible geometry.
```

The first DRC set should include:

```text
- component outside board,
- two pins in one hole unless explicitly allowed,
- pin placed on a cut hole,
- jumper endpoint outside board,
- cut outside board,
- component body blocker colliding with another pin,
- unassigned footprint terminal.
```

This verification layer should know nothing about how the layout was produced.
It should validate manual layouts, legacy projection adapters where meaningful,
and future routed layouts.

### Phase 4: Route Onto Stripboard

Only after extraction and verification exist should the project replace the
row-per-net projection with a real planner.

The first router can still be conservative:

```text
- use schematic positions and current projection rows as placement hints,
- place components on legal holes with footprints,
- prefer existing strip runs for same-net pins,
- insert cuts to isolate different nets sharing a strip,
- add top-side jumpers when a strip path cannot connect the net,
- verify every candidate layout before accepting it.
```

The existing algorithms should not be discarded. They become heuristics:

```text
get_schema_net_visualizations:
    placement hint extraction

assign_schema_nets_to_stripboard:
    legacy initial row hint / diagnostic projection

compact_sparse_stripboard_rows:
    hint for packing low-degree nets into shared rows

compact_stripboard_connections_left:
    component-marker compaction heuristic

permute_stripboard_rows_for_element_span:
    row-order scoring heuristic

render_stripboard_overlay:
    legacy visualization and renderer compatibility target
```

The key behavioral change is that routing results must be accepted because
physical extraction verifies them, not because the projection algorithm created
them.

### Phase 5: Produce Build Outputs

Once layouts verify, add build-oriented outputs:

```text
- top assembly SVG/PNG,
- bottom copper and cut SVG/PNG,
- debug connectivity SVG/PNG,
- markdown build checklist,
- machine-readable JSON for the circuit, layout, and verification report.
```

The SVGs should remain inspectable: preserve `data-net`, `data-row`,
`data-col`, `data-element`, and `data-terminal` attributes where practical.

## Renderer Refactor Plan

The renderer should move toward a view-model boundary:

```python
@dataclass(frozen=True)
class StripboardRenderModel:
    board: Stripboard
    strips: tuple[RenderedStrip, ...]
    holes: tuple[RenderedHole, ...]
    cuts: tuple[RenderedCut, ...]
    jumpers: tuple[RenderedJumper, ...]
    component_bodies: tuple[RenderedComponentBody, ...]
    markers: tuple[RenderedMarker, ...]
    labels: tuple[RenderedLabel, ...]
```

Adapters can then feed the same renderer:

```text
StripboardNetAssignment + Schema -> StripboardRenderModel
PhysicalLayout + Circuit         -> StripboardRenderModel
DebugExtractionReport            -> StripboardRenderModel
```

This keeps the best current code alive while reducing coupling between
rendering and the projection algorithm.

Preserve these current renderer traits:

```text
- SVG and PNG output selected by file extension,
- deterministic output,
- collision-aware labels,
- class names and data attributes useful for tests,
- board dimensions in grid units with renderer-only scaling.
```

## Suggested Package Shape

The project can start with the current single-file implementation and split only
when the new model becomes real. A likely end state:

```text
mege_circuits/
    simple.py
        stable friendly import surface

    dsl.py
        current alignment-first authoring API

    circuit/
        model.py
        lower.py          # Schema -> Circuit
        netlist.py
        erc.py

    footprints/
        model.py
        library.py

    stripboard/
        model.py
        legacy.py         # StripboardNetAssignment adapters
        placement.py
        routing.py
        extraction.py
        verify.py
        scoring.py

    render/
        schematic.py
        stripboard.py
        viewmodel.py
```

Do not split just for tidiness. Split when a module has a stable responsibility
and tests that make the boundary obvious.

## Public API Target

The existing API should remain useful:

```python
from mege_circuits.simple import *

schema = create_schema(nodes, elements, wires)
render_schemdraw(schema, file="schematic.svg")

assignment = assign_schema_nets_to_stripboard(schema)
render_stripboard_overlay(assignment.stripboard, assignment, schema, file="preview.svg")
```

Add the new API beside it:

```python
circuit = circuit_from_schema(schema)
netlist = export_netlist(circuit)

layout, report = plan_stripboard(
    circuit,
    board=create_stripboard(32, 14),
    footprints=default_footprints(),
    hints=stripboard_hints_from_schema(schema),
)

if not report.ok:
    raise RuntimeError(report.summary())

render_stripboard_layout(layout, circuit, file="top.svg")
render_stripboard_bottom(layout, circuit, file="bottom.svg")
render_stripboard_debug(layout, circuit, report, file="debug.svg")
```

The future planner should also accept manual overrides because stripboard work is
often partly human:

```python
layout, report = plan_stripboard(
    circuit,
    board=create_stripboard(32, 14),
    footprints=default_footprints(),
    fixed_placements={"Q1": ((4, 8), 0)},
    fixed_cuts=((3, 12),),
)
```

## Implementation Milestones

### Milestone 1: Semantic Netlist

Deliverables:

```text
- `Circuit`, `Component`, and semantic `Terminal` data classes,
- `circuit_from_schema(schema)`,
- `export_netlist(circuit)` returning deterministic structured data,
- ERC report object,
- tests against voltage divider, high-side switch, and TB6600 examples.
```

Success condition:

```text
Existing schematics export stable semantic netlists independent of drawing
coordinates.
```

### Milestone 2: Footprints And Manual Layout

Deliverables:

```text
- footprint model and small default footprint library,
- manual `PhysicalLayout`,
- placed pin enumeration,
- layout renderer adapter reusing current stripboard rendering code,
- tests for manual valid and invalid layouts.
```

Success condition:

```text
A small manually placed circuit renders through the new physical layout path.
```

### Milestone 3: Extraction And Verification

Deliverables:

```text
- conductor graph extraction,
- open/short detection,
- DRC checks,
- verification report,
- debug render adapter for connected components.
```

Success condition:

```text
Known-good manual layouts pass, and intentional open/short/cut/pin mistakes fail
with specific diagnostics.
```

### Milestone 4: Legacy Projection Adapter

Deliverables:

```text
- adapter from `StripboardNetAssignment` to render model,
- optional adapter from legacy assignments to partial physical/debug model,
- tests proving current SVG/PNG projection output remains covered.
```

Success condition:

```text
The current TB6600 projection still renders while the new layout renderer exists.
```

### Milestone 5: First Router

Deliverables:

```text
- initial component placement using footprints and schematic hints,
- strip-run assignment,
- cut synthesis,
- simple top-side jumper routing,
- verification-gated candidate acceptance,
- score function for cuts, jumpers, board area, and readability.
```

Success condition:

```text
Small examples route automatically into verified stripboard layouts.
```

### Milestone 6: TB6600-Class Layout

Deliverables:

```text
- enough footprint and connector support for the Pico-to-TB6600 interface,
- manual hints where needed,
- top/bottom/debug/checklist outputs,
- comparison tests against the current projection's readability constraints.
```

Success condition:

```text
The TB6600 example produces a readable, verified, solderable stripboard plan.
```

## Testing Strategy

Keep the current tests. They protect the visualization engine and projection
workflow.

Add tests in layers:

```text
Semantic:
    Schema -> Circuit -> netlist is deterministic.
    Drawing-only movement does not change the netlist.
    Bad terminal/net/reference data reports ERC errors.

Footprints:
    Every supported component kind has matching terminal names.
    Rotations produce expected absolute pin holes.

Physical model:
    Pins, blockers, cuts, jumpers, and board bounds validate cleanly.

Extraction:
    Horizontal strips connect as expected.
    Cuts split strips.
    Jumpers connect endpoints.
    Component pins attach semantic nets to holes.

Verification:
    Known opens fail.
    Known shorts fail.
    Valid small layouts pass.

Rendering:
    Current projection SVG/PNG still renders.
    New physical layout SVG/PNG renders.
    Debug views expose data attributes for nets and connected components.
```

## Summary

The current stripboard code is a good visualization and placement experiment,
not yet a verified stripboard compiler. The right evolution is incremental:

```text
1. Export a canonical circuit netlist from today's `Schema`.
2. Add footprints and a real physical layout model.
3. Extract and verify physical connectivity independently.
4. Route onto stripboard using the current projection algorithms as hints.
5. Keep the renderer, but feed it a cleaner render model.
```

That keeps the part of `mege-circuits` that already works well while replacing
the fragile core assumption: stripboard layout should come from a semantic
netlist routed onto physical copper, not from schematic drawing rows alone.
