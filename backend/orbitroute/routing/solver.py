"""Capacitated VRP with time windows, solved with PyVRP over a precomputed cost matrix."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pyvrp import ActivityType, Model
from pyvrp.stop import MaxRuntime

from orbitroute.routing.matrix import CostMatrix
from orbitroute.routing.scenario import Scenario


@dataclass
class Stop:
    order: int  # 1-based order index (matrix row)
    node: int
    arrive_s: int
    leave_s: int


@dataclass
class Route:
    vehicle: int
    stops: list[Stop]
    start_s: int
    end_s: int
    distance_m: int
    time_warp_s: int  # > 0 means PyVRP could not honour a time window on this route


@dataclass
class Plan:
    routes: list[Route]
    feasible: bool  # PyVRP's own verdict, NOT the verification result
    solve_seconds: float
    cost: int
    unserved: list[int] = field(default_factory=list)

    @property
    def served(self) -> int:
        return sum(len(r.stops) for r in self.routes)


def solve_vrp(scenario: Scenario, matrix: CostMatrix, *, time_limit_s: float = 3.0, seed: int = 0) -> Plan:
    p = scenario.problem
    n = len(scenario.order_nodes)
    m = Model()
    locs = [m.add_location(*map(float, scenario.graph.nodes[node])) for node in matrix.nodes]
    depot = m.add_depot(locs[0], tw_early=p.shift_start_s, tw_late=p.deadline_s)
    m.add_vehicle_type(
        p.n_vehicles,
        capacity=[p.capacity],
        start_depot=depot,
        end_depot=depot,
        tw_early=p.shift_start_s,
        tw_late=p.deadline_s,
        unit_distance_cost=1 if p.objective == "min_distance" else 0,
        unit_duration_cost=1 if p.objective == "min_time" else 0,
    )
    for i in range(1, n + 1):
        m.add_client(
            locs[i],
            delivery=[1],
            service_duration=p.service_s,
            tw_early=p.shift_start_s,
            tw_late=p.deadline_s - p.service_s,
        )
    for a in range(n + 1):
        for b in range(n + 1):
            m.add_edge(locs[a], locs[b], distance=int(matrix.dist_m[a, b]), duration=int(matrix.time_s[a, b]))

    t0 = time.perf_counter()
    result = m.solve(stop=MaxRuntime(time_limit_s), display=False, seed=seed)
    elapsed = time.perf_counter() - t0

    sol = result.best
    routes: list[Route] = []
    for k, r in enumerate(sol.routes()):
        stops = [
            Stop(
                order=a.idx + 1,  # PyVRP numbers clients from 0; matrix row 0 is the depot
                node=matrix.nodes[a.idx + 1],
                arrive_s=int(a.start_time),
                leave_s=int(a.end_time),
            )
            for a in r.schedule()
            if a.type == ActivityType.CLIENT
        ]
        routes.append(
            Route(
                vehicle=k,
                stops=stops,
                start_s=int(r.start_time()),
                end_s=int(r.end_time()),
                distance_m=int(r.distance()),
                time_warp_s=int(r.time_warp()),
            )
        )
    served = {s.order for r in routes for s in r.stops}
    return Plan(
        routes=routes,
        feasible=bool(result.is_feasible()),
        solve_seconds=elapsed,
        cost=int(result.cost()) if result.is_feasible() else -1,
        unserved=[i for i in range(1, n + 1) if i not in served],
    )
