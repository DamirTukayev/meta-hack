"""Dirt tracks: does the map graph reach roads that the photo hides? Three forest squares where most of the mapped road is a track.

Reviewers noted that reading roads from an aerial photo misses dirt roads. For three 1.5 km squares whose OpenStreetMap roads are
mostly `highway=track` (© OpenStreetMap contributors, ODbL) this measures, with SAM 3.1 read live once (about $0.45 a square, cached):
  - how much of the mapped track the road graph read from the photo reaches (within 15 m), and how much the road mask follows (within 8 m);
  - how much of the square lies within 80 m of each graph (can a plan serve an address there at all);
  - random scenarios planned on both graphs (verified or not);
  - what Muse Spark says about the longest stretches of track the photo does not confirm: a clear road, standing water, debris, or
    that it cannot tell (the crops are written to a folder so that a person can judge them).
Writes eval/TRACKS.md and eval/tracks.json.

Usage: uv run python scripts/eval_tracks.py [--crops DIR]
"""

from __future__ import annotations

import io
import json
import random
import sys
from collections import Counter
from pathlib import Path

import networkx as nx
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, str(Path(__file__).parent))
from eval_hybrid import coverage, scenarios  # noqa: E402

from orbitroute.agent import inspection  # noqa: E402
from orbitroute.agent.loop import run_agent  # noqa: E402
from orbitroute.agent.repair import PolicyDecider  # noqa: E402
from orbitroute.areas import ensure_area  # noqa: E402
from orbitroute.config import ROOT, Settings  # noqa: E402
from orbitroute.eval.runner import World, build_scenario  # noqa: E402
from orbitroute.llm.budget import BudgetGuard  # noqa: E402
from orbitroute.llm.client import MetaClient, guard_for  # noqa: E402
from orbitroute.perception.evidence import annotate  # noqa: E402
from orbitroute.perception.graph import build_road_graph  # noqa: E402
from orbitroute.perception.osm import osm_graph  # noqa: E402
from orbitroute.perception.segment import segment_roads  # noqa: E402
from orbitroute.pipeline import get_sample  # noqa: E402
from orbitroute.understanding.scene import Scene  # noqa: E402

PLACES = [("Medicine Bow NF, WY", 41.30, -106.30), ("Apalachicola NF, FL", 30.30, -84.90), ("Sam Houston NF, TX", 30.60, -95.30)]
TOL_GRAPH_M, TOL_MASK_M = 15.0, 8.0


def track_points(graph, step_px: float = 5.0) -> np.ndarray:
    pts = []
    for e in graph.edges:
        if e.highway != "track":
            continue
        a, b = graph.nodes[e.u], graph.nodes[e.v]
        n = max(int(np.hypot(*(b - a)) / step_px), 1)
        pts.extend(a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False))
    return np.array(pts)


def reach(graph, mask_dist: np.ndarray, pts: np.ndarray, tol_px: float) -> float:
    xs, ys = np.clip(pts[:, 0].astype(int), 0, mask_dist.shape[1] - 1), np.clip(pts[:, 1].astype(int), 0, mask_dist.shape[0] - 1)
    return float((mask_dist[ys, xs] <= tol_px).mean())


def graph_distance(graph, size: int) -> np.ndarray:
    im = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(im)
    for e in graph.edges:
        d.line([tuple(graph.nodes[e.u]), tuple(graph.nodes[e.v])], fill=255, width=1)
    return distance_transform_edt(np.asarray(im) == 0)


def track_runs(graph, min_m: float = 60.0) -> list[list[tuple[int, int]]]:
    """Connected stretches of unconfirmed track, as paths between their two ends, longest first."""
    ug = nx.Graph([(e.u, e.v) for e in graph.edges if e.highway == "track" and e.risk == "unseen"])
    length = {(e.u, e.v): e.length_m for e in graph.edges}
    length.update({(v, u): m for (u, v), m in length.items()})
    runs = []
    for comp in nx.connected_components(ug):
        sub = ug.subgraph(comp)
        ends = [n for n in sub if sub.degree(n) == 1]
        if len(ends) < 2:
            continue
        a, b = max(((x, y) for x in ends for y in ends if x < y), key=lambda p: nx.shortest_path_length(sub, *p))
        path = nx.shortest_path(sub, a, b)
        edges = list(zip(path, path[1:]))
        if sum(length[e] for e in edges) >= min_m:
            runs.append(edges)
    return sorted(runs, key=lambda r: -sum(length[e] for e in r))


