"""USGS NAIP imagery (public domain) for a square area around a point, via the USGS National Map ImageServer."""

from __future__ import annotations

import io
import math

import httpx
import numpy as np
from PIL import Image

URL = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
DEFAULT_SPAN_M = 1500.0
DEFAULT_PX = 1536
# Rough extent of the United States including Alaska and Hawaii; NAIP exists nowhere else.
US_LAT = (18.5, 71.6)
US_LON = (-179.5, -66.0)


class NoImagery(ValueError):
    """The requested place has no NAIP imagery (outside the US, over water, or not yet flown)."""


EARTH_R = 6_378_137.0  # Web Mercator sphere radius, metres


def to_mercator(lon: float, lat: float) -> tuple[float, float]:
    return EARTH_R * math.radians(lon), EARTH_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def from_mercator(x: float, y: float) -> tuple[float, float]:
    return math.degrees(x / EARTH_R), math.degrees(2 * math.atan(math.exp(y / EARTH_R)) - math.pi / 2)


def mercator_bbox(lon: float, lat: float, span_m: float) -> tuple[float, float, float, float]:
    """A square of `span_m` metres on the ground, as a Web Mercator box.

    Mercator stretches every distance by 1 / cos(latitude) in both directions, so the box is wider by that factor and
    the picture comes back with square pixels of span_m / px ground metres. (Asking for a box in degrees does not:
    the service enlarges it to the pixel aspect ratio and the picture is 30% taller on the ground than it is wide.)
    """
    x, y = to_mercator(lon, lat)
    half = span_m / math.cos(math.radians(lat)) / 2
    return x - half, y - half, x + half, y + half


def bbox_around(lon: float, lat: float, span_m: float) -> tuple[float, float, float, float]:
    """The same square as (lon_min, lat_min, lon_max, lat_max), for the record."""
    x0, y0, x1, y1 = mercator_bbox(lon, lat, span_m)
    (w, s), (e, n) = from_mercator(x0, y0), from_mercator(x1, y1)
    return w, s, e, n


def in_us(lat: float, lon: float) -> bool:
    return US_LAT[0] <= lat <= US_LAT[1] and US_LON[0] <= lon <= US_LON[1]


def has_imagery(jpeg: bytes) -> bool:
    """USGS answers with an all-black image where it has no coverage."""
    a = np.asarray(Image.open(io.BytesIO(jpeg)).convert("L"))
    return float((a <= 5).mean()) < 0.5 and float(a.std()) > 8


def fetch_tile(lon: float, lat: float, *, span_m: float = DEFAULT_SPAN_M, px: int = DEFAULT_PX, client: httpx.Client | None = None) -> tuple[bytes, tuple[float, float, float, float]]:
    """Returns (jpeg bytes, bbox lon/lat). Raises NoImagery when there is nothing to show."""
    if not in_us(lat, lon):
        raise NoImagery("Imagery is only available in the United States (USGS NAIP).")
    bbox = bbox_around(lon, lat, span_m)
    params = {
        "bbox": ",".join(f"{v:.2f}" for v in mercator_bbox(lon, lat, span_m)),
        "bboxSR": 3857,
        "imageSR": 3857,
        "size": f"{px},{px}",
        "format": "jpgpng",
        "f": "image",
    }
    http = client or httpx.Client(timeout=90)
    try:
        resp = http.get(URL, params=params)
    finally:
        if client is None:
            http.close()
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image"):
        raise NoImagery("The imagery service returned no picture for this place.")
    data = resp.content
    img = Image.open(io.BytesIO(data))
    if img.format != "JPEG":  # keep files small and uniform
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=92)
        data = buf.getvalue()
    if not has_imagery(data):
        raise NoImagery("No aerial imagery here. Try a populated area in the United States.")
    return data, bbox
