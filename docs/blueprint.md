# mege-circuits: Stripboard Layout Engine Blueprint

Status: architecture blueprint  
Target project: `mege-circuits`  
Primary goal: turn code-defined circuits into verified, solder-ready stripboard SVGs.

This document describes the vocabulary, internal architecture, and implementation steps for a small Python tool that starts from semantically defined circuit schematics and produces a practical stripboard visualization: components, holes, strips, cuts, jumpers, labels, and build checks.

The intended first-class output is not a PCB file. It is a trusted build document: SVG views that can be printed or viewed while soldering.

## 1. Scope

The initial project should support this workflow:

```text
Python circuit definition
    -> semantic circuit model
    -> footprinted physical problem
    -> stripboard placement
    -> strip/cut/jumper routing
    -> physical extraction and verification
    -> solder-ready SVG visualization
```

In scope for the first serious implementation:

```text
- Python API for defining small analog/digital helper circuits
- Semantic netlist extraction
- Footprint assignment for through-hole parts
- Rectangular 2.54 mm stripboard model
- Component placement on holes
- Copper strip cuts
- Top-side jumpers or links
- Physical conductor graph extraction
- Open/short verification
- SVG rendering of top, bottom, and debug views
- Human-readable build checklist
```

Explicitly out of scope for the first implementation:

```text
- Full PCB design
- Gerber generation
- KiCad import/export as a core dependency
- SPICE simulation as a core feature
- Perfect global autorouting
- Arbitrary curved or free-angle wiring
- Multi-board systems
```

SPICE, KiCad, DSN/SES, Gerber, and other interchange formats should remain future-facing export ideas. The internal model should be clean enough that these exporters can be added later, but the first project should not be bent around them.

## 2. Design principles

### 2.1 Separate the three truths

The tool should maintain three distinct forms of truth:

```text
Semantic truth:
    The intended electrical circuit.
    Components, terminals, nets, values, labels.

Physical truth:
    The actual stripboard implementation.
    Holes, strips, cuts, jumpers, solder points, component pins.

Presentation truth:
    What humans see.
    Schematic drawings, top views, bottom views, labels, build diagrams.
```

The central invariant should be:

```text
extracted_physical_netlist(layout) == semantic_netlist(circuit)
```

In plain language: the board that the user solders must connect exactly the nets that the schematic intended, with no missing connections and no accidental shorts.

### 2.2 Grid first, millimetres later

Internally, everything physical should live on integer grid coordinates:

```text
(row, col)
```

Only the renderer should convert grid coordinates to millimetres or SVG units.

Recommended convention:

```text
row = 0 at top in rendered top view
col = 0 at left in rendered top view
pitch = 2.54 mm
horizontal stripboard = copper strips run along rows
```

### 2.3 Verify independently of the router

The router will be heuristic and sometimes wrong. The verifier must be separate and strict.

Do not trust a generated layout because the algorithm says it routed the circuit. Trust it only after extracting the physical conductor graph and comparing it to the semantic circuit graph.

### 2.4 Make good simple layouts before clever layouts

For small stripboard circuits, human-like structure matters more than algorithmic fireworks.

Prioritize:

```text
- simple rails
- repeated cells
- compact local connections
- readable labels
- few jumpers
- few cuts
- obvious soldering order
```

Only add global optimization once deterministic placement, routing, cut synthesis, verification, and SVG rendering are solid.

## 3. Vocabulary and core concepts

### 3.1 Circuit-side concepts

A `Circuit` is the semantic electrical design. It has components and nets, but no board coordinates.

A `Component` is a concrete part instance such as `R1`, `Q3`, `C1`, or `J1`. It has a reference designator, kind, value, terminals, and optional metadata.

A `Terminal` is an abstract electrical endpoint of a component, for example `Q1.base`, `Q1.collector`, or `R1.end`.

A `Net` is an equipotential electrical group. Every terminal assigned to the same net must be physically connected on the final board.

A `Netlist` is the flattened circuit connectivity:

```text
component terminal -> net
```

Example:

