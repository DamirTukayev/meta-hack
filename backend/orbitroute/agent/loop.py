"""The agent loop: plan -> solve -> verify -> (repair -> re-solve)*, bounded by iterations and budget."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from orbitroute.agent.events import Emit, Event, silent
from orbitroute.agent.relax import RelaxationOption, find_relaxations
from orbitroute.agent.repair import Decider, DecisionContext, PolicyDecider
from orbitroute.llm.budget import BudgetExceeded
from orbitroute.routing.matrix import CostMatrix, build_matrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, solve_vrp
from orbitroute.routing.zones import banned_edges, inside_lengths
from orbitroute.verifier.checks import Report, verify

MAX_ITERATIONS = 5


@dataclass
class Iteration:
    n: int
    plan: Plan
    report: Report
    action: str | None = None  # the repair applied after this iteration
    reason: str | None = None
    decided_by: str | None = None


@dataclass
class AgentResult:
    status: str  # verified | verified_partial | needs_relaxation | unresolved
    scenario: Scenario  # the scenario the final plan belongs to (relaxed, if a relaxation was applied)
    plan: Plan
    report: Report
    matrix: CostMatrix
    iterations: list[Iteration]
    excluded: dict[int, str]
    relaxations: list[RelaxationOption] = field(default_factory=list)
    seconds: float = 0.0


def run_agent(
    scenario: Scenario,
    *,
    decider: Decider | None = None,
    emit: Emit = silent,
    max_iterations: int = MAX_ITERATIONS,
    time_limit_s: float = 3.0,
    verify_plan: bool = True,
) -> AgentResult:
    """verify_plan=False is the 'no verifier' ablation: one solve, returned as is."""
    decider = decider or PolicyDecider()
    t0 = time.perf_counter()
    p = scenario.problem
    avoid = scenario.scene.zones_of(p.avoid_zone_kinds)
    inside = inside_lengths(scenario.graph, avoid)
    zone_edges = banned_edges(inside)
    banned: set[tuple[int, int]] = set()
    excluded: dict[int, str] = {}
    history: list[str] = []
    iterations: list[Iteration] = []
    time_limit, seed = time_limit_s, 0

    emit(Event("start", f"{p.n_orders} orders, {p.n_vehicles} trucks, avoiding {p.avoid_zone_kinds or 'nothing'}", {"problem": p.model_dump()}))

    plan, report = None, None
    for it in range(max_iterations + 1):
        matrix = build_matrix(scenario.graph, scenario.location_nodes, banned)
        unreachable = sorted({j for i, j in matrix.unreachable if i == 0 and j not in excluded})  # orders the depot cannot reach
        emit(Event("matrix", f"travel times over the road graph ({len(banned)} segments forbidden)", {"banned": len(banned), "unreachable_orders": unreachable}))
        plan = solve_vrp(scenario, matrix, time_limit_s=time_limit, seed=seed, excluded=frozenset(excluded))
        emit(Event("solve", f"solve #{it + 1}: {plan.served} orders on {len(plan.routes)} trucks in {plan.solve_seconds:.1f}s", {"iteration": it + 1, "served": plan.served, "routes": len(plan.routes)}, obj=(plan, matrix)))
        if not verify_plan:
            return AgentResult("unverified", scenario, plan, verify(scenario, plan, excluded=excluded, inside=inside), matrix, iterations, excluded, seconds=time.perf_counter() - t0)

        report = verify(scenario, plan, excluded=excluded, inside=inside)
        iterations.append(Iteration(it + 1, plan, report))
        emit(Event("verify", f"verification: {sum(c.passed for c in report.checks)}/{len(report.checks)} checks passed", {"ok": report.ok, "checks": [c.__dict__ for c in report.checks], "violations": [v.message for v in report.violations]}, obj=report))
        if report.ok:
            status = "verified_partial" if excluded else "verified"
            emit(Event("final", f"plan verified{' (some orders excluded)' if excluded else ''}", {"status": status, "metrics": report.metrics}))
            return AgentResult(status, scenario, plan, report, matrix, iterations, excluded, seconds=time.perf_counter() - t0)
        if it == max_iterations:
            break

        ctx = DecisionContext(report, it + 1, list(history), unreachable, all_zone_edges_banned=zone_edges <= banned)
        try:
            decision = decider.decide(ctx)
        except BudgetExceeded as exc:
            emit(Event("final", f"stopped: {exc}", {"status": "unresolved"}))
            break
        history.append(decision.action)
        iterations[-1].action, iterations[-1].reason, iterations[-1].decided_by = decision.action, decision.reason, decision.source
        emit(Event("decision", f"{decision.action}: {decision.reason}", {"action": decision.action, "reason": decision.reason, "source": decision.source}))

        if decision.action == "ban_violating_edges":
            new = {e for v in report.of_kind("zones") for e in v.data["edges"]}
            banned |= new
            emit(Event("repair", f"forbidding {len(new)} road segments that entered the zone", {"edges": len(new)}))
        elif decision.action == "ban_all_zone_edges":
            banned |= zone_edges
            emit(Event("repair", f"forbidding all {len(zone_edges)} road segments inside the zone", {"edges": len(zone_edges)}))
        elif decision.action == "exclude_unreachable":
            for o in unreachable:
                excluded[o] = "cannot be reached without entering an avoided zone"
            emit(Event("repair", f"leaving out {len(unreachable)} unreachable order(s): {unreachable}", {"orders": unreachable}))
        elif decision.action == "resolve_longer":
            time_limit, seed = time_limit * 2, seed + 1
            emit(Event("repair", f"re-solving with a {time_limit:.0f}s limit and seed {seed}", {}))
        elif decision.action == "propose_relaxation":
            options = find_relaxations(scenario, matrix, excluded, inside)
            for o in options:
                emit(Event("relaxation", f"smallest fix: {o.description}", {"kind": o.kind, "amount": o.amount}))
            if options:
                best = options[0]
                return AgentResult("needs_relaxation", best.scenario, best.plan, best.report, matrix, iterations, excluded, options, time.perf_counter() - t0)
            emit(Event("final", "no relaxation within limits makes this feasible", {"status": "unresolved"}))
            break

    return AgentResult("unresolved", scenario, plan, report, matrix, iterations, excluded, seconds=time.perf_counter() - t0)
