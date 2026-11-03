"""How much of the map does a flood make false, over many floods? NOAA photos from nine disasters, SAM 3.1 for the water and the roofs.

`scripts/eval_flood.py` measured two Hurricane Harvey photos. This sweeps 1.5 km squares of NOAA Emergency Response Imagery (public domain)
chosen by the author from towns that flooded in nine events (Harvey, Florence, Ian, Helene, Ida, Laura, Sally, Milton, the 2025 Texas flood),
plus the seven flood scenes bundled with the app. The squares were picked from where NOAA has a photo of the town on the days after the storm,
before any model ran on them: dry squares and permanent water (canals, harbours, rivers) are in, and say so. For each square:
  - the standing water SAM 3.1 finds (`flooded area`, `flood water`), as zones enlarged by 6 m;
  - the streets mapped in OpenStreetMap (© OpenStreetMap contributors, ODbL; a yardstick only) and how much of them lie under that water;
  - the roofs SAM 3.1 finds and how many stand in the water or within 15 m of it (the water card of the app).
Writes eval/FLOOD_SWEEP.md and eval/flood_sweep.json. Usage: uv run python scripts/eval_flood_sweep.py [--budget 8] [--fetch-only]
"""

from __future__ import annotations

import io
import json
import statistics
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from orbitroute.config import CACHE_DIR, ROOT, Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.naip import mercator_bbox, to_mercator
from orbitroute.perception.buildings import building_points, segment_buildings
from orbitroute.perception.exposure import SURROUND_M, wet_mask
from orbitroute.perception.flood import flood_zones, segment_floods
from orbitroute.perception.osm import fetch_roads
from orbitroute.pipeline import get_sample
from orbitroute.storm import fetch_storm_tile

STREETS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}
SPAN_M, PX = 1500.0, 1536
MAX_NODATA, MIN_STREET_KM = 0.10, 2.0  # a square with more black (no photo) or fewer mapped streets than this is left out, whatever the water shows
DIR = CACHE_DIR / "sweep"

# event, name, dataset, lon, lat: from the NOAA coverage probe (the first dataset that holds a photo of the town)
PLACES = [
    ("Harvey", "beaumont", "20170901a", -94.13, 30.08), ("Harvey", "friendswood", "20170903a", -95.20, 29.53), ("Harvey", "houston-addicks", "20170830", -95.665, 29.775),
    ("Harvey", "houston-kingwood", "20170831a", -95.22, 30.05), ("Harvey", "houston-meyerland", "20170831b", -95.466, 29.683), ("Harvey", "houston-northeast", "20170901b", -95.28, 29.86),
    ("Harvey", "orange-tx", "20170901c", -93.736, 30.094), ("Harvey", "port-arthur", "20170901a", -93.94, 29.885), ("Harvey", "vidor-tx", "20170902a", -93.99, 30.13),
    ("Florence", "conway-sc", "20180919c", -79.047, 33.836), ("Florence", "kinston-nc", "20180919a", -77.58, 35.26), ("Florence", "trenton-nc", "20180919a", -77.35, 35.06),
    ("Florence", "wilmington-nc", "20180918a", -77.945, 34.226),
    ("Ian", "bonita-springs", "20220930b", -81.78, 26.34), ("Ian", "naples-fl", "20220930b", -81.80, 26.15), ("Ian", "north-fort-myers", "20220930b", -81.88, 26.72),
    ("Ian", "port-charlotte", "20220930b", -82.12, 26.99), ("Ian", "punta-gorda", "20220929a", -82.05, 26.93), ("Ian", "st-james-city", "20220930b", -82.09, 26.50),
    ("Helene", "biltmore-nc", "20241005b", -82.55, 35.57), ("Helene", "chimney-rock-nc", "20241007a", -82.25, 35.43), ("Helene", "hot-springs-nc", "20241006b", -82.83, 35.89),
    ("Helene", "marshall-nc", "20241007a", -82.683, 35.797), ("Helene", "spruce-pine-nc", "20241005a", -82.065, 35.915),
    ("Ida", "houma-la", "20210830a", -90.72, 29.60), ("Ida", "larose-la", "20210830a", -90.38, 29.57),
    ("Laura", "lake-charles", "20200830d", -93.217, 30.227), ("Laura", "sulphur-la", "20200830d", -93.377, 30.237),
    ("Sally", "gulf-shores", "20200918c", -87.70, 30.246), ("Sally", "pensacola", "20200919a", -87.217, 30.421), ("Sally", "perdido-key", "20200918c", -87.45, 30.30),
    ("Milton", "davis-islands", "20241014a", -82.46, 27.90), ("Milton", "englewood-fl", "20241011b", -82.35, 26.96), ("Milton", "siesta-key", "20241011a", -82.55, 27.27),
    ("Milton", "st-petersburg-fl", "20241012c", -82.64, 27.77), ("Milton", "venice-fl", "20241011b", -82.45, 27.10),
    ("Texas 2025", "comfort-tx", "20250721b", -98.90, 29.97), ("Texas 2025", "ingram-tx", "20250711b", -99.24, 30.07), ("Texas 2025", "marble-falls", "20250710a", -98.275, 30.578),
]
BUNDLED = [
    ("Harvey", "houston-harvey"), ("Harvey", "houston-harvey-b"), ("Florence", "flood-lumberton"), ("Ian", "flood-fort-myers-shores"), ("Ian", "flood-iona"),
    ("Helene", "flood-swannanoa"), ("Texas 2025", "flood-kerrville"),
]


