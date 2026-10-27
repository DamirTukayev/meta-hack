"""Assemble a 1.5 km square of NOAA Emergency Response Imagery (public domain) into a sample under data/samples.

Usage: uv run python scripts/fetch_storm.py NAME DATASET LON LAT --label "..." [--event "..."] [--date YYYY-MM-DD]
Example: uv run python scripts/fetch_storm.py houston-harvey 20170830-rgb -95.69697 29.77224 \
    --label "Houston, TX - Hurricane Harvey flooding" --event "Hurricane Harvey" --date 2017-08-30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbitroute.naip import mercator_bbox
from orbitroute.storm import CREDIT, fetch_storm_tile


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("dataset")
    p.add_argument("lon", type=float)
    p.add_argument("lat", type=float)
    p.add_argument("--label", required=True)
    p.add_argument("--event", default="")
    p.add_argument("--date", default="")
    p.add_argument("--span-m", type=float, default=1500)
    p.add_argument("--px", type=int, default=1536)
    p.add_argument("--out", type=Path, default=Path("data/samples"))
    a = p.parse_args()

    data, bbox = fetch_storm_tile(a.dataset, a.lon, a.lat, span_m=a.span_m, px=a.px)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{a.name}.jpg").write_bytes(data)
    (a.out / f"{a.name}.json").write_text(
        json.dumps(
            {
                "source": "NOAA NGS Emergency Response Imagery",
                "dataset": a.dataset,
                "event": a.event,
                "captured": a.date,
                "label": a.label,
                "credit": CREDIT,
                "bbox_lonlat": list(bbox),
                "bbox_mercator": list(mercator_bbox(a.lon, a.lat, a.span_m)),
                "span_m": a.span_m,
                "width_px": a.px,
                "height_px": a.px,
                "m_per_px": a.span_m / a.px,
            },
            indent=1,
        )
    )
    print(f"{a.name}: {len(data) // 1024} KB, bbox {bbox}")


if __name__ == "__main__":
    main()
