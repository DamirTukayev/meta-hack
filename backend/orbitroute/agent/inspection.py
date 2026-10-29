"""A second look, by the model, at the stretches of a plan that the photo does not confirm.

The map says a road is there; the road mask of SAM may simply have missed it (trees, shadow, a dirt track). Only the stretches a plan
actually drives on matter, so after a plan is verified the longest of its unconfirmed runs are cropped from the photo, the stretch is
marked on the crop and Muse Spark is asked whether a truck can drive along it. A stretch it finds drivable is marked "clear"; one it finds
blocked (standing water, debris, a missing road) is marked "blocked", which makes routing avoid it when there is a way round.
What it cannot tell stays "unseen": a doubt is never turned into a verdict.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass

from PIL import Image, ImageDraw

from orbitroute.config import CACHE_DIR, resolve_cached
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import image_part
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan
from orbitroute.routing.zones import edge_key

MAX_LOOKS = 6  # runs looked at per plan: about $0.01 each
MIN_RUN_M = 40.0  # shorter runs are one gap in the mask, not worth a look
MIN_CONFIDENCE = 0.6
PAD_PX, MIN_WINDOW_PX = 70, 230

CONDITIONS = ("clear_road", "standing_water", "debris", "no_road_visible", "hidden_by_trees_or_shadow")
SCHEMA = {
    "type": "object",
    "properties": {"condition": {"type": "string", "enum": list(CONDITIONS)}, "confidence": {"type": "number"}},
    "required": ["condition", "confidence"],
}
PROMPT = (
    "This is an aerial photo, enlarged. A map says there is a road along the thin yellow line between the two circles, and a delivery truck "
    "is to drive along it. Look only at the ground under and around that line and say what you see there:\n"
    "- clear_road: a road, street, track or paved or open surface that a truck could drive on\n"
    "- standing_water: water covers the ground along the line\n"
    "- debris: debris, wreckage or fallen trees lie on it\n"
    "- no_road_visible: the line crosses roofs, pools or open ground that is clearly not a road\n"
    "- hidden_by_trees_or_shadow: trees or shadow cover the line, so you cannot tell (streets in leafy neighbourhoods are often half hidden: "
    "choose this rather than no_road_visible whenever trees overlap the line)\n"
    "Pick the one that fits best and give your confidence from 0 to 1."
)
# Only a positive sign of an obstacle (water, wreckage) settles a stretch as blocked. "No road visible" contradicts the map and the model
# says it readily under tree cover, so it stays a doubt, like trees and shadow.
CONDITION_VERDICT = {"clear_road": "clear", "standing_water": "blocked", "debris": "blocked", "no_road_visible": "unseen", "hidden_by_trees_or_shadow": "unseen"}


@dataclass
class Finding:
    edges: list[tuple[int, int]]
    length_m: float
    verdict: str  # "clear", "blocked" or "unseen" (could not tell)
    condition: str
    confidence: float
    center: tuple[float, float]


def unconfirmed_runs(scenario: Scenario, plan: Plan) -> list[list[tuple[int, int]]]:
    """Consecutive driven edges that are 'unseen', per route, in driving order."""
    g = scenario.graph.to_networkx()
    runs: list[list[tuple[int, int]]] = []
    for r in plan.routes:
        for leg in r.legs:  # a stop ends a run: the way out and the way back are looked at on their own
            cur: list[tuple[int, int]] = []
            for u, v in zip(leg, leg[1:]):
                if g[u][v].get("risk") == "unseen" and (not cur or cur[-1][1] == u):
                    cur.append((u, v))
                else:
                    if cur:
                        runs.append(cur)
                    cur = [(u, v)] if g[u][v].get("risk") == "unseen" else []
            if cur:
                runs.append(cur)
    return runs


def _crop(image: Image.Image, scenario: Scenario, run: list[tuple[int, int]]) -> tuple[bytes, tuple[float, float]]:
    pts = [scenario.graph.nodes[run[0][0]], *[scenario.graph.nodes[v] for _, v in run]]
    xs, ys = [float(p[0]) for p in pts], [float(p[1]) for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    size = int(max(MIN_WINDOW_PX, max(xs) - min(xs) + 2 * PAD_PX, max(ys) - min(ys) + 2 * PAD_PX))
    left = int(min(max(cx - size / 2, 0), max(image.width - size, 0)))
    top = int(min(max(cy - size / 2, 0), max(image.height - size, 0)))
    crop = image.crop((left, top, min(left + size, image.width), min(top + size, image.height))).convert("RGB")
    zoom = max(1.0, 512 / max(crop.size))  # small crops are enlarged so that a street is a few pixels wide
    crop = crop.resize((round(crop.width * zoom), round(crop.height * zoom)), Image.LANCZOS)
    draw = ImageDraw.Draw(crop)
    local = [((x - left) * zoom, (y - top) * zoom) for x, y in zip(xs, ys)]
    draw.line(local, fill=(255, 230, 0), width=2)
    for x, y in (local[0], local[-1]):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=(255, 230, 0), width=2)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=92)
    return buf.getvalue(), (cx, cy)


def look(client, crop: bytes, *, run: RunBudget | None = None) -> dict:
    """The model's answer for one crop; remembered on disk, so a repeated plan costs nothing."""
    path = resolve_cached(CACHE_DIR, f"inspect_{hashlib.sha256(crop).hexdigest()[:16]}.json")
    if path.exists():
        return json.loads(path.read_text())
    messages = [{"role": "user", "content": [{"type": "text", "text": PROMPT}, image_part(crop)]}]
    for attempt in range(3):  # the open-weight model now and then answers with nothing; asking again is cheap
        try:
            answer, _ = client.chat_json(messages, "StretchLook", SCHEMA, max_completion_tokens=3000, reasoning_effort="low", run=run, label="inspect")
            break
        except ValueError:
            if attempt == 2:
                raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answer))
    return answer


