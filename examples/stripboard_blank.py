"""Render a blank horizontal-strip stripboard preview."""

from pathlib import Path

from mege_circuits.simple import *


def create_blank_stripboard():
    return create_stripboard(24, 12)


def main():
    board = create_blank_stripboard()
    for suffix in (".svg", ".png"):
        outfile = Path(__file__).with_name(f"stripboard_blank{suffix}")
        render_stripboard(board, file=outfile)
        print(f"Wrote {outfile}")


if __name__ == "__main__":
    main()
