# Pinout Diagrams

`mege-circuits` can render top and underside pinout diagrams from YAML or JSON
configuration files. The renderer is useful for connector-to-board wiring maps:
it draws pins, color-coded wires, optional routed waypoints around other pins,
and view-specific labels.

## CLI Usage

```bash
mege-circuits-pinout path/to/pinout.yaml -o output/
```

or:

```bash
python -m mege_circuits.pinout path/to/pinout.yaml -o output/
```

Outputs:

- `<basename>_top.svg`
- `<basename>_bottom.svg`
- `<basename>_top_discrete.svg` when `component_placements` are present

The discrete top view is a component-side assembly aid. It shows all configured
contacts for orientation, omits the routed wire list, and draws the components
that are installed between those contacts. The normal top and underside views
remain the wiring references.

Options:

- `--basename NAME`: override output filename prefix
- `--top-only`: only write top view
- `--bottom-only`: only write underside view
- `--no-routing`: disable waypoint routing
- `--verbose`: print routing decisions

Example:

```bash
mege-circuits-pinout \
  examples/pinout/demo_pico_w_btt_tmc2226_single_driver.yaml \
  -o /tmp/pinout-demo
```

## YAML Example

```yaml
basename: headmask_pinout

metadata:
  version_label: v1.2
  svg_margins_px:
    left: 24
    right: 20
    top: 20
    bottom: 24
  notes: |
    Diode: 1N5819 Schottky.
    Compass: QMC5883L.

color_map:
  power: "#d62728"
  hazard_power: "#8b4513"
  ground: "#111111"
  clock: "#1f77b4"
  data: "#f2c94c"
  default: "#808080"

pin_sets:
  - id: xiao_left
    prefix: xiao_
    origin: [0, 7]
    direction: up
    discrete_pin_numbers: {start: 1, step: 1}
    pins: [d6, d5, d4, d3, d2, d1, d0]
  - id: xiao_right
    prefix: xiao_
    origin: [6, 7]
    direction: up
    discrete_pin_numbers: {start: 14, step: -1}
    pins: [d7, d8, d9, d10, "3v3", gnd, "5v"]

pins:
  compass_vcc: [20, 5]
  compass_gnd: [20, 4]
  compass_scl: [20, 3]
  compass_sda: [20, 2]

boxes:
  - id: compass_module
    label: |
      Compass module
      physical outline
    top_left: [18, 6]
    size_pitches: [6, 5]

physical_components:
  - id: xiao
    label: XIAO module
    component_type: xiao_2x7
    pin_sets: [xiao_left, xiao_right]
    downholder: corner
  - id: compass
    label: Compass module
    component_type: boxed_module
    pin_sets: []
    through_pin_sets: []
    box: compass_module
    downholder: none

wires:
  - from: xiao_3v3
    to: compass_vcc
    type: power
  - from: xiao_gnd
    to: compass_gnd
    type: ground
  - from: xiao_d5
    to: compass_scl
    type: clock
  - from: xiao_d4
    to: compass_sda
    color: "#00b894"

component_placements:
  - ref: R1
    kind: resistor
    value: 10k
    terminals: {start: xiao_d6, end: compass_vcc}

discrete_view:
  title: Headmask component placement — top side
  notes: |
    Insert components from this side, then flip the board for wire wrapping.
  groups:
    - id: xiao
      label: XIAO module
      pin_sets: [xiao_left, xiao_right]
  anchor_labels:
    xiao_d6: pin 1
```

## Schema Summary

- `basename` (optional): output filename prefix, default `pinout`
- `metadata.version_label` (optional): shown in the SVG corner
- `metadata.notes` (optional): multiline notes shown in the SVG corner
- `metadata.svg_margins_px` (optional): one number for all sides or a
  `left`/`right`/`top`/`bottom` mapping, default `20`