```python
{
    "Q1": {
        "kind": "bjt_npn",
        "value": "BC337",
        "terminals": {
            "collector": "step_pul_minus",
            "base": "step_base",
            "emitter": "gnd",
        },
    },
    "R1": {
        "kind": "resistor",
        "value": "2k2",
        "terminals": {
            "start": "step_gpio",
            "end": "step_base",
        },
    },
}
```

A `Schematic` is the semantic circuit plus human drawing information: node views, labels, alignments, wires, junction dots, grouping, and visual hints. The router should not depend on schematic drawing geometry for correctness, but it may use it as a placement hint.

A `RefDes` is the stable reference designator: `R1`, `R2`, `Q1`, `C1`, `J1`. It should survive every transformation and appear in rendered SVGs.

### 3.2 Physical-side concepts

A `Board` is a rectangular grid of holes.

A `Grid` is the coordinate system used for all physical decisions.

A `Hole` is a physical point on the board at `(row, col)`. It may be unused, occupied by a component pin, used as a jumper endpoint, cut, blocked by a component body, or available.

A `Strip` is the original continuous copper conductor on a classic stripboard. On horizontal stripboard, each row starts as one long copper strip.

A `StripSegment` or `StripRun` is a continuous copper region after cuts have split the original strip.

A `Cut` is a deliberate break in a copper strip.

Recommended v1 convention:

```text
cut-at-hole
```

A cut at `(row, col)` removes that hole from bottom-copper connectivity and breaks the strip on both sides of it. This matches common hand practice and is easy to visualize.

A `Jumper`, `Link`, or `Wire` is an intentional top-side conductor between two holes. For v1, model jumpers as endpoint-only conductors: they electrically connect their endpoints but do not interact with holes they pass over.

A `SolderBridge` is an intentional short between neighbouring holes. Support this later as an optional high-cost conductor. It is useful, but should not become the router's favourite trick.

A `Footprint` is the physical pin geometry of a component. It maps terminal names to relative hole coordinates.

Example:

```python
Footprint(
    name="TO92_CBE_flat",
    pins={
        "collector": (0, 0),
        "base": (0, 1),
        "emitter": (0, 2),
    },
    allowed_rotations=(0, 180),
)
```

A `Keepout` or `Blocker` is a hole or area unavailable for routing because a component body, lead bend, connector body, screw, label, or construction constraint occupies it.

A `PlacedComponent` is a component instance with a footprint, origin, and rotation.

A `PhysicalLayout` is the complete physical proposal:

```text
board + placed components + cuts + jumpers + optional solder bridges
```

### 3.3 Checking and debugging concepts

A `Ratsnest` is the set of still-unrouted required connections. It is useful for debugging and visualization, but should not be part of the final physical layout.

An `ERC`, electrical rule check, checks the semantic circuit:

```text
- duplicate reference designators
- missing terminal assignments
- unknown component types
- unnamed nets
- suspicious floating nets
- missing ground, if required
```

A `DRC`, design rule check, checks the physical layout:

```text
- two pins in one hole
- pin on cut hole
- component outside board
- overlapping component bodies
- jumper endpoint outside board
- jumper through blocked area, if using non-insulated jumpers
- cut under a required solder point
```

`Physical extraction` means deriving the actual conductor graph from strips, cuts, jumpers, and pins. This is the decisive verification step.

## 4. Canonical internal data model

The project should use one canonical internal model that is neither SPICE, nor KiCad, nor SVG. External formats should be generated from this model later.

A minimal starting point:

