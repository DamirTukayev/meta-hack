"""Write the OpenStreetMap roads of the bundled photos to data/prewarmed/, so that a fresh server needs no network for them.

The files hold only drivable ways with a few tags, and the schools, hospitals and stores that name large buildings (© OpenStreetMap contributors, ODbL; see data/SOURCES.md). A way the cache already
has is reused, otherwise it is fetched from Overpass.

Usage: uv run python scripts/prewarm_osm.py
"""

from __future__ import annotations

import json

from orbitroute.config import PREWARMED_DIR
from orbitroute.perception.osm import cache_name, fetch_places, fetch_roads, places_cache_name, trim
from orbitroute.pipeline import list_samples


def main() -> None:
    PREWARMED_DIR.mkdir(parents=True, exist_ok=True)
    for sm in list_samples():
        data = trim(fetch_roads(sm.name, sm.meta["bbox_lonlat"]))
        out = PREWARMED_DIR / cache_name(sm.name)
        out.write_text(json.dumps(data, separators=(",", ":")))
        print(f"{sm.name}: {len(data['elements'])} ways, {out.stat().st_size / 1000:.0f} kB (OSM data of {data['osm3s']['timestamp_osm_base']})")
        places = fetch_places(sm.name, sm.meta["bbox_lonlat"])  # schools, hospitals, stores: they only name large buildings
        (PREWARMED_DIR / places_cache_name(sm.name)).write_text(json.dumps({"osm3s": {"copyright": "© OpenStreetMap contributors, ODbL"}, "elements": places}, separators=(",", ":")))
        print(f"   {len(places)} places")


if __name__ == "__main__":
    main()
