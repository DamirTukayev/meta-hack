"""Road segmentation with SAM 3.1.

SAM's concept prompt returns only a few instances for a whole image ("road" finds just the main
arterial), so the image is cut into overlapping tiles, each tile is segmented, and the masks are
united. Results are cached on disk by image hash and parameters so repeated runs cost nothing.
"""

from __future__ import annotations

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from orbitroute.config import ROOT
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.perception.sam import parse_instances, response_text

CACHE_DIR = ROOT / "data" / "cache"
# 6x6 tiles of ~256 px: narrow residential streets are only found when each tile is small. On a suburban
# area 3x3 tiles found 4.8 km of road, 5x5 found 14.2 km and 6x6 found 18.3 km (about $0.09 per image).
DEFAULT_TILES = 6
DEFAULT_OVERLAP = 48
MIN_CONFIDENCE = 0.0  # SAM confidences on thin roads are low (~0.5); filtering is left to later stages


def tile_windows(width: int, height: int, n: int, overlap: int) -> list[tuple[int, int, int, int]]:
    """n x n windows (left, top, right, bottom) that cover the image with the given overlap."""
    xs = np.linspace(0, width, n + 1).astype(int)
    ys = np.linspace(0, height, n + 1).astype(int)
    out = []
    for r in range(n):
        for c in range(n):
            out.append(
                (
                    max(xs[c] - overlap, 0),
                    max(ys[r] - overlap, 0),
                    min(xs[c + 1] + overlap, width),
                    min(ys[r + 1] + overlap, height),
                )
            )
    return out


def _cache_path(image_bytes: bytes, concept: str, n: int, overlap: int) -> Path:
    key = hashlib.sha256(image_bytes).hexdigest()[:16]
    return CACHE_DIR / f"sam_{key}_{concept.replace(' ', '_')}_{n}x{n}_o{overlap}.npz"


def segment_concept(
    client: MetaClient,
    image_bytes: bytes,
    concept: str = "road",
    *,
    n: int = DEFAULT_TILES,
    overlap: int = DEFAULT_OVERLAP,
    run: RunBudget | None = None,
    use_cache: bool = True,
    workers: int = 8,
) -> np.ndarray:
    """Union of SAM masks for `concept` over n x n overlapping tiles. Returns a bool (H, W) mask."""
    cache = _cache_path(image_bytes, concept, n, overlap)
    if use_cache and cache.exists():
        return np.load(cache)["mask"]

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = img.size
    windows = tile_windows(width, height, n, overlap)

    def run_tile(win: tuple[int, int, int, int]) -> np.ndarray:
        left, top, right, bottom = win
        buf = io.BytesIO()
        img.crop(win).save(buf, "JPEG", quality=92)
        data, _ = client.segment_raw(buf.getvalue(), concept, run=run, label=f"sam_{concept}")
        local = np.zeros((height, width), dtype=bool)
        for inst in parse_instances(response_text(data), concept, right - left, bottom - top):
            if (inst.confidence or 0.0) >= MIN_CONFIDENCE:
                local[top:bottom, left:right] |= inst.mask
        return local

    mask = np.zeros((height, width), dtype=bool)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(run_tile, windows):
            mask |= part

    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, mask=mask)
    return mask
