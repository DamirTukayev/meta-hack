"""Record the model's understanding of every example sentence, so the demo runs without any API key.

For each bundled sample and each of its example sentences this asks the model once (or reads the answer already on disk)
and copies the answer into data/prewarmed (committed). The counts of orders and trucks come from the interface, so one
answer serves any counts.
Usage: uv run python scripts/prewarm_requests.py
"""

import shutil

import orbitroute.api as api
from orbitroute.config import CACHE_DIR, PREWARMED_DIR
from orbitroute.pipeline import list_samples
from orbitroute.understanding.request import parse_request_cached, request_cache_name

if api.offline_demo:
    raise SystemExit("Set MODEL_API_KEY first: this records what the model answers.")
PREWARMED_DIR.mkdir(parents=True, exist_ok=True)
client = api.get_text_client()
sentences = sorted({ex for s in list_samples() for ex in api.sample_dict(s)["examples"]})
for sentence in sentences:
    problem = parse_request_cached(client, sentence, f"20 orders. 3 trucks. {sentence}", n_orders=20, n_vehicles=3)
    name = request_cache_name(sentence)
    if (CACHE_DIR / name).exists():
        shutil.copy(CACHE_DIR / name, PREWARMED_DIR / name)
    print(f"{sentence!r}: deadline {problem.deadline_s // 3600:02d}:{problem.deadline_s % 3600 // 60:02d}, avoid {problem.avoid_zone_kinds} -> {name}")
