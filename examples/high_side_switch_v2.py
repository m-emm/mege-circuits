"""Render a small high-side switch schematic."""

from pathlib import Path

from mege_circuits.simple import *


def create_high_side_switch():
    p24 = create_node(Dot, "p24", label="+24V")
    p24 = modify_label_alignment(p24, Alignment.LEFT)
    after_fuse = create_node(Dot, "after_fuse")
    gate = create_node(Dot, "gate")
    vmot = create_node(Dot, "vmot", label="VMOT")
    gnd = create_node(Ground, "gnd")
    base_drive = create_node(Dot, "base_drive")
    q2_collector = create_node(Dot, "q2_collector")
    gpio = create_node(Dot, "gpio", label="GPIO")
    gpio = modify_label_alignment(gpio, Alignment.LEFT)

    f1 = create_element(Fuse, "F1", None, p24, after_fuse)
    q1 = create_element(PMos, "Q1", source=after_fuse, gate=gate, drain=vmot)
    r1 = create_element(Resistor, "R1", None, gate, q2_collector)

    d1 = create_element(Zener, "D1", "12V", gate, after_fuse)

    q2 = create_element(
        BjtNpn,
        "Q2",
        base=base_drive,
        collector=q2_collector,
        emitter=gnd,
    )

    r2 = create_element(Resistor, "R2", None, gpio, base_drive)

    # Layout

    f1 = rotate(90)(f1)
    f1 = align(f1, p24, Alignment.CENTER)
    f1 = align(f1, p24, Alignment.STACK_RIGHT)

    d1 = rotate(180)(d1)
    d1 = align(d1, f1, Alignment.TOP_CENTER)
    d1 = align(d1, f1, Alignment.STACK_RIGHT)
    d1 = modify_label_alignment(d1, Alignment.LEFT)

    q1 = rotate(90)(q1)
    q1 = align(
        q1,
        f1,
        Alignment.CENTER,
    )

    q1 = align(
        q1,
        d1,
        Alignment.STACK_RIGHT,
        stack_gap=0,
    )

    vmot = align(vmot, q1, Alignment.CENTER, stack_gap=0)

    vmot = align(vmot, q1, Alignment.STACK_RIGHT, stack_gap=0)

    r1 = align(r1, q1, Alignment.LEFT)
    r1 = align(r1, d1, Alignment.STACK_BOTTOM)
    r1 = modify_label_alignment(r1, Alignment.RIGHT)

    q2 = align(q2, r1, Alignment.CENTER)
    q2 = align(q2, r1, Alignment.STACK_BOTTOM)

    gnd = align(gnd, q2, Alignment.CENTER)
    gnd = align(gnd, q2, Alignment.STACK_BOTTOM)

    r2 = rotate(90)(r2)
    r2 = align(r2, q2, Alignment.CENTER)
    r2 = align(r2, q2, Alignment.STACK_LEFT)

    return create_schema(
        [p24, after_fuse, gate, vmot, gnd, base_drive, q2_collector, gpio],
        [f1, q1, r1, d1, q2, r2],
    )


def main():
    schema = create_high_side_switch()
    outfile = Path(__file__).with_name("high_side_switch_v2.svg")
    render_schemdraw(schema, file=outfile)
    print(f"Wrote {outfile}")


if __name__ == "__main__":
    main()
