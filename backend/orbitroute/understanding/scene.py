"""Scene grounding with Muse Spark: land-use zones (as polygons) and warehouse points on the image.

The model answers on a normalized 0-1000 grid; everything is converted to image pixels here.
Results are cached on disk by image hash, since the answer for one image never changes.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field

from PIL import Image
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from orbitroute.config import ROOT, resolve_cached
from orbitroute.llm.budget import RunBudget
from orbitroute import prompts
from orbitroute.llm.client import MetaClient, image_part

CACHE_DIR = ROOT / "data" / "cache"
ZONE_KINDS = ["industrial", "commercial", "residential", "park_forest", "other"]

SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "zones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ZONE_KINDS},
                    "polygon": {
                        "type": "array",
                        "description": "3-8 vertices on a 0-1000 grid, (0,0) = top-left",
                        "items": {
                            "type": "object",
                            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                            "required": ["x", "y"],
                        },
                    },
                },
                "required": ["kind", "polygon"],
            },
        },
        "warehouses": {
            "type": "array",
            "description": "centre points of large flat-roof warehouse or distribution buildings",
            "items": {
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
        },
    },
    "required": ["zones", "warehouses"],
}

@dataclass
class Zone:
    kind: str
    polygon: Polygon  # image pixels
    _prepared: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._prepared = prep(self.polygon)

    def contains(self, x: float, y: float) -> bool:
        return self._prepared.contains(Point(x, y))


@dataclass
class Scene:
    width: int
    height: int
    zones: list[Zone]
    warehouses: list[tuple[float, float]]

    def kinds_at(self, x: float, y: float) -> set[str]:
        return {z.kind for z in self.zones if z.contains(x, y)}

    def zones_of(self, kinds: set[str] | list[str]) -> list[Zone]:
        return [z for z in self.zones if z.kind in set(kinds)]


def scene_from_raw(raw: dict, width: int, height: int) -> Scene:
    zones: list[Zone] = []
    for z in raw.get("zones", []):
        pts = [(p["x"] * width / 1000, p["y"] * height / 1000) for p in z.get("polygon", [])]
        if len(pts) < 3 or z.get("kind") not in ZONE_KINDS:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        zones.append(Zone(z["kind"], poly))
    warehouses = [(w["x"] * width / 1000, w["y"] * height / 1000) for w in raw.get("warehouses", [])]
    return Scene(width, height, zones, warehouses)


def analyze_scene(
    client: MetaClient,
    image_bytes: bytes,
    *,
    run: RunBudget | None = None,
    use_cache: bool = True,
    max_completion_tokens: int = 6000,
    prompt_version: str | None = None,
) -> Scene:
    width, height = Image.open(io.BytesIO(image_bytes)).size
    version, prompt = prompts.load("scene", prompt_version)
    # v1 keeps its original cache file name, so answers cached before prompts were versioned stay valid
    suffix = "" if version == "v1" else f"_{version}"
    cache = resolve_cached(CACHE_DIR, f"scene_{hashlib.sha256(image_bytes).hexdigest()[:16]}{suffix}.json")
    if use_cache and cache.exists():
        return scene_from_raw(json.loads(cache.read_text()), width, height)

    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, image_part(image_bytes)]}]
    raw, _ = client.chat_json(
        messages,
        "Scene",
        SCENE_SCHEMA,
        max_completion_tokens=max_completion_tokens,
        reasoning_effort="low",
        run=run,
        label="scene",
    )
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw))
    return scene_from_raw(raw, width, height)
