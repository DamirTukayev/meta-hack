"""Flooded areas from an aerial photo, found with SAM 3.1.

Navigators know the roads as they were before the water came. A photo taken during the flood shows what is passable now:
SAM segments the standing water, the water becomes zones the trucks must not enter, and the verifier checks the routes
against them like any other avoided zone.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from shapely.geometry import Polygon
from skimage.measure import find_contours
from skimage.morphology import remove_small_holes, remove_small_objects

from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.perception.segment import segment_concept
from orbitroute.understanding.scene import Zone

FLOOD_CONCEPTS = ("flooded area", "flood water")  # united: each finds water the other misses
FLOOD_TILES, FLOOD_OVERLAP = 4, 64  # water is large and plain, so far fewer tiles than for roads (32 calls, about $0.08)
MIN_AREA_M2 = 250.0  # smaller puddles do not block a street
MARGIN_M = 6.0  # water spreads a little beyond what is visible, and roads run along its edge


def segment_floods(client: MetaClient, image_bytes: bytes, *, run: RunBudget | None = None, use_cache: bool = True) -> np.ndarray:
    mask: np.ndarray | None = None
    for concept in FLOOD_CONCEPTS:
        part = segment_concept(client, image_bytes, concept, n=FLOOD_TILES, overlap=FLOOD_OVERLAP, run=run, use_cache=use_cache)
        mask = part if mask is None else mask | part
    assert mask is not None
    return mask


def flood_cache_names(image_bytes: bytes) -> list[str]:
    import hashlib

    key = hashlib.sha256(image_bytes).hexdigest()[:16]
    return [f"sam_{key}_{c.replace(' ', '_')}_{FLOOD_TILES}x{FLOOD_TILES}_o{FLOOD_OVERLAP}.npz" for c in FLOOD_CONCEPTS]


def flood_zones(mask: np.ndarray, m_per_px: float, *, min_area_m2: float = MIN_AREA_M2, margin_m: float = MARGIN_M) -> list[Zone]:
    """One zone per connected patch of water, slightly enlarged. Holes are filled: a dry spot inside the flood cannot be reached."""
    min_px = max(int(min_area_m2 / (m_per_px**2)), 1)
    clean = ndi.binary_closing(mask, structure=np.ones((5, 5), bool))
    clean = remove_small_holes(clean, max_size=min_px)
    clean = remove_small_objects(clean, max_size=min_px - 1)
    labels, n = ndi.label(clean)
    margin_px = margin_m / m_per_px
    zones: list[Zone] = []
    for lab in range(1, n + 1):
        patch = np.pad(labels == lab, 1)
        contours = find_contours(patch.astype(float), 0.5)
        if not contours:
            continue
        ring = max(contours, key=len)
        poly = Polygon([(float(c) - 1, float(r) - 1) for r, c in ring])  # find_contours gives (row, col)
        if not poly.is_valid:
            poly = poly.buffer(0)
        poly = poly.buffer(margin_px).simplify(1.5 / m_per_px * 0.5)
        if poly.is_empty:
            continue
        for part in getattr(poly, "geoms", [poly]):
            if part.geom_type == "Polygon" and part.area * m_per_px**2 >= min_area_m2:
                zones.append(Zone("flooded", part))
    return zones