def fetch_square(event: str, name: str, dataset: str, lon: float, lat: float) -> tuple[bytes, dict]:
    jpg, meta = DIR / f"{name}.jpg", DIR / f"{name}.json"
    if not jpg.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        data, bbox = fetch_storm_tile(f"{dataset}-rgb", lon, lat, span_m=SPAN_M, px=PX)
        jpg.write_bytes(data)
        meta.write_text(json.dumps({"event": event, "dataset": f"{dataset}-rgb", "bbox_lonlat": list(bbox), "bbox_mercator": list(mercator_bbox(lon, lat, SPAN_M)), "span_m": SPAN_M, "width_px": PX, "height_px": PX, "m_per_px": SPAN_M / PX}))
    return jpg.read_bytes(), json.loads(meta.read_text())


def retry(fn, what: str, tries: int = 3):
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a timed-out tile or an empty answer is asked again; answers already read are cached
            print(f"  {what}: attempt {attempt + 1} failed ({type(exc).__name__})", flush=True)
            if attempt == tries - 1:
                raise
            time.sleep(5)


def measure(event: str, name: str, image: bytes, meta: dict, client: MetaClient, run) -> dict:
    mpp = meta["m_per_px"]
    W, H = meta["width_px"], meta["height_px"]
    x0, y0, x1, y1 = meta["bbox_mercator"]
    nodata = float((np.asarray(Image.open(io.BytesIO(image)).convert("RGB")).max(axis=2) < 8).mean())  # black corners where NOAA has no photo
    osm = retry(lambda: fetch_roads(name, meta["bbox_lonlat"], deadline_s=150.0), f"{name} OSM")

    def px(lon: float, lat: float) -> tuple[float, float]:
        x, y = to_mercator(lon, lat)
        return (x - x0) / (x1 - x0) * W, (y1 - y) / (y1 - y0) * H

    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for el in osm["elements"]:
        if "geometry" in el and el.get("tags", {}).get("highway") in STREETS:
            d.line([px(p["lon"], p["lat"]) for p in el["geometry"] if p], fill=255, width=1)  # Overpass now and then returns a null vertex
    streets = np.asarray(im) > 0
    street_km = streets.sum() * mpp / 1000
    if nodata > MAX_NODATA or street_km < MIN_STREET_KM:  # the rule is fixed before any model looks at the square
        return {"event": event, "name": name, "skipped": f"{nodata:.0%} of the square has no photo" if nodata > MAX_NODATA else f"only {street_km:.1f} km of named streets mapped"}
    water = retry(lambda: segment_floods(client, image, run=run), f"{name} water")
    zones = flood_zones(water, mpp)
    wet = wet_mask(zones, water.shape)
    under = streets & wet
    roofs = retry(lambda: segment_buildings(client, image, run=run), f"{name} roofs")
    pts = building_points(roofs, mpp)
    near = ndi.distance_transform_edt(~wet) * mpp if wet.any() else np.full(wet.shape, 1e9)
    counts = {"in_water": 0, "surrounded": 0, "dry": 0}
    for x, y in pts:
        xi, yi = min(max(int(x), 0), W - 1), min(max(int(y), 0), H - 1)
        counts["in_water" if wet[yi, xi] else "surrounded" if near[yi, xi] <= SURROUND_M else "dry"] += 1
    return {
        "event": event, "name": name, "water_share_of_photo": float(wet.mean()), "water_patches": len(zones),
        "named_street_km": round(streets.sum() * mpp / 1000, 2), "under_water_km": round(under.sum() * mpp / 1000, 2),
        "buildings": len(pts), **{f"buildings_{k}": v for k, v in counts.items()},
    }


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 8.0
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, "--fetch-only" not in sys.argv)
    client = MetaClient(s, guard)
    run = guard.new_run(budget)
    spent0 = guard.total_spent()
    squares = []
    for event, name, dataset, lon, lat in PLACES:
        try:
            image, meta = fetch_square(event, name, dataset, lon, lat)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: no photo ({type(exc).__name__}: {str(exc)[:80]})", flush=True)
            continue
        squares.append((event, name, image, meta))
    for event, name in BUNDLED:
        sm = get_sample(name)
        squares.append((event, name, sm.image_bytes, sm.meta))
    print(f"{len(squares)} squares", flush=True)
    if "--fetch-only" in sys.argv:
        return
    out_path = ROOT / "eval" / "flood_sweep.json"
    rows = json.loads(out_path.read_text()) if out_path.exists() else []
    done = {r["name"] for r in rows}
    for event, name, image, meta in squares:
        if name in done:
            continue
        if guard.total_spent() - spent0 >= budget:
            print(f"stopping: ${guard.total_spent() - spent0:.2f} spent of the ${budget:.2f} given", flush=True)
            break
        try:
            r = measure(event, name, image, meta, client, run)
        except Exception as exc:  # noqa: BLE001 - one square failing must not stop the sweep
            print(f"{name}: failed ({type(exc).__name__}: {str(exc)[:100]})", flush=True)
            continue
        rows.append(r)
        out_path.write_text(json.dumps(rows, indent=1))
        if "skipped" in r:
            print(f"{name:26s} left out: {r['skipped']}", flush=True)
            continue
        share = r["under_water_km"] / r["named_street_km"] if r["named_street_km"] else 0
        print(f"{name:26s} water {r['water_share_of_photo']:4.0%}  streets {r['named_street_km']:5.1f} km  under water {r['under_water_km']:5.2f} km ({share:3.0%})  roofs {r['buildings']:5d} wet {r['buildings_in_water'] + r['buildings_surrounded']:4d}  ${guard.total_spent() - spent0:.2f}", flush=True)
    report(rows, guard.total_spent() - spent0)


