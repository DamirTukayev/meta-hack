"""Write readable traces of a few runs to examples/runs/*.md: the agent log, the verification and the outcome.

They run on the recorded answers (no API key, no cost), so anyone can regenerate them and compare.
Usage: uv run python scripts/record_runs.py
"""

import json
import os

os.environ["OFFLINE_DEMO"] = "1"  # recorded answers only: no model call can happen

from fastapi.testclient import TestClient

import orbitroute.api as api
from orbitroute.limits import RateLimiter

api.run_limit_ip = RateLimiter(1000, 60)
api.run_limit_day = RateLimiter(1000, 60)
client = TestClient(api.app)

RUNS = [
    ("columbus-industrial", "Columbus, OH: the plan crosses the industrial zone, the agent repairs it", "columbus", "by 12:00, avoid the industrial zone", {"auto_orders": 20, "trucks": 3}),
    ("houston-flood", "Houston after Hurricane Harvey: keep the trucks out of the flood", "houston-harvey", "by 14:00, avoid the flooded areas", {"auto_orders": 20, "trucks": 3}),
    ("houston-cutoff", "Houston, flooded streets, orders clicked freely: the water cuts most of them off", "houston-harvey-b", "by 14:00, avoid the flooded areas", {"free_orders": 16, "trucks": 3}),
]


def stream(body: dict) -> list[dict]:
    out = []
    for block in client.post("/api/run", json=body).text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append({"event": lines["event"], **json.loads(lines["data"])})
    return out


def spread_points(sample: str, n: int) -> tuple[list, list]:
    """The depot the agent picks and n orders spread over the road graph, as a user clicking around would place them."""
    got = stream({"sample": sample, "request": "by 14:00, avoid the flooded areas", "auto_orders": 5, "trucks": 3})
    nodes = next(e["data"]["graph"]["nodes"] for e in got if e.get("type") == "perception")
    depot = next(e["data"]["depot"] for e in got if e.get("type") == "scenario")
    pts = [nodes[0]]
    while len(pts) < n:
        pts.append(max(nodes, key=lambda c: min((c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2 for p in pts)))
    return depot, [p for p in pts if (p[0] - depot[0]) ** 2 + (p[1] - depot[1]) ** 2 > 900]


def trace(slug: str, title: str, sample: str, sentence: str, extra: dict) -> str:
    body = {"sample": sample, "request": sentence, **{k: v for k, v in extra.items() if k != "free_orders"}}
    if "free_orders" in extra:
        depot, orders = spread_points(sample, extra["free_orders"])
        body["custom"] = {"depot": depot, "orders": orders}
    events = stream(body)
    ev = [e for e in events if e["event"] == "event"]
    t0 = ev[0]["t"]
    result = next(e["data"] for e in ev if e["type"] == "result")
    lines = [f"# {title}", "", f"Sample `{sample}`, request: *\"{sentence}\"*, {extra.get('auto_orders') or len(body['custom']['orders'])} orders, {extra['trucks']} trucks. Recorded answers only: no API key, no model call, so the repair choices and the recommendation come from the deterministic rules; with a key Muse Spark makes them.", "", "## What the agent did", ""]
    for e in ev:
        if e["type"] in ("matrix", "stage", "start") or e["message"] == "":
            continue
        lines.append(f"- `{e['t'] - t0:5.1f}s` **{e['type']}**: {e['message']}")
    lines += ["", "## Verification of the plan shown", "", "| Check | Result | Detail |", "|---|---|---|"]
    for c in result["report"]["checks"]:
        lines.append(f"| {c['title']} | {'pass' if c['passed'] else 'FAIL'} | {c['detail']} |")
    m = result["report"]["metrics"]
    lines += ["", f"**Outcome: {result['status']}.** {result['plan']['served']} orders served, last truck back at {m['last_return']}, {m['total_km']} km."]
    if result["relaxations"]:
        lines += ["", "Alternatives, each solved and verified:", ""]
        for i, o in enumerate(result["relaxations"]):
            mark = " (recommended)" if result.get("recommendation") and result["recommendation"]["index"] == i else ""
            lines.append(f"{i + 1}. {o['description']}{mark}")
        if result.get("recommendation"):
            lines += ["", f"Recommendation ({result['recommendation']['source']}): {result['recommendation']['reason']}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for slug, title, sample, sentence, extra in RUNS:
        text = trace(slug, title, sample, sentence, extra)
        open(f"examples/runs/{slug}.md", "w").write(text)
        print(f"{slug}: {len(text.splitlines())} lines")
