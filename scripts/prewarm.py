"""Copy the cached model answers for the bundled samples into data/prewarmed (committed).

A fresh deployment then serves the two sample images without any SAM / scene call.
Usage: uv run python scripts/prewarm.py
"""

import hashlib
import json
import shutil

from orbitroute.config import PREWARMED_DIR, ROOT
from orbitroute.perception.flood import flood_cache_names
from orbitroute.perception.segment import cache_names

CACHE = ROOT / "data" / "cache"
PREWARMED_DIR.mkdir(parents=True, exist_ok=True)
for jpg in sorted((ROOT / "data" / "samples").glob("*.jpg")):
    h = hashlib.sha256(jpg.read_bytes()).hexdigest()[:16]
    meta = json.loads(jpg.with_suffix(".json").read_text())
    wanted = [*cache_names(jpg.read_bytes()), f"scene_{h}.json", *(flood_cache_names(jpg.read_bytes()) if meta.get("event") else [])]
    for name in wanted:
        src = CACHE / name
        if not src.exists():
            raise SystemExit(f"{name} is not cached yet: run the app once on {jpg.stem} first")
        shutil.copy(src, PREWARMED_DIR / name)
        print(f"{jpg.stem}: {name} ({src.stat().st_size // 1024 + 1} KB)")
