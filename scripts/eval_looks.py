"""Do Muse Spark 1.3 and Muse Spark Open say the same about the same road stretch? The second look, on many places.

For every photo of `scripts/eval_hybrid.py --more` the three longest stretches of mapped road that the SAM mask does not confirm are
cropped with the stretch marked (as the product does), and both models are asked what they see: a clear road, standing water, debris,
no road visible, or hidden. There are no ground-truth labels, so this measures agreement between two models and the spread of what they
say, not accuracy; the crops of the disagreements are written to a local folder so that a person can look at them.
Writes eval/LOOKS.md and eval/looks.json. Usage: uv run python scripts/eval_looks.py [--crops DIR]
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

import networkx as nx
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from eval_hybrid import BUNDLED, CITIES
from prewarm_areas import MORE

import orbitroute.api as api
from orbitroute.agent import inspection
from orbitroute.areas import ensure_area
from orbitroute.config import ROOT
from orbitroute.llm.client import MetaClient, guard_for
from orbitroute.perception.evidence import annotate
from orbitroute.perception.osm import osm_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.pipeline import get_sample

PER_PHOTO, MIN_M = 3, 60.0


def ask(client, crop: bytes) -> dict:
    """`inspection.look` without its on-disk memory: that memory is keyed by the crop alone, so the second model would be handed the first one's answer."""
    messages = [{"role": "user", "content": [{"type": "text", "text": inspection.PROMPT}, inspection.image_part(crop)]}]
    for attempt in range(3):  # same retry as the product: the open-weight model now and then answers with nothing
        try:
            return client.chat_json(messages, "StretchLook", inspection.SCHEMA, max_completion_tokens=3000, reasoning_effort="low", run=None, label="inspect-eval")[0]
        except ValueError:
            if attempt == 2:
                raise


def unseen_runs(graph) -> list[list[tuple[int, int]]]:
    """Connected stretches of unconfirmed road, as paths between their two ends, longest first."""
    ug = nx.Graph([(e.u, e.v) for e in graph.edges if e.risk == "unseen"])
    length = {(e.u, e.v): e.length_m for e in graph.edges}
    length.update({(v, u): m for (u, v), m in length.items()})
    runs = []
    for comp in nx.connected_components(ug):
        sub = ug.subgraph(comp)
        ends = [n for n in sub if sub.degree(n) == 1]
        if len(ends) < 2:
            continue
        a, b = max(((x, y) for x in ends for y in ends if x < y), key=lambda p: nx.shortest_path_length(sub, *p))
        path = nx.shortest_path(sub, a, b)
        edges = list(zip(path, path[1:]))
        if sum(length[e] for e in edges) >= MIN_M:
            runs.append(edges)
    return sorted(runs, key=lambda r: -sum(length[e] for e in r))


def main() -> None:
    crops_dir = Path(sys.argv[sys.argv.index("--crops") + 1]) if "--crops" in sys.argv else None
    s = api.settings
    meta = api.get_client()
    clients = {"meta": meta, "baseten": MetaClient(s, guard_for(s, "baseten"), provider="baseten")}
    guard_meta = api.guard
    spent0 = {"meta": guard_meta.total_spent(), "baseten": guard_for(s, "baseten").total_spent()}
    run = guard_meta.new_run(3.0)
    names = BUNDLED + [ensure_area(lat, lon).name for lat, lon in CITIES] + [ensure_area(lat, lon).name for _, lat, lon in MORE]
    rows = []
    for name in names:
        sm = get_sample(name)
        mask = segment_roads(meta, sm.image_bytes, run=run)  # cached: read before
        graph = osm_graph(name, sm.meta)
        annotate(graph, mask, [])
        img = Image.open(io.BytesIO(sm.image_bytes))

        class Stub:
            pass

        Stub.graph = graph
        for i, r in enumerate(unseen_runs(graph)[:PER_PHOTO]):
            crop, _ = inspection._crop(img, Stub, r)
            said = {}
            for key, client in clients.items():
                try:
                    a = ask(client, crop)
                    said[key] = {"condition": a["condition"], "confidence": a["confidence"], "verdict": inspection.verdict_of(a)}
                except Exception as exc:  # one failed answer must not stop the sweep
                    said[key] = {"condition": "error", "confidence": 0.0, "verdict": "error", "error": type(exc).__name__}
            rows.append({"photo": name, **said})
            if crops_dir and said["meta"]["condition"] != said["baseten"]["condition"]:
                crops_dir.mkdir(parents=True, exist_ok=True)
                (crops_dir / f"{name}_{i}_{said['meta']['condition']}_vs_{said['baseten']['condition']}.jpg").write_bytes(crop)
        print(name, len([r for r in rows if r["photo"] == name]), "stretches", flush=True)
        (ROOT / "eval" / "looks.json").write_text(json.dumps(rows, indent=1))

    ok = [r for r in rows if r["meta"]["condition"] != "error" and r["baseten"]["condition"] != "error"]
    same = sum(r["meta"]["condition"] == r["baseten"]["condition"] for r in ok)
    same_verdict = sum(r["meta"]["verdict"] == r["baseten"]["verdict"] for r in ok)
    cm, cb = Counter(r["meta"]["condition"] for r in ok), Counter(r["baseten"]["condition"] for r in ok)
    confusion = Counter((r["meta"]["condition"], r["baseten"]["condition"]) for r in ok if r["meta"]["condition"] != r["baseten"]["condition"])
    cost = {k: (guard_meta if k == "meta" else guard_for(s, k)).total_spent() - spent0[k] for k in clients}
    lines = [
        "# Second look: two models, the same crops", "",
        f"Generated by `scripts/eval_looks.py`. On {len(set(r['photo'] for r in rows))} photos the {PER_PHOTO} longest stretches of mapped road that the SAM mask does not confirm were cropped with the stretch marked (as the product does) and shown to Muse Spark 1.3 (Meta API) and Muse Spark Open (Baseten): {len(ok)} stretches.",
        "There are no labels: this measures how often the two agree and what they say, not which is right. Only standing water or debris would make the agent plan around a stretch; the other answers leave the plan as it is.", "",
        "| What they said | Muse Spark 1.3 | Muse Spark Open |", "|---|---|---|",
        *[f"| {c} | {cm.get(c, 0)} | {cb.get(c, 0)} |" for c in sorted(set(cm) | set(cb))], "",
        f"Same answer: **{same} of {len(ok)}** ({same / max(len(ok), 1):.0%}). Same consequence for the plan (blocked or not): **{same_verdict} of {len(ok)}** ({same_verdict / max(len(ok), 1):.0%}). "
        + ("Where they differed (Muse Spark 1.3 → Muse Spark Open): " + ", ".join(f"{a} → {b} ×{n}" for (a, b), n in confusion.most_common()) + "." if confusion else "They never differed."),
        f"Cost of this run: about ${cost['meta']:.2f} on the Meta API and ${cost['baseten']:.2f} on Baseten. Limits: no ground truth, the choice of stretches (the longest unconfirmed ones) favours trees and shadow, and the crops are one 1.5 km tile each.", "",
    ]
    (ROOT / "eval" / "LOOKS.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
