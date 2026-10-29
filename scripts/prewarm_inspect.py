"""Record the model's look at the unconfirmed stretches for the bundled photos, so that the recorded demo shows it too.

Runs every example sentence of every bundled photo as the interface does by default (20 orders placed by the agent, 3 trucks,
the deterministic repair policy, which is also what the keyless demo uses), so the crops asked about are the ones the demo will
ask about; the answers (a few cents in all) are copied to data/prewarmed/inspect_*.json.

Usage: uv run python scripts/prewarm_inspect.py       (needs a key in .env)
"""

from __future__ import annotations

import shutil

from orbitroute import api
from orbitroute.config import CACHE_DIR, PREWARMED_DIR
from orbitroute.pipeline import get_sample, run_pipeline


def main() -> None:
    for old in CACHE_DIR.glob("inspect_*.json"):  # start clean: whatever is there at the end was asked for by these runs
        old.unlink()
    for s in api.list_samples():
        for sentence in api.EXAMPLES.get(s.name, []):
            result = run_pipeline(
                get_sample(s.name), sentence, client=api.get_client(), text_client=api.get_text_client(), guard=api.guard, run_cap_usd=1.0,
                seed=0, use_model_decider=False, auto_orders=20, trucks=3, emit=lambda e: None,
            )
            print(f"{s.name}: {sentence!r}: {result.status}")
    PREWARMED_DIR.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in CACHE_DIR.glob("inspect_*.json"))
    for name in names:
        shutil.copy(CACHE_DIR / name, PREWARMED_DIR / name)
    print(f"{len(names)} answers copied to {PREWARMED_DIR}")


if __name__ == "__main__":
    main()
