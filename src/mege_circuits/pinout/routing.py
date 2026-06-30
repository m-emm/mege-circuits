"""Routing and waypoint selection logic extracted from the pinout notebook."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any


@dataclass(frozen=True)
class RoutingWeights:
    """Weights for waypoint scoring."""

    violations: float = 10.0
    length: float = 1.0
    projection: float = 3.0


DEFAULT_DISTANCE_THRESHOLD = 0.25
DEFAULT_ROUTING_WEIGHTS = RoutingWeights()


def point_to_line_distance(
    point: tuple[float, float],
    line_start: tuple[float, float],
    line_end: tuple[float, float],
) -> float:
    """Calculate the minimum distance from a point to a line segment."""
    px, py = point
    x1, y1 = line_start
    x2, y2 = line_end

    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:
        return hypot(px - x1, py - y1)

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return hypot(px - closest_x, py - closest_y)


def calculate_projection_score(
    waypoint: tuple[float, float],
    from_pos: tuple[float, float],
    to_pos: tuple[float, float],
) -> float:
    """
    Calculate how far a waypoint is outside the edge bounding box.

    A score of 0 means the waypoint lies inside the projection rectangle.
    """
    wx, wy = waypoint
    x1, y1 = from_pos
    x2, y2 = to_pos

    min_x, max_x = min(x1, x2), max(x1, x2)
    min_y, max_y = min(y1, y2), max(y1, y2)

    outside_x = 0.0
    outside_y = 0.0
    if wx < min_x:
        outside_x = min_x - wx
    elif wx > max_x:
        outside_x = wx - max_x

    if wy < min_y:
        outside_y = min_y - wy
    elif wy > max_y:
        outside_y = wy - max_y

    return outside_x + outside_y


def _connection_endpoints(
    pin_positions: dict[str, tuple[float, float]],
    connection: dict[str, Any],
) -> tuple[str, str, tuple[float, float], tuple[float, float]]:
    from_pin = str(connection["from"])
    to_pin = str(connection["to"])
    return from_pin, to_pin, pin_positions[from_pin], pin_positions[to_pin]


def analyze_connection_violations(
    pin_positions: dict[str, tuple[float, float]],
    connection: dict[str, Any],
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> tuple[int, list[dict[str, Any]]]:
    """Analyze a connection and find pins that are too close to the straight path."""
    from_pin, to_pin, from_pos, to_pos = _connection_endpoints(
        pin_positions, connection
    )
    violations: list[dict[str, Any]] = []
    penalty_score = 0

    for pin_name, pin_pos in pin_positions.items():
        if pin_name in (from_pin, to_pin):
            continue
        distance = point_to_line_distance(pin_pos, from_pos, to_pos)
        if distance < threshold:
            violations.append(
                {"pin": pin_name, "position": pin_pos, "distance": distance}
            )
            penalty_score += 1

    return penalty_score, violations


def analyze_all_connections(
    pin_positions: dict[str, tuple[float, float]],
    connections: list[dict[str, Any]],
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Analyze all connections and return the problematic subset."""
    problematic_connections: list[dict[str, Any]] = []
    for i, connection in enumerate(connections):
        score, violations = analyze_connection_violations(
            pin_positions, connection, threshold=threshold
        )
        if violations:
            problematic_connections.append(
                {
                    "index": i,
                    "connection": connection,
                    "score": score,
                    "violations": violations,
                }
            )
    return problematic_connections


def get_label_blocked_positions(
    pin_positions: dict[str, tuple[float, float]],
) -> set[tuple[float, float]]:
    """
    Positions blocked by labels.

    This mirrors the notebook behavior by reserving three positions to the right
    when a pin has no close right-neighbor.
    """
    blocked_positions: set[tuple[float, float]] = set()
    for name, (x, y) in pin_positions.items():
        has_right_neighbor = any(
            other != name and oy == y and 0 < ox - x < 3
            for other, (ox, oy) in pin_positions.items()
        )
        if not has_right_neighbor:
            for dx in range(1, 4):
                blocked_positions.add((x + dx, y))
    return blocked_positions


