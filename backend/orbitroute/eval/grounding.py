"""How trustworthy is the land-use grounding, and which scene prompt is better?

There are no human labels for these images, so two objective checks are used instead of an accuracy score:
- stability: ask the model several times about the same image and measure how much its zone maps agree;
- vegetation sanity: park/forest zones should be greener (excess-green index) than built-up zones.
Plus structural quality: polygons of different kinds should not overlap.
"""

from __future__ import annotations

import io
import itertools
from dataclasses import dataclass
from statistics import mean

import numpy as np
import shapely
from PIL import Image

from orbitroute import prompts
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.pipeline import get_sample
from orbitroute.understanding.scene import ZONE_KINDS, Scene, analyze_scene

GRID = 96
KIND_ID = {k: i + 1 for i, k in enumerate(ZONE_KINDS)}  # 0 = not covered by any zone


def rasterize(scene: Scene, grid: int = GRID) -> np.ndarray:
    """Zone kind per grid cell (first polygon wins where several overlap), 0 where nothing is outlined."""
    xs = (np.arange(grid) + 0.5) * scene.width / grid
    ys = (np.arange(grid) + 0.5) * scene.height / grid
    gx, gy = np.meshgrid(xs, ys)
    out = np.zeros((grid, grid), dtype=np.int8)
    for z in scene.zones:
        inside = shapely.contains_xy(z.polygon, gx, gy) & (out == 0)
        out[inside] = KIND_ID[z.kind]
    return out


def overlap_share(scene: Scene, grid: int = GRID) -> float:
    """Share of the covered area where polygons of two or more different kinds lie on top of each other."""
    xs = (np.arange(grid) + 0.5) * scene.width / grid
    ys = (np.arange(grid) + 0.5) * scene.height / grid
    gx, gy = np.meshgrid(xs, ys)
    kinds_here = np.zeros((len(ZONE_KINDS) + 1, grid, grid), dtype=bool)
    for z in scene.zones:
        kinds_here[KIND_ID[z.kind]] |= shapely.contains_xy(z.polygon, gx, gy)
    count = kinds_here.sum(axis=0)
    covered = (count >= 1).sum()
    return float((count >= 2).sum() / covered) if covered else 0.0


def agreement(a: np.ndarray, b: np.ndarray) -> float:
    """Share of cells with the same label, among cells either map outlines."""
    either = (a > 0) | (b > 0)
    return float((a[either] == b[either]).mean()) if either.any() else 1.0


def excess_green(image_bytes: bytes, grid: int = GRID) -> np.ndarray:
    """Excess-green vegetation index (2G - R - B, 0..255 scale) per grid cell."""
    img = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((grid, grid), Image.BILINEAR)).astype(float)
    return 2 * img[..., 1] - img[..., 0] - img[..., 2]


def greenness_by_kind(label_map: np.ndarray, exg: np.ndarray) -> dict[str, float]:
    return {k: float(exg[label_map == i].mean()) for k, i in KIND_ID.items() if (label_map == i).any()}


@dataclass
class RunStats:
    zones: int
    warehouses: int
    covered: float
    overlap: float
    green: dict[str, float]


def run_grounding_eval(client: MetaClient, guard: BudgetGuard, samples: list[str], repeats: int = 3, log=print) -> dict:
    result: dict = {"repeats": repeats, "versions": {}}
    for version in prompts.versions("scene"):
        per_sample = {}
        cost0 = guard.total_spent()
        for name in samples:
            sample = get_sample(name)
            exg = excess_green(sample.image_bytes)
            maps, stats = [], []
            for _ in range(repeats):
                scene = analyze_scene(client, sample.image_bytes, use_cache=False, prompt_version=version)
                lm = rasterize(scene)
                maps.append(lm)
                stats.append(RunStats(len(scene.zones), len(scene.warehouses), float((lm > 0).mean()), overlap_share(scene), greenness_by_kind(lm, exg)))
            pair = [agreement(a, b) for a, b in itertools.combinations(maps, 2)]
            kinds = sorted({k for s in stats for k in s.green})
            per_sample[name] = {
                "stability": round(mean(pair), 3),
                "stability_min": round(min(pair), 3),
                "zones_per_run": [s.zones for s in stats],
                "covered_share": round(mean(s.covered for s in stats), 3),
                "overlap_share": round(mean(s.overlap for s in stats), 3),
                "excess_green_by_kind": {k: round(mean(s.green[k] for s in stats if k in s.green), 1) for k in kinds},
            }
            log(f"scene {version} {name}: stability {per_sample[name]['stability']}, overlap {per_sample[name]['overlap_share']}, zones {per_sample[name]['zones_per_run']}")
        result["versions"][version] = {"samples": per_sample, "cost_usd": round(guard.total_spent() - cost0, 4)}
    return result
