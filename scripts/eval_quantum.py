"""Quantum polishing on the fixed evaluation scenarios: CPU only, no model calls.

For every scenario of the main suite (orbitroute.eval.scenarios, built exactly as scripts/run_eval.py builds them) where the agent
returns a verified plan, the plan is polished by brute force (the quality ceiling), simulated annealing, and QAOA at depth 1 and 2
(simulated on CPU with a state vector, not quantum hardware), with three seeds each, from two starting plans:

  strong  the agent's verified plan (PyVRP with the usual 3 s limit)
  weak    the same trucks with the same stops, each route re-ordered greedily by nearest neighbour from the depot, so there is room
          to improve (a 0.05 s PyVRP run was tried first and returned the 3 s plan, so it was not a weak start)

Every polished plan goes through the verifier and the independent audit. The suite states every request as "min_time"; each
scenario is also run with the objective switched to "min_distance", where a shorter segment can arrive later.

The road graphs, scenes and buildings come from the recorded SAM 3.1 / Muse Spark answers for the bundled tiles: the client
here refuses every live call, so a missing recording stops the script instead of spending money.

Usage: uv run python scripts/eval_quantum.py [--limit N] [--sweeps 1000]
Writes eval/QUANTUM.md and eval/quantum.json.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev

from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import PolicyDecider
from orbitroute.eval.runner import build_scenario, load_world
from orbitroute.eval.scenarios import SCENARIOS
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import OfflineClient
from orbitroute.routing.quantum import HARDWARE_NOTE, path_cost, polish_plan
from orbitroute.routing.solver import rebuild_route
from orbitroute.routing.zones import inside_lengths
from orbitroute.verifier.checks import verify
from orbitroute.verifier.independent import audit_plan, disagreements

OUT_MD = Path("eval/QUANTUM.md")
OUT_JSON = Path("eval/quantum.json")
SOLVERS = ["exact", "sa", "qaoa_p1", "qaoa_p2"]
SEEDS = [0, 1, 2]
STRONG_LIMIT_S = 3.0
M_SEG = 4


def nearest_neighbour(plan, scenario, matrix, C):
    """Each truck keeps its stops; their order becomes: from the depot, always the cheapest unvisited stop next."""
    routes = []
    for r in plan.routes:
        left, order, cur = [s.order for s in r.stops], [], 0
        while left:
            nxt = min(left, key=lambda o: (int(C[cur, o]), o))
            order.append(nxt)
            left.remove(nxt)
            cur = nxt
        routes.append(rebuild_route(r, order, scenario, matrix) if r.stops else r)
    return type(plan)(routes, all(r.time_warp_s == 0 for r in routes), 0.0, -1, list(plan.unserved))


def plan_cost(plan, C) -> int:
    return sum(path_cost([s.order for s in r.stops], 0, 0, C) for r in plan.routes if r.stops)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios (for a quick check)")
    ap.add_argument("--sweeps", type=int, default=1000, help="simulated annealing sweeps per read")
    ap.add_argument("--reads", type=int, default=100, help="simulated annealing reads per segment")
    ap.add_argument("--shots", type=int, default=1000, help="QAOA measurement samples per segment")
    ap.add_argument("--report-only", action="store_true", help="rewrite eval/QUANTUM.md from eval/quantum.json without running anything")
    a = ap.parse_args()
    if a.report_only:
        d = json.loads(OUT_JSON.read_text())
        OUT_MD.write_text(report_md(d["meta"], d["plans"], d["segments"]))
        return

    t_start = time.perf_counter()
    client = OfflineClient("eval_quantum.py runs on recorded answers only")
    run = RunBudget(cap_usd=0.0)
    worlds: dict = {}
    segments: list[dict] = []  # one record per polished segment
    plans: list[dict] = []  # one record per polished plan
    skipped: list[dict] = []
    scenarios = SCENARIOS[: a.limit] if a.limit else SCENARIOS
    for sc in scenarios:
        if sc.sample not in worlds:
            worlds[sc.sample] = load_world(client, sc.sample, run)
        base = build_scenario(worlds[sc.sample], sc)
        for objective in ("min_time", "min_distance"):
            scenario = base
            scenario.problem = base.problem.model_copy(update={"objective": objective})
            res = run_agent(scenario, decider=PolicyDecider(), time_limit_s=STRONG_LIMIT_S)
            if res.status not in ("verified", "verified_partial"):
                skipped.append({"scenario": sc.id, "objective": objective, "status": res.status})
                print(f"{sc.id:22s} {objective:12s} {res.status}: skipped")
                continue
            sc_run = res.scenario
            matrix = res.matrix
            C = matrix.time_s if objective == "min_time" else matrix.dist_m
            inside = inside_lengths(sc_run.graph, sc_run.scene.zones_of(sc_run.problem.avoid_zone_kinds))
            weak = nearest_neighbour(res.plan, sc_run, matrix, C)
            starts = {"strong": res.plan, "weak": weak}
            for initial, plan in starts.items():
                start_report = verify(sc_run, plan, excluded=res.excluded, inside=inside)
                for solver in SOLVERS:
                    for seed in [0] if solver == "exact" else SEEDS:
                        polished, rep = polish_plan(plan, sc_run, matrix, solver=solver, m_seg=M_SEG, seed=seed, shots=a.shots, sa_reads=a.reads, sa_sweeps=a.sweeps)
                        report = verify(sc_run, polished, excluded=res.excluded, inside=inside)
                        audit = audit_plan(sc_run, polished, excluded=report.excluded)
                        dis = disagreements(report, audit)
                        key = {"scenario": sc.id, "objective": objective, "initial": initial, "solver": solver, "seed": seed}
                        plans.append({
                            **key, "orders": sc.n_orders, "initial_ok": start_report.ok, "segments": len(rep.segments), "accepted": rep.accepted,
                            "cost_before": rep.cost_before, "cost_after": rep.cost_after, "verifier_ok": report.ok,
                            "failed_checks": [c.kind for c in report.checks if not c.passed], "audit_ok": audit.ok, "disagreements": dis,
                            "seconds": round(rep.seconds, 3),
                        })
                        for s in rep.segments:
                            segments.append({
                                **key, "vehicle": s.vehicle, "orders": s.orders, "orders_after": s.orders_after, "start": s.start, "end": s.end,
                                "qubits": s.qubits, "feasible_share": round(s.feasible_share, 4), "found_optimum": s.found_optimum,
                                "cost_before": s.cost_before, "cost_after": s.cost_after, "best_found_cost": s.best_found_cost,
                                "optimum_cost": s.optimum_cost, "accepted": s.accepted, "seconds": round(s.seconds, 4),
                                "p_feasible_exact": None if s.p_feasible_exact is None else round(s.p_feasible_exact, 4),
                                "params_transferred": s.params_transferred,
                            })
            print(f"{sc.id:22s} {objective:12s} strong {plan_cost(res.plan, C)} weak {plan_cost(weak, C)}  {time.perf_counter() - t_start:6.0f}s")

    elapsed = time.perf_counter() - t_start
    meta = {
        "note": HARDWARE_NOTE, "m_seg": M_SEG, "seeds": SEEDS, "strong_limit_s": STRONG_LIMIT_S,
        "sa_reads": a.reads, "sa_sweeps": a.sweeps, "qaoa_shots": a.shots, "penalty_factor": 2.0, "seconds": round(elapsed, 1),
        "scenarios": len(scenarios), "skipped": skipped, "python": platform.python_version(), "machine": platform.machine(), "cpu": platform.processor(),
    }
    OUT_JSON.write_text(json.dumps({"meta": meta, "plans": plans, "segments": segments}, separators=(",", ":")))
    OUT_MD.write_text(report_md(meta, plans, segments))
    print(f"done in {elapsed:.0f} s: {len(plans)} polished plans, {len(segments)} segments -> {OUT_MD}, {OUT_JSON}")


def ms(values: list[float], fmt: str) -> str:
    """mean ± standard deviation over the seeds (just the value when there is one seed)."""
    if len(values) == 1:
        return format(values[0], fmt)
    return f"{format(mean(values), fmt)} ± {format(pstdev(values), fmt)}"


def report_md(meta: dict, plans: list[dict], segments: list[dict]) -> str:
    seg_by = defaultdict(list)
    for s in segments:
        seg_by[(s["objective"], s["initial"], s["solver"], s["seed"])].append(s)
    plan_by = defaultdict(list)
    for p in plans:
        plan_by[(p["objective"], p["initial"], p["solver"], p["seed"])].append(p)

    n_scen = {obj: len({p["scenario"] for p in plans if p["objective"] == obj}) for obj in ("min_time", "min_distance")}
    lines = [
        "# Quantum polishing on the evaluation scenarios",
        "",
        f"**{meta['note']}.** Every QAOA number below comes from an exact state-vector simulation on a CPU; no quantum hardware and no cloud",
        "service was used. Simulated annealing and brute force run on the same CPU.",
        "",
        "What was run: the verified plans of the fixed evaluation suite (`orbitroute/eval/scenarios.py`, the 62 scenarios of",
        "`scripts/run_eval.py`, built by the same code) are cut into anchored segments of at most "
        f"{meta['m_seg']} stops ({meta['m_seg'] ** 2} qubits); each segment is re-ordered by a path QUBO and replaced only when its",
        "travel cost goes down; the polished plan then goes through the same verifier and the independent audit.",
        "",
        f"- Scenarios with a verified plan: {n_scen['min_time']} of {meta['scenarios']} as stated (`min_time`), {n_scen['min_distance']} with the objective switched to `min_distance`. The others end without a verified plan (mostly `needs_relaxation`), so there is nothing to polish.",
        f"- Starting plans: **strong** = the agent's verified plan (PyVRP, {meta['strong_limit_s']:.0f} s); **weak** = the same trucks with the same stops, each route re-ordered by nearest neighbour from the depot (a PyVRP run with a 0.05 s limit was tried first and returned the same plan as the 3 s run, so it gave nothing to improve).",
        f"- Solvers: `exact` (brute force over the m! orders, the quality ceiling), `sa` ({meta['sa_reads']} reads × {meta['sa_sweeps']} sweeps), `qaoa_p1`, `qaoa_p2` ({meta['qaoa_shots']} shots; angles by a 12 × 8 grid + COBYLA, optimised once per segment size per plan and reused for the other segments of that size). Penalty A = {meta['penalty_factor']} × the largest arc cost of the segment.",
        f"- Seeds {', '.join(map(str, meta['seeds']))} for `sa` and QAOA (QAOA angles are deterministic; the seed changes the measurement samples). Values are mean ± standard deviation over the seeds.",
        f"- Total run time: {meta['seconds'] / 60:.1f} min on {meta['machine']} (Python {meta['python']}), single process.",
        "",
    ]
    for obj in ("min_time", "min_distance"):
        unit = "travel time" if obj == "min_time" else "distance"
        lines += [
            f"## Objective `{obj}` (cost = {unit})",
            "",
            "| solver | initial | segments | qubits/segment | P_feas | optimum found, % | accepted swaps | cost change, % | verifier reverts | s/segment |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for initial in ("strong", "weak"):
            for solver in SOLVERS:
                seeds = [0] if solver == "exact" else meta["seeds"]
                rows_s = [seg_by[(obj, initial, solver, sd)] for sd in seeds]
                rows_p = [plan_by[(obj, initial, solver, sd)] for sd in seeds]
                if not rows_p[0]:
                    continue
                nseg = [len(r) for r in rows_s]
                qub = [mean(s["qubits"] for s in r) for r in rows_s]
                pfe = [mean(s["feasible_share"] for s in r) for r in rows_s]
                opt = [100 * mean(s["found_optimum"] for s in r) for r in rows_s]
                acc = [sum(s["accepted"] for s in r) for r in rows_s]
                chg = [100 * (sum(p["cost_after"] for p in r) - sum(p["cost_before"] for p in r)) / sum(p["cost_before"] for p in r) for r in rows_p]
                rev = [sum(1 for p in r if p["initial_ok"] and not p["verifier_ok"]) for r in rows_p]
                sps = [mean(s["seconds"] for s in r) for r in rows_s]
                pf = "— (no sampling)" if solver == "exact" else ms(pfe, ".3f")
                lines.append(f"| {solver} | {initial} | {ms(nseg, '.0f')} | {ms(qub, '.1f')} | {pf} | {ms(opt, '.1f')} | {ms(acc, '.1f')} | {ms(chg, '.3f')} | {ms(rev, '.1f')} | {ms(sps, '.4f')} |")
        lines.append("")

    # what the verifier rejected
    rejected = [p for p in plans if p["initial_ok"] and not p["verifier_ok"]]
    weak_bad = len({(p["scenario"], p["objective"]) for p in plans if p["initial"] == "weak" and not p["initial_ok"]})
    lines += ["## What the verifier rejected", ""]
    if rejected:
        by = Counter((p["objective"], c) for p in rejected for c in p["failed_checks"])
        lines += ["| objective | failed check | polished plans |", "|---|---|---|"]
        lines += [f"| {o} | {c} | {n} |" for (o, c), n in sorted(by.items())]
        lines.append("")
        lines.append(f"{len(rejected)} of {sum(p['initial_ok'] for p in plans)} polished plans (whose starting plan passed) failed the verifier; in the product the agent would revert them to the classical plan.")
    else:
        lines.append(f"None: all {sum(p['initial_ok'] for p in plans)} polished plans whose starting plan passed the verifier passed it again.")
        lines.append("")
        lines.append(
            "This was expected to differ under `min_distance`, where a segment that is shorter in metres can take longer and push a truck past"
            " the deadline; on these scenarios it never did. The revert path (verifier rejects the polished plan, the agent keeps the classical"
            " one and logs `revert_quantum`) is therefore exercised only by a unit test (`test_failed_polish_is_reverted_to_the_classical_plan`),"
            " not by this evaluation."
        )
    if weak_bad:
        lines.append(f"Not counted as reverts: {weak_bad} weak (nearest-neighbour) starting plans already failed the verifier before polishing.")
    lines.append("")

    n_dis = sum(1 for p in plans if p["disagreements"])
    lines += [
        "## Verifier vs. independent audit",
        "",
        f"On all {len(plans)} polished plans the verifier and the independent audit (`verifier/independent.py`) disagreed on {n_dis}.",
        "",
    ]

    qaoa = [s for s in segments if s["solver"].startswith("qaoa") and s["p_feasible_exact"] is not None]
    if qaoa:
        lines += ["## QAOA: probability of a valid order, by segment size", "", "| solver | qubits | segments | P_feas (samples) | P_feas (exact, from the state) | optimum found, % |", "|---|---|---|---|---|---|"]
        for solver in ("qaoa_p1", "qaoa_p2"):
            for q in sorted({s["qubits"] for s in qaoa}):
                r = [s for s in qaoa if s["solver"] == solver and s["qubits"] == q]
                if r:
                    lines.append(f"| {solver} | {q} | {len(r)} | {mean(s['feasible_share'] for s in r):.3f} | {mean(s['p_feasible_exact'] for s in r):.3f} | {100 * mean(s['found_optimum'] for s in r):.1f} |")
        lines += ["", "A random 16-bit string is a valid 4 × 4 permutation matrix with probability 24/65536 ≈ 0.0004, 3 × 3: 6/512 ≈ 0.012, 2 × 2: 2/16 = 0.125.", ""]

    lines += [
        "## Limits",
        "",
        "- QAOA is simulated exactly on a CPU (state vector); a real device adds noise and readout error, so these P_feas values are an upper bound for the same circuits.",
        f"- Segments are at most {meta['m_seg']} stops (16 qubits) with both ends fixed: polishing can only re-order stops inside a segment, never move a stop between segments or trucks, so it cannot fix what the segmentation does not see.",
        "- The scenarios are synthetic: fixed random orders on four bundled aerial tiles (two USGS NAIP, two NOAA flood imagery), road graphs read from recorded SAM 3.1 masks; the deadline is shared by all orders.",
        "- One author built the scenarios, the solvers and this evaluation; nothing was tuned on these numbers, and every scenario with a verified plan is reported.",
        "",
        "Reproduce: `uv run python scripts/eval_quantum.py` (CPU only, no API key needed). Raw per-segment records: `eval/quantum.json`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
