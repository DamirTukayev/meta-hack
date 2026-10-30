"""Who is exposed when a photo shows standing water, and where could they go.

Two rough readings of the same photo, both from what SAM 3.1 already finds (buildings and water), nothing else:
  - Exposure: how many buildings stand in the water, how many are surrounded by it (within 15 m), and from that a range of people
    (2.5 per building, the US household size; commercial and industrial zones are left out). It is an order of magnitude, not a count:
    the photo shows water, not how deep it is inside a house, and not damage.
  - Shelters: large buildings (1,200-40,000 m2, compact like a school, a store or a hall) that are dry and not surrounded, with the
    time to reach them from the depot by roads that are not under water, and what they could hold on the ground floor at
    3.5 m2 per person (the Sphere minimum for a shelter). A school, hospital or store of OpenStreetMap at the same spot gives the building a name and a kind.
Nothing here says that a building is safe or open; it says where to look first.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable

import networkx as nx
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage.measure import regionprops

from orbitroute.config import CACHE_DIR, resolve_cached, write_atomic
from orbitroute.llm.client import image_part
from orbitroute.perception.buildings import building_points
from orbitroute.perception.graph import RoadGraph
from orbitroute.perception.osm import to_pixels
from orbitroute.routing.zones import banned_edges, inside_lengths
from orbitroute.understanding.scene import Zone

PEOPLE_PER_BUILDING = 2.5  # US average household size
SURROUND_M = 15.0  # a building this close to the water is counted as surrounded by it
SHELTER_MIN_M2, SHELTER_MAX_M2, SHELTER_SOLIDITY = 1200.0, 40000.0, 0.8
M2_PER_PERSON = 3.5  # Sphere minimum covered area per person
SNAP_M = 80.0
LABEL_M = 60.0  # an OSM school, hospital or store within this distance of the building names it
NOT_HOMES = ("industrial", "commercial")


def wet_mask(zones: list[Zone], shape: tuple[int, int]) -> np.ndarray:
    im = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(im)
    for z in zones:
        if z.kind == "flooded":
            d.polygon([tuple(p) for p in z.polygon.exterior.coords], fill=255)
    return np.asarray(im) > 0


def _label(x: float, y: float, places: list[tuple[float, float, dict]], mpp: float) -> dict | None:
    best = min(places, key=lambda p: math.hypot(p[0] - x, p[1] - y), default=None)
    if best and math.hypot(best[0] - x, best[1] - y) * mpp <= LABEL_M:
        return best[2]
    return None


KINDS = ("school", "hospital_or_clinic", "store_or_mall", "church_or_hall", "hotel_or_office", "sports_or_event_hall", "warehouse_or_factory", "apartment_block", "houses", "other")
SHELTER_KINDS = ("school", "hospital_or_clinic", "store_or_mall", "church_or_hall", "hotel_or_office", "sports_or_event_hall")  # a crowd can be put up there; homes and factories are not offered
KIND_SCHEMA = {"type": "object", "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "confidence": {"type": "number"}}, "required": ["kind", "confidence"]}
KIND_PROMPT = (
    "This is an aerial photo. Look only at the building inside the yellow circle. What kind of building is it? "
    "school; hospital_or_clinic; store_or_mall (a shop, supermarket or mall with a car park); church_or_hall; hotel_or_office; "
    "sports_or_event_hall; warehouse_or_factory (large flat roof, loading docks, yards); apartment_block (several residential blocks or rows of flats); "
    "houses (ordinary homes); other. Give your confidence from 0 to 1."
)
LOOK_PROMPT_VERSION = 1  # part of the name of a remembered answer from version 2 on
MIN_LOOK_CONFIDENCE = 0.6
MAX_LOOKS = 8  # buildings looked at per photo: about half a cent each


def building_crop(image: Image.Image, cx: float, cy: float, area_px: float) -> bytes:
    """The photo around a building with a yellow circle on it, enlarged so that a roof is clearly a roof."""
    radius = max(math.sqrt(area_px / math.pi) * 1.3, 18.0)
    size = int(max(256, radius * 2 + 130))
    left = int(min(max(cx - size / 2, 0), max(image.width - size, 0)))
    top = int(min(max(cy - size / 2, 0), max(image.height - size, 0)))
    crop = image.crop((left, top, min(left + size, image.width), min(top + size, image.height))).convert("RGB")
    zoom = max(1.0, 512 / max(crop.size))
    crop = crop.resize((round(crop.width * zoom), round(crop.height * zoom)), Image.LANCZOS)
    x, y, r = (cx - left) * zoom, (cy - top) * zoom, radius * zoom
    ImageDraw.Draw(crop).ellipse((x - r, y - r, x + r, y + r), outline=(255, 230, 0), width=3)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def look_at_building(client, crop: bytes, *, run=None) -> dict:
    """What the model says the building is; remembered on disk by the crop, so the same photo costs nothing twice."""
    stem = hashlib.sha256(crop).hexdigest()[:16]
    path = resolve_cached(CACHE_DIR, f"shelterlook_{stem}.json" if LOOK_PROMPT_VERSION == 1 else f"shelterlook_v{LOOK_PROMPT_VERSION}_{stem}.json")
    if path.exists():
        return json.loads(path.read_text())
    messages = [{"role": "user", "content": [{"type": "text", "text": KIND_PROMPT}, image_part(crop)]}]
    for attempt in range(3):  # the open-weight model now and then answers with nothing
        try:
            answer, _ = client.chat_json(messages, "BuildingKind", KIND_SCHEMA, max_completion_tokens=3000, reasoning_effort="low", run=run, label="shelter_look")
            break
        except ValueError:
            if attempt == 2:
                raise
    write_atomic(CACHE_DIR / path.name, json.dumps(answer))
    return answer


def assess(building_mask: np.ndarray, zones: list[Zone], graph: RoadGraph, depot_node: int, meta: dict, places: list[dict] | None = None, *, image: Image.Image | None = None, look: Callable[[bytes], dict] | None = None) -> dict | None:
    """Exposure and shelter candidates for a photo with standing water; None when there is no water. `look` (crop -> {kind, confidence}) names the
    large buildings by what they are; without it (no model) every dry large building is offered as it is, unnamed."""
    mpp = meta["m_per_px"]
    wet = wet_mask(zones, building_mask.shape)
    if not wet.any():
        return None
    near_wet = ndi.distance_transform_edt(~wet) * mpp
    homes_excluded = [z for z in zones if z.kind in NOT_HOMES]

    # --- exposure: one point per roof, as for the delivery addresses
    pts = building_points(building_mask, mpp)
    h, w = wet.shape
    counts = {"in_water": 0, "surrounded": 0, "dry": 0}
    people_pool = {"in_water": 0, "surrounded": 0}
    for x, y in pts:
        xi, yi = min(max(int(x), 0), w - 1), min(max(int(y), 0), h - 1)
        state = "in_water" if wet[yi, xi] else "surrounded" if near_wet[yi, xi] <= SURROUND_M else "dry"
        counts[state] += 1
        if state != "dry" and not any(z.contains(x, y) for z in homes_excluded):
            people_pool[state] += 1
    low = people_pool["in_water"] * PEOPLE_PER_BUILDING
    high = (people_pool["in_water"] + people_pool["surrounded"]) * PEOPLE_PER_BUILDING

    # --- shelters: large, compact, dry buildings; the roads to them must not be under water
    px = to_pixels(meta)
    labelled = [(*px(p["lon"], p["lat"]), p) for p in (places or [])]
    clean = ndi.binary_opening(building_mask, structure=np.ones((3, 3), bool))
    labels, _ = ndi.label(clean)
    g = graph.to_networkx()
    g.remove_edges_from([e for e in banned_edges(inside_lengths(graph, [z for z in zones if z.kind == "flooded"])) if g.has_edge(*e)])
    reach, _ = nx.single_source_dijkstra(g, depot_node, weight="time_s")
    shelters, cut_off, in_or_near_water = [], 0, 0
    for r in regionprops(labels):
        area = r.area * mpp**2
        if not (SHELTER_MIN_M2 <= area <= SHELTER_MAX_M2) or r.solidity < SHELTER_SOLIDITY:
            continue
        if r.bbox[0] == 0 or r.bbox[1] == 0 or r.bbox[2] == h or r.bbox[3] == w:  # cut by the edge of the photo: its size is not known
            continue
        comp = labels[r.slice] == r.label
        if wet[r.slice][comp].mean() >= 0.2 or near_wet[r.slice][comp].min() <= SURROUND_M:
            in_or_near_water += 1
            continue
        cy, cx = r.centroid
        node, dist_m = graph.nearest_node(cx, cy)
        if dist_m > SNAP_M or node not in reach:
            cut_off += 1
            continue
        place = _label(cx, cy, labelled, mpp)
        shelters.append({
            "xy": [round(cx, 1), round(cy, 1)], "area_m2": round(area), "capacity": int(area / M2_PER_PERSON // 10 * 10),
            "minutes": round(reach[node] / 60, 1), "kind": place["kind"] if place else None, "name": (place or {}).get("name") or None, "area_px": float(r.area),
        })
    shelters.sort(key=lambda s: s["minutes"])
    rejected = {}
    if look is not None and image is not None:  # the nearest few are looked at: a block of flats is not a shelter, a school or a store is
        kept = []
        for sh in shelters[:MAX_LOOKS]:
            try:
                answer = look(building_crop(image, sh["xy"][0], sh["xy"][1], sh["area_px"]))
            except Exception:  # no model, no budget, no answer: the building stays, unnamed
                kept.append(sh)
                continue
            sure = float(answer.get("confidence", 0)) >= MIN_LOOK_CONFIDENCE
            kind = answer.get("kind") if sure else None
            if not sure and answer.get("kind") in KINDS and answer.get("kind") != "other":
                sh["guess"] = answer["kind"]  # shown as a guess, never used to take a building out or to name it
            if kind in KINDS and kind not in SHELTER_KINDS and kind != "other":
                rejected[kind] = rejected.get(kind, 0) + 1
                continue
            if kind in SHELTER_KINDS and not sh["kind"]:
                sh["kind"] = kind
            kept.append(sh)
        shelters = kept + shelters[MAX_LOOKS:]
    for sh in shelters:
        sh.pop("area_px", None)
    shelters.sort(key=lambda s: (s["kind"] is None, s["minutes"]))  # a named school or store first, then the nearest
    return {
        "buildings": len(pts), **counts, "people_low": int(low + 0.5), "people_high": int(high + 0.5),
        "assumption": f"{PEOPLE_PER_BUILDING} people per building in or beside the water, houses only (commercial and industrial zones left out)",
        "shelters": shelters[:5], "shelter_candidates": len(shelters), "not_shelters": rejected, "cut_off_by_water": cut_off, "wet_or_surrounded": in_or_near_water,
    }
