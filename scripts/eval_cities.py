"""Road accuracy on many different places, and which SAM tilings to use: a measurement against OpenStreetMap.

For each place a 1.5 km NAIP square is read with SAM 3.1 at several tilings (paid, cached on disk), and every combination of
tilings is scored against the OpenStreetMap streets of the same square (© OpenStreetMap contributors, ODbL, used only as a
yardstick). Writes eval/CITIES.md and eval/cities.json.
Usage: uv run python scripts/eval_cities.py [--budget 16]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from itertools import combinations

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

from orbitroute.areas import ensure_area
from orbitroute.config import CACHE_DIR, ROOT, Settings
from orbitroute.llm.budget import BudgetExceeded, BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.naip import to_mercator
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.segment import segment_concept
from orbitroute.pipeline import get_sample

# (name, lat, lon, what it tests, tilings to read)
SWEEP = [4, 6, 8, 10, 12, 16]
CITIES = [
    ("Chicago Loop", 41.8827, -87.6278, "dense downtown", True),
    ("Brooklyn", 40.6782, -73.9442, "dense residential", True),
    ("Plano TX", 33.0198, -96.6989, "suburb", True),
    ("Mesa AZ", 33.4152, -111.8315, "suburban grid", True),
    ("Houston ship channel", 29.7330, -95.2420, "industrial", True),
    ("Atlanta Buckhead", 33.8400, -84.3800, "tree-covered residential", True),
    ("Seattle Ravenna", 47.6800, -122.3000, "tree-covered residential", True),
    ("Denver", 39.7392, -104.9903, "mixed", True),
    ("Los Angeles", 34.0522, -118.2437, "dense mixed", False),
    ("Portland OR", 45.5231, -122.6765, "residential", False),
    ("Minneapolis", 44.9778, -93.2650, "mixed", False),
    ("Miami", 25.7617, -80.1918, "mixed", False),
]
OVERLAP = {4: 64, 5: 56, 6: 48, 7: 44, 8: 40, 10: 32, 12: 28, 16: 24}
STREETS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}
HIDDEN = {"parking_aisle", "driveway", "drive-through"}
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
TOL = 15


def fetch_osm(name: str, bbox: list[float]) -> dict:
    path = CACHE_DIR / f"osm_{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    w, s, e, n = bbox
    q = f'[out:json][timeout:50];way["highway"]({s},{w},{n},{e});out geom;'
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(6):
        for url in OVERPASS:
            subprocess.run(["curl", "-s", "-m", "80", "-A", "OrbitRoute-eval/0.1 (hackathon evaluation)", "--data-urlencode", f"data={q}", url, "-o", str(path)])
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, FileNotFoundError):  # the server answered with an error page, or curl wrote nothing
                time.sleep(15)
    raise RuntimeError(f"Overpass did not answer for {name}")


def reference(sm, osm: dict):
    W, H, mpp = sm.meta["width_px"], sm.meta["height_px"], sm.meta["m_per_px"]
    x0, y0, x1, y1 = sm.meta["bbox_mercator"]

    def px(lon, lat):
        x, y = to_mercator(lon, lat)
        return (x - x0) / (x1 - x0) * W, (y1 - y) / (y1 - y0) * H

    def raster(keep):
        im = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(im)
        for el in osm["elements"]:
            if "geometry" in el and keep(el.get("tags", {})):
                d.line([px(p["lon"], p["lat"]) for p in el["geometry"]], fill=255, width=1)
        return np.asarray(im) > 0

    R = {"streets": raster(lambda t: t.get("highway") in STREETS), "service": raster(lambda t: t.get("highway") is not None and t.get("service") not in HIDDEN), "all": raster(lambda t: t.get("highway") is not None)}
    return R, {k: distance_transform_edt(~v) * mpp for k, v in R.items()}, (W, H, mpp)


def score(mask: np.ndarray, R, dist, dims) -> dict:
    W, H, mpp = dims
    graph = build_road_graph(mask, mpp)
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for e in graph.edges:
        d.line([tuple(graph.nodes[e.u]), tuple(graph.nodes[e.v])], fill=255, width=1)
    G = np.asarray(im) > 0
    dG = distance_transform_edt(~G) * mpp
    return {
        "km": graph.stats["road_km"],
        "recall_streets": float((dG[R["streets"]] <= TOL).mean()) if R["streets"].any() else None,
        "recall_service": float((dG[R["service"]] <= TOL).mean()) if R["service"].any() else None,
        "precision": float((dist["all"][G] <= TOL).mean()) if G.any() else None,
    }


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 16.0
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, True)
    client = MetaClient(s, guard)
    spent0 = guard.total_spent()
    results = []
    for name, lat, lon, kind, full in CITIES:
        if guard.total_spent() - spent0 > budget:
            print("stopping: the budget of $%.0f for this evaluation is used up" % budget)
            break
        area = ensure_area(lat, lon)
        sm = get_sample(area.name)
        osm = fetch_osm(area.name, sm.meta["bbox_lonlat"])
        R, dist, dims = reference(sm, osm)
        tilings = SWEEP if full else [6, 12]
        masks = {}
        run = guard.new_run(3.0)
        for n in tilings:
            masks[n] = segment_concept(client, sm.image_bytes, "road", n=n, overlap=OVERLAP[n], run=run)
        combos = [c for k in (1, 2, 3) for c in combinations(tilings, k) if (len(c) == 1 or 6 in c or 8 in c) and sum(c) <= 40] if full else [(6, 12)]
        row = {"city": name, "kind": kind, "area": area.name, "osm_streets_km": round(float(R["streets"].sum()) * dims[2] / 1000, 1), "combos": {}}
        for c in combos:
            m = masks[c[0]].copy()
            for n in c[1:]:
                m |= masks[n]
            row["combos"]["+".join(map(str, c))] = score(m, R, dist, dims)
        results.append(row)
        base = row["combos"]["6+12"]
        print(f"{name:22s} {kind:26s} 6+12: streets recall {base['recall_streets']:.0%} precision {base['precision']:.0%}  (spent ${guard.total_spent() - spent0:.2f})", flush=True)
        json.dump(results, open(ROOT / "eval" / "cities.json", "w"), indent=1)

    cost_per = {n: {4: 16, 5: 25, 6: 36, 7: 49, 8: 64, 10: 100, 12: 144, 16: 256}[n] * 0.0025 for n in SWEEP}
    names = sorted({k for r in results for k in r["combos"] if all(k in rr["combos"] for rr in results if rr["combos"].get("6+12") and len(rr["combos"]) > 1)} or {"6+12"}, key=lambda k: (len(k.split("+")), k))
    full_rows = [r for r in results if len(r["combos"]) > 1]
    lines = ["# Road accuracy on many places", "", "Generated by `scripts/eval_cities.py`. Each 1.5 km square is read with SAM 3.1 and the road graph is compared with OpenStreetMap",
             "(© OpenStreetMap contributors, ODbL, a yardstick only). Recall = share of the named OSM streets within 15 m of the graph; precision = share of the graph within 15 m of any mapped way.", ""]
    lines += ["## Default setting (6x6 + 12x12 tilings), every place", "", "| Place | Kind | Named streets found | Precision | Graph | OSM named streets |", "|---|---|---|---|---|---|"]
    for r in results:
        b = r["combos"]["6+12"]
        lines.append(f"| {r['city']} | {r['kind']} | {b['recall_streets']:.0%} | {b['precision']:.0%} | {b['km']} km | {r['osm_streets_km']} km |")
    mean = lambda xs: sum(xs) / len(xs)
    lines += ["", f"Mean over {len(results)} places: named streets found {mean([r['combos']['6+12']['recall_streets'] for r in results]):.0%}, precision {mean([r['combos']['6+12']['precision'] for r in results]):.0%}.", ""]
    if full_rows:
        lines += [f"## Which tilings? Mean over the {len(full_rows)} places read at every tiling", "", "| Tilings | Named streets found | Service roads found | Precision | SAM cost per new area |", "|---|---|---|---|---|"]
        keys = sorted({k for r in full_rows for k in r["combos"]}, key=lambda k: (len(k.split("+")), [int(x) for x in k.split("+")]))
        for k in keys:
            if not all(k in r["combos"] for r in full_rows):
                continue
            rows = [r["combos"][k] for r in full_rows]
            cost = sum(cost_per[int(x)] for x in k.split("+"))
            lines.append(f"| {k} | {mean([x['recall_streets'] for x in rows]):.0%} | {mean([x['recall_service'] for x in rows]):.0%} | {mean([x['precision'] for x in rows]):.0%} | ${cost:.2f} |")
    lines += ["", "Limits: one 1.5 km square per place; OSM is itself incomplete and of a different date than the imagery; no human labels.", ""]
    (ROOT / "eval" / "CITIES.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except BudgetExceeded as exc:
        print("budget guard:", exc)
