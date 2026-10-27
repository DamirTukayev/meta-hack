"""Download a NAIP tile (USGS National Map ImageServer, public domain) as a JPEG.

Usage: uv run python scripts/fetch_naip.py NAME LON LAT [--span-m 1500] [--px 1536] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbitroute.naip import fetch_tile, mercator_bbox


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("lon", type=float)
    p.add_argument("lat", type=float)
    p.add_argument("--span-m", type=float, default=1500)
    p.add_argument("--px", type=int, default=1536)
    p.add_argument("--out", type=Path, default=Path("data/samples"))
    a = p.parse_args()

    data, bbox = fetch_tile(a.lon, a.lat, span_m=a.span_m, px=a.px)
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{a.name}.jpg"
    path.write_bytes(data)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "source": "USGS NAIP",
                "bbox_lonlat": list(bbox),
                "bbox_mercator": list(mercator_bbox(a.lon, a.lat, a.span_m)),  # EPSG:3857 box of the picture; its pixels are square
                "span_m": a.span_m,
                "width_px": a.px,
                "height_px": a.px,
                "m_per_px": a.span_m / a.px,
            },
            indent=1,
        )
    )
    print(f"{path}  {len(data) // 1024} KB  bbox(lon/lat)={','.join(f'{v:.6f}' for v in bbox)}")


if __name__ == "__main__":
    main()
