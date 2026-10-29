"""How accurate are the zones the model outlines? A comparison of the scene prompt versions with OpenStreetMap land use.

For each of the four bundled photos and the twelve 1.5 km squares of `eval/CITIES.md` the scene prompt is run several times
per version (paid, cached on disk), and the zones are compared pixel by pixel with the land-use polygons mapped in
OpenStreetMap (© OpenStreetMap contributors, ODbL; a yardstick only: it is coarse, incomplete and of another date). Only
pixels that OSM labels with one of the four kinds count, because OSM says nothing about the rest. Writes
eval/SCENE_OSM.md and eval/scene_osm.json.

Usage: uv run python scripts/eval_scene_osm.py [--repeats 3] [--versions v1 v2]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from orbitroute.areas import ensure_area
from orbitroute.config import CACHE_DIR, ROOT, Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.naip import to_mercator
from orbitroute.pipeline import get_sample
from orbitroute.understanding.scene import analyze_scene

KINDS = ["residential", "industrial", "commercial", "park_forest"]
GRID = 384  # pixels per side of the comparison raster (4 image pixels per cell)
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
BUNDLED = ["columbus", "memphis", "houston-harvey", "houston-harvey-b"]
CITIES = [  # the places of scripts/eval_cities.py
    (41.8827, -87.6278), (40.6782, -73.9442), (33.0198, -96.6989), (33.4152, -111.8315), (29.7330, -95.2420), (33.8400, -84.3800),
    (47.6800, -122.3000), (39.7392, -104.9903), (34.0522, -118.2437), (45.5231, -122.6765), (44.9778, -93.2650), (25.7617, -80.1918),
]


def osm_kind(tags: dict) -> str | None:
    lu, leisure, natural = tags.get("landuse"), tags.get("leisure"), tags.get("natural")
    if lu == "residential":
        return "residential"
    if lu == "industrial":
        return "industrial"
    if lu in ("commercial", "retail"):
        return "commercial"
    if lu in ("forest", "grass", "meadow", "recreation_ground", "village_green") or leisure in ("park", "garden", "golf_course", "nature_reserve", "pitch") or natural in ("wood", "grassland", "scrub"):
        return "park_forest"
    return None


def fetch_landuse(name: str, bbox: list[float]) -> dict:
    path = CACHE_DIR / f"osm_landuse_{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    w, s, e, n = bbox
    box = f"({s},{w},{n},{e})"
    q = (
        f'[out:json][timeout:60];(nwr["landuse"]{box};nwr["leisure"~"^(park|garden|golf_course|nature_reserve|pitch)$"]{box};'
        f'nwr["natural"~"^(wood|grassland|scrub)$"]{box};);out geom;'
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(6):
        for url in OVERPASS:
            subprocess.run(["curl", "-s", "-m", "90", "-A", "OrbitRoute-eval/0.1 (hackathon evaluation)", "--data-urlencode", f"data={q}", url, "-o", str(path)])
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                time.sleep(15)
    raise RuntimeError(f"Overpass did not answer for {name}")


def osm_polygons(osm: dict) -> list[tuple[str, list[tuple[float, float]]]]:
    """(kind, ring of (lon, lat)) per mapped area: closed ways, and relations built from their outer ways."""
    out = []
    for el in osm["elements"]:
        kind = osm_kind(el.get("tags", {}))
        if kind is None:
            continue
        if el["type"] == "way" and "geometry" in el:
            ring = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(ring) >= 4 and ring[0] == ring[-1]:
                out.append((kind, ring))
        elif el["type"] == "relation":
            lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 2]
            if lines:
                merged = unary_union(lines)
                if merged.geom_type == "MultiLineString":
                    merged = linemerge(merged)
                for poly in polygonize([merged]):
                    out.append((kind, list(poly.exterior.coords)))
    return out


def paint(items: list[tuple[str, list[tuple[float, float]]]]) -> np.ndarray:
    """Label raster, 0 = no label, 1..4 = KINDS. Larger areas first, so a park inside a residential area stays a park."""
    im = Image.new("L", (GRID, GRID), 0)
    d = ImageDraw.Draw(im)
    for kind, ring in sorted(items, key=lambda it: -Polygon(it[1]).area if len(it[1]) >= 3 else 0):
        if len(ring) >= 3 and kind in KINDS:  # the model's "other" is no label
            d.polygon(ring, fill=KINDS.index(kind) + 1)
    return np.asarray(im)


def model_zones(client: MetaClient, sm, version: str, rep: int) -> list[tuple[str, list[tuple[float, float]]]]:
    key = hashlib.sha256(sm.image_bytes).hexdigest()[:16]
    path = CACHE_DIR / f"sceneosm_{key}_{version}_{rep}.json"
    if path.exists():
        return [(k, [tuple(p) for p in ring]) for k, ring in json.loads(path.read_text())]
    scene = analyze_scene(client, sm.image_bytes, use_cache=False, prompt_version=version)
    zones = [(z.kind, [(x, y) for x, y in z.polygon.exterior.coords]) for z in scene.zones]
    path.write_text(json.dumps(zones))
    return zones


def scale(items, f) -> list:
    return [(k, [f(x, y) for x, y in ring]) for k, ring in items]


def compare(model: np.ndarray, osm: np.ndarray) -> dict:
    labelled = osm > 0
    n = int(labelled.sum())
    row = {"osm_share": float(labelled.mean()), "pixels": n, "correct": int((model[labelled] == osm[labelled]).sum()), "model_labelled": int((model[labelled] > 0).sum())}
    for i, k in enumerate(KINDS, start=1):
        row[k] = {"osm": int((osm == i).sum()), "model_in_labelled": int(((model == i) & labelled).sum()), "both": int(((model == i) & (osm == i)).sum())}
    return row


def pool(rows: list[dict]) -> dict:
    """Pixel-weighted totals over images; recall, precision and F1 per kind."""
    n = sum(r["pixels"] for r in rows)
    out = {"accuracy": sum(r["correct"] for r in rows) / n, "model_labelled": sum(r["model_labelled"] for r in rows) / n}
    for k in KINDS:
        osm, mod, both = (sum(r[k][x] for r in rows) for x in ("osm", "model_in_labelled", "both"))
        rec, prec = (both / osm if osm else None), (both / mod if mod else None)
        out[k] = {"recall": rec, "precision": prec, "f1": (2 * rec * prec / (rec + prec)) if rec and prec else 0.0, "osm_share": osm / n}
    out["macro_f1"] = float(np.mean([out[k]["f1"] for k in KINDS]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--versions", nargs="+", default=["v1", "v2"])
    a = ap.parse_args()
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, True)
    client = MetaClient(s, guard)
    spent0 = guard.total_spent()

    names = BUNDLED + [ensure_area(lat, lon).name for lat, lon in CITIES]
    jobs, osm_rasters, samples = [], {}, {}
    for name in names:
        sm = get_sample(name)
        samples[name] = sm
        W, H = sm.meta["width_px"], sm.meta["height_px"]
        x0, y0, x1, y1 = sm.meta["bbox_mercator"]
        osm = osm_polygons(fetch_landuse(name, sm.meta["bbox_lonlat"]))

        def to_grid(lon, lat, x0=x0, y0=y0, x1=x1, y1=y1):
            x, y = to_mercator(lon, lat)
            return (x - x0) / (x1 - x0) * GRID, (y1 - y) / (y1 - y0) * GRID

        osm_rasters[name] = paint(scale(osm, to_grid))
        jobs += [(name, v, r) for v in a.versions for r in range(a.repeats)]

    def run(job):
        name, v, r = job
        return job, model_zones(client, samples[name], v, r)

    answers = {}
    with ThreadPoolExecutor(max_workers=4) as pool_:
        for job, zones in pool_.map(run, jobs):
            answers[job] = zones
    print(f"model calls done, spent ${guard.total_spent() - spent0:.2f}", flush=True)

    scene_rows: dict[str, dict[int, dict[str, dict]]] = {v: {} for v in a.versions}
    for (name, v, r), zones in answers.items():
        k = GRID / samples[name].meta["width_px"]
        scene_rows[v].setdefault(r, {})[name] = compare(paint(scale(zones, lambda x, y: (x * k, y * k))), osm_rasters[name])

    baseline = {}  # one label for the whole image: what a model that ignores the photo would score
    for kind in KINDS:
        rows = [compare(np.full((GRID, GRID), KINDS.index(kind) + 1), osm_rasters[n]) for n in names]
        baseline[kind] = pool(rows)["accuracy"]

    result = {"images": names, "repeats": a.repeats, "osm_share": {n: float((osm_rasters[n] > 0).mean()) for n in names}, "baseline_accuracy": baseline, "versions": {}}
    for v in a.versions:
        per_rep = [pool(list(rows.values())) for rows in scene_rows[v].values()]
        bundled = [pool([rows[n] for n in BUNDLED]) for rows in scene_rows[v].values()]
        cities = [pool([rows[n] for n in names if n not in BUNDLED]) for rows in scene_rows[v].values()]
        mean = lambda xs, f: float(np.mean([f(x) for x in xs]))
        result["versions"][v] = {
            "accuracy": mean(per_rep, lambda p: p["accuracy"]), "accuracy_min": min(p["accuracy"] for p in per_rep), "accuracy_max": max(p["accuracy"] for p in per_rep),
            "macro_f1": mean(per_rep, lambda p: p["macro_f1"]), "model_labelled": mean(per_rep, lambda p: p["model_labelled"]),
            "bundled_accuracy": mean(bundled, lambda p: p["accuracy"]), "cities_accuracy": mean(cities, lambda p: p["accuracy"]),
            "kinds": {k: {m: (None if per_rep[0][k][m] is None else mean(per_rep, lambda p, k=k, m=m: p[k][m] or 0.0)) for m in ("recall", "precision", "f1")} for k in KINDS},
        }
    result["spent_usd"] = round(guard.total_spent() - spent0, 3)
    (ROOT / "eval" / "scene_osm.json").write_text(json.dumps(result, indent=1))

    cover = np.mean(list(result["osm_share"].values()))
    lines = [
        "# Zone accuracy against OpenStreetMap land use", "",
        f"Generated by `scripts/eval_scene_osm.py`. The scene prompt was run {a.repeats} times per version on {len(names)} photos (the four bundled ones and the twelve squares of `eval/CITIES.md`, 1.5 km each) with Muse Spark 1.3.",
        "The zones are compared with the land-use polygons mapped in OpenStreetMap (© OpenStreetMap contributors, ODbL; a yardstick only: coarse, incomplete, of another date).",
        f"Only pixels that OSM labels as residential, industrial, commercial or park/forest count (on average {cover:.0%} of a photo), because OSM says nothing about the rest. A pixel is right when the model's zone there has the same kind; no zone there counts as wrong.", "",
        "| Version | Pixels right | Range over repeats | Bundled photos | Twelve squares | Macro F1 | Pixels the model labelled |", "|---|---|---|---|---|---|---|",
    ]
    for v, d in result["versions"].items():
        lines.append(f"| {v} | {d['accuracy']:.0%} | {d['accuracy_min']:.0%}-{d['accuracy_max']:.0%} | {d['bundled_accuracy']:.0%} | {d['cities_accuracy']:.0%} | {d['macro_f1']:.2f} | {d['model_labelled']:.0%} |")
    lines += ["", "A model that ignored the photo and gave the whole image one kind would score: " + ", ".join(f"{k} {x:.0%}" for k, x in baseline.items()) + ".", "", "| Version | Kind | Recall | Precision | F1 |", "|---|---|---|---|---|"]
    for v, d in result["versions"].items():
        for k in KINDS:
            m = d["kinds"][k]
            lines.append(f"| {v} | {k} | {m['recall']:.0%} | {m['precision']:.0%} | {m['f1']:.2f} |")
    lines += ["", f"Cost: a fresh scene call is about $0.01-0.02; the three versions on the 16 photos, three repeats each, cost about $1.8 in all (answers are cached, so a rerun is free). Limits: OSM land use is drawn by hand with its own idea of a boundary; it labels only part of every photo; a mapped park next to houses is a judgement call; one tile per place.", ""]
    (ROOT / "eval" / "SCENE_OSM.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
