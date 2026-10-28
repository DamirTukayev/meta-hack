"""Second look at the gaps the road graph had to bridge.

A tiled SAM pass finds most streets, but under trees and shadows it leaves holes, and the graph builder then draws a straight
link across the hole so that the network stays connected. Such a link is a guess. Here each long link gets a closer look:
a crop around it, only a bit larger than a tile of the finest tiling, goes to SAM again. If the new mask follows the link
(the road is there, it was just missed), the road is added to the mask; otherwise the link stays and is reported as unconfirmed.
Only a corridor around the link is taken from the new mask, so a second look cannot add roads somewhere else.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt

from orbitroute.config import CACHE_DIR, resolve_cached
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import RoadGraph
from orbitroute.perception.sam import parse_instances, response_text

MIN_LINK_M = 30.0  # shorter links are tree shadows and crossings, not worth a second look (same as the verifier's note)
MIN_WINDOW_PX = 180  # about a tile of the 12x12 tiling with its overlap: the size at which narrow streets are found
PAD_PX = 50
CORRIDOR_PX = 14  # only mask pixels this close to the link are taken over
CONFIRM_SHARE = 0.7  # share of the link that the new mask must cover (within 6 px) to count as a road


@dataclass
class GapResult:
    mask: np.ndarray
    looked: int = 0
    confirmed: int = 0


def _window(a: np.ndarray, b: np.ndarray, width: int, height: int) -> tuple[int, int, int, int]:
    mid = (a + b) / 2
    size = max(MIN_WINDOW_PX, int(np.linalg.norm(a - b)) + 2 * PAD_PX)
    left = int(min(max(mid[0] - size / 2, 0), max(width - size, 0)))
    top = int(min(max(mid[1] - size / 2, 0), max(height - size, 0)))
    return left, top, min(left + size, width), min(top + size, height)


def _cache_path(image_bytes: bytes, win: tuple[int, int, int, int]) -> str:
    key = hashlib.sha256(image_bytes).hexdigest()[:16]
    return f"sam_{key}_gap_{win[0]}_{win[1]}_{win[2]}_{win[3]}.npz"


def gap_cache_names(image_bytes: bytes, graph: RoadGraph, width: int, height: int) -> list[str]:
    return [_cache_path(image_bytes, _window(graph.nodes[e.u], graph.nodes[e.v], width, height)) for e in _long_links(graph)]


def _long_links(graph: RoadGraph):
    return [e for e in graph.edges if e.bridge and e.length_m > MIN_LINK_M]


def _crop_mask(client: MetaClient, image_bytes: bytes, img: Image.Image, win: tuple[int, int, int, int], run: RunBudget | None) -> np.ndarray:
    path = resolve_cached(CACHE_DIR, _cache_path(image_bytes, win))
    if path.exists():
        return np.load(path)["mask"]
    left, top, right, bottom = win
    buf = io.BytesIO()
    img.crop(win).save(buf, "JPEG", quality=92)
    data, _ = client.segment_raw(buf.getvalue(), "road", run=run, label="sam_gap")
    local = np.zeros((bottom - top, right - left), dtype=bool)
    for inst in parse_instances(response_text(data), "road", right - left, bottom - top):
        local |= inst.mask
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, mask=local)
    return local


def fill_gaps(client: MetaClient, image_bytes: bytes, mask: np.ndarray, graph: RoadGraph, *, run: RunBudget | None = None, workers: int = 8) -> GapResult:
    """The road mask with the roads found by a closer look at the long links of `graph`; build the graph again from it."""
    links = _long_links(graph)
    if not links:
        return GapResult(mask)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    height, width = mask.shape
    wins = [_window(graph.nodes[e.u], graph.nodes[e.v], width, height) for e in links]

    def look(i: int) -> np.ndarray:
        return _crop_mask(client, image_bytes, img, wins[i], run)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        crops = list(pool.map(look, range(len(links))))

    out = mask.copy()
    confirmed = 0
    for e, win, crop in zip(links, wins, crops):
        a, b = graph.nodes[e.u], graph.nodes[e.v]
        left, top, right, bottom = win
        n = max(int(np.linalg.norm(a - b) / 2), 2)
        pts = np.linspace(a, b, n)
        xs = np.clip((pts[:, 0] - left).round().astype(int), 0, right - left - 1)
        ys = np.clip((pts[:, 1] - top).round().astype(int), 0, bottom - top - 1)
        dist = distance_transform_edt(~crop) if crop.any() else np.full(crop.shape, 1e9)
        if (dist[ys, xs] <= 6).mean() < CONFIRM_SHARE:
            continue
        corridor = np.zeros(crop.shape, dtype=bool)
        corridor[ys, xs] = True
        corridor = binary_dilation(corridor, iterations=CORRIDOR_PX)
        out[top:bottom, left:right] |= crop & corridor
        confirmed += 1
    return GapResult(out, looked=len(links), confirmed=confirmed)
