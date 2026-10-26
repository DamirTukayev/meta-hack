"""Ground zones and warehouses on a sample image with Muse Spark (cached) and print a summary."""

import sys
from pathlib import Path

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.understanding.scene import analyze_scene

s = Settings.load()
guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
client = MetaClient(s, guard)
run = guard.new_run(s.run_cap_usd)
path = Path("data/samples") / f"{sys.argv[1]}.jpg"
scene = analyze_scene(client, path.read_bytes(), run=run)
print(f"{len(scene.zones)} zones, {len(scene.warehouses)} warehouses, run cost ${run.spent:.4f}")
for z in scene.zones:
    print(f"  {z.kind:12s} area={z.polygon.area / (scene.width * scene.height):.1%}")
