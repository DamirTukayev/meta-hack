"""End to end (no verification yet): image + request text -> routes on a map.

Usage: uv run python scripts/plan.py columbus "40 orders, 3 trucks, by 12:00, avoid the industrial zone" [--seed 0]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.overlay import draw_plan
from orbitroute.perception.segment import segment_roads
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.scenario import make_scenario
from orbitroute.routing.solver import solve_vrp
from orbitroute.understanding.constraints import seconds_to_hhmm
from orbitroute.understanding.request import parse_request
from orbitroute.understanding.scene import analyze_scene


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("request")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("scratch"))
    a = ap.parse_args()

    path = Path("data/samples") / f"{a.name}.jpg"
    image_bytes = path.read_bytes()
    meta = json.loads(path.with_suffix(".json").read_text())
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
    client = MetaClient(s, guard)
    run = guard.new_run(s.run_cap_usd)

    mask = segment_roads(client, image_bytes, run=run)
    graph = build_road_graph(mask, meta["m_per_px"])
    scene = analyze_scene(client, image_bytes, run=run)
    problem = parse_request(client, a.request, run=run)
    print("PROBLEM", problem.model_dump_json(indent=1))

    scenario = make_scenario(graph, scene, problem, seed=a.seed)
    matrix = build_matrix(graph, scenario.location_nodes)  # first pass: no zone bans
    plan = solve_vrp(scenario, matrix)
    print(f"PyVRP feasible={plan.feasible} served={plan.served}/{problem.n_orders} "
          f"routes={len(plan.routes)} solve={plan.solve_seconds:.1f}s unreachable_pairs={len(matrix.unreachable)}")
    for r in plan.routes:
        print(f"  truck {r.vehicle}: {len(r.stops)} stops, {r.distance_m / 1000:.1f} km, "
              f"{seconds_to_hhmm(r.start_s)}-{seconds_to_hhmm(r.end_s)}, time_warp={r.time_warp_s}s")
    avoid = scene.zones_of(problem.avoid_zone_kinds)
    a.out.mkdir(exist_ok=True)
    out = a.out / f"plan_{a.name}.jpg"
    draw_plan(Image.open(path), graph, scenario, plan, matrix, avoid).save(out)
    print(f"run cost ${run.spent:.4f} ({run.calls} paid calls) -> {out}")


if __name__ == "__main__":
    main()
