"""User-placed inputs: a depot, orders and an avoided zone, placed by clicking on the map.

Everything arrives in image pixels. Points are snapped to the nearest road node; the notes describe
anything the user should know about (snapping, a count that differs from the request text).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field
from shapely.geometry import Polygon

from orbitroute.perception.graph import RoadGraph
from orbitroute.routing.scenario import Scenario, make_scenario
from orbitroute.understanding.constraints import Problem, with_order_count
from orbitroute.understanding.scene import Scene, Zone

MAX_ORDERS = 100
MAX_ZONE_VERTICES = 40
MAX_SNAP_M = 150.0  # a point further than this from any road cannot be served


Num = Annotated[float, Field(allow_inf_nan=False)]
Point = tuple[Num, Num]


class CustomInputs(BaseModel):
    depot: Point | None = None
    orders: list[Point] = Field(default_factory=list, max_length=MAX_ORDERS)
    zone: list[Point] = Field(default_factory=list, max_length=MAX_ZONE_VERTICES)

    @property
    def empty(self) -> bool:
        return self.depot is None and not self.orders and not self.zone


def _in_bounds(p: Point, scene: Scene) -> bool:
    return 0 <= p[0] <= scene.width and 0 <= p[1] <= scene.height


def _snap(graph: RoadGraph, p: Point, what: str) -> tuple[int, float]:
    node, dist_m = graph.nearest_node(*p)
    if dist_m > MAX_SNAP_M:
        raise ValueError(f"The {what} is {dist_m:.0f} m from the nearest road the agent found (limit {MAX_SNAP_M:.0f} m). Place it closer to a road; the Graph layer shows the roads it found.")
    return node, dist_m


def apply_custom(graph: RoadGraph, scene: Scene, problem: Problem, custom: CustomInputs, seed: int = 0) -> tuple[Scenario, Problem, Scene, list[str]]:
    """Returns the scenario, the (possibly adjusted) problem and scene, and notes for the user."""
    notes: list[str] = []
    for p in [*custom.orders, *custom.zone, *([custom.depot] if custom.depot else [])]:
        if not _in_bounds(p, scene):
            raise ValueError("A point lies outside the image.")

    if custom.zone:
        if len(custom.zone) < 3:
            raise ValueError("An avoided zone needs at least 3 corners.")
        poly = Polygon(custom.zone)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon" or poly.area < 100:
            raise ValueError("The avoided zone you drew is degenerate; draw it again.")
        scene = Scene(scene.width, scene.height, [*scene.zones, Zone("custom", poly)], scene.warehouses)
        if "custom" not in problem.avoid_zone_kinds:
            problem = problem.model_copy(update={"avoid_zone_kinds": [*problem.avoid_zone_kinds, "custom"]})
        notes.append("Trucks must also avoid the zone you drew.")

    depot_node = None
    if custom.depot:
        depot_node, d = _snap(graph, custom.depot, "depot")
        if scene.kinds_at(*graph.nodes[depot_node]) & set(problem.avoid_zone_kinds):
            raise ValueError("The depot is inside an avoided zone; move it outside.")
        if d > 25:
            notes.append(f"Depot snapped {d:.0f} m to the nearest road.")

    if custom.orders:
        nodes, snaps = [], []
        for i, p in enumerate(custom.orders, 1):
            node, d = _snap(graph, p, f"order {i}")
            nodes.append(node)
            snaps.append(d)
        if depot_node is None:
            from orbitroute.routing.scenario import pick_depot

            depot_node = pick_depot(graph, scene, problem)
        if problem.n_orders != len(nodes):
            notes.append(f"Using the {len(nodes)} orders you placed instead of the {problem.n_orders} in the request.")
        problem = with_order_count(problem, len(nodes))
        if max(snaps) > 25:
            notes.append(f"Some orders were snapped to the nearest road (up to {max(snaps):.0f} m).")
        scenario = Scenario(graph, scene, problem, depot_node=depot_node, order_nodes=nodes, seed=seed)
    else:
        scenario = make_scenario(graph, scene, problem, seed=seed, depot_node=depot_node)
    return scenario, problem, scene, notes
