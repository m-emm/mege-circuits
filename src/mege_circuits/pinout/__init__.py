"""Pinout diagram generation with routing and SVG export."""

from .catalog import (
    ComponentCatalog,
    DeviceDefinition,
    DevicePinout,
    InventoryDefinition,
    PackageDefinition,
    load_component_catalog,
)
from .config import (
    DiscreteComponentPlacement,
    DiscretePinGroup,
    DiscreteViewConfig,
    PinoutBox,
    PinoutDownholderKind,
    PinoutPhysicalComponent,
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
    "ComponentCatalog",
    "DeviceDefinition",
    "DevicePinout",
    "DiscreteComponentPlacement",
    "DiscretePinGroup",
    "DiscreteViewConfig",
    "InventoryDefinition",
    "PackageDefinition",
    "PinoutBox",
    "PinoutDownholderKind",
    "PinoutPhysicalComponent",
    "PinoutProject",
    "analyze_all_connections",
    "analyze_connection_violations",
    "calculate_projection_score",
    "find_optimal_waypoint",
    "generate_discrete_top_svg",
    "generate_routed_svg",
    "load_component_catalog",
    "load_pinout_config",
    "point_to_line_distance",
    "route_problematic_connections",
    "write_svg",
]
