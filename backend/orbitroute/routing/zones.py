"""How much of each road segment lies inside the zones a request wants avoided."""

from __future__ import annotations

from shapely.geometry import LineString

from orbitroute.perception.graph import RoadGraph
from orbitroute.understanding.scene import Zone

ZONE_TOLERANCE_M = 10.0  # a segment grazing a zone border by less than this is not a crossing


def edge_key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def inside_lengths(graph: RoadGraph, zones: list[Zone]) -> dict[tuple[int, int], float]:
    """Metres of each edge inside any of `zones`; only edges with a positive length are listed."""
    out: dict[tuple[int, int], float] = {}
    if not zones:
        return out
    for e in graph.edges:
        line = LineString([tuple(graph.nodes[e.u]), tuple(graph.nodes[e.v])])
        inside_px = sum(z.polygon.intersection(line).length for z in zones)
        if inside_px > 0:
            out[edge_key(e.u, e.v)] = min(inside_px * graph.m_per_px, e.length_m)
    return out


def banned_edges(inside: dict[tuple[int, int], float], tolerance_m: float = ZONE_TOLERANCE_M) -> set[tuple[int, int]]:
    return {k for k, m in inside.items() if m > tolerance_m}
