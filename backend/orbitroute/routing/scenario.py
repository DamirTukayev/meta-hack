"""A concrete problem instance: a road graph, a depot, and order locations on it."""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx
import numpy as np

from orbitroute.perception.graph import RoadGraph
from orbitroute.routing.zones import banned_edges, inside_lengths
from orbitroute.understanding.constraints import Problem
from orbitroute.understanding.scene import Scene

# Where deliveries tend to be: houses and shops, rarely parks, never in an avoided zone.
MAX_TARGET_SNAP_M = 80.0  # a building further than this from every usable road node is not a delivery address
BUILDING_SEP_M = 35.0  # deliveries to neighbouring houses are fine, but not to the same one twice
KIND_WEIGHT = {"residential": 3.0, "commercial": 2.0, "other": 1.0, "park_forest": 0.3, "industrial": 1.0}


@dataclass
class Scenario:
    graph: RoadGraph
    scene: Scene
    problem: Problem
    depot_node: int
    order_nodes: list[int]  # graph node of each order
    seed: int
    order_targets: list[tuple[float, float] | None] | None = None  # the building each order belongs to, where known (image pixels)

    @property
    def location_nodes(self) -> list[int]:
        """Node list used for matrices: index 0 is the depot, 1..n are the orders."""
        return [self.depot_node, *self.order_nodes]


def _blocked(scene: Scene, problem: Problem, x: float, y: float) -> bool:
    return bool(scene.kinds_at(x, y) & set(problem.avoid_zone_kinds))


def _legal_component_sizes(graph: RoadGraph, scene: Scene, problem: Problem) -> dict[int, int]:
    """For every road node: how many nodes its connected piece of road has once the avoided zones are closed."""
    g = graph.to_networkx()
    banned = banned_edges(inside_lengths(graph, scene.zones_of(problem.avoid_zone_kinds)))
    g.remove_edges_from([e for e in banned if g.has_edge(*e)])
    return {n: len(c) for c in nx.connected_components(g) for n in c}


def pick_depot(graph: RoadGraph, scene: Scene, problem: Problem, prefer_connected: bool = False) -> int:
    """A warehouse outside the avoided zones, closest to the image centre; else the node nearest the centre.

    With prefer_connected the depot is where the trucks can legally reach the most road (a warehouse if the photo has one,
    else a staging point on the largest dry piece of the network; ties: nearest the centre), so a depot boxed in by the
    avoided zone does not squeeze every order into one pocket.
    """
    cx, cy = scene.width / 2, scene.height / 2
    allowed = [w for w in scene.warehouses if not _blocked(scene, problem, *w)]
    if prefer_connected and problem.avoid_zone_kinds:
        sizes = _legal_component_sizes(graph, scene, problem)
        if allowed:
            nodes = [graph.nearest_node(x, y)[0] for x, y in allowed]
            best = min(zip(nodes, allowed), key=lambda na: (-sizes.get(na[0], 0), math.dist(na[1], (cx, cy))))
            return best[0]
        free = [i for i, (x, y) in enumerate(graph.nodes) if not _blocked(scene, problem, x, y)]
        if free:
            top = max(sizes.get(i, 0) for i in free)
            return min((i for i in free if sizes.get(i, 0) == top), key=lambda i: math.dist(graph.nodes[i], (cx, cy)))
    if allowed:
        x, y = min(allowed, key=lambda w: math.dist(w, (cx, cy)))
        return graph.nearest_node(x, y)[0]
    free = [i for i, (x, y) in enumerate(graph.nodes) if not _blocked(scene, problem, x, y)]
    if not free:
        raise ValueError("every road node lies in an avoided zone")
    return min(free, key=lambda i: math.dist(graph.nodes[i], (cx, cy)))


def _legally_reachable(graph: RoadGraph, scene: Scene, problem: Problem, depot: int) -> set[int]:
    """Nodes the depot can reach without driving through an avoided zone."""
    g = graph.to_networkx()
    banned = banned_edges(inside_lengths(graph, scene.zones_of(problem.avoid_zone_kinds)))
    g.remove_edges_from([e for e in banned if g.has_edge(*e)])
    return set(nx.node_connected_component(g, depot))


def make_scenario(
    graph: RoadGraph,
    scene: Scene,
    problem: Problem,
    seed: int = 0,
    min_sep_m: float = 90.0,
    ensure_reachable: bool = True,
    depot_node: int | None = None,
    prefer_connected: bool = False,
    targets: list[tuple[float, float]] | None = None,
) -> Scenario:
    """Place `problem.n_orders` synthetic orders on road nodes, deterministically for a given seed.

    With ensure_reachable (default) orders are only placed where a truck can legally get to; turn it off
    to create stress cases with orders that the avoided zone cuts off.
    """
    rng = np.random.default_rng(seed)
    depot = depot_node if depot_node is not None else pick_depot(graph, scene, problem, prefer_connected)
    reachable = _legally_reachable(graph, scene, problem, depot) if ensure_reachable and problem.avoid_zone_kinds else None
    if reachable is not None and len(reachable) - 1 < problem.n_orders:
        reachable = None  # not enough legal nodes: fall back to the whole graph

    candidates, weights = [], []
    for i, (x, y) in enumerate(graph.nodes):
        if i == depot or _blocked(scene, problem, x, y) or (reachable is not None and i not in reachable):
            continue
        kinds = scene.kinds_at(x, y) or {"other"}
        candidates.append(i)
        weights.append(max(KIND_WEIGHT.get(k, 1.0) for k in kinds))
    if len(candidates) < problem.n_orders:
        raise ValueError(f"only {len(candidates)} usable road nodes for {problem.n_orders} orders")

    chosen: list[int] = []
    chosen_targets: dict[int, tuple[float, float]] = {}
    if targets:
        usable = set(candidates)
        pairs: dict[int, tuple[float, float]] = {}
        for x, y in targets:  # a building is served from the nearest road node, if the trucks may use it
            node, dist_m = graph.nearest_node(x, y)
            if dist_m <= MAX_TARGET_SNAP_M and node in usable and node not in pairs:
                pairs[node] = (x, y)
        building_nodes = list(pairs)
        sep_px = BUILDING_SEP_M / graph.m_per_px
        for i in rng.permutation(len(building_nodes)):
            node = building_nodes[int(i)]
            if all(math.dist(graph.nodes[node], graph.nodes[c]) >= sep_px for c in chosen):
                chosen.append(node)
                chosen_targets[node] = pairs[node]
            if len(chosen) == problem.n_orders:
                break

    p = np.array(weights) / sum(weights)
    order = list(rng.choice(candidates, size=len(candidates), replace=False, p=p))
    sep_px = min_sep_m / graph.m_per_px
    for node in order:  # greedy: keep orders apart; relax if the area is too small
        if len(chosen) == problem.n_orders:
            break
        if int(node) not in chosen and all(math.dist(graph.nodes[node], graph.nodes[c]) >= sep_px for c in chosen):
            chosen.append(int(node))
    for node in order:
        if len(chosen) == problem.n_orders:
            break
        if int(node) not in chosen:
            chosen.append(int(node))
    chosen = [int(n) for n in chosen]
    order_targets = [chosen_targets.get(n) for n in chosen] if chosen_targets else None
    return Scenario(graph=graph, scene=scene, problem=problem, depot_node=depot, order_nodes=chosen, seed=seed, order_targets=order_targets)