def find_optimal_waypoint(
    pin_positions: dict[str, tuple[float, float]],
    connection: dict[str, Any],
    existing_waypoints: set[tuple[float, float]] | None = None,
    *,
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    weights: RoutingWeights = DEFAULT_ROUTING_WEIGHTS,
    search_padding: int = 3,
    debug: bool = False,
) -> tuple[tuple[int, int] | None, dict[str, Any] | None]:
    """
    Find one waypoint minimizing violations, path length and projection score.

    Returns:
        (best_waypoint, score_info) or (None, None)
    """
    if existing_waypoints is None:
        existing_waypoints = set()

    from_pin, to_pin, from_pos, to_pos = _connection_endpoints(
        pin_positions, connection
    )

    label_blocked = get_label_blocked_positions(pin_positions)
    occupied_positions = (
        set(pin_positions.values()) | existing_waypoints | label_blocked
    )

    min_x = int(min(from_pos[0], to_pos[0]) - search_padding)
    max_x = int(max(from_pos[0], to_pos[0]) + search_padding)
    min_y = int(min(from_pos[1], to_pos[1]) - search_padding)
    max_y = int(max(from_pos[1], to_pos[1]) + search_padding)

    candidates: list[dict[str, Any]] = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            waypoint = (x, y)
            if waypoint in occupied_positions or waypoint in (from_pos, to_pos):
                continue

            violations1 = 0
            violations2 = 0
            violated_pins: list[str] = []
            for pin_name, pin_pos in pin_positions.items():
                if pin_name in (from_pin, to_pin):
                    continue
                distance1 = point_to_line_distance(pin_pos, from_pos, waypoint)
                if distance1 < threshold:
                    violations1 += 1
                    violated_pins.append(f"{pin_name}@{pin_pos}:d={distance1:.3f}")

                distance2 = point_to_line_distance(pin_pos, waypoint, to_pos)
                if distance2 < threshold:
                    violations2 += 1
                    violated_pins.append(f"{pin_name}@{pin_pos}:d={distance2:.3f}")

            total_violations = violations1 + violations2
            total_length = hypot(
                waypoint[0] - from_pos[0], waypoint[1] - from_pos[1]
            ) + hypot(to_pos[0] - waypoint[0], to_pos[1] - waypoint[1])
            projection_score = calculate_projection_score(waypoint, from_pos, to_pos)
            candidates.append(
                {
                    "waypoint": waypoint,
                    "violations": total_violations,
                    "length": total_length,
                    "projection": projection_score,
                    "violations1": violations1,
                    "violations2": violations2,
                    "violated_pins": violated_pins,
                }
            )

    if not candidates:
        return None, None

    violation_values = [c["violations"] for c in candidates]
    length_values = [c["length"] for c in candidates]
    projection_values = [c["projection"] for c in candidates]

    min_violations, max_violations = min(violation_values), max(violation_values)
    min_length, max_length = min(length_values), max(length_values)
    min_projection, max_projection = min(projection_values), max(projection_values)

    violation_range = (max_violations - min_violations) or 1.0
    length_range = (max_length - min_length) or 1.0
    projection_range = (max_projection - min_projection) or 1.0

    best_waypoint: tuple[int, int] | None = None
    best_score = float("inf")
    best_info: dict[str, Any] | None = None

    for candidate in candidates:
        normalized_violations = (
            candidate["violations"] - min_violations
        ) / violation_range
        normalized_length = (candidate["length"] - min_length) / length_range
        normalized_projection = (
            candidate["projection"] - min_projection
        ) / projection_range

        combined_score = (
            weights.violations * normalized_violations
            + weights.length * normalized_length
            + weights.projection * normalized_projection
        )
        if combined_score >= best_score:
            continue

        best_score = combined_score
        best_waypoint = candidate["waypoint"]
        best_info = {
            "violations": candidate["violations"],
            "length": candidate["length"],
            "projection": candidate["projection"],
            "normalized_violations": normalized_violations,
            "normalized_length": normalized_length,
            "normalized_projection": normalized_projection,
            "combined_score": combined_score,
            "violations1": candidate["violations1"],
            "violations2": candidate["violations2"],
            "violated_pins": candidate["violated_pins"],
        }

    if debug and best_info is not None:
        print(
            f"waypoint {from_pin}->{to_pin}: {best_waypoint}, "
            f"violations={best_info['violations']}, "
            f"projection={best_info['projection']:.2f}, "
            f"score={best_info['combined_score']:.3f}"
        )

    return best_waypoint, best_info


def route_problematic_connections(
    pin_positions: dict[str, tuple[float, float]],
    connections: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    weights: RoutingWeights = DEFAULT_ROUTING_WEIGHTS,
    search_padding: int = 3,
    verbose: bool = False,
    debug: bool = False,
) -> dict[int, dict[str, Any]]:
    """Route every problematic connection using one waypoint per connection."""
    problematic = analyze_all_connections(
        pin_positions, connections, threshold=threshold
    )
    if not problematic:
        if verbose:
            print("No problematic connections found.")
        return {}

    waypoint_solutions: dict[int, dict[str, Any]] = {}
    existing_waypoints: set[tuple[float, float]] = set()
    if verbose:
        print(f"Routing {len(problematic)} problematic connection(s)...")

    for problem in problematic:
        conn_index = problem["index"]
        connection = problem["connection"]
        waypoint, info = find_optimal_waypoint(
            pin_positions,
            connection,
            existing_waypoints,
            threshold=threshold,
            weights=weights,
            search_padding=search_padding,
            debug=debug,
        )
        if waypoint is None or info is None:
            if verbose:
                print(
                    f"No suitable waypoint for connection {conn_index}: "
                    f"{connection['from']} -> {connection['to']}"
                )
            continue

        existing_waypoints.add(waypoint)
        waypoint_solutions[conn_index] = {
            "waypoint": waypoint,
            "connection": connection,
            "info": info,
        }
        if verbose:
            print(
                f"{conn_index}: {connection['from']} -> {connection['to']} "
                f"via {waypoint} (violations={info['violations']})"
            )

    return waypoint_solutions