def main() -> None:
    crops_dir = Path(sys.argv[sys.argv.index("--crops") + 1]) if "--crops" in sys.argv else None
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, True)
    client = MetaClient(s, guard)
    looker = MetaClient(s, guard_for(s, "baseten"), provider="baseten")
    run = guard.new_run(3.0)
    spent0 = guard.total_spent()
    rows = []
    for name, lat, lon in PLACES:
        area = ensure_area(lat, lon)
        sm = get_sample(area.name)
        size, mpp = sm.meta["width_px"], sm.meta["m_per_px"]
        mask = segment_roads(client, sm.image_bytes, run=run)
        sam, omap = build_road_graph(mask, mpp), osm_graph(area.name, sm.meta)
        evidence = annotate(omap, mask, [])
        pts = track_points(omap)
        mask_dist = distance_transform_edt(~mask)
        row = {
            "place": name, "area": area.name, "map_km": omap.stats["road_km"], "track_km": omap.stats["track_km"], "sam_km": sam.stats["road_km"],
            "track_reached_by_sam_graph": reach(sam, graph_distance(sam, size), pts, TOL_GRAPH_M / mpp), "track_followed_by_mask": reach(omap, mask_dist, pts, TOL_MASK_M / mpp),
            "covers_sam": coverage(sam, np.random.default_rng(5).uniform(0, size, (4000, 2))), "covers_map": coverage(omap, np.random.default_rng(5).uniform(0, size, (4000, 2))),
            "runs": {},
        }
        scene = Scene(size, size, [], [])
        for kind, graph in (("sam", sam), ("map", omap)):
            res = Counter()
            for sc in scenarios(area.name, 8, False, random.Random(f"{area.name}-8")):
                try:
                    scenario = build_scenario(World(graph, scene, None), sc)
                except ValueError:
                    res["refused"] += 1
                    continue
                res[run_agent(scenario, decider=PolicyDecider(), time_limit_s=1.0).status] += 1
            row["runs"][kind] = dict(res)
        # the model's look at the longest unconfirmed stretches of track
        class Stub:
            graph = omap
        img = Image.open(io.BytesIO(sm.image_bytes))
        row["looks"] = []
        for i, r in enumerate(track_runs(omap)[:4]):
            crop, _ = inspection._crop(img, Stub, r)
            answer = inspection.look(looker, crop)
            row["looks"].append({"condition": answer["condition"], "confidence": answer["confidence"], "verdict": inspection.verdict_of(answer)})
            if crops_dir:
                crops_dir.mkdir(parents=True, exist_ok=True)
                (crops_dir / f"{area.name}_{i}_{answer['condition']}.jpg").write_bytes(crop)
        rows.append(row)
        print(name, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items() if k not in ("runs", "looks")}, row["runs"], [l["condition"] for l in row["looks"]], flush=True)
        (ROOT / "eval" / "tracks.json").write_text(json.dumps(rows, indent=1))

    ok = lambda r: r.get("verified", 0) + r.get("verified_partial", 0)
    lines = [
        "# Dirt tracks: the map graph against the graph read from the photo", "",
        "Generated by `scripts/eval_tracks.py`. Three 1.5 km forest squares whose OpenStreetMap roads (© OpenStreetMap contributors, ODbL) are mostly `highway=track`. SAM 3.1 reads the road mask of each",
        "photo; two graphs are built, one from the mask and one from the map. \"Reached\" = the mapped track lies within 15 m of the graph read from the photo; \"followed\" = within 8 m of the road mask.", "",
        "| Square | Mapped road | of which track | Road read from the photo | Track reached by it | Track followed by the mask | Points within 80 m of the road, photo / map | Verified plans of 8, photo / map |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['place']} | {r['map_km']:.1f} km | {r['track_km']:.1f} km | {r['sam_km']:.1f} km | {r['track_reached_by_sam_graph']:.0%} | {r['track_followed_by_mask']:.0%} | {r['covers_sam']:.0%} / {r['covers_map']:.0%} | {ok(r['runs']['sam'])} / {ok(r['runs']['map'])} |")
    looks = [x for r in rows for x in r["looks"]]
    cond = Counter(x["condition"] for x in looks)
    lines += [
        "", f"Muse Spark was shown the longest stretches of track the photo does not confirm ({len(looks)} stretches, a crop with the stretch marked) and said: " + ", ".join(f"{k} {v}" for k, v in cond.most_common()) + ".",
        f"Cost of this run: about ${guard.total_spent() - spent0:.2f} (SAM, read once and cached). Limits: three squares picked because the map has tracks there; OSM tracks are mapped by people and some may be overgrown or gone; the random scenarios are not real requests; the model's answers were checked by eye on the saved crops, not against labels.", "",
    ]
    (ROOT / "eval" / "TRACKS.md").write_text("\n".join(lines))
    print("\n".join(lines[-12:]))


if __name__ == "__main__":
    main()
