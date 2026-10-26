"""When a request cannot be met as stated: find the smallest relaxation that works, with a verified plan."""

from __future__ import annotations

from dataclasses import dataclass, replace

from orbitroute.routing.matrix import CostMatrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, solve_vrp
from orbitroute.understanding.constraints import seconds_to_hhmm
from orbitroute.verifier.checks import Report, verify

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


def find_relaxations(
    scenario: Scenario,
    matrix: CostMatrix,
    excluded: dict[int, str],
    inside: dict,
    *,
    time_limit_s: float = 1.5,
    seed: int = 0,
) -> list[RelaxationOption]:
    """Smallest verified relaxations, one per dimension: more trucks, or a later deadline."""
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
    return options
