"""Capacitated VRP with time windows, solved with PyVRP over a precomputed cost matrix."""

from __future__ import annotations

import time
import warnings
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
    legs: list[list[int]] = field(default_factory=list)  # graph-node path of each leg: depot->s1, s1->s2, ..., sN->depot


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


def solve_vrp(
    scenario: Scenario,
    matrix: CostMatrix,
    *,
    time_limit_s: float = 3.0,
    seed: int = 0,
    excluded: frozenset[int] = frozenset(),
) -> Plan:
    """`excluded` orders (matrix rows) are left out of the model, e.g. ones that cannot be reached legally."""
    p = scenario.problem
    n = len(scenario.order_nodes)
    included = [i for i in range(1, n + 1) if i not in excluded]
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
    for i in included:
        m.add_client(
            locs[i],
            delivery=[1],
            service_duration=p.service_s,
            tw_early=p.shift_start_s,
            tw_late=p.deadline_s - p.service_s,
        )
    rows = [0, *included]
    for a in rows:
        for b in rows:
            m.add_edge(locs[a], locs[b], distance=int(matrix.dist_m[a, b]), duration=int(matrix.time_s[a, b]))

    t0 = time.perf_counter()
    with warnings.catch_warnings():  # PyVRP warns when an instance is infeasible; the verifier reports that properly
        warnings.simplefilter("ignore")
        result = m.solve(stop=MaxRuntime(time_limit_s), display=False, seed=seed)
    elapsed = time.perf_counter() - t0

    sol = result.best
    routes: list[Route] = []
    for k, r in enumerate(sol.routes()):
        stops = [
            Stop(
                order=included[a.idx],  # PyVRP numbers clients 0..k-1 in the order they were added
                node=matrix.nodes[included[a.idx]],
                arrive_s=int(a.start_time),
                leave_s=int(a.end_time),
            )
            for a in r.schedule()
            if a.type == ActivityType.CLIENT
        ]
        seq = [0, *(st.order for st in stops), 0]
        routes.append(
            Route(
                vehicle=k,
                stops=stops,
                legs=[matrix.paths.get((a, b), []) for a, b in zip(seq, seq[1:])],
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
        unserved=[i for i in included if i not in served],
    )