def verdict_of(answer: dict) -> str:
    """clear, blocked or unseen (not told): only a confident answer settles a doubt."""
    if float(answer.get("confidence", 0.0)) < MIN_CONFIDENCE:
        return "unseen"
    return CONDITION_VERDICT.get(str(answer.get("condition")), "unseen")


def inspect_plan(client, image_bytes: bytes, scenario: Scenario, plan: Plan, *, run: RunBudget | None = None, max_looks: int = MAX_LOOKS) -> list[Finding]:
    """Look at the longest unconfirmed runs of `plan` and set the risk of their edges in the graph (in place)."""
    graph = scenario.graph
    lengths = {edge_key(e.u, e.v): e.length_m for e in graph.edges}
    runs = [r for r in unconfirmed_runs(scenario, plan) if sum(lengths[edge_key(u, v)] for u, v in r) >= MIN_RUN_M]
    seen: set[frozenset] = set()
    unique = []
    for r in sorted(runs, key=lambda r: -sum(lengths[edge_key(u, v)] for u, v in r)):
        key = frozenset(edge_key(u, v) for u, v in r)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    image = Image.open(io.BytesIO(image_bytes))
    by_key: dict[tuple[int, int], list] = {}
    for e in graph.edges:
        by_key.setdefault(edge_key(e.u, e.v), []).append(e)
    findings: list[Finding] = []
    for r in unique[:max_looks]:
        crop, center = _crop(image, scenario, r)
        answer = look(client, crop, run=run)
        verdict = verdict_of(answer)
        if verdict != "unseen":
            for u, v in r:
                for e in by_key[edge_key(u, v)]:
                    e.risk = verdict
        findings.append(Finding(r, sum(lengths[edge_key(u, v)] for u, v in r), verdict, str(answer.get("condition")), float(answer.get("confidence", 0.0)), center))
    return findings


def describe(findings: list[Finding]) -> str:
    n = {k: sum(f.verdict == k for f in findings) for k in ("clear", "blocked", "unseen")}
    return f"Muse Spark looked at {len(findings)} unconfirmed stretches ({sum(f.length_m for f in findings):.0f} m): {n['clear']} drivable, {n['blocked']} blocked, {n['unseen']} could not be told"


__all__ = ["Finding", "describe", "inspect_plan", "look", "unconfirmed_runs", "verdict_of"]