```python
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Net:
    name: str
    kind: str = "signal"          # signal, power, ground, external, local
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Component:
    refdes: str
    kind: str                     # resistor, capacitor, bjt_npn, connector, wire
    value: str | None
    terminal_nets: Mapping[str, str]
    footprint_name: str | None = None
    spice_model: str | None = None


@dataclass(frozen=True)
class Circuit:
    components: Mapping[str, Component]
    nets: Mapping[str, Net]


@dataclass(frozen=True)
class Footprint:
    name: str
    pins: Mapping[str, tuple[int, int]]
    body_keepout: tuple[tuple[int, int], ...] = ()
    allowed_rotations: tuple[int, ...] = (0, 90, 180, 270)


@dataclass(frozen=True)
class Board:
    width: int
    height: int
    pitch_mm: float = 2.54
    strip_direction: str = "horizontal"


@dataclass(frozen=True)
class PlacedComponent:
    refdes: str
    footprint_name: str
    origin: tuple[int, int]
    rotation: int


@dataclass(frozen=True)
class Cut:
    hole: tuple[int, int]


@dataclass(frozen=True)
class Jumper:
    start: tuple[int, int]
    end: tuple[int, int]
    net: str
    kind: str = "insulated"


@dataclass(frozen=True)
class PhysicalLayout:
    board: Board
    placed_components: tuple[PlacedComponent, ...]
    cuts: tuple[Cut, ...]
    jumpers: tuple[Jumper, ...]
```

The schematic DSL can remain a friendly authoring layer. It should lower into this model before stripboard planning begins.

## 5. Proposed package architecture

```text
mege_circuits/
    circuit/
        model.py              # Circuit, Component, Net
        dsl.py                # friendly Python circuit authoring API
        lower.py              # schematic/drawing DSL -> Circuit
        erc.py                # semantic checks

    stripboard/
        model.py              # Board, Hole, Cut, Jumper, PhysicalLayout
        footprints.py         # through-hole footprint library
        problem.py            # LayoutProblem, constraints, preferences
        placement.py          # deterministic and heuristic placement
        routing.py            # graph search, net routing, route ordering
        cuts.py               # cut synthesis
        extract.py            # physical conductor graph extraction
        verify.py             # opens, shorts, DRC
        optimize.py           # local moves, beam search, rip-up/retry
        render_svg.py         # top, bottom, debug, and build SVGs
        checklist.py          # coordinate lists for cuts, jumpers, components

    exporters/
        ideas_spice.py        # future idea, not v1 core
        ideas_kicad.py        # future idea, not v1 core
        ideas_json.py         # optional debug export

    examples/
        pico_tb6600_interface.py

    tests/
        test_lowering.py
        test_footprints.py
        test_conductor_extraction.py
        test_cut_synthesis.py
        test_verification.py
        test_svg_rendering.py
        test_pico_tb6600_example.py
```

The `stripboard` package should not import from SVG, KiCad, or SPICE code. Rendering and exporting should depend on the model, not the other way around.

## 6. End-to-end pipeline

### Stage 1: Define the circuit in Python

The user writes a semantic circuit, optionally with schematic drawing hints.

Example style:

```python
c = CircuitBuilder("pico_tb6600_interface")

c.net("v5", kind="power")
c.net("gnd", kind="ground")
c.net("step_gpio")
c.net("step_base")
c.net("step_pul_minus")

c.resistor("R1", "2k2", "step_gpio", "step_base")
c.resistor("R2", "47k", "step_base", "gnd")
c.bjt_npn(
    "Q1",
    "BC337",
    collector="step_pul_minus",
    base="step_base",
    emitter="gnd",
    footprint="TO92_CBE_flat",
)
```

The schematic drawing layer may exist, but the router should consume the semantic `Circuit`.

### Stage 2: Lower to semantic circuit model

Input:

```text
Python DSL objects
```

Output:

```text
Circuit
```

Algorithm:

```text
1. Collect all components.
2. Collect all nets.
3. Collect terminal-to-net assignments.
4. Merge net aliases.
5. Drop visual-only schematic nodes.
6. Preserve labels and layout hints as metadata.
7. Validate the semantic circuit.
8. Emit Circuit.
```

Validation examples:

```text
- every refdes is unique
- every component has all required terminals
- every terminal connects to exactly one net
- every referenced net exists
- every component kind is known
```

### Stage 3: Assign footprints

Input:

```text
Circuit + footprint library
```

Output:

```text
Footprinted circuit
```

Algorithm:

```text
For each component:
    1. If a footprint is explicitly assigned, use it.
    2. Otherwise select a default footprint for the component kind and value.
    3. Verify that footprint pins match component terminals.
    4. Attach allowed rotations and body keepouts.
```

Example footprint library entries:

