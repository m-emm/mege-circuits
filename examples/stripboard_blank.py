"""Render a blank horizontal-strip stripboard preview."""

import logging
from pathlib import Path

from mege_circuits.simple import *

_logger = logging.getLogger(__name__)


def create_blank_stripboard():
    return create_stripboard(24, 12)


def main():
    board = create_blank_stripboard()
    for suffix in (".svg", ".png"):
        outfile = Path(__file__).with_name(f"stripboard_blank{suffix}")
        render_stripboard(board, file=outfile)
        _logger.info("Wrote %s", outfile)


if __name__ == "__main__":
    main()
