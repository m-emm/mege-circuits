"""Render a small high-side switch schematic."""

import logging
from pathlib import Path

from mege_circuits.simple import *

_logger = logging.getLogger(__name__)


def create_high_side_switch():
    #
    # Nodes
    #

    p24 = create_node(Dot, "p24", label="+24V")
    p24 = modify_label_alignment(p24, Alignment.LEFT)

    after_fuse = create_node(Dot, "after_fuse")

    gate = create_node(Dot, "gate")

    vmot = create_node(Dot, "vmot", label="VMOT")
    vmot = modify_label_alignment(vmot, Alignment.RIGHT)

    gnd = create_node(Ground, "gnd")

    q2_collector = create_node(Dot, "q2_collector")
    base_drive = create_node(Dot, "base_drive")

    gpio = create_node(Dot, "gpio", label="GPIO")
    gpio = modify_label_alignment(gpio, Alignment.LEFT)

    #
    # Elements
    #

    f1 = create_element(Fuse, "F1", None, p24, after_fuse)

    q1 = create_element(
        PMos,
        "Q1",
        "IRF5210",
        source=after_fuse,
        gate=gate,
        drain=vmot,
    )

    # Gate-source zener clamp.
    # Desired polarity:
    #   cathode -> after_fuse / Q1 source
    #   anode   -> gate
    d1 = create_element(
        Zener,
        "D1",
        "12V",
        gate,
        after_fuse,
    )

    # Gate-source pull-up: Q1 OFF by default.
    r1 = create_element(
        Resistor,
        "R1",
        "100k",
        after_fuse,
        gate,
    )

    # Gate pull-down current limiter.
    r2 = create_element(
        Resistor,
        "R2",
        "10k",
        gate,
        q2_collector,
    )

    q2 = create_element(
        BjtNpn,
        "Q2",
        "BC547",
        base=base_drive,
        collector=q2_collector,
        emitter=gnd,
    )

    # Base resistor.
    r3 = create_element(
        Resistor,
        "R3",
        "4.7k",
        gpio,
        base_drive,
    )

    # Base pulldown: Q2 OFF if GPIO floats.
    r4 = create_element(
        Resistor,
        "R4",
        "100k",
        base_drive,
        gnd,
    )

    #
    # Layout: main top rail
    #
    # Keep the top cluster orderly:
    #   F1 -> D1 -> R1 -> Q1
    #
    # D1 and R1 are vertical elements between:
    #   after_fuse / Q1 source
    #   gate
    #

    f1 = rotate(90)(f1)
    f1 = align(f1, p24, Alignment.CENTER)
    f1 = align(f1, p24, Alignment.STACK_RIGHT)

    d1 = rotate(180)(d1)
    d1 = align(d1, f1, Alignment.TOP_CENTER)
    d1 = align(d1, f1, Alignment.STACK_RIGHT)
    d1 = modify_label_alignment(d1, Alignment.LEFT)

    r1 = align(r1, f1, Alignment.TOP_CENTER)
    r1 = align(r1, d1, Alignment.STACK_RIGHT)
    r1 = modify_label_alignment(r1, Alignment.RIGHT)

    q1 = rotate(90)(q1)
    q1 = align(q1, f1, Alignment.TOP_CENTER)
    q1 = align(q1, r1, Alignment.STACK_RIGHT)

    vmot = align(vmot, q1, Alignment.CENTER)
    vmot = align(vmot, q1, Alignment.STACK_RIGHT)

    #
    # Layout: gate pull-down path
    #
    # R2 sits below the gate node cluster.
    # Q2 sits below R2.
    #

    r2 = align(r2, r1, Alignment.CENTER)
    r2 = align(r2, r1, Alignment.STACK_BOTTOM)
    r2 = modify_label_alignment(r2, Alignment.RIGHT)

    q2 = align(q2, r2, Alignment.CENTER)
    q2 = align(q2, r2, Alignment.STACK_BOTTOM)

    #
    # Layout: GPIO input
    #

    gpio = align(gpio, q2, Alignment.CENTER)
    gpio = align(gpio, p24, Alignment.LEFT)

    # Put R4 below the base-drive side, not on the power-switch cluster.
    r4 = align(r4, q2, Alignment.TOP_CENTER)
    r4 = align(r4, q2, Alignment.STACK_LEFT)
    r4 = modify_label_alignment(r4, Alignment.LEFT)

    r3 = rotate(90)(r3)
    r3 = align(r3, gpio, Alignment.CENTER)
    r3 = align(r3, r4, Alignment.STACK_LEFT)

    gnd = align(gnd, q2, Alignment.CENTER)
    gnd = align(gnd, r4, Alignment.STACK_BOTTOM)

    return create_schema(
        [
            p24,
            after_fuse,
            gate,
            vmot,
            gnd,
            q2_collector,
            base_drive,
            gpio,
        ],
        [
            f1,
            d1,
            r1,
            q1,
            r2,
            q2,
            r3,
            r4,
        ],
    )


def main():
    schema = create_high_side_switch()
    outfile = Path(__file__).with_name("high_side_switch_v3.svg")
    render_schemdraw(schema, file=outfile)
    _logger.info("Wrote %s", outfile)


if __name__ == "__main__":
    main()
