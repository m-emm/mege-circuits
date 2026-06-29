"""Render a minimal stacked voltage divider schematic."""

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


def main():
    schema = create_voltage_divider()
    outfile = Path(__file__).with_name("voltage_divider.svg")
    render_schemdraw(schema, file=outfile)
    print(f"Wrote {outfile}")


if __name__ == "__main__":
    main()