```text
resistor_axial_400mil
resistor_axial_500mil
capacitor_radial_100mil
TO92_CBE_flat
TO92_EBC_flat
screw_terminal_2pin_508mil
pin_header_1x04
```

Keep component kind and footprint separate. `BJT_NPN` is electrical; `TO92_CBE_flat` is physical.

### Stage 4: Create the stripboard problem

Input:

```text
Circuit + footprints + board candidate
```

Output:

```text
LayoutProblem
```

A `LayoutProblem` contains:

```text
- board size
- component footprints
- required net connectivity
- fixed placements, if any
- hard constraints
- soft preferences
```

Hard constraints:

```text
- pins must land on holes
- no two pins may occupy the same hole
- no pin may land on a cut hole
- component bodies must not overlap
- components must stay inside the board
- blocked holes may not be used as solder points
```

Soft preferences:

```text
- small board area
- few jumpers
- few cuts
- short jumpers
- long clean rails
- repeated channel cells look similar
- external connectors near board edge
- labels readable in SVG
```

### Stage 5: Initial placement

For small analog helper circuits, start with a structured placement rather than a blind global search.

Recommended placement strategy:

```text
1. Place external connectors on one edge.
2. Reserve GND and supply rails.
3. Detect repeated circuit cells, such as STEP/DIR/ENABLE channels.
4. Place each repeated cell left-to-right or top-to-bottom.
5. Place local resistors close to the transistor or IC pins they serve.
6. Place decoupling capacitors near supply rails.
7. Compact unused rows and columns.
```

A first scoring function:

```python
def placement_score(layout: PhysicalLayout) -> int:
    return (
        10000 * hard_error_count(layout)
        + 1000 * estimated_unrouted_net_count(layout)
        + 100 * component_overlap_count(layout)
        + 30 * total_component_span(layout)
        + 10 * external_terminal_distance(layout)
        + 5 * repeated_cell_deviation(layout)
        + board_area(layout.board)
    )
```

Suggested algorithms, in implementation order:

```text
1. Deterministic template placement.
2. Greedy placement.
3. Row and column compaction.
4. Beam search over candidate placements.
5. Local improvement moves.
6. Simulated annealing only if needed.
```

Useful local moves:

```text
- move one component by one hole
- rotate one component
- swap two repeated cells
- mirror a repeated cell
- move a connector block
- move a rail row
- compact empty rows
- compact empty columns
```

### Stage 6: Build the conductor graph

The conductor graph models what copper and wires actually connect.

Vertices:

```text
one vertex for each usable hole
```

Bottom-layer edges:

```text
edges between adjacent holes on the same strip, unless cut
```

Top-layer edges:

```text
jumpers, links, and optional solder bridges
```

For a horizontal stripboard before cuts:

```python
for row in range(board.height):
    for col in range(board.width - 1):
        add_bottom_edge((row, col), (row, col + 1))
```

For cut-at-hole behavior:

```python
def apply_cut_at_hole(graph, hole):
    graph.remove_bottom_copper_edges_touching(hole)
    graph.mark_unsolderable(hole)
```

Component pins attach component terminals to hole vertices. Component bodies do not automatically short pins together.

### Stage 7: Route nets

A stripboard route assigns existing copper segments and adds jumpers. It does not draw arbitrary copper like a PCB router.

For each net:

```text
1. Find all pin holes belonging to the net.
2. Start a route tree at one pin.
3. Repeatedly connect the nearest unconnected pin to the tree.
4. Use Dijkstra or A* over the conductor graph.
5. Reserve used resources for that net.
6. Continue until all pins on the net are connected.
```

Basic path cost model:

```python
COST = {
    "existing_same_net_copper": 0,
    "unused_strip_edge": 1,
    "new_jumper_endpoint": 8,
    "new_jumper_length": 2,
    "new_cut_needed": 10,
    "near_component_body": 5,
    "foreign_net": 1_000_000,
}
```

Route order matters. A simple v1 route order:

```text
1. Fixed rails: GND, +5V, +24V.
2. Nets with many pins.
3. Short local nets.
4. Long awkward nets.
5. Remaining external connector nets.
```

