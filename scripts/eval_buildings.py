"""Does SAM 3.1 find the buildings, and do the delivery points land on them? Compared with OpenStreetMap footprints on 44 photos.

For each photo (the four bundled ones, the twelve squares of `eval/CITIES.md`, the 28 places of `scripts/prewarm_areas.py`) the
building mask SAM returns (paid, cached on disk) and the delivery points the product derives from it (`building_points`) are compared
with the building footprints mapped in OpenStreetMap (© OpenStreetMap contributors, ODbL; a yardstick only: it is incomplete in some
places and of another date, so a point on an unmapped house counts against SAM here). Measured:
  - points on a building: the share of delivery points that fall inside (or within 3 m of) a mapped footprint;
  - buildings reached: the share of mapped footprints (40 m² or more) that hold at least one delivery point;
  - pixels: precision and recall of the mask against the rasterised footprints.
Writes eval/BUILDINGS.md and eval/buildings.json. Usage: uv run python scripts/eval_buildings.py [--budget 6]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, Polygon
from shapely.prepared import prep
from shapely.strtree import STRtree

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from eval_hybrid import BUNDLED, CITIES
from prewarm_areas import MORE

from orbitroute.areas import ensure_area
from orbitroute.config import CACHE_DIR, ROOT, Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.naip import to_mercator
from orbitroute.perception.buildings import building_points, segment_buildings
from orbitroute.pipeline import get_sample

OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
MIN_M2 = 40.0  # the same floor the product uses for a delivery address
NEAR_M = 3.0  # a point this close to a footprint still counts as on it (a footprint is traced from another photo)


def fetch_buildings(name: str, bbox: list[float]) -> list[list[tuple[float, float]]]:
    """Footprints (rings of lon, lat) of every building way and multipolygon outer ring in the box; cached on disk."""
    path = CACHE_DIR / f"osm_buildings_{name}.json"
    if not path.exists():
        w, s, e, n = bbox
        q = f'[out:json][timeout:90];(way["building"]({s},{w},{n},{e}););out geom;'
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for _ in range(6):
            for url in OVERPASS:
                subprocess.run(["curl", "-s", "-m", "120", "-A", "OrbitRoute-eval/0.1 (hackathon evaluation)", "--data-urlencode", f"data={q}", url, "-o", str(path)])
                try:
                    json.loads(path.read_text())
                    break
                except (json.JSONDecodeError, FileNotFoundError):
                    time.sleep(15)
            else:
                continue
            break
        else:
            raise RuntimeError(f"Overpass did not answer for {name}")
    rings = []
    for el in json.loads(path.read_text())["elements"]:
        g = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
        if len(g) >= 4 and g[0] == g[-1]:
            rings.append(g)
    return rings


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 6.0
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, True)
    client = MetaClient(s, guard)
    run = guard.new_run(budget)
    spent0 = guard.total_spent()
    names = BUNDLED + [ensure_area(lat, lon).name for lat, lon in CITIES] + [ensure_area(lat, lon).name for _, lat, lon in MORE]
    rows = []
    for name in names:
        sm = get_sample(name)
        mask = None
        for attempt in range(3):  # a timed-out tile is asked again; the tiles already read are cached
            try:
                mask = segment_buildings(client, sm.image_bytes, run=run)
                break
            except Exception as exc:  # noqa: BLE001 - one place failing must not stop the sweep
                print(f"{name}: attempt {attempt + 1} failed ({type(exc).__name__})", flush=True)
        if mask is None:
            continue
        mpp = sm.meta["m_per_px"]
        h, w = mask.shape
        x0, y0, x1, y1 = sm.meta["bbox_mercator"]

        def to_px(lon, lat):
            x, y = to_mercator(lon, lat)
            return (x - x0) / (x1 - x0) * w, (y1 - y) / (y1 - y0) * h

        polys = []
        for ring in fetch_buildings(name, sm.meta["bbox_lonlat"]):
            p = Polygon([to_px(lon, lat) for lon, lat in ring])
            if p.is_valid and p.area * mpp**2 >= MIN_M2:
                polys.append(p)
        raster = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(raster)
        for p in polys:
            d.polygon(list(p.exterior.coords), fill=1)
        truth = np.asarray(raster) > 0
        pts = building_points(mask, mpp)
        tree = STRtree(polys) if polys else None
        near_px = NEAR_M / mpp
        hit = set()  # footprints that hold a point
        on = 0
        for x, y in pts:
            pt = Point(x, y)
            found = [i for i in (tree.query(pt.buffer(near_px)) if tree else []) if polys[i].distance(pt) <= near_px]
            if found:
                on += 1
                hit.update(int(i) for i in found)
        tp = int((mask & truth).sum())
        rows.append({
            "photo": name, "mapped": len(polys), "points": len(pts), "points_on_building": on, "buildings_reached": len(hit),
            "mask_px": int(mask.sum()), "truth_px": int(truth.sum()), "both_px": tp,
        })
        r = rows[-1]
        print(f"{name:22s} mapped {r['mapped']:5d}  points {r['points']:5d}  on building {r['points_on_building']:5d}  reached {r['buildings_reached']:5d}  ${guard.total_spent() - spent0:.2f}", flush=True)
        (ROOT / "eval" / "buildings.json").write_text(json.dumps(rows, indent=1))

    def pooled(rs):
        pts, on = sum(r["points"] for r in rs), sum(r["points_on_building"] for r in rs)
        mapped, reached = sum(r["mapped"] for r in rs), sum(r["buildings_reached"] for r in rs)
        mp, tp, both = sum(r["mask_px"] for r in rs), sum(r["truth_px"] for r in rs), sum(r["both_px"] for r in rs)
        return {"points": pts, "on": on, "mapped": mapped, "reached": reached, "px_precision": both / mp if mp else 0.0, "px_recall": both / tp if tp else 0.0}

    allp = pooled(rows)
    dense = [r for r in rows if r["mapped"] >= 300]  # where OSM has many buildings the yardstick is the most complete
    densep = pooled(dense)
    per_photo_precision = sorted(r["points_on_building"] / r["points"] for r in rows if r["points"])
    cost = guard.total_spent() - spent0
    lines = [
        "# Buildings: SAM 3.1 against OpenStreetMap footprints", "",
        f"Generated by `scripts/eval_buildings.py`. On {len(rows)} photos (1.5 km squares: the four bundled ones, the twelve of `eval/CITIES.md`, 28 more places) the building mask of SAM 3.1 and the delivery points derived from it were compared with the building footprints mapped in OpenStreetMap (© OpenStreetMap contributors, ODbL).",
        "OSM is a yardstick only: it is incomplete in some places and of another date, so a point on an unmapped house counts against SAM here. A point is on a building when it lies within 3 m of a footprint; footprints under 40 m² are left out (the product ignores them too).", "",
        "| What | All photos | Photos with 300+ mapped buildings |", "|---|---|---|",
        f"| Delivery points | {allp['points']} | {densep['points']} |",
        f"| Points on a mapped building | **{allp['on'] / max(allp['points'], 1):.0%}** | **{densep['on'] / max(densep['points'], 1):.0%}** |",
        f"| Mapped buildings that hold a point | **{allp['reached'] / max(allp['mapped'], 1):.0%}** of {allp['mapped']} | **{densep['reached'] / max(densep['mapped'], 1):.0%}** of {densep['mapped']} |",
        f"| Mask pixels on a footprint (precision) | {allp['px_precision']:.0%} | {densep['px_precision']:.0%} |",
        f"| Footprint pixels covered by the mask (recall) | {allp['px_recall']:.0%} | {densep['px_recall']:.0%} |", "",
        f"Per photo, the share of points on a building ran from {per_photo_precision[0]:.0%} to {per_photo_precision[-1]:.0%} (median {per_photo_precision[len(per_photo_precision) // 2]:.0%}); the table is in `eval/buildings.json`. "
        f"{len(dense)} of the {len(rows)} photos have 300 or more mapped buildings; where OSM has fewer the yardstick is nearly empty ("
        + ", ".join(f"{r['photo']}: {r['mapped']} mapped against {r['points']} points" for r in rows if r["mapped"] < 300)
        + "), so the \"on a building\" share there says little about SAM.",
        f"Cost of this run: about ${cost:.2f} on the Meta API (answers are cached, so a rerun is free). Limits: the yardstick has gaps and its own errors; one tile per place; a point on a mapped garage or shed over 40 m² counts as a building; houses in a row come out of SAM as one blob and are told apart by the shape, which is a heuristic.", "",
    ]
    (ROOT / "eval" / "BUILDINGS.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
