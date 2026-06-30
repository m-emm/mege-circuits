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
  ground: "#111111"
  clock: "#1f77b4"
  data: "#f2c94c"
  default: "#808080"

pin_sets:
  - prefix: xiao_
    origin: [0, 7]
    direction: up
    pins: [d6, d5, d4, d3, d2, d1, d0]
  - prefix: xiao_
    origin: [6, 7]
    direction: up
    pins: [d7, d8, d9, d10, "3v3", gnd, "5v"]

pins:
  compass_vcc: [20, 5]
  compass_gnd: [20, 4]
  compass_scl: [20, 3]
  compass_sda: [20, 2]

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
```

## Schema Summary

- `basename` (optional): output filename prefix, default `pinout`
- `metadata.version_label` (optional): shown in the SVG corner
- `metadata.notes` (optional): multiline notes shown in the SVG corner
- `metadata.svg_margins_px` (optional): one number for all sides or a
  `left`/`right`/`top`/`bottom` mapping, default `20`
- `color_map` (optional): wire type to color mapping
- `pin_sets` (optional): repeated linear pin definitions
  - `origin`: `[x, y]` start coordinate
  - `pins` or `names`: list of pin names in sequence
  - `prefix` (optional): prepended to every pin name
  - `direction` (optional): `up`, `down`, `left`, or `right`, default `up`
  - `step` (optional): spacing between consecutive pins, default `1`
- `pins` (optional): explicit pin coordinate map, `name: [x, y]`
- `wires` or `connections` (required): list of connections
  - `from`, `to` (required)
  - `type` or `kind` (optional): color-map key, default `default`
  - `color` (optional): explicit wire color override

At least one of `pin_sets` or `pins` must be provided. Duplicate pin names,
duplicate pin coordinates, and connections to unknown pins are rejected.