Later, generate several route orders, route them all, verify each result, and keep the lowest-scoring valid layout.

### Stage 8: Synthesize cuts

The router should identify which strip regions are used by which net. Cuts then separate different nets on the same original copper strip.

Algorithm per row:

```text
1. Collect all used copper regions on the row.
2. Sort regions by column.
3. Walk neighbouring regions.
4. If two neighbouring regions belong to different nets, choose a legal cut hole between them.
5. Reject the layout if no legal cut exists.
6. Add all cuts.
7. Re-extract the physical conductor graph.
8. Verify again.
```

Pseudocode:

```python
def synthesize_row_cuts(regions):
    cuts = []
    regions = sorted(regions, key=lambda r: r.start_col)

    for left, right in zip(regions, regions[1:]):
        if left.net == right.net:
            continue

        candidates = range(left.end_col + 1, right.start_col)
        cut_col = choose_best_cut(candidates)
        if cut_col is None:
            raise LayoutError(
                f"No legal cut between {left.net} and {right.net}"
            )
        cuts.append(cut_col)

    return cuts
```

Cut selection preferences:

```text
- not under a component body
- not under a component pin
- not at a jumper endpoint
- visible in bottom SVG
- enough free space around the cut
- preferably near the middle of the gap
```

### Stage 9: Extract and verify the physical layout

This is the most important subsystem.

Input:

```text
Circuit + PhysicalLayout + footprints
```

Output:

```text
VerificationReport
```

Algorithm:

```text
1. Build conductor graph from board, cuts, jumpers, and solder bridges.
2. Compute connected components of the conductor graph.
3. Attach placed component pins to graph vertices.
4. For each physical connected component, collect the schematic nets present in it.
5. If one physical connected component contains more than one schematic net, report a short.
6. For each schematic net, collect physical connected components containing its pins.
7. If one schematic net appears in more than one physical component, report an open.
8. Run DRC checks.
9. Return report.
```

Pseudocode:

```python
def verify_layout(circuit, layout, footprints):
    graph = extract_conductor_graph(layout)
    islands = connected_components(graph)

    island_by_hole = {}
    for island_id, holes in enumerate(islands):
        for hole in holes:
            island_by_hole[hole] = island_id

    nets_by_island = {}
    islands_by_net = {}

    for pin in placed_pins(circuit, layout, footprints):
        island_id = island_by_hole.get(pin.hole)
        if island_id is None:
            report.pin_not_connected(pin)
            continue

        nets_by_island.setdefault(island_id, set()).add(pin.net)
        islands_by_net.setdefault(pin.net, set()).add(island_id)

    for island_id, nets in nets_by_island.items():
        if len(nets) > 1:
            report.short(island_id=island_id, nets=sorted(nets))

    for net, island_ids in islands_by_net.items():
        if len(island_ids) > 1:
            report.open(net=net, islands=sorted(island_ids))

    run_drc_checks(report, circuit, layout, footprints)
    return report
```

A layout is solder-ready only when:

```text
- no shorts
- no opens
- no unsolderable pins
- no overlapping components
- no illegal cuts
- no illegal jumper endpoints
```

### Stage 10: Score and improve layouts

Correctness dominates aesthetics.

Suggested score:

```python
def layout_score(layout, report):
    return (
        1_000_000 * report.short_count
        + 500_000 * report.open_count
        + 100_000 * report.unsolderable_pin_count
        + 10_000 * report.drc_error_count
        + 500 * len(layout.jumpers)
        + 100 * len(layout.cuts)
        + 10 * total_jumper_length(layout)
        + 5 * visual_disorder(layout)
        + board_area(layout.board)
    )
```

Optimization loop:

```python
best = None

for board in candidate_board_sizes():
    for seed in make_seed_placements(problem, board):
        for candidate in improve(seed):
            routed = route(candidate)
            with_cuts = synthesize_cuts(routed)
            report = verify_layout(circuit, with_cuts, footprints)
            score = layout_score(with_cuts, report)

            if best is None or score < best.score:
                best = Candidate(with_cuts, report, score)

return best
```

