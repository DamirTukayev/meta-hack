"""Download a NAIP tile (USGS National Map ImageServer, public domain) as a JPEG.

Usage: uv run python scripts/fetch_naip.py NAME LON LAT [--span-m 1500] [--px 1536] [--out DIR]
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import httpx

URL = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"


def bbox_around(lon: float, lat: float, span_m: float) -> tuple[float, float, float, float]:
    half = span_m / 2
    dlat = half / 111_320
    dlon = half / (111_320 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("lon", type=float)
    p.add_argument("lat", type=float)
    p.add_argument("--span-m", type=float, default=1500)
    p.add_argument("--px", type=int, default=1536)
    p.add_argument("--out", type=Path, default=Path("data/samples"))
    a = p.parse_args()

    bbox = bbox_around(a.lon, a.lat, a.span_m)
    params = {
        "bbox": ",".join(f"{v:.6f}" for v in bbox),
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{a.px},{a.px}",
        "format": "jpgpng",
        "f": "image",
    }
    resp = httpx.get(URL, params=params, timeout=90)
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image"):
        raise SystemExit(f"unexpected response: {resp.text[:300]}")
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.name}.jpg"
    path.write_bytes(resp.content)
    print(f"{path}  {len(resp.content) // 1024} KB  bbox(lon/lat)={params['bbox']}")


if __name__ == "__main__":
    main()
