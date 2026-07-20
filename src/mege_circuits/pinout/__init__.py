"""Pinout diagram generation with routing and SVG export."""

from .config import (
    DiscreteComponentPlacement,
    DiscretePinGroup,
    DiscreteViewConfig,
    PinoutProject,
    load_pinout_config,
)
from .discrete import generate_discrete_top_svg
from .routing import (
    analyze_all_connections,
    analyze_connection_violations,
    calculate_projection_score,
    find_optimal_waypoint,
    point_to_line_distance,
    route_problematic_connections,
)
from .svg import DEFAULT_COLOR_MAP, generate_routed_svg, write_svg

__all__ = [
    "DEFAULT_COLOR_MAP",
    "DiscreteComponentPlacement",
    "DiscretePinGroup",
    "DiscreteViewConfig",
    "PinoutProject",
    "analyze_all_connections",
    "analyze_connection_violations",
    "calculate_projection_score",
    "find_optimal_waypoint",
    "generate_discrete_top_svg",
    "generate_routed_svg",
    "load_pinout_config",
    "point_to_line_distance",
    "route_problematic_connections",
    "write_svg",
]
