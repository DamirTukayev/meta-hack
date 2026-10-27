"""A second, separately written audit of a plan, used to check the verifier itself.

`checks.verify` is the verifier the agent runs. If the evaluation judged plans with the same code, a bug in it would pass
unnoticed on both sides. This module re-derives the same six verdicts a different way: from the polylines of the
route legs with shapely (exact intersection with the zone polygons, nothing precomputed per edge) and from the edge list
of the graph instead of the networkx copy. It shares no code with `checks` or `routing.zones`; the differential tests and
the evaluation compare the two.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString
from shapely.ops import unary_union

from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan

ZONE_TOLERANCE_M = 10.0  # a road segment may touch a zone by this much (polygon outlines are approximate)
KINDS = ("coverage", "fleet", "capacity", "paths", "deadline", "zones")


@dataclass
class Audit:
    failed: dict[str, list[str]] = field(default_factory=dict)  # kind -> reasons

    @property
    def ok(self) -> bool:
        return not self.failed

    def fails(self, kind: str) -> bool:
        return kind in self.failed


def audit_plan(scenario: Scenario, plan: Plan, *, excluded: dict[int, str] | None = None) -> Audit:
    excluded = excluded or {}
    p, g = scenario.problem, scenario.graph
    mpp = g.m_per_px
    out: dict[str, list[str]] = {}

    def fail(kind: str, why: str) -> None:
        out.setdefault(kind, []).append(why)

    # coverage: each wanted order exactly once, nothing else
    served = [s.order for r in plan.routes for s in r.stops]
    wanted = set(range(1, len(scenario.order_nodes) + 1)) - set(excluded)
    if set(served) != wanted or len(served) != len(set(served)):
        fail("coverage", f"served {sorted(served)} but wanted {sorted(wanted)}")

    used = [r for r in plan.routes if r.stops]
    if len(used) > p.n_vehicles:
        fail("fleet", f"{len(used)} trucks used of {p.n_vehicles}")

    # the fastest edge between two nodes is the one a route would use
    fastest: dict[tuple[int, int], float] = {}
    for e in g.edges:
        speed = e.speed_kmh / 3.6
        for key in ((e.u, e.v), (e.v, e.u)):
            fastest[key] = max(fastest.get(key, 0.0), speed)

    zone = unary_union([z.polygon for z in scenario.scene.zones_of(p.avoid_zone_kinds)]) if p.avoid_zone_kinds else None

    for r in used:
        if len(r.stops) > p.capacity:
            fail("capacity", f"truck {r.vehicle} carries {len(r.stops)} of {p.capacity}")
        stops = [scenario.depot_node, *(s.node for s in r.stops), scenario.depot_node]
        clock = float(r.start_s)
        if clock < p.shift_start_s:
            fail("deadline", f"truck {r.vehicle} leaves before the shift starts")
        for leg_no, (a, b) in enumerate(zip(stops, stops[1:])):
            path = r.legs[leg_no] if leg_no < len(r.legs) else []
            steps = list(zip(path, path[1:]))
            if not path or path[0] != a or path[-1] != b or any((u, v) not in fastest for u, v in steps):
                fail("paths", f"truck {r.vehicle} leg {leg_no + 1} is not a chain of road segments")
                continue
            for u, v in steps:
                (x1, y1), (x2, y2) = g.nodes[u], g.nodes[v]
                metres = math.hypot(x2 - x1, y2 - y1) * mpp
                clock += metres / fastest[(u, v)]
                if zone is not None and LineString([(x1, y1), (x2, y2)]).intersection(zone).length * mpp > ZONE_TOLERANCE_M:
                    fail("zones", f"truck {r.vehicle} drives through an avoided zone on segment {u}-{v}")
            if leg_no < len(r.stops):
                clock += p.service_s
        if clock > p.deadline_s:
            fail("deadline", f"truck {r.vehicle} is back at {clock:.0f} s, after {p.deadline_s} s")
    return Audit(out)


def disagreements(report, audit: Audit) -> list[str]:
    """Kinds on which the verifier (`checks.verify` report) and this audit give different verdicts."""
    verifier_failed = {v.kind for v in report.violations}
    return [k for k in KINDS if (k in verifier_failed) != audit.fails(k)]
