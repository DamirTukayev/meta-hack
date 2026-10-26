"""A concrete problem instance: a road graph, a depot, and order locations on it."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from orbitroute.perception.graph import RoadGraph
from orbitroute.understanding.constraints import Problem
from orbitroute.understanding.scene import Scene

# Where deliveries tend to be: houses and shops, rarely parks, never in an avoided zone.
KIND_WEIGHT = {"residential": 3.0, "commercial": 2.0, "other": 1.0, "park_forest": 0.3, "industrial": 1.0}


@dataclass
class Scenario:
    graph: RoadGraph
    scene: Scene
    problem: Problem
    depot_node: int
    order_nodes: list[int]  # graph node of each order
    seed: int

    @property
    def location_nodes(self) -> list[int]:
        """Node list used for matrices: index 0 is the depot, 1..n are the orders."""
        return [self.depot_node, *self.order_nodes]


def _blocked(scene: Scene, problem: Problem, x: float, y: float) -> bool:
    return bool(scene.kinds_at(x, y) & set(problem.avoid_zone_kinds))


def pick_depot(graph: RoadGraph, scene: Scene, problem: Problem) -> int:
    """A warehouse outside the avoided zones, closest to the image centre; else the node nearest the centre."""
    cx, cy = scene.width / 2, scene.height / 2
    allowed = [w for w in scene.warehouses if not _blocked(scene, problem, *w)]
    if allowed:
        x, y = min(allowed, key=lambda w: math.dist(w, (cx, cy)))
        return graph.nearest_node(x, y)[0]
    free = [i for i, (x, y) in enumerate(graph.nodes) if not _blocked(scene, problem, x, y)]
    if not free:
        raise ValueError("every road node lies in an avoided zone")
    return min(free, key=lambda i: math.dist(graph.nodes[i], (cx, cy)))


def make_scenario(graph: RoadGraph, scene: Scene, problem: Problem, seed: int = 0, min_sep_m: float = 90.0) -> Scenario:
    """Place `problem.n_orders` synthetic orders on road nodes, deterministically for a given seed."""
    rng = np.random.default_rng(seed)
    depot = pick_depot(graph, scene, problem)

    candidates, weights = [], []
    for i, (x, y) in enumerate(graph.nodes):
        if i == depot or _blocked(scene, problem, x, y):
            continue
        kinds = scene.kinds_at(x, y) or {"other"}
        candidates.append(i)
        weights.append(max(KIND_WEIGHT.get(k, 1.0) for k in kinds))
    if len(candidates) < problem.n_orders:
        raise ValueError(f"only {len(candidates)} usable road nodes for {problem.n_orders} orders")

    p = np.array(weights) / sum(weights)
    order = list(rng.choice(candidates, size=len(candidates), replace=False, p=p))
    chosen: list[int] = []
    sep_px = min_sep_m / graph.m_per_px
    for node in order:  # greedy: keep orders apart; relax if the area is too small
        if all(math.dist(graph.nodes[node], graph.nodes[c]) >= sep_px for c in chosen):
            chosen.append(int(node))
        if len(chosen) == problem.n_orders:
            break
    for node in order:
        if len(chosen) == problem.n_orders:
            break
        if int(node) not in chosen:
            chosen.append(int(node))
    return Scenario(graph=graph, scene=scene, problem=problem, depot_node=depot, order_nodes=chosen, seed=seed)
