"""Segment roads (SAM 3.1, cached), build the road graph and save a debug overlay.

Usage: uv run python scripts/build_graph.py columbus [--tiles 3] [--overlap 96] [--out scratch]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.overlay import draw_graph
from orbitroute.perception.segment import DEFAULT_OVERLAP, DEFAULT_TILES, segment_concept


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--tiles", type=int, default=DEFAULT_TILES)
    p.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    p.add_argument("--out", type=Path, default=Path("scratch"))
    a = p.parse_args()

    image_path = Path("data/samples") / f"{a.name}.jpg"
    meta = json.loads(image_path.with_suffix(".json").read_text())
    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
    client = MetaClient(s, guard)
    run = guard.new_run(s.run_cap_usd)

    mask = segment_concept(client, image_path.read_bytes(), "road", n=a.tiles, overlap=a.overlap, run=run)
    graph = build_road_graph(mask, meta["m_per_px"])
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out / f"graph_{a.name}.jpg"
    draw_graph(Image.open(image_path), graph, mask).save(out)
    print(json.dumps(graph.stats), f"run cost ${run.spent:.4f}", out)


if __name__ == "__main__":
    main()
