"""Run the evaluation: agent with the verifier vs. the same solver without it, plus request-parsing accuracy."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import mean

from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import ModelDecider, PolicyDecider
from orbitroute.custom import CustomInputs, apply_custom
from orbitroute.eval.parse_cases import CASES
from orbitroute.eval.scenarios import SCENARIOS, EvalScenario
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.pipeline import get_sample
from orbitroute.routing.scenario import make_scenario
from orbitroute.understanding.constraints import ParsedRequest, hhmm_to_seconds, resolve
from orbitroute.understanding.request import parse_request
from orbitroute.understanding.scene import analyze_scene


@dataclass
class World:
    graph: object
    scene: object


def load_world(client: MetaClient, name: str, run) -> World:
    s = get_sample(name)
    graph = build_road_graph(segment_roads(client, s.image_bytes, run=run), s.meta["m_per_px"])
    return World(graph, analyze_scene(client, s.image_bytes, run=run))


def build_scenario(world: World, sc: EvalScenario):
    # Depot rule of the product: the warehouse that can reach the most road without entering an avoided zone. The older rule
    # (warehouse nearest the image centre) often boxed the depot in behind the zone, so orders could only be reached through it.
    parsed = ParsedRequest(
        n_orders=sc.n_orders, n_vehicles=sc.n_vehicles, deadline=sc.deadline, shift_start=sc.shift_start,
        vehicle_capacity=sc.capacity, avoid_zone_kinds=list(sc.avoid),
    )
    problem = resolve(parsed)
    if sc.zone:
        scenario, *_ = apply_custom(world.graph, world.scene, problem, CustomInputs(zone=list(sc.zone)), seed=sc.seed, prefer_connected=True, ensure_reachable=not sc.anywhere)
        return scenario
    return make_scenario(world.graph, world.scene, problem, seed=sc.seed, prefer_connected=True)


def run_scenarios(client: MetaClient, guard: BudgetGuard, *, time_limit_s: float = 2.0, model_decider_on: int = 6, log=print) -> list[dict]:
    run = guard.new_run(5.0)
    worlds: dict[str, World] = {}
    rows: list[dict] = []
    model_used = 0
    for sc in SCENARIOS:
        if sc.sample not in worlds:
            worlds[sc.sample] = load_world(client, sc.sample, run)
        scenario = build_scenario(worlds[sc.sample], sc)
        res = run_agent(scenario, decider=PolicyDecider(), time_limit_s=time_limit_s)
        first = res.iterations[0]
        row = {
            "id": sc.id, "sample": sc.sample, "orders": sc.n_orders, "trucks": sc.n_vehicles, "deadline": sc.deadline,
            "avoid": list(sc.avoid) or (["drawn zone"] if sc.zone else []), "expect": sc.expect,
            # baseline = the first solve, exactly what the pipeline would return without a verifier
            "baseline_solver_feasible": first.plan.feasible,
            "baseline_audit_ok": first.report.ok,
            "baseline_violations": first.report.summary(),
            "agent_status": res.status,
            "agent_iterations": len(res.iterations),
            "agent_actions": [i.action for i in res.iterations if i.action],
            "excluded_orders": len(res.excluded),
            "relaxations": [o.description for o in res.relaxations],
            "final_report_ok": res.report.ok,
            "seconds": round(res.seconds, 1),
        }
        if not first.report.ok and model_used < model_decider_on:
            before = run.spent
            mres = run_agent(scenario, decider=ModelDecider(client, run), time_limit_s=time_limit_s)
            model_used += 1
            row["model_decider"] = {"status": mres.status, "actions": [i.action for i in mres.iterations if i.action], "iterations": len(mres.iterations), "cost_usd": round(run.spent - before, 4)}
        rows.append(row)
        log(f"{sc.id:22s} baseline_ok={row['baseline_audit_ok']!s:5} -> {row['agent_status']:17s} iters={row['agent_iterations']} {row['seconds']}s")
    return rows


def summarize_scenarios(rows: list[dict]) -> dict:
    n = len(rows)
    claims_ok = [r for r in rows if r["baseline_solver_feasible"]]
    invalid = [r for r in claims_ok if not r["baseline_audit_ok"]]
    kinds: dict[str, int] = {}
    for r in rows:
        for k, c in r["baseline_violations"].items():
            kinds[k] = kinds.get(k, 0) + 1
    with_violation = [r for r in rows if not r["baseline_audit_ok"]]
    repaired = [r for r in with_violation if r["agent_status"] in ("verified", "verified_partial")]
    infeasible = [r for r in rows if r["expect"] == "infeasible"]
    detected = [r for r in infeasible if r["agent_status"] == "needs_relaxation"]
    verified_final = [r for r in rows if r["agent_status"] in ("verified", "verified_partial")]
    models = [r["model_decider"] for r in rows if "model_decider" in r]
    return {
        "scenarios": n,
        "baseline": {
            "solver_says_feasible": len(claims_ok),
            "invalid_after_independent_audit": len(invalid),
            "invalid_rate_among_claimed_feasible": round(len(invalid) / len(claims_ok), 3) if claims_ok else None,
            "violation_kinds_in_scenarios": kinds,
        },
        "agent": {
            "status_counts": {s: sum(r["agent_status"] == s for r in rows) for s in sorted({r["agent_status"] for r in rows})},
            "scenarios_with_a_first_pass_violation": len(with_violation),
            "of_those_ended_verified": len(repaired),
            "mean_iterations": round(mean(r["agent_iterations"] for r in rows), 2),
            "mean_seconds": round(mean(r["seconds"] for r in rows), 1),
            "final_plan_passes_audit": sum(r["final_report_ok"] for r in rows),
            "provably_infeasible": len(infeasible),
            "infeasible_correctly_flagged": len(detected),
            "verified_but_partial": sum(r["agent_status"] == "verified_partial" for r in rows),
        },
        "model_decider": {
            "runs": len(models),
            "reached_verified": sum(m["status"] in ("verified", "verified_partial") for m in models),
            "mean_cost_usd": round(mean(m["cost_usd"] for m in models), 4) if models else None,
        },
        "verified_scenarios": len(verified_final),
    }


# ---------- request parsing ----------

FIELDS = ["n_orders", "n_vehicles", "vehicle_capacity", "shift_start", "deadline", "service_minutes", "avoid", "objective"]


def _actual(problem) -> dict:
    """Compare against what the user said, not against defaults: assumptions mark the fields that were defaulted."""
    said = problem.assumptions
    return {
        "n_orders": problem.n_orders,
        "n_vehicles": problem.n_vehicles,
        "vehicle_capacity": None if any("carries" in a for a in said) else problem.capacity,
        "shift_start": None if any("leave the depot" in a for a in said) else _hhmm(problem.shift_start_s),
        "deadline": None if any("finished by" in a for a in said) else _hhmm(problem.deadline_s),
        "service_minutes": None if any("Each stop takes" in a for a in said) else problem.service_s / 60,
        "avoid": set(problem.avoid_zone_kinds),
        "objective": problem.objective,
    }


def _hhmm(s: int) -> str:
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


def run_parse_eval(client: MetaClient, guard: BudgetGuard, log=print, prompt_version: str | None = None) -> dict:
    run = guard.new_run(2.0)
    results = []
    for text, expected in CASES:
        want = {"n_orders": None, "n_vehicles": None, "vehicle_capacity": None, "shift_start": None, "deadline": None,
                "service_minutes": None, "avoid": set(), "objective": "min_time", **expected}
        t0 = time.perf_counter()
        try:
            got = _actual(parse_request(client, text, run=run, prompt_version=prompt_version))
            error = None
        except Exception as exc:  # a parse failure counts as all fields wrong
            got, error = {}, str(exc)
        wrong = {f: (want[f], got.get(f)) for f in FIELDS if got.get(f) != want[f]}
        results.append({"text": text, "ok": not wrong, "wrong": {k: [str(a), str(b)] for k, (a, b) in wrong.items()}, "error": error, "seconds": round(time.perf_counter() - t0, 1)})
        log(f"{'OK ' if not wrong else 'BAD'} {text[:70]}{'' if not wrong else '  ' + str(results[-1]['wrong'])}")
    n_fields = len(CASES) * len(FIELDS)
    wrong_fields = sum(len(r["wrong"]) if r["error"] is None else len(FIELDS) for r in results)
    return {
        "cases": len(CASES),
        "exact_match_cases": sum(r["ok"] for r in results),
        "field_accuracy": round(1 - wrong_fields / n_fields, 3),
        "mean_seconds": round(mean(r["seconds"] for r in results), 1),
        "cost_usd": round(run.spent, 4),
        "failures": [r for r in results if not r["ok"]],
    }
