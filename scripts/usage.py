"""Print our own running spend tally for each provider (estimates; the providers' dashboards are authoritative).

Usage: uv run python scripts/usage.py
"""

from orbitroute.config import Settings
from orbitroute.llm.client import guard_for

s = Settings.load()
for provider, label in (("meta", "Meta Model API"), ("baseten", "Baseten (Muse Spark Open)")):
    u = guard_for(s, provider).summary()
    print(f"{label}: ${u['spent_usd']} of our ${u['cap_usd']} cap, {u['calls']} paid calls")
    for k, v in list(u["by_label"].items())[:6]:
        print(f"    {k:18s} ${v}")
