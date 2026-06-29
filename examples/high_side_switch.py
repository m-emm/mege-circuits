"""Render a small high-side switch schematic."""

import logging
from pathlib import Path

from mege_circuits.simple import *

_logger = logging.getLogger(__name__)


def create_high_side_switch():
    p24 = create_node(Dot, "p24", label="+24V")
    p24 = modify_label_alignment(p24, Alignment.LEFT)
    source = create_node(Dot, "source")
    gate = create_node(Dot, "gate")
    vmot = create_node(Dot, "vmot", label="VMOT")
    gpio = create_node(Dot, "gpio", label="GPIO")
    gpio = modify_label_alignment(gpio, Alignment.LEFT)
    base_drive = create_node(Dot, "base_drive")
    gnd = create_node(Ground, "gnd")

    f1 = create_element(Fuse, "F1", None, p24, source)
    q1 = create_element(PMos, "Q1", source=source, gate=gate, drain=vmot)
    r1 = create_element(Resistor, "R1", None, source, gate)
    d1 = create_element(Zener, "D1", None, source, gate)
    q2 = create_element(
        BjtNpn,
        "Q2",
        base=base_drive,
        collector=gate,
        emitter=gnd,
    )
    r2 = create_element(Resistor, "R2", None, gpio, base_drive)

    f1 = rotate(90)(f1)

    q1 = align(
        q1,
        f1,
        Alignment.STACK_RIGHT,
    )
    q1 = align(
        q1,
        f1,
        Alignment.STACK_BOTTOM,
    )
    vmot = align(vmot, q1, Alignment.CENTER)
    vmot = align(vmot, q1, Alignment.STACK_RIGHT)

    r1 = rotate(180)(r1)
    r1 = align(r1, q1, Alignment.CENTER)
    r1 = align(r1, q1, Alignment.STACK_BOTTOM)
    r1 = modify_label_alignment(r1, Alignment.LEFT)

    d1 = align(d1, q1, Alignment.CENTER)
    d1 = align(d1, q1, Alignment.STACK_LEFT)
    d1 = align(d1, q1, Alignment.STACK_BOTTOM)
    d1 = modify_label_alignment(d1, Alignment.BOTTOM)
    q2 = align(q2, r1, Alignment.CENTER)
    q2 = align(q2, r1, Alignment.STACK_BOTTOM)

    r2 = rotate(90)(r2)
    r2 = align(r2, q2, Alignment.CENTER)
    r2 = align(r2, q2, Alignment.STACK_LEFT)

    return create_schema(
        [p24, source, gate, vmot, gpio, base_drive, gnd],
        [f1, q1, r1, d1, q2, r2],
    )


def main():
    schema = create_high_side_switch()
    outfile = Path(__file__).with_name("high_side_switch.svg")
    render_schemdraw(schema, file=outfile)
    _logger.info("Wrote %s", outfile)


if __name__ == "__main__":
    main()
