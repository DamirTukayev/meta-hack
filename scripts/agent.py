"""Run the full agent on a sample image: plan, verify, repair, re-solve. Prints the agent log.

Usage: uv run python scripts/agent.py columbus "40 orders, 3 trucks, by 12:00, avoid the industrial zone" [--seed 0] [--policy]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import ModelDecider, PolicyDecider
from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.overlay import draw_plan
from orbitroute.perception.segment import segment_concept
from orbitroute.routing.scenario import make_scenario
from orbitroute.understanding.request import parse_request
from orbitroute.understanding.scene import analyze_scene

ICON = {"start": "▶", "matrix": "·", "solve": "◆", "verify": "✓", "decision": "?", "repair": "↻", "relaxation": "≈", "final": "■"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("request")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--policy", action="store_true", help="use the deterministic policy instead of Muse Spark for repair decisions")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("scratch"))
    a = ap.parse_args()

    path = Path("data/samples") / f"{a.name}.jpg"
    image_bytes = path.read_bytes()
    meta = json.loads(path.with_suffix(".json").read_text())
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
    client = MetaClient(s, guard)
    run = guard.new_run(s.run_cap_usd)

    graph = build_road_graph(segment_concept(client, image_bytes, "road", run=run), meta["m_per_px"])
    scene = analyze_scene(client, image_bytes, run=run)
    problem = parse_request(client, a.request, run=run)
    for note in problem.assumptions:
        print("  assumption:", note)
    scenario = make_scenario(graph, scene, problem, seed=a.seed)

    decider = PolicyDecider() if a.policy else ModelDecider(client, run)
    result = run_agent(scenario, decider=decider, verify_plan=not a.no_verify,
                       emit=lambda e: print(f"{ICON.get(e.type, '-')} [{e.type}] {e.message}"))

    print(f"\nSTATUS {result.status} in {result.seconds:.1f}s | run cost ${run.spent:.4f} ({run.calls} paid calls)")
    for c in result.report.checks:
        print(f"  {'PASS' if c.passed else 'FAIL'}  {c.title}: {c.detail}")
    for o in result.relaxations:
        print(f"  relaxation: {o.description}")
    if result.excluded:
        print("  excluded orders:", result.excluded)
    a.out.mkdir(exist_ok=True)
    avoid = result.scenario.scene.zones_of(result.scenario.problem.avoid_zone_kinds)
    draw_plan(Image.open(path), graph, result.scenario, result.plan, result.matrix, avoid).save(a.out / f"agent_{a.name}_final.jpg")
    print("saved", a.out / f"agent_{a.name}_final.jpg")


if __name__ == "__main__":
    main()
