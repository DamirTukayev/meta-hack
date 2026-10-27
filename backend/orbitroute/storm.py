"""NOAA Emergency Response Imagery: aerial photos taken in the days after a hurricane or flood (public domain).

NOAA's National Geodetic Survey serves the photos as ready-made web-map tiles, so a square of any size around a point
can be assembled from a few hundred small JPEGs instead of downloading multi-gigabyte GeoTIFFs. The result has the same
shape as `naip.fetch_tile`: a JPEG with square pixels plus its bounding box.
"""

from __future__ import annotations

import io
import math
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from orbitroute.naip import DEFAULT_PX, DEFAULT_SPAN_M, EARTH_R, NoImagery, bbox_around, mercator_bbox, to_mercator

CDN = "https://stormscdn.ngs.noaa.gov"
ZOOM = 18  # about 0.52 m per pixel on the ground at 30 degrees north; the photos are 0.3 m
TILE = 256
CREDIT = "Imagery: NOAA National Geodetic Survey, Emergency Response Imagery (public domain)"
ORIGIN = math.pi * EARTH_R  # half the width of the Web Mercator world in metres


def _tile_coords(x_m: float, y_m: float, z: int) -> tuple[float, float]:
    """Web Mercator metres -> fractional XYZ tile coordinates."""
    n = 2**z
    return (x_m + ORIGIN) / (2 * ORIGIN) * n, (ORIGIN - y_m) / (2 * ORIGIN) * n


def fetch_storm_tile(dataset: str, lon: float, lat: float, *, span_m: float = DEFAULT_SPAN_M, px: int = DEFAULT_PX, client: httpx.Client | None = None, zoom: int = ZOOM) -> tuple[bytes, tuple[float, float, float, float]]:
    """A `span_m` ground square of the NOAA dataset (for example "20170830-rgb") centred on a point, as a JPEG with square pixels."""
    bbox = bbox_around(lon, lat, span_m)
    x0, y0, x1, y1 = mercator_bbox(lon, lat, span_m)
    fx0, fy0 = _tile_coords(x0, y1, zoom)  # top-left of the box in tile coordinates
    fx1, fy1 = _tile_coords(x1, y0, zoom)
    tx0, ty0, tx1, ty1 = int(fx0), int(fy0), int(fx1), int(fy1)
    cols, rows = tx1 - tx0 + 1, ty1 - ty0 + 1
    mosaic = Image.new("RGB", (cols * TILE, rows * TILE))
    http = client or httpx.Client(timeout=30)
    found = 0

    def get(ij: tuple[int, int]) -> tuple[int, int, bytes | None]:
        i, j = ij
        r = http.get(f"{CDN}/{dataset}/{zoom}/{tx0 + i}/{ty0 + j}")
        return i, j, r.content if r.status_code == 200 and r.headers.get("content-type", "").startswith(("image", "binary")) else None

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for i, j, data in pool.map(get, [(i, j) for i in range(cols) for j in range(rows)]):
                if data:
                    try:
                        mosaic.paste(Image.open(io.BytesIO(data)).convert("RGB"), (i * TILE, j * TILE))
                        found += 1
                    except OSError:
                        pass
    finally:
        if client is None:
            http.close()
    if found < 0.8 * cols * rows:
        raise NoImagery("NOAA has no photo of this place in that dataset.")
    box = (round((fx0 - tx0) * TILE), round((fy0 - ty0) * TILE), round((fx1 - tx0) * TILE), round((fy1 - ty0) * TILE))
    out = mosaic.crop(box).resize((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92)
    return buf.getvalue(), bbox
