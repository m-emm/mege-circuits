"""Render the planned Pico-to-TB6600 stripboard interface schematic."""

from pathlib import Path

from mege_circuits.simple import *


DEFAULT_OUTPUT_DIR = Path(__file__).with_name("diagrams")


TRANSISTOR_TYPE = "BC337"
SCHEMATIC_JUNCTION = "schematic_junction"

RAIL_LENGTH = 27.4
RAIL_TO_RAIL_GAP = 8.8

DECOUPLING_FROM_RAIL_LEFT_GAP = 2.4
FIRST_STAGE_GAP = 9.8
STAGE_GAP = 7.1

RAIL_TERMINAL_STEM_GAP = 2.6
TERMINAL_PAIR_GAP = 1.4
COLLECTOR_TO_TERMINAL_GAP = 1.2
EMITTER_TO_RETURN_GAP = 1.0

PULLDOWN_TO_TRANSISTOR_GAP = 0.55
GPIO_TO_BASE_RESISTOR_GAP = 1.15

ENA_JUNCTION_TO_TERMINAL_GAP = 0.9
ENA_COLLECTOR_TO_PLUS_GAP = 2.2
ENA_FEED_TO_JUNCTION_GAP = 3.2
PARALLEL_FEED_GAP = 0.5

REFDES = {
    "STEP": {
        "base": "R1",
        "pulldown": "R2",
        "transistor": "Q1",
    },
    "DIR": {
        "base": "R3",
        "pulldown": "R4",
        "transistor": "Q2",
    },
}


def create_tb6600_nets():
    return {
        name: create_net(name)
        for name in [
            "v5",
            "gnd",
            "v24",
            "step_pul_minus",
            "step_base",
            "step_gpio",
            "dir_minus",
            "dir_base",
            "dir_gpio",
            "ena_plus",
            "ena_base",
            "ena_gpio",
        ]
    }


def create_rails(nets):
    v5_rail = create_node(
        Dot,
        "v5_rail",
        net=nets["v5"],
        label="+5V rail",
        label_alignment=Alignment.LEFT,
    )
    v5_rail = create_rail(
        v5_rail,
        Direction.HORIZONTAL,
        RAIL_LENGTH,
        anchor=Alignment.LEFT,
    )

    gnd_rail = create_node(
        Ground,
        "gnd_rail",
        net=nets["gnd"],
        label="GND rail",
        label_alignment=Alignment.LEFT,
    )
    gnd_rail = create_rail(
        gnd_rail,
        Direction.HORIZONTAL,
        RAIL_LENGTH,
        anchor=Alignment.LEFT,
    )
    gnd_rail = align(gnd_rail, v5_rail, Alignment.STACK_BOTTOM, stack_gap=RAIL_TO_RAIL_GAP)
    gnd_rail = align(
        point_at(gnd_rail, Alignment.LEFT),
        point_at(v5_rail, Alignment.LEFT),
        Alignment.CENTER,
        axes=["x"],
    )

    return {"v5": v5_rail, "gnd": gnd_rail}


