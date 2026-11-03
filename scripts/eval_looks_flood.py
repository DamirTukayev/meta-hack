"""The second look on flooded towns: does it find the water that SAM finds, and do two models agree?

`scripts/eval_looks.py` showed two models the same crops on dry photos, where standing water is nearly absent (3 of 130). Here the crops come from the
squares of `scripts/eval_flood_sweep.py` (towns after Harvey, Florence, Ian, Helene, Ida, Sally, Milton and the 2025 Texas flood): for each square the five longest
stretches of mapped road that the SAM mask does not confirm are cropped with the stretch marked, as the product does, and both Muse Spark 1.3 and Muse Spark Open say what they see.
For every stretch the share of its length inside the water outlines SAM 3.1 found on the whole photo is also measured, which gives a second, independent route to the same fact.
There are no human labels: both routes are models, so this measures how often independent perception agrees, not accuracy.
Writes eval/LOOKS_FLOOD.md and eval/looks_flood.json. Usage: uv run python scripts/eval_looks_flood.py [--budget 25]
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from eval_flood_sweep import BUNDLED, DIR, PLACES
from eval_looks import ask, unseen_runs

import orbitroute.api as api
from orbitroute.agent import inspection
from orbitroute.config import ROOT
from orbitroute.llm.client import MetaClient, guard_for
from orbitroute.perception.evidence import annotate
from orbitroute.perception.exposure import wet_mask
from orbitroute.perception.flood import flood_zones, segment_floods
from orbitroute.perception.osm import osm_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.pipeline import get_sample

PER_PHOTO = 5
WET, DRY = 0.5, 0.1  # a stretch is "in the water" when at least half of it lies inside SAM's water, "dry" when under a tenth does


def squares() -> list[tuple[str, bytes, dict]]:
    swept = {r["name"] for r in json.loads((ROOT / "eval" / "flood_sweep.json").read_text()) if "skipped" not in r}
    out = []
    for _, name, *_ in PLACES:
        if name in swept:
            out.append((name, (DIR / f"{name}.jpg").read_bytes(), json.loads((DIR / f"{name}.json").read_text())))
    for _, name in BUNDLED:
        if name in swept:
            sm = get_sample(name)
            out.append((name, sm.image_bytes, sm.meta))
    return out


def wet_share(graph, run: list[tuple[int, int]], wet: np.ndarray) -> float:
    inside = total = 0.0
    for u, v in run:
        (x0, y0), (x1, y1) = graph.nodes[u], graph.nodes[v]
        n = max(int(np.hypot(x1 - x0, y1 - y0) / 4), 2)
        for t in np.linspace(0, 1, n):
            x, y = int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))
            if 0 <= y < wet.shape[0] and 0 <= x < wet.shape[1]:
                total += 1
                inside += bool(wet[y, x])
    return inside / total if total else 0.0


def main() -> None:
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 25.0
    s = api.settings
    meta = api.get_client()
    clients = {"meta": meta, "baseten": MetaClient(s, guard_for(s, "baseten"), provider="baseten")}
    guard_meta = api.guard
    spent0 = {"meta": guard_meta.total_spent(), "baseten": guard_for(s, "baseten").total_spent()}
    run = guard_meta.new_run(budget)
    out_path = ROOT / "eval" / "looks_flood.json"
    rows = json.loads(out_path.read_text()) if out_path.exists() else []
    done = {r["photo"] for r in rows}
    for name, image, m in squares():
        if name in done:
            continue
        if guard_meta.total_spent() - spent0["meta"] >= budget:
            print("stopping: budget reached", flush=True)
            break
        try:
            mask = segment_roads(meta, image, run=run)
            wet = wet_mask(flood_zones(segment_floods(meta, image, run=run), m["m_per_px"]), mask.shape)
            graph = osm_graph(name, m)
        except Exception as exc:  # noqa: BLE001 - one square failing must not stop the sweep
            print(f"{name}: failed ({type(exc).__name__}: {str(exc)[:90]})", flush=True)
            continue
        annotate(graph, mask, [])
        img = Image.open(io.BytesIO(image))

        class Stub:
            pass

        Stub.graph = graph
        length = {(e.u, e.v): e.length_m for e in graph.edges}
        length.update({(v, u): m_ for (u, v), m_ in list(length.items())})
        for r in unseen_runs(graph)[:PER_PHOTO]:
            crop, _ = inspection._crop(img, Stub, r)
            said = {}
            for key, client in clients.items():
                try:
                    a = ask(client, crop)
                    said[key] = {"condition": a["condition"], "confidence": a["confidence"], "verdict": inspection.verdict_of(a)}
                except Exception as exc:  # noqa: BLE001
                    said[key] = {"condition": "error", "confidence": 0.0, "verdict": "error", "error": type(exc).__name__}
            rows.append({"photo": name, "length_m": round(sum(length[e] for e in r)), "wet_share": round(wet_share(graph, r, wet), 3), **said})
        out_path.write_text(json.dumps(rows, indent=1))
        print(name, len([r for r in rows if r["photo"] == name]), "stretches", f"${guard_meta.total_spent() - spent0['meta']:.2f}", flush=True)
    report(rows, {k: (guard_meta if k == "meta" else guard_for(s, k)).total_spent() - spent0[k] for k in clients})


def report(rows: list[dict], cost: dict) -> None:
    ok = [r for r in rows if r["meta"]["condition"] != "error" and r["baseten"]["condition"] != "error"]
    if not ok:
        return
    same = sum(r["meta"]["condition"] == r["baseten"]["condition"] for r in ok)
    same_v = sum(r["meta"]["verdict"] == r["baseten"]["verdict"] for r in ok)
    cm, cb = Counter(r["meta"]["condition"] for r in ok), Counter(r["baseten"]["condition"] for r in ok)
    wet = [r for r in ok if r["wet_share"] >= WET]
    dry = [r for r in ok if r["wet_share"] < DRY]

    def blocked(rs: list[dict], key: str) -> str:
        n = sum(r[key]["verdict"] == "blocked" for r in rs)
        return f"{n} of {len(rs)} ({n / max(len(rs), 1):.0%})"

    lines = [
        "# Second look on flooded towns: two models and SAM's water", "",
        f"Generated by `scripts/eval_looks_flood.py`. On {len({r['photo'] for r in ok})} NOAA squares of flooded towns (the squares of `eval/FLOOD_SWEEP.md`) the {PER_PHOTO} longest stretches of mapped road that the SAM mask does not confirm were cropped with the stretch marked "
        f"and shown to Muse Spark 1.3 (Meta API) and Muse Spark Open (Baseten): {len(ok)} stretches. For each stretch the share of its length inside the water outlines SAM 3.1 found on the whole photo was measured as a second, independent route to the same fact.",
        "There are no human labels, and both routes are models: this measures how often independent perception agrees, not which is right.", "",
        "| What they said | Muse Spark 1.3 | Muse Spark Open |", "|---|---|---|",
        *[f"| {c} | {cm.get(c, 0)} | {cb.get(c, 0)} |" for c in sorted(set(cm) | set(cb))], "",
        f"The two models gave the same answer on **{same} of {len(ok)}** ({same / len(ok):.0%}) and the same consequence for the plan (blocked or not) on **{same_v}** ({same_v / len(ok):.0%}).", "",
        "| Stretches | How many | Muse Spark 1.3 said blocked (water or debris) | Muse Spark Open said blocked |", "|---|---|---|---|",
        f"| at least half inside SAM's water | {len(wet)} | {blocked(wet, 'meta')} | {blocked(wet, 'baseten')} |",
        f"| under a tenth inside SAM's water | {len(dry)} | {blocked(dry, 'meta')} | {blocked(dry, 'baseten')} |", "",
        f"Cost of this run: about ${cost['meta']:.2f} on the Meta API and ${cost['baseten']:.2f} on Baseten by the local counters, which overstate the real bills. Limits: no ground truth; the stretches are the longest ones the road mask does not confirm, which favours trees and shadow; "
        "SAM's water is itself a model output and misses water under trees; a crop is one stretch of one 1.5 km square; the product also forbids every road inside SAM's water before the second look, so this tests the look on stretches that are often already avoided.", "",
    ]
    (ROOT / "eval" / "LOOKS_FLOOD.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
