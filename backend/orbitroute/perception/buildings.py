"""Delivery addresses from an aerial photo: the buildings SAM 3.1 finds.

Orders used to be scattered over road nodes. A delivery goes to a house, so the targets are building centres; each one is
then served from the nearest road node that the trucks may use.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max

from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.perception.segment import segment_concept

CONCEPT = "building"
TILES, OVERLAP = 6, 48
MIN_AREA_M2, MAX_AREA_M2 = 40.0, 6000.0  # sheds and vehicles are too small; huge blobs are lots or roofs run together


def segment_buildings(client: MetaClient, image_bytes: bytes, *, run: RunBudget | None = None, use_cache: bool = True) -> np.ndarray:
    return segment_concept(client, image_bytes, CONCEPT, n=TILES, overlap=OVERLAP, run=run, use_cache=use_cache)


def building_cache_name(image_bytes: bytes) -> str:
    import hashlib

    return f"sam_{hashlib.sha256(image_bytes).hexdigest()[:16]}_{CONCEPT}_{TILES}x{TILES}_o{OVERLAP}.npz"


def building_points(mask: np.ndarray, m_per_px: float, *, min_area_m2: float = MIN_AREA_M2, max_area_m2: float = MAX_AREA_M2) -> list[tuple[float, float]]:
    """One (x, y) per building in image pixels. Houses in a row come out of SAM as one blob: they are told apart by the
    peaks of the distance transform, about one per roof."""
    clean = ndi.binary_opening(mask, structure=np.ones((3, 3), bool))
    labels, n = ndi.label(clean)
    dist = ndi.distance_transform_edt(clean)
    min_px, max_px = min_area_m2 / m_per_px**2, max_area_m2 / m_per_px**2
    sizes = ndi.sum(clean, labels, range(1, n + 1))
    points: list[tuple[float, float]] = []
    spacing = max(int(7 / m_per_px), 3)  # roofs are rarely closer than 7 m
    for lab, size in enumerate(sizes, start=1):
        if size < min_px or size > max_px:
            continue
        comp = labels == lab
        peaks = peak_local_max(np.where(comp, dist, 0.0), min_distance=spacing, threshold_abs=1.5 / m_per_px, labels=comp.astype(int), exclude_border=False)
        if len(peaks) == 0:  # a small roof: its brightest point of the distance map is its middle
            r, c = np.unravel_index(np.argmax(np.where(comp, dist, 0.0)), comp.shape)
            peaks = np.array([[r, c]])
        points.extend((float(c), float(r)) for r, c in peaks)
    return points