def create_low_side_channel(
    *,
    refdes,
    prefix,
    plus,
    minus,
    base_net,
    input_net,
    gnd_net,
    v5_rail,
    gnd_rail,
    input_label,
):
    base = create_node(
        Dot,
        f"{prefix}_base",
        net=base_net,
        kind=SCHEMATIC_JUNCTION,
    )
    gnd_junction = create_node(
        Dot,
        f"{prefix}_gnd_junction",
        net=gnd_net,
        kind=SCHEMATIC_JUNCTION,
    )
    pulldown_gnd = create_node(
        Dot,
        f"{prefix}_pulldown_gnd",
        net=gnd_net,
        kind=SCHEMATIC_JUNCTION,
    )

    transistor = create_element(
        BjtNpn,
        refdes["transistor"],
        TRANSISTOR_TYPE,
        base=base,
        collector=minus,
        emitter=gnd_junction,
    )
    transistor = align(transistor.collector, minus, Alignment.CENTER, axes=["x"])
    transistor = align(
        transistor.collector,
        minus,
        Alignment.STACK_BOTTOM,
        stack_gap=COLLECTOR_TO_TERMINAL_GAP,
    )
    transistor = modify_label_alignment(transistor, Alignment.RIGHT)

    gnd_junction = align(gnd_junction, transistor.emitter, Alignment.CENTER)
    gnd_junction = align(
        gnd_junction,
        transistor.emitter,
        Alignment.STACK_BOTTOM,
        stack_gap=EMITTER_TO_RETURN_GAP,
    )

    pulldown = create_element(
        Resistor,
        refdes["pulldown"],
        "47k",
        base,
        pulldown_gnd,
    )
    pulldown = align(
        pulldown,
        transistor,
        Alignment.STACK_LEFT,
        stack_gap=PULLDOWN_TO_TRANSISTOR_GAP,
    )
    pulldown = align(pulldown.start, transistor.base, Alignment.CENTER, axes=["y"])
    pulldown = modify_label_alignment(pulldown, Alignment.RIGHT)

    base = align(base, pulldown.start, Alignment.CENTER)
    pulldown_gnd = align(pulldown_gnd, pulldown.end, Alignment.CENTER)

    gpio = create_node(
        Dot,
        f"{prefix}_gpio",
        net=input_net,
        label=input_label,
        label_alignment=Alignment.LEFT,
    )
    base_resistor = create_element(
        Resistor,
        refdes["base"],
        "2k2",
        gpio,
        base,
    )
    base_resistor = align(base_resistor.end, base, Alignment.CENTER)
    base_resistor = modify_label_alignment(base_resistor, Alignment.RIGHT)

    gpio = align(gpio, base_resistor.start, Alignment.CENTER)
    gpio = align(
        gpio,
        base_resistor.start,
        Alignment.STACK_LEFT,
        stack_gap=GPIO_TO_BASE_RESISTOR_GAP,
    )

    return (
        [gpio, base, gnd_junction, pulldown_gnd],
        [
            create_wire(v5_rail, plus),
            create_wire(gnd_junction, gnd_rail),
            create_wire(pulldown_gnd, gnd_rail),
            transistor,
            base_resistor,
            pulldown,
        ],
    )