- `color_map` (optional): wire type to color mapping
- `pin_sets` (optional): repeated linear pin definitions
  - `id` (optional): stable identifier used by discrete-view groups
  - `origin`: `[x, y]` start coordinate
  - `pins` or `names`: list of pin names in sequence
  - `prefix` (optional): prepended to every pin name
  - `direction` (optional): `up`, `down`, `left`, or `right`, default `up`
  - `step` (optional): spacing between consecutive pins, default `1`
  - `discrete_pin_numbers` (optional): integer `start` and `step` used for
    compact contact labels in the discrete view
- `pins` (optional): explicit pin coordinate map, `name: [x, y]`
- `boxes` (optional): physical outlines rendered behind wiring in every view
  - `id` and `label` identify the outlined module; multi-line labels are allowed
  - `top_left`: shared `[x, y]` coordinate in the pinout raster
  - `size_pitches`: `[width, height]` in the same raster units
- `physical_components` (optional): neutral physical topology for downstream
  carrier or assembly generators
  - `id` (required): unique component identity
  - `label` (optional): non-empty human-readable name
  - `component_type` (required): semantic key used by the consuming assembly to
    select its separately supplied mechanical profile
  - `pin_sets` (optional): pin sets belonging to this real component; defaults
    to an empty list for a box-only component
  - `through_pin_sets` (optional): subset whose contacts pass through the
    carrier; omission means all listed `pin_sets`, while `[]` means none
  - `downholder` (required): semantic retention kind: `corner`,
    `center_strip`, `perimeter_frame`, `pin_line_clamp`,
    `pin_line_upholder`, or `none`
  - `box` (optional): existing `boxes.id` providing the component's exact
    raster outline
- `wires` or `connections` (required): list of connections
  - `from`, `to` (required)
  - `type` or `kind` (optional): color-map key, default `default`
  - `color` (optional): explicit wire color override
- `component_placements` (optional): components installed on the top side
  - `ref`, `kind`, and `value` are required
  - `terminals` maps semantic terminal names to existing pins
  - supported kinds are `resistor`, `capacitor`, `diode`, `zener`, `bjt_pnp`,
    and `dip`
  - resistors/capacitors use `start`/`end`; diodes/zener diodes use
    `anode`/`cathode`; PNP transistors use `collector`/`base`/`emitter`; DIP
    packages use consecutive numeric terminals `1..N`
- `discrete_view` (optional): presentation for `_top_discrete.svg`
  - `title` and `notes` provide assembly-specific annotations
  - `groups` name and outline one or more pin sets
  - `anchor_labels` maps selected pins to short orientation labels

At least one of `pin_sets` or `pins` must be provided. Duplicate pin names,
duplicate pin coordinates, and connections to unknown pins are rejected.
Discrete placements additionally reject unknown terminals, unsupported component
kinds, duplicate references, and multiple components occupying one contact.

## Physical Component Topology

`physical_components` identifies which pin sets form one real component. It is
independent of `discrete_view.groups`: discrete groups are presentation aids,
while physical components are neutral input for consumers such as a printed
carrier generator.

Each pin set may be owned by at most one physical component. Every referenced
pin set and box must exist. A component must reference at least one pin set or
one box. `through_pin_sets`, when present, must be a duplicate-free subset of
that component's `pin_sets`.

Omitting `through_pin_sets` is the normal case for a socket or header: every
grouped contact needs a carrier hole. This also covers a StepStick adapter with
two ordinary rows plus a separate `DIAG0`/`DIAG1` row—both diagnostic pins are
physical through-pins even if one is electrically unused. Use an explicit
empty list for a terminal row which belongs to a box-backed module but does not
penetrate the carrier.

The section deliberately contains no mechanical manufacturing parameters.
Plate thickness, raster pitch in millimetres, component-body margins, holder
dimensions, screw sizes, and printable clearances belong to the consuming
assembly's parameter set. The pinout owns only component grouping, semantic
type and holder choice, through-contact roles, exact raster coordinates, and
box dimensions.

`pin_line_clamp` identifies a single in-line header which needs a rigid clamp
or retaining feature. The contact count and direction come from its pin set;
the consuming assembly owns the header-body, slot, clamp, and clearance
dimensions. This makes short connector rows and longer general-purpose
wire-wrap rows use the same neutral physical topology without embedding a
particular printable clamp design in the pinout.
