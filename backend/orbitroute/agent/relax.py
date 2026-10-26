"""When a request cannot be met as stated: find the smallest relaxation that works, with a verified plan."""

from __future__ import annotations

from dataclasses import dataclass, replace

from orbitroute.routing.matrix import CostMatrix, build_matrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, solve_vrp
from orbitroute.routing.zones import edge_key
from orbitroute.understanding.constraints import seconds_to_hhmm
from orbitroute.verifier.checks import Check, Report, verify

DEADLINE_STEP_S = 15 * 60
MAX_EXTRA_VEHICLES = 3
MAX_EXTRA_DEADLINE_S = 4 * 3600


@dataclass
class RelaxationOption:
    kind: str  # add_vehicles | extend_deadline
    amount: int  # trucks, or seconds
    description: str
    scenario: Scenario
    plan: Plan
    report: Report


def _try(scenario: Scenario, matrix: CostMatrix, excluded: dict[int, str], inside, time_limit_s: float, seed: int):
    plan = solve_vrp(scenario, matrix, time_limit_s=time_limit_s, seed=seed, excluded=frozenset(excluded))
    report = verify(scenario, plan, excluded=excluded, inside=inside)
    return plan, report


def _through_m(scenario: Scenario, plan: Plan, inside: dict) -> float:
    """Metres of the plan's roads that lie inside the zones the request wanted avoided."""
    g = scenario.graph.to_networkx()
    return sum(inside.get(edge_key(a, b), 0.0) for r in plan.routes for leg in r.legs for a, b in zip(leg, leg[1:]) if g.has_edge(a, b))


def _mark_zone_relaxed(report: Report, through_m: float) -> Report:
    """In a plan that stopped avoiding the zone the zone check is vacuous: say so instead of showing a green tick."""
    report.checks = [
        Check(c.kind, c.title + " (relaxed)", False, f"avoidance switched off in this option: the plan drives {through_m:.0f} m through the zone") if c.kind == "zones" else c
        for c in report.checks
    ]
    return report


def find_relaxations(
    scenario: Scenario,
    matrix: CostMatrix,
    excluded: dict[int, str],
    inside: dict,
    *,
    time_limit_s: float = 1.5,
    seed: int = 0,
    zone_edges: set | None = None,
) -> list[RelaxationOption]:
    """Smallest verified relaxations, one per dimension: more trucks, a later deadline, or entering the zone."""
    options: list[RelaxationOption] = []
    p = scenario.problem

    for extra in range(1, MAX_EXTRA_VEHICLES + 1):
        sc = replace(scenario, problem=p.model_copy(update={"n_vehicles": p.n_vehicles + extra}))
        plan, report = _try(sc, matrix, excluded, inside, time_limit_s, seed)
        if report.ok:
            options.append(
                RelaxationOption("add_vehicles", extra, f"use {p.n_vehicles + extra} trucks instead of {p.n_vehicles}", sc, plan, report)
            )
            break

    # smallest deadline extension, by bisection in 15-minute steps (feasibility is monotone in the deadline)
    top = MAX_EXTRA_DEADLINE_S // DEADLINE_STEP_S

    def with_deadline(k: int):
        sc = replace(scenario, problem=p.model_copy(update={"deadline_s": p.deadline_s + k * DEADLINE_STEP_S}))
        plan, report = _try(sc, matrix, excluded, inside, time_limit_s, seed)
        return report.ok, sc, plan, report

    ok, sc, plan, report = with_deadline(top)
    if ok:
        best, lo, hi = (top, sc, plan, report), 0, top  # k=0 is the original, known to fail
        while hi - lo > 1:
            mid = (lo + hi) // 2
            ok, sc, plan, report = with_deadline(mid)
            if ok:
                best, hi = (mid, sc, plan, report), mid
            else:
                lo = mid
        k, sc, plan, report = best
        options.append(
            RelaxationOption(
                "extend_deadline",
                k * DEADLINE_STEP_S,
                f"move the deadline from {seconds_to_hhmm(p.deadline_s)} to {seconds_to_hhmm(sc.problem.deadline_s)}",
                sc,
                plan,
                report,
            )
        )

    # stop avoiding the zones: the only fix when orders are reachable solely through them
    if p.avoid_zone_kinds and zone_edges:
        free_problem = p.model_copy(update={"avoid_zone_kinds": []})
        sc = replace(scenario, problem=free_problem)
        free_matrix = build_matrix(sc.graph, sc.location_nodes)
        plan = solve_vrp(sc, free_matrix, time_limit_s=time_limit_s, seed=seed)
        report = verify(sc, plan, excluded={}, inside={})
        kinds = " and ".join("drawn" if k == "custom" else k for k in p.avoid_zone_kinds)
        if report.ok:
            m = _through_m(scenario, plan, inside)
            options.append(RelaxationOption("allow_zone", int(m), f"stop avoiding the {kinds} zone (the plan drives {m:.0f} m through it)", sc, plan, _mark_zone_relaxed(report, m)))
        else:
            # the zone is not the only problem: combine with the smallest other relaxation in the zone-free world
            for other in find_relaxations(sc, free_matrix, {}, {}, time_limit_s=time_limit_s, seed=seed, zone_edges=None):
                m = _through_m(scenario, other.plan, inside)
                options.append(
                    RelaxationOption(f"allow_zone+{other.kind}", other.amount, f"stop avoiding the {kinds} zone and {other.description} (the plan drives {m:.0f} m through the zone)", other.scenario, other.plan, _mark_zone_relaxed(other.report, m))
                )
                break
    return options