def create_enable_channel(terminals, nets, gnd_rail):
    v24 = create_node(
        Dot,
        "ena_v24",
        net=nets["v24"],
        label="+24V",
        label_alignment=Alignment.LEFT,
    )

    ena_plus_junction = create_node(
        Dot,
        "ena_plus_junction",
        net=nets["ena_plus"],
        kind=SCHEMATIC_JUNCTION,
    )
    ena_plus_junction = align(
        ena_plus_junction,
        terminals["ena_plus"],
        Alignment.CENTER,
        axes=["y"],
    )
    ena_plus_junction = align(
        ena_plus_junction,
        terminals["ena_plus"],
        Alignment.STACK_LEFT,
        stack_gap=ENA_JUNCTION_TO_TERMINAL_GAP,
    )

    base = create_node(
        Dot,
        "ena_base",
        net=nets["ena_base"],
        kind=SCHEMATIC_JUNCTION,
    )
    gnd_junction = create_node(
        Dot,
        "ena_gnd_junction",
        net=nets["gnd"],
        kind=SCHEMATIC_JUNCTION,
    )
    pulldown_gnd = create_node(
        Dot,
        "ena_pulldown_gnd",
        net=nets["gnd"],
        kind=SCHEMATIC_JUNCTION,
    )

    transistor = create_element(
        BjtNpn,
        "Q3",
        TRANSISTOR_TYPE,
        base=base,
        collector=ena_plus_junction,
        emitter=gnd_junction,
    )
    transistor = align(transistor.collector, ena_plus_junction, Alignment.CENTER, axes=["x"])
    transistor = align(
        transistor.collector,
        ena_plus_junction,
        Alignment.STACK_BOTTOM,
        stack_gap=ENA_COLLECTOR_TO_PLUS_GAP,
    )
    transistor = modify_label_alignment(transistor, Alignment.RIGHT)

    gnd_junction = align(gnd_junction, transistor.emitter, Alignment.CENTER)
    gnd_junction = align(
        gnd_junction,
        transistor.emitter,
        Alignment.STACK_BOTTOM,
        stack_gap=EMITTER_TO_RETURN_GAP,
    )

    feed_a = create_element(Resistor, "R5", "4k7 0.25W", v24, ena_plus_junction)
    feed_a = align(
        feed_a,
        ena_plus_junction,
        Alignment.STACK_LEFT,
        stack_gap=ENA_FEED_TO_JUNCTION_GAP,
    )
    feed_a = align(
        feed_a.end,
        ena_plus_junction,
        Alignment.CENTER,
        axes=["y"],
    )
    feed_a = modify_label_alignment(feed_a, Alignment.LEFT)

    feed_b = create_element(Resistor, "R6", "4k7 0.25W", v24, ena_plus_junction)
    feed_b = align(feed_b.end, ena_plus_junction, Alignment.CENTER, axes=["y"])
    feed_b = align(feed_b, feed_a, Alignment.STACK_RIGHT, stack_gap=PARALLEL_FEED_GAP)
    feed_b = modify_label_alignment(feed_b, Alignment.RIGHT)

    v24 = align(v24, feed_a.start, Alignment.CENTER)

    gpio = create_node(
        Dot,
        "ena_gpio",
        net=nets["ena_gpio"],
        label="Pico ENABLE GPIO2",
        label_alignment=Alignment.LEFT,
    )

    pulldown = create_element(Resistor, "R8", "47k", base, pulldown_gnd)
    pulldown = align(
        pulldown,
        transistor,
        Alignment.STACK_LEFT,
        stack_gap=PULLDOWN_TO_TRANSISTOR_GAP,
    )
    pulldown = align(pulldown.start, transistor.base, Alignment.CENTER, axes=["y"])
    pulldown = modify_label_alignment(pulldown, Alignment.RIGHT)

    base = align(base, pulldown.start, Alignment.CENTER)
    pulldown_gnd = align(pulldown_gnd, pulldown.end, Alignment.CENTER)

    base_resistor = create_element(Resistor, "R7", "2k2", gpio, base)
    base_resistor = align(base_resistor.end, base, Alignment.CENTER)
    base_resistor = modify_label_alignment(base_resistor, Alignment.RIGHT)

    gpio = align(gpio, base_resistor.start, Alignment.CENTER)
    gpio = align(
        gpio,
        base_resistor.start,
        Alignment.STACK_LEFT,
        stack_gap=GPIO_TO_BASE_RESISTOR_GAP,
    )

    return (
        [
            v24,
            ena_plus_junction,
            gpio,
            base,
            gnd_junction,
            pulldown_gnd,
        ],
        [
            feed_a,
            feed_b,
            transistor,
            base_resistor,
            pulldown,
            create_wire(ena_plus_junction, terminals["ena_plus"]),
            create_wire(gnd_rail, terminals["ena_minus"]),
            create_wire(gnd_junction, gnd_rail),
            create_wire(pulldown_gnd, gnd_rail),
        ],
    )


def create_decoupling(v5_rail, gnd_rail):
    capacitor = create_element(Capacitor, "C1", "100nF", v5_rail, gnd_rail)
    capacitor = align(
        capacitor,
        point_at(v5_rail, Alignment.LEFT),
        Alignment.STACK_RIGHT,
        stack_gap=DECOUPLING_FROM_RAIL_LEFT_GAP,
    )
    capacitor = align(
        capacitor.start,
        v5_rail,
        Alignment.CENTER,
        axes=["y"],
    )
    capacitor = modify_label_alignment(capacitor, Alignment.RIGHT)
    return [], [capacitor]


