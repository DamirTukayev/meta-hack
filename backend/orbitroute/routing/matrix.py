"""Travel-time / distance matrices over the road graph, with the actual paths kept for verification."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from orbitroute.perception.graph import RoadGraph
from orbitroute.routing.zones import banned_edges, edge_key, inside_lengths
from orbitroute.understanding.scene import Zone

UNREACHABLE_S = 10**6  # large, still safe for PyVRP's integer arithmetic


def edges_in_zones(graph: RoadGraph, zones: list[Zone]) -> set[tuple[int, int]]:
    """Graph edges that run through the zones (beyond the grazing tolerance)."""
    return banned_edges(inside_lengths(graph, zones))


@dataclass
class CostMatrix:
    nodes: list[int]  # graph node per matrix row (0 = depot, 1..n = orders)
    time_s: np.ndarray  # int, (n+1, n+1)
    dist_m: np.ndarray  # int, (n+1, n+1)
    paths: dict[tuple[int, int], list[int]] = field(default_factory=dict)  # (i, j) -> graph node path
    unreachable: list[tuple[int, int]] = field(default_factory=list)


def build_matrix(graph: RoadGraph, nodes: list[int], banned: set[tuple[int, int]] | None = None) -> CostMatrix:
    g = graph.to_networkx()
    if banned:
        g.remove_edges_from([e for e in banned if g.has_edge(*e)])
    n = len(nodes)
    time_s = np.zeros((n, n), dtype=np.int64)
    dist_m = np.zeros((n, n), dtype=np.int64)
    paths: dict[tuple[int, int], list[int]] = {}
    unreachable: list[tuple[int, int]] = []
    for i, src in enumerate(nodes):
        lengths, routes = nx.single_source_dijkstra(g, src, weight="time_s")
        for j, dst in enumerate(nodes):
            if i == j:
                continue
            if dst not in routes:
                time_s[i, j] = UNREACHABLE_S
                dist_m[i, j] = UNREACHABLE_S
                unreachable.append((i, j))
                continue
            path = routes[dst]
            paths[(i, j)] = path
            time_s[i, j] = int(round(lengths[dst]))
            dist_m[i, j] = int(round(sum(g[a][b]["length_m"] for a, b in zip(path, path[1:]))))
    return CostMatrix(nodes=nodes, time_s=time_s, dist_m=dist_m, paths=paths, unreachable=unreachable)