In v1, this can be much simpler:

```text
1. Create one deterministic placement.
2. Route it.
3. Synthesize cuts.
4. Verify.
5. Render.
```

Then add retries and improvement later.

## 7. SVG rendering

The built-in SVG renderer is a core feature.

It should generate multiple views from the same verified layout.

### 7.1 Top assembly view

Purpose: place and solder components.

Show:

```text
- board outline
- holes
- component bodies
- component reference designators
- values, where useful
- pin labels for transistors and connectors
- jumpers
- optional net labels
- row/column coordinates
```

### 7.2 Bottom copper and cut view

Purpose: cut copper strips correctly.

Show:

```text
- copper strips
- holes
- cut locations
- cut coordinate labels
- mirrored indicator if rendered as bottom view
- optional net names on copper segments
```

Important: make the orientation unambiguous. Either render the bottom as seen from below and label it clearly, or render it as a top-reference cut map and label it clearly. Do not let the user wonder which side is mirrored while holding a drill bit.

### 7.3 Debug connectivity view

Purpose: inspect and trust the layout.

Show:

```text
- physical conductor islands
- net names
- unrouted ratsnest lines, if any
- shorts and opens highlighted textually
```

The debug view can be less pretty. It should be honest.

### 7.4 Build checklist

Generate a Markdown or text checklist next to the SVGs:

```text
Cuts:
  C03  isolate step_base from gnd
  F11  isolate dir_minus from +5V

Jumpers:
  J1  B02 -> H02  GND
  J2  C05 -> C09  +5V

Components:
  R1  2k2   A04 -> C04
  R2  47k   C04 -> G04
  Q1  BC337 C=E06 B=E07 E=E08
```

This checklist is not a separate source of truth. It is generated from the verified `PhysicalLayout`.

## 8. Minimal public API target

A pleasant v1 user API could look like this:

```python
from mege_circuits import CircuitBuilder
from mege_circuits.stripboard import Board, plan_stripboard, render_build_svgs


c = CircuitBuilder("pico_tb6600_interface")

# Define nets.
c.net("v5", kind="power")
c.net("gnd", kind="ground")
c.net("step_gpio")
c.net("step_base")
c.net("step_pul_minus")

# Define components.
c.resistor("R1", "2k2", "step_gpio", "step_base")
c.resistor("R2", "47k", "step_base", "gnd")
c.bjt_npn(
    "Q1",
    "BC337",
    collector="step_pul_minus",
    base="step_base",
    emitter="gnd",
    footprint="TO92_CBE_flat",
)

circuit = c.build()

layout = plan_stripboard(
    circuit,
    board=Board(width=32, height=14),
    preferences={
        "external_connectors": "right",
        "inputs": "left",
        "rails": ["v5", "gnd"],
    },
)

render_build_svgs(
    circuit,
    layout,
    output_dir="build/pico_tb6600_stripboard",
)
```

Generated files:

```text
pico_tb6600_stripboard.top.svg
pico_tb6600_stripboard.bottom_cuts.svg
pico_tb6600_stripboard.debug.svg
pico_tb6600_stripboard.checklist.md
```

## 9. Implementation milestones

### Milestone 1: Semantic core

Deliver:

```text
- Circuit model
- Component model
- Net model
- Python builder API
- Netlist extraction
- ERC checks
- Unit tests
```

Success condition:

```text
A small circuit can be defined in Python and converted into a normalized semantic netlist.
```

### Milestone 2: Footprints and manual layout

Deliver:

```text
- Footprint model
- Basic footprint library
- Board model
- Manual component placement
- Hole occupancy checks
- Basic top SVG renderer
```

Success condition:

```text
A manually placed circuit renders as a top-side stripboard assembly SVG.
```

### Milestone 3: Conductor extraction and verification

Deliver:

```text
- Bottom copper graph generation
- Cut handling
- Jumper handling
- Connected-component extraction
- Open/short verification
- DRC report
```

Success condition:

```text
A manual layout can be proven electrically equivalent or reported invalid.
```

### Milestone 4: Cut synthesis

Deliver:

