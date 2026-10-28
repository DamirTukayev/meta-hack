"""Areas the user picks on a map: a NAIP tile is fetched once, stored, and then behaves like a bundled sample."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from orbitroute.config import AREAS_DIR
from orbitroute.naip import DEFAULT_PX, DEFAULT_SPAN_M, fetch_tile, mercator_bbox

PREFIX = "area-"
MAX_AREAS = 300  # picked areas kept on disk; the oldest are deleted beyond this, so downloads cannot fill the disk


def area_id(lat: float, lon: float) -> str:
    """Stable id; positions are rounded to ~11 m so nearby picks share one cached tile."""
    key = f"{round(lat, 4):.4f},{round(lon, 4):.4f}"
    return PREFIX + hashlib.sha1(key.encode()).hexdigest()[:10]


@dataclass
class Area:
    name: str
    created: bool  # False when the tile was already stored (no new download)


def ensure_area(lat: float, lon: float, *, client=None) -> Area:
    name = area_id(lat, lon)
    jpg = AREAS_DIR / f"{name}.jpg"
    if jpg.exists():
        return Area(name, created=False)
    data, bbox = fetch_tile(lon, lat, client=client)
    AREAS_DIR.mkdir(parents=True, exist_ok=True)
    jpg.write_bytes(data)
    (AREAS_DIR / f"{name}.json").write_text(
        json.dumps(
            {
                "source": "USGS NAIP",
                "label": f"Custom area ({lat:.4f}, {lon:.4f})",
                "lat": lat,
                "lon": lon,
                "bbox_lonlat": list(bbox),
                "bbox_mercator": list(mercator_bbox(lon, lat, DEFAULT_SPAN_M)),
                "span_m": DEFAULT_SPAN_M,
                "width_px": DEFAULT_PX,
                "height_px": DEFAULT_PX,
                "m_per_px": DEFAULT_SPAN_M / DEFAULT_PX,
            }
        )
    )
    _prune(MAX_AREAS)
    return Area(name, created=True)


def _prune(keep: int) -> None:
    """Delete the oldest stored areas beyond `keep` (an image and its sidecar JSON each)."""
    images = sorted(AREAS_DIR.glob(f"{PREFIX}*.jpg"), key=lambda p: p.stat().st_mtime)
    for jpg in images[: max(len(images) - keep, 0)]:
        jpg.unlink(missing_ok=True)
        jpg.with_suffix(".json").unlink(missing_ok=True)
