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


def bbox_around(lon: float, lat: float, span_m: float) -> tuple[float, float, float, float]:
    half = span_m / 2
    dlat = half / 111_320
    dlon = half / (111_320 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


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
        "bbox": ",".join(f"{v:.6f}" for v in bbox),
        "bboxSR": 4326,
        "imageSR": 4326,
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
