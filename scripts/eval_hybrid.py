"""The road graph from the map against the graph read from the photo, on 16 photos, with the same scenarios: no paid calls.

For each photo (the four bundled ones and the twelve squares of eval/CITIES.md) both graphs are built from cached answers: the SAM
road mask (as before) and the OpenStreetMap ways (© OpenStreetMap contributors, ODbL). Then:
  - how much road each graph has, and what share of random points of the photo lie within 80 m of it (an address a plan can serve);
  - how much of the OSM graph the photo confirms (the road mask follows it), how much lies under water;
  - the same random scenarios (a drawn zone, 8-40 orders at random points, 1-4 trucks, a deadline) planned on both graphs by the
    agent with its deterministic policy: how many end verified, how many need a relaxation, and for the map graph how much of the
    driving is on roads the photo does not confirm.
Writes eval/HYBRID.md and eval/hybrid.json.

Usage: uv run python scripts/eval_hybrid.py [N=8 scenarios per photo]
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter

import numpy as np
from scipy.spatial import cKDTree

from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import PolicyDecider
from orbitroute.areas import ensure_area
from orbitroute.config import ROOT, Settings
from orbitroute.eval.runner import World, build_scenario
from orbitroute.eval.scenarios import EvalScenario
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.evidence import annotate
from orbitroute.perception.flood import flood_zones, segment_floods
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.osm import osm_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.pipeline import get_sample
from orbitroute.understanding.scene import Scene
from orbitroute.verifier.independent import audit_plan

BUNDLED = ["columbus", "memphis", "houston-harvey", "houston-harvey-b"]
CITIES = [
    (41.8827, -87.6278), (40.6782, -73.9442), (33.0198, -96.6989), (33.4152, -111.8315), (29.7330, -95.2420), (33.8400, -84.3800),
    (47.6800, -122.3000), (39.7392, -104.9903), (34.0522, -118.2437), (45.5231, -122.6765), (44.9778, -93.2650), (25.7617, -80.1918),
]
DEADLINES = ["11:00", "12:00", "13:00", "15:00"]
SNAP_M = 80.0


def coverage(graph, points: np.ndarray) -> float:
    """Share of `points` (pixels) within 80 m of a node of the graph."""
    d, _ = cKDTree(graph.nodes).query(points)
    return float((d * graph.m_per_px <= SNAP_M).mean())


def scenarios(photo: str, n: int, flood: bool, rng: random.Random) -> list[EvalScenario]:
    out = []
    for i in range(n):
        size = rng.uniform(250, 600)
        x, y = rng.uniform(0, 1536 - size), rng.uniform(0, 1536 - size)
        out.append(EvalScenario(
            f"hy-{photo}-{i}", photo, rng.randint(8, 40), rng.randint(1, 4), rng.choice(DEADLINES), ("flooded",) if flood and rng.random() < 0.5 else (),
            seed=rng.randint(0, 99), capacity=rng.choice([None, 10, 15]),
            zone=((x, y), (x + size, y), (x + size, y + size), (x, y + size)), anywhere=rng.random() < 0.5,
        ))
    return out


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, False)  # cached answers only
    client = MetaClient(s, guard)
    run = guard.new_run(1.0)
    names = BUNDLED + [ensure_area(lat, lon).name for lat, lon in CITIES]
    rng = random.Random(11)
    rows, t0 = [], time.perf_counter()
    for name in names:
        sm = get_sample(name)
        mpp, size = sm.meta["m_per_px"], sm.meta["width_px"]
        mask = segment_roads(client, sm.image_bytes, run=run)
        sam = build_road_graph(mask, mpp)
        omap = osm_graph(name, sm.meta)
        zones = []
        if sm.meta.get("event"):
            zones = flood_zones(segment_floods(client, sm.image_bytes, run=run), mpp)
        evidence = annotate(omap, mask, zones)
        total = sum(evidence.values()) or 1.0
        pts = np.random.default_rng(5).uniform(0, size, (4000, 2))
        row = {
            "photo": name, "sam_km": sam.stats["road_km"], "osm_km": omap.stats["road_km"], "osm_pieces": omap.stats["pieces_kept"], "osm_track_km": omap.stats["track_km"],
            "sam_covers": coverage(sam, pts), "osm_covers": coverage(omap, pts),
            "seen": evidence.get("seen", 0) / total, "unseen": evidence.get("unseen", 0) / total, "water": evidence.get("water", 0) / total, "runs": {},
        }
        scene = Scene(size, size, zones, [])
        for kind, graph in (("sam", sam), ("osm", omap)):
            world = World(graph, scene, None)
            res = Counter()
            driven = flagged = water = 0.0
            audit_bad = 0
            for sc in scenarios(name, n, bool(zones), random.Random(f"{name}-{n}")):
                try:
                    scenario = build_scenario(world, sc)
                except ValueError:  # no room for that many orders on this graph: a refusal, reported
                    res["refused"] += 1
                    continue
                out = run_agent(scenario, decider=PolicyDecider(), time_limit_s=1.0)
                res[out.status] += 1
                if out.status in ("verified", "verified_partial"):
                    m = out.report.metrics
                    driven += m["total_km"] * 1000
                    flagged += m.get("flagged_m", 0)
                    water += m.get("risk_m", {}).get("water", 0)
                    audit_bad += not audit_plan(out.scenario, out.plan, excluded=out.report.excluded).ok
            row["runs"][kind] = {**dict(res), "driven_m": round(driven), "flagged_m": round(flagged), "water_m": round(water), "audit_failures": audit_bad}
        rows.append(row)
        r = row["runs"]
        print(f"{name:18s} km sam {row['sam_km']:5.1f} osm {row['osm_km']:5.1f} | covers sam {row['sam_covers']:.0%} osm {row['osm_covers']:.0%} | seen {row['seen']:.0%} | verified sam {r['sam'].get('verified', 0)}/{n} osm {r['osm'].get('verified', 0)}/{n} ({time.perf_counter() - t0:.0f}s)", flush=True)
        (ROOT / "eval" / "hybrid.json").write_text(json.dumps(rows, indent=1))

    mean = lambda key: float(np.mean([r[key] for r in rows]))
    ok = lambda kind: sum(r["runs"][kind].get("verified", 0) + r["runs"][kind].get("verified_partial", 0) for r in rows)
    ran = lambda kind: sum(sum(v for k, v in r["runs"][kind].items() if k in ("verified", "verified_partial", "needs_relaxation", "unresolved")) for r in rows)
    lines = [
        "# The map as the road graph, the photo as evidence", "",
        "Generated by `scripts/eval_hybrid.py`. Both graphs are built for the same 16 photos (the four bundled ones and the twelve 1.5 km squares of `eval/CITIES.md`): the roads SAM 3.1 reads",
        "from the photo, and the ways of OpenStreetMap (© OpenStreetMap contributors, ODbL) that a truck can use. The same random scenarios (a zone drawn on the photo, 8-40 orders at random",
        f"points, 1-4 trucks, a deadline; {n} per photo; flooded areas avoided on the Houston photos half of the time) are planned on both by the agent with its deterministic policy, no model calls.", "",
        "| Photo | Road, SAM graph | Road, map graph | Points within 80 m of the road, SAM / map | Map road the photo confirms | not found in the mask | under water | Verified plans, SAM / map |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['photo']} | {r['sam_km']:.1f} km | {r['osm_km']:.1f} km | {r['sam_covers']:.0%} / {r['osm_covers']:.0%} | {r['seen']:.0%} | {r['unseen']:.0%} | {r['water']:.0%} | {r['runs']['sam'].get('verified', 0) + r['runs']['sam'].get('verified_partial', 0)} / {r['runs']['osm'].get('verified', 0) + r['runs']['osm'].get('verified_partial', 0)} of {n} |")
    flagged = sum(r["runs"]["osm"]["flagged_m"] for r in rows)
    driven = sum(r["runs"]["osm"]["driven_m"] for r in rows) or 1
    lines += [
        "", f"Mean over the photos: SAM graph {mean('sam_km'):.1f} km, map graph {mean('osm_km'):.1f} km; points within 80 m of the road {mean('sam_covers'):.0%} (SAM) against {mean('osm_covers'):.0%} (map); the photo confirms {mean('seen'):.0%} of the map's roads.",
        f"Plans that ended verified (or verified with some orders left out): {ok('sam')} of {ran('sam')} on the SAM graph, {ok('osm')} of {ran('osm')} on the map graph. On the map graph {flagged / driven:.0%} of the driving ran on roads the photo does not confirm.",
        f"Independent audit of the returned plans: {sum(r['runs']['sam']['audit_failures'] for r in rows)} failures on the SAM graph, {sum(r['runs']['osm']['audit_failures'] for r in rows)} on the map graph.", "",
        "Limits: the map is the source of the graph here, so there is no independent yardstick for it in this table (the earlier tables used it as the yardstick for the SAM graph); a verified plan is valid by the map, and one-way streets are not enforced",
        "(the graph is undirected). \"Not found in the road mask\" mixes trees, shadow and real problems; SAM finds about half of the streets of a city photo. Random scenarios, not real requests.", "",
    ]
    (ROOT / "eval" / "HYBRID.md").write_text("\n".join(lines))
    print("\n".join(lines[-6:]))


if __name__ == "__main__":
    main()
