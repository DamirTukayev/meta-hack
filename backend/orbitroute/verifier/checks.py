"""Independent plan verifier.

It trusts neither the solver, nor the cost matrix, nor the language model: from the plan it takes only
the stop order and the graph path of every leg, and recomputes times, lengths, loads and zone
crossings directly from the road graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orbitroute.perception.graph import FLAGGED
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan
from orbitroute.routing.zones import ZONE_TOLERANCE_M, edge_key, inside_lengths

# A link the road graph drew itself across a gap between two pieces of found road. Short ones are tree shadows and crossings;
# longer ones are a guess that the photo does not show, so a plan that drives on them says so (it is a note, not a failed check).
UNCONFIRMED_MIN_M = 30.0

CHECK_NAMES = {
    "coverage": "Every order is served exactly once",
    "fleet": "Fleet size is respected",
    "capacity": "Truck capacity is respected",
    "paths": "Every leg follows real roads",
    "deadline": "All work finishes before the deadline",
    "zones": "Avoided zones are not entered",
}


@dataclass
class Violation:
    kind: str  # one of CHECK_NAMES
    message: str
    route: int | None = None
    data: dict = field(default_factory=dict)


@dataclass
class Check:
    kind: str
    title: str
    passed: bool
    detail: str


@dataclass
class Report:
    checks: list[Check]
    violations: list[Violation]
    metrics: dict
    excluded: dict[int, str] = field(default_factory=dict)
    unconfirmed: list[tuple[int, int]] = field(default_factory=list)  # driven graph edges the photo does not show directly
    flagged: list[tuple[int, int, str]] = field(default_factory=list)  # driven map roads the photo does not confirm, with the reason

    @property
    def ok(self) -> bool:
        return not self.violations

    def of_kind(self, kind: str) -> list[Violation]:
        return [v for v in self.violations if v.kind == kind]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.kind] = out.get(v.kind, 0) + 1
        return out


def _fmt_clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


def verify(
    scenario: Scenario,
    plan: Plan,
    *,
    excluded: dict[int, str] | None = None,
    inside: dict[tuple[int, int], float] | None = None,
) -> Report:
    """`excluded` maps orders that were knowingly left out (with the reason) to their explanation."""
    excluded = excluded or {}
    p = scenario.problem
    g = scenario.graph.to_networkx()
    if inside is None:
        inside = inside_lengths(scenario.graph, scenario.scene.zones_of(p.avoid_zone_kinds))
    violations: list[Violation] = []

    # coverage: every non-excluded order exactly once, nothing unknown
    n = len(scenario.order_nodes)
    counts: dict[int, int] = {}
    for r in plan.routes:
        for s in r.stops:
            counts[s.order] = counts.get(s.order, 0) + 1
    wanted = [i for i in range(1, n + 1) if i not in excluded]
    missing = [i for i in wanted if counts.get(i, 0) == 0]
    dup = [i for i, c in counts.items() if c > 1]
    unknown = [i for i in counts if i < 1 or i > n or i in excluded]
    if missing:
        violations.append(Violation("coverage", f"{len(missing)} order(s) not served: {missing[:10]}", data={"missing": missing}))
    if dup:
        violations.append(Violation("coverage", f"order(s) served more than once: {dup}", data={"duplicate": dup}))
    if unknown:
        violations.append(Violation("coverage", f"plan contains unknown or excluded orders: {unknown}", data={"unknown": unknown}))

    # fleet
    used = [r for r in plan.routes if r.stops]
    if len(used) > p.n_vehicles:
        violations.append(Violation("fleet", f"{len(used)} trucks used, only {p.n_vehicles} available", data={"used": len(used)}))

    total_m = 0.0
    unconfirmed_m = 0.0
    unconfirmed: set[tuple[int, int]] = set()
    risk_m: dict[str, float] = {}
    flagged: dict[tuple[int, int], str] = {}
    latest_end = 0.0
    route_metrics = []
    for r in plan.routes:
        if not r.stops:
            continue
        # capacity (every order is one unit)
        if len(r.stops) > p.capacity:
            violations.append(
                Violation("capacity", f"truck {r.vehicle}: {len(r.stops)} units, capacity {p.capacity}", route=r.vehicle, data={"load": len(r.stops)})
            )

        # re-simulate the route on the real graph
        seq = [scenario.depot_node, *(s.node for s in r.stops), scenario.depot_node]
        t = float(r.start_s)
        if r.start_s < p.shift_start_s:
            violations.append(Violation("deadline", f"truck {r.vehicle} leaves at {_fmt_clock(r.start_s)}, before the shift start", route=r.vehicle))
        route_m = 0.0
        zone_hits: list[dict] = []
        first_late: int | None = None
        for leg_idx, (a, b) in enumerate(zip(seq, seq[1:])):
            path = r.legs[leg_idx] if leg_idx < len(r.legs) else []
            if not path or path[0] != a or path[-1] != b or any(not g.has_edge(u, v) for u, v in zip(path, path[1:])):
                violations.append(
                    Violation("paths", f"truck {r.vehicle}: leg {leg_idx + 1} is not a connected road path", route=r.vehicle, data={"leg": leg_idx, "from": a, "to": b})
                )
                continue
            for u, v in zip(path, path[1:]):
                t += g[u][v]["time_s"]
                route_m += g[u][v]["length_m"]
                if g[u][v].get("bridge") and g[u][v]["length_m"] > UNCONFIRMED_MIN_M:
                    unconfirmed_m += g[u][v]["length_m"]
                    unconfirmed.add(edge_key(u, v))
                risk = g[u][v].get("risk", "seen")
                if risk in FLAGGED:
                    risk_m[risk] = risk_m.get(risk, 0.0) + g[u][v]["length_m"]
                    flagged[edge_key(u, v)] = risk
                m_in = inside.get(edge_key(u, v), 0.0)
                if m_in > ZONE_TOLERANCE_M:
                    zone_hits.append({"edge": edge_key(u, v), "inside_m": m_in, "leg": leg_idx})
            if leg_idx < len(r.stops):  # service at the stop we just reached
                t += p.service_s
                if t > p.deadline_s and first_late is None:
                    first_late = leg_idx + 1
        if t > p.deadline_s:
            where = f"stop {first_late}" if first_late else "the return to the depot"
            violations.append(
                Violation(
                    "deadline",
                    f"truck {r.vehicle} finishes at {_fmt_clock(t)}, {(t - p.deadline_s) / 60:.0f} min after {_fmt_clock(p.deadline_s)} (first late at {where})",
                    route=r.vehicle,
                    data={"end_s": t, "over_s": t - p.deadline_s, "first_late_stop": first_late},
                )
            )
        if zone_hits:
            edges = sorted({h["edge"] for h in zone_hits})
            inside_m = sum(h["inside_m"] for h in zone_hits)
            violations.append(
                Violation(
                    "zones",
                    f"truck {r.vehicle} drives {inside_m:.0f} m through an avoided zone ({len(edges)} road segments)",
                    route=r.vehicle,
                    data={"edges": edges, "inside_m": inside_m},
                )
            )
        total_m += route_m
        latest_end = max(latest_end, t)
        route_metrics.append({"truck": r.vehicle, "stops": len(r.stops), "km": round(route_m / 1000, 2), "ends": _fmt_clock(t)})

    by_kind: dict[str, list[Violation]] = {}
    for v in violations:
        by_kind.setdefault(v.kind, []).append(v)
    details = {
        "coverage": f"{len(wanted) - len(missing)}/{len(wanted)} orders served" + (f", {len(excluded)} excluded with reasons" if excluded else ""),
        "fleet": f"{len(used)}/{p.n_vehicles} trucks used",
        "capacity": f"max load {max((len(r.stops) for r in plan.routes), default=0)}/{p.capacity}",
        "paths": "all legs are connected road paths" if "paths" not in by_kind else f"{len(by_kind['paths'])} broken leg(s)",
        "deadline": f"last truck back at {_fmt_clock(latest_end)} (deadline {_fmt_clock(p.deadline_s)})" if route_metrics else "no routes",
        "zones": "no avoided zone entered" if "zones" not in by_kind else f"{sum(v.data['inside_m'] for v in by_kind['zones']):.0f} m inside avoided zones",
    }
    checks = [Check(k, title, k not in by_kind, details[k]) for k, title in CHECK_NAMES.items()]
    metrics = {
        "total_km": round(total_m / 1000, 2), "last_return": _fmt_clock(latest_end), "routes": route_metrics,
        "unconfirmed_m": round(unconfirmed_m), "unconfirmed_share": round(unconfirmed_m / total_m, 3) if total_m else 0.0,
        "risk_m": {k: round(v) for k, v in sorted(risk_m.items())}, "flagged_m": round(sum(risk_m.values())),
        "flagged_share": round(sum(risk_m.values()) / total_m, 3) if total_m else 0.0,
    }
    return Report(
        checks=checks, violations=violations, metrics=metrics, excluded=dict(excluded), unconfirmed=sorted(unconfirmed),
        flagged=sorted((a, b, r) for (a, b), r in flagged.items()),
    )