```text
- Used strip-region detection
- Automatic cut placement between different nets
- Bottom cut SVG renderer
- Cut checklist
```

Success condition:

```text
Given placed components and intended strip usage, the tool computes cuts and verifies the result.
```

### Milestone 5: Simple router

Deliver:

```text
- Net terminal collection
- Route tree per net
- Dijkstra or A* path search over stripboard graph
- Jumper insertion
- Basic route ordering
- Rip-up/retry for failed nets
```

Success condition:

```text
Small circuits route automatically with valid cuts and jumpers.
```

### Milestone 6: Structured placement

Deliver:

```text
- Rails
- Connector placement preferences
- Repeated cell templates
- Greedy placement
- Row/column compaction
```

Success condition:

```text
The Pico-to-TB6600-style interface lays out into a readable, solderable stripboard SVG without manual coordinate placement.
```

### Milestone 7: Polish the build output

Deliver:

```text
- top assembly SVG
- bottom cut SVG
- debug connectivity SVG
- build checklist
- stable coordinate labels
- print-friendly scaling
```

Success condition:

```text
The SVGs and checklist are sufficient to build the board with a soldering iron and continuity tester.
```

## 10. Testing strategy

The test suite should treat verification as a first-class feature.

Core tests:

```text
- lowering preserves all component terminal nets
- duplicate refdes are rejected
- unknown terminals are rejected
- footprint terminal mismatch is rejected
- two pins in one hole are rejected
- cut under pin is rejected
- jumper endpoint outside board is rejected
- connected GND rail extracts as one physical island
- missing cut produces a short
- missing jumper produces an open
- valid known layout verifies cleanly
```

Golden example tests:

```text
- one resistor between two nets
- LED plus resistor
- one NPN low-side switch
- two repeated NPN low-side switches
- Pico-to-TB6600 interface subset
- full Pico-to-TB6600 interface
```

Property-like tests:

```text
- removing a required jumper creates an open
- removing a required cut creates a short
- moving a component pin onto a foreign strip creates a short or open
- shuffling metadata does not change semantic netlist
```

## 11. Future export and interoperability ideas

These should remain optional exporters, not core architecture drivers.

Possible future exports:

```text
SPICE netlist:
    Useful for simple simulation or sanity checks.
    Should be generated from Circuit, not PhysicalLayout.

KiCad schematic:
    Useful for review in a standard EDA tool.
    Should be generated from Circuit plus optional schematic presentation hints.

KiCad PCB:
    Useful as a viewer/export artifact.
    Should represent the stripboard layout, but not become the source of truth.

Specctra DSN/SES:
    Interesting for experiments with traditional autorouters.
    Probably useful only for subproblems, such as jumper routing.

Gerber:
    Useful only if the project later grows a PCB-manufacturing mode.
```

The key rule:

```text
Exports are projections of the canonical model.
They must not define the canonical model.
```

## 12. First practical implementation path

The fastest useful path is:

```text
1. Define Circuit, Component, Net.
2. Lower the existing Python schematic DSL into Circuit.
3. Define Board, Footprint, PlacedComponent, Cut, Jumper.
4. Allow manual placement in Python.
5. Render top SVG.
6. Extract physical conductor graph.
7. Verify opens and shorts.
8. Render bottom cut SVG.
9. Generate checklist.
10. Add cut synthesis.
11. Add simple jumper routing.
12. Add template placement for repeated circuits.
```

This order gives value early. The project becomes useful before it becomes clever.

## 13. Summary

`mege-circuits` should be a small, grid-native stripboard compiler:

```text
semantic circuit -> physical stripboard -> verified build SVG
```

The essential architecture is:

```text
Circuit model
    independent of drawing and board geometry

Footprint model
    maps abstract terminals to physical holes

Physical layout model
    board, components, cuts, jumpers

Conductor extractor
    derives what is actually connected

Verifier
    proves the physical layout matches the semantic circuit

Renderer
    produces top, bottom, debug, and checklist build artifacts
```

The router can start simple. The verifier cannot. Once extraction and verification are solid, every later algorithm becomes safer to experiment with.
