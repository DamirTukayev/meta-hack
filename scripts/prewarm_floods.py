"""Run the whole pipeline once on each bundled NOAA flood scene so that every answer is cached (paid, then free forever).

The scenes are the `flood-*` samples of data/samples (1.5 km squares of NOAA Emergency Response Imagery, public domain, fetched with
`scripts/fetch_storm.py`). One run reads the roads and buildings with SAM 3.1, the flood water, the scene and the request with
Muse Spark; `scripts/prewarm.py` then copies those answers into data/prewarmed. Usage: uv run python scripts/prewarm_floods.py [--budget 5]
"""

from __future__ import annotations

import sys
import time

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.osm import osm_graph
from orbitroute.pipeline import list_samples, run_pipeline

REQUEST = "by 15:00, avoid the flooded areas"


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 5.0
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, True)
    client = MetaClient(s, guard)
    spent0 = guard.total_spent()
    for sample in [x for x in list_samples() if x.name.startswith("flood-")]:
        if guard.total_spent() - spent0 >= budget:
            print(f"stopping: ${guard.total_spent() - spent0:.2f} spent of the ${budget:.2f} given")
            break
        before, t0 = guard.total_spent(), time.perf_counter()
        events = []
        try:
            run_pipeline(sample, REQUEST, client=client, guard=guard, run_cap_usd=1.5, auto_orders=20, trucks=3, use_model_decider=False, emit=events.append)
        except Exception as exc:  # noqa: BLE001 - one scene failing must not stop the others
            print(f"{sample.name}: failed ({type(exc).__name__}: {str(exc)[:150]})", flush=True)
            continue
        last = events[-1] if events else None
        print(f"{sample.name:26s} {len(events)} events  ${guard.total_spent() - before:.2f}  {time.perf_counter() - t0:.0f}s  last: {getattr(last, 'type', None)}", flush=True)
        osm_graph(sample.name, sample.meta)


if __name__ == "__main__":
    main()
