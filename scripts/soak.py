"""Soak test: many random runs through the real API (live models) to find crashes before a user does.

Each run picks a bundled sample, a sentence (some odd on purpose), counts of orders and trucks, and sometimes points clicked
at random, zones drawn at random and invalid input. Anything that ends in an "Unexpected error" or an exception is a bug;
refusals with a clear message are fine.
Usage: uv run python scripts/soak.py [N=120] [--seed 0]
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import orbitroute.api as api
from orbitroute.limits import RateLimiter

api.run_limit_ip = RateLimiter(10_000, 60)  # the soak is not a public visitor
api.run_limit_day = RateLimiter(10_000, 60)
client = TestClient(api.app)

SENTENCES = [
    "by 12:00, avoid the residential area", "by 09:00, avoid the industrial zone", "by 17:30, keep away from the commercial areas",
    "finish by 3pm and stay out of the park", "by 14:00, avoid the flooded areas", "no later than 11:15, avoid industrial and residential",
    "by 10:00", "avoid the residential area", "as fast as possible, avoid the factories", "by 18:00, each stop takes 8 minutes, avoid the flooded streets",
    "start at 07:00, back by 13:00, avoid the shops", "by noon, don't drive through houses", "by 16:00 shortest distance, avoid the industrial zone",
    "by 08:05, avoid the residential area", "by 20:00, avoid the flooded areas and the commercial area", "by 12:00 avoid the lake", "by 25:99, avoid the residential area",
    "", "x" * 390, "by 13:00, avoid the residential area; also deliver pizza to the moon",
]


def clicks(rng: random.Random, n: int, size: int = 1536) -> list[list[float]]:
    return [[rng.uniform(0, size), rng.uniform(0, size)] for _ in range(n)]


def one(i: int, seed: int) -> dict:
    rng = random.Random(seed * 100_003 + i)
    samples = [s["name"] for s in client.get("/api/samples").json() if not s["name"].startswith("area-")]  # bundled images only: their SAM answers are recorded
    sample = rng.choice(samples)
    body = {"sample": sample, "request": rng.choice(SENTENCES), "trucks": rng.randint(1, 8)}
    kind = rng.choices(["auto", "custom", "broken"], [0.55, 0.35, 0.10])[0]
    if kind == "auto":
        body["auto_orders"] = rng.randint(1, 60)
    elif kind == "custom":
        body["custom"] = {"depot": clicks(rng, 1)[0], "orders": clicks(rng, rng.randint(1, 30)), "zone": clicks(rng, rng.randint(3, 8)) if rng.random() < 0.5 else []}
    else:
        body["custom"] = rng.choice([{"orders": [[-5, -5]]}, {"orders": [[1e9, 1e9]], "depot": [0, 0]}, {"zone": [[1, 1], [2, 2]]}, {"orders": [[100, 100]] * 3, "zone": [[0, 0], [0, 0], [0, 0]]}])
        body["auto_orders"] = rng.choice([None, 5])
    t0 = time.perf_counter()
    out = {"i": i, "sample": sample, "sentence": body["request"][:60], "kind": kind, "trucks": body["trucks"]}
    try:
        r = client.post("/api/run", json=body)
        out["http"] = r.status_code
        if r.status_code != 200:
            out["outcome"] = f"http {r.status_code}"
        else:
            events = []
            for block in r.text.strip().split("\n\n"):
                lines = dict(line.split(": ", 1) for line in block.splitlines())
                events.append((lines["event"], json.loads(lines["data"])))
            failure = next((d["message"] for k, d in events if k == "failure"), None)
            result = next((d["data"] for k, d in events if k == "event" and d["type"] == "result"), None)
            out["outcome"] = f"failure: {failure[:90]}" if failure else (result["status"] if result else "NO RESULT")
            out["cost"] = result["cost_usd"] if result else 0
            out["bug"] = bool(failure and "Unexpected error" in failure) or (not failure and not result)
    except Exception as exc:  # a crash of the app itself
        out["outcome"] = f"EXCEPTION {type(exc).__name__}: {exc}"[:160]
        out["bug"] = True
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 0
    u0 = {k: v["spent_usd"] for k, v in client.get("/api/usage").json().items() if isinstance(v, dict)}
    with ThreadPoolExecutor(3) as pool:
        rows = list(pool.map(lambda i: one(i, seed), range(n)))
    u1 = {k: v["spent_usd"] for k, v in client.get("/api/usage").json().items() if isinstance(v, dict)}
    print(Counter(r["outcome"].split(":")[0] for r in rows))
    bugs = [r for r in rows if r.get("bug")]
    print(f"{len(rows)} runs, {len(bugs)} bugs, mean {sum(r['seconds'] for r in rows) / len(rows):.1f}s, spent", {k: round(u1[k] - u0[k], 4) for k in u1})
    for r in bugs:
        print("BUG", r)
    json.dump(rows, open("scratch/soak.json", "w"), indent=1)