def report(all_rows: list[dict], cost: float) -> None:
    rows = [r for r in all_rows if "skipped" not in r]
    left_out = [r for r in all_rows if "skipped" in r]
    if not rows:
        return
    def share(r: dict) -> float:
        return r["under_water_km"] / r["named_street_km"] if r["named_street_km"] else 0.0
    streets, under = sum(r["named_street_km"] for r in rows), sum(r["under_water_km"] for r in rows)
    shares = sorted(share(r) for r in rows if r["named_street_km"] >= 5)
    roofs, wet = sum(r["buildings"] for r in rows), sum(r["buildings_in_water"] + r["buildings_surrounded"] for r in rows)
    in_water = sum(r["buildings_in_water"] for r in rows)
    events = sorted({r["event"] for r in rows})
    lines = [
        "# Flood sweep: how much of the map a flood makes false", "",
        f"Generated by `scripts/eval_flood_sweep.py`. {len(rows)} squares of 1.5 km of NOAA Emergency Response Imagery (public domain) from {len(events)} disasters ({', '.join(events)}): "
        "towns that flooded, chosen by the author from where NOAA has a photo of the town after the storm, before any model ran on them, plus the seven flood scenes bundled with the app. "
        "Dry squares and permanent water (canals, harbours, rivers) are included. Streets are the named streets of OpenStreetMap (© OpenStreetMap contributors, ODbL), used only as a yardstick.", "",
        "| Measure | Value |", "|---|---|",
        f"| Squares | {len(rows)} |",
        f"| Named streets mapped | {streets:.0f} km |",
        f"| Of those, under the water SAM 3.1 finds | **{under:.0f} km ({under / max(streets, 1):.0%})** |",
        f"| Squares with at least 1 km of named street under water | {sum(1 for r in rows if r['under_water_km'] >= 1)} of {len(rows)} |",
        f"| Squares with at least 10% of their named streets under water | {sum(1 for r in rows if share(r) >= 0.10)} of {len(rows)} |",
        f"| Share per square, median (squares with 5+ km of streets) | {statistics.median(shares):.0%}, from {shares[0]:.0%} to {shares[-1]:.0%} |",
        f"| Roofs found | {roofs} |",
        f"| Roofs in the water or within 15 m of it | {wet} ({wet / max(roofs, 1):.0%}), of which {in_water} in the water |", "",
        "| Event | Place | Water in photo | Named streets | Under water | Share | Roofs found | In or beside water |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r["event"], r["name"])):
        lines.append(f"| {r['event']} | {r['name']} | {r['water_share_of_photo']:.0%} | {r['named_street_km']} km | {r['under_water_km']} km | {share(r):.0%} | {r['buildings']} | {r['buildings_in_water'] + r['buildings_surrounded']} |")
    lines += [
        "", "Left out before any model ran, by a rule fixed in advance (more than 10% of the square without a photo, or under 2 km of named streets mapped): " + (", ".join(f"{r['name']} ({r['skipped']})" for r in left_out) or "none") + ".", "",
        f"Cost: about ${cost:.2f} on the Meta API by the local counter (three runs, resumed after Overpass timeouts), which overstates the real bill; answers are cached, so a rerun is free.", "",
        "Limits: no human labels for the water, so these are SAM's outlines, not measured flood extent; permanent water and wet fields are found too (a truck should avoid them, but they are not the flood); "
        "water under trees is missed, so shares are lower bounds there; OSM streets are incomplete in some towns; one square per place, chosen by the author and centred on the town, not on the streets known to have flooded, so most squares hold little water and the pooled share says how common flooding was in a town-centre square, not how bad it was where it hit; three Harvey squares taken in poor light (beaumont, friendswood, houston-kingwood: 0% water, 3 roofs found in the last) are probably under-read by SAM; photos of one town were taken on different days of each event; "
        "'under water' means the street lies inside a water outline, not that it is impassable to every vehicle.", "",
    ]
    (ROOT / "eval" / "FLOOD_SWEEP.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
