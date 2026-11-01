"""Read the roads of 28 more places with SAM 3.1 (paid, cached on disk) and fetch their OpenStreetMap ways.

The places extend the twelve squares of `eval/CITIES.md` so that `scripts/eval_hybrid.py --more` can compare the map graph with the
graph read from the photo on 44 photos instead of 16. Each place costs about $0.4-0.5 of SAM once; afterwards a run on it is cheap
and quick. Stops at the budget given. Usage: uv run python scripts/prewarm_areas.py [--budget 16]
"""

from __future__ import annotations

import sys
import time

from orbitroute.areas import ensure_area
from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetExceeded, BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.osm import osm_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.pipeline import get_sample

# (label, lat, lon): a mix of dense cores, suburbs, rural land and coast, all inside the NAIP coverage
MORE = [
    ("Philadelphia", 39.9526, -75.1652), ("Washington DC", 38.9072, -77.0369), ("Baltimore", 39.2904, -76.6122), ("Pittsburgh", 40.4406, -79.9959),
    ("Cleveland", 41.4993, -81.6944), ("Detroit", 42.3314, -83.0458), ("Indianapolis", 39.7684, -86.1581), ("St. Louis", 38.6270, -90.1994),
    ("Kansas City", 39.0997, -94.5786), ("Dallas", 32.7767, -96.7970), ("San Antonio", 29.4241, -98.4936), ("New Orleans", 29.9511, -90.0715),
    ("Nashville", 36.1627, -86.7816), ("Charlotte", 35.2271, -80.8431), ("Tampa", 27.9506, -82.4572), ("Salt Lake City", 40.7608, -111.8910),
    ("Phoenix", 33.4484, -112.0740), ("Las Vegas", 36.1699, -115.1398), ("San Diego", 32.7157, -117.1611), ("Sacramento", 38.5816, -121.4944),
    ("Boise", 43.6150, -116.2023), ("Albuquerque", 35.0844, -106.6504), ("Galveston", 29.3013, -94.7977), ("Savannah", 32.0809, -81.0912),
    ("Charleston", 32.7765, -79.9311), ("Asheville", 35.5951, -82.5515), ("Ames, Iowa (rural)", 42.0308, -93.6319), ("Burlington, Vermont", 44.4759, -73.2121),
]


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 16.0
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
    client = MetaClient(s, guard)
    spent0 = guard.total_spent()
    t0 = time.perf_counter()
    for label, lat, lon in MORE:
        if guard.total_spent() - spent0 >= budget:
            print(f"stopping: ${guard.total_spent() - spent0:.2f} spent of the ${budget:.2f} given")
            break
        before = guard.total_spent()
        try:
            area = ensure_area(lat, lon)
            sm = get_sample(area.name)
            segment_roads(client, sm.image_bytes, run=guard.new_run(2.0))
            g = osm_graph(area.name, sm.meta)
        except BudgetExceeded as exc:
            print(f"{label}: budget guard stopped it ({exc})")
            break
        except Exception as exc:  # one place failing (no coverage, SAM error) must not stop the others
            print(f"{label}: failed ({type(exc).__name__}: {str(exc)[:120]})", flush=True)
            continue
        print(f"{label:22s} {area.name} osm {g.stats['road_km']:5.1f} km  ${guard.total_spent() - before:.2f}  total ${guard.total_spent() - spent0:.2f}  {time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