def create_schema_for_tb6600_interface():
    nets = create_tb6600_nets()
    rails = create_rails(nets)

    decoupling_nodes, decoupling_elements = create_decoupling(rails["v5"], rails["gnd"])

    pul_plus = create_node(
        Dot,
        "STEP_plus",
        net=nets["v5"],
        label="PUL+",
        label_alignment=Alignment.RIGHT,
    )
    pul_plus = align(
        pul_plus,
        point_at(rails["v5"], Alignment.LEFT),
        Alignment.STACK_RIGHT,
        stack_gap=FIRST_STAGE_GAP,
    )
    pul_plus = align(
        pul_plus,
        rails["v5"],
        Alignment.STACK_BOTTOM,
        stack_gap=RAIL_TERMINAL_STEM_GAP,
    )

    pul_minus = create_node(
        Dot,
        "STEP_minus",
        net=nets["step_pul_minus"],
        label="PUL-",
        label_alignment=Alignment.RIGHT,
    )
    pul_minus = align(pul_minus, pul_plus, Alignment.CENTER, axes=["x"])
    pul_minus = align(
        pul_minus,
        pul_plus,
        Alignment.STACK_BOTTOM,
        stack_gap=TERMINAL_PAIR_GAP,
    )

    dir_plus = create_node(
        Dot,
        "DIR_plus",
        net=nets["v5"],
        label="DIR+",
        label_alignment=Alignment.RIGHT,
    )
    dir_plus = align(
        dir_plus,
        pul_plus,
        Alignment.STACK_RIGHT,
        stack_gap=STAGE_GAP,
    )
    dir_plus = align(
        dir_plus,
        rails["v5"],
        Alignment.STACK_BOTTOM,
        stack_gap=RAIL_TERMINAL_STEM_GAP,
    )

    dir_minus = create_node(
        Dot,
        "DIR_minus",
        net=nets["dir_minus"],
        label="DIR-",
        label_alignment=Alignment.RIGHT,
    )
    dir_minus = align(dir_minus, dir_plus, Alignment.CENTER, axes=["x"])
    dir_minus = align(
        dir_minus,
        dir_plus,
        Alignment.STACK_BOTTOM,
        stack_gap=TERMINAL_PAIR_GAP,
    )

    ena_plus = create_node(
        Dot,
        "ena_plus",
        net=nets["ena_plus"],
        label="ENA+",
        label_alignment=Alignment.RIGHT,
    )
    ena_plus = align(
        ena_plus,
        dir_plus,
        Alignment.STACK_RIGHT,
        stack_gap=STAGE_GAP,
    )
    ena_plus = align(ena_plus, dir_plus, Alignment.CENTER, axes=["y"])

    ena_minus = create_node(
        Dot,
        "ena_minus",
        net=nets["gnd"],
        label="ENA-",
        label_alignment=Alignment.RIGHT,
    )
    ena_minus = align(ena_minus, ena_plus, Alignment.CENTER, axes=["x"])
    ena_minus = align(
        ena_minus,
        ena_plus,
        Alignment.STACK_BOTTOM,
        stack_gap=TERMINAL_PAIR_GAP,
    )

    terminals = {
        "pul_plus": pul_plus,
        "pul_minus": pul_minus,
        "dir_plus": dir_plus,
        "dir_minus": dir_minus,
        "ena_plus": ena_plus,
        "ena_minus": ena_minus,
    }

    nodes = [*rails.values(), *terminals.values(), *decoupling_nodes]
    elements = [*decoupling_elements]

    for channel_nodes, channel_elements in [
        create_low_side_channel(
            refdes=REFDES["STEP"],
            prefix="STEP",
            plus=terminals["pul_plus"],
            minus=terminals["pul_minus"],
            base_net=nets["step_base"],
            input_net=nets["step_gpio"],
            gnd_net=nets["gnd"],
            v5_rail=rails["v5"],
            gnd_rail=rails["gnd"],
            input_label="Pico STEP GPIO0",
        ),
        create_low_side_channel(
            refdes=REFDES["DIR"],
            prefix="DIR",
            plus=terminals["dir_plus"],
            minus=terminals["dir_minus"],
            base_net=nets["dir_base"],
            input_net=nets["dir_gpio"],
            gnd_net=nets["gnd"],
            v5_rail=rails["v5"],
            gnd_rail=rails["gnd"],
            input_label="Pico DIR GPIO1",
        ),
        create_enable_channel(terminals, nets, rails["gnd"]),
    ]:
        nodes.extend(channel_nodes)
        elements.extend(channel_elements)

    return create_schema(nodes, elements)


def render_tb6600_schematic(output_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_file = output_dir / "pico_tb6600_stripboard_interface.svg"
    png_file = output_dir / "pico_tb6600_stripboard_interface.png"
    schema = create_schema_for_tb6600_interface()
    for output_file in (svg_file, png_file):
        render_schemdraw(schema, file=output_file)
        print(f"Wrote {output_file}")
    return svg_file, png_file


def main():
    render_tb6600_schematic()


if __name__ == "__main__":
    main()
