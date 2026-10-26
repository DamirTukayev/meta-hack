"""Debug rendering of masks and graphs on top of the source image."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from orbitroute.perception.graph import RoadGraph

SPEED_COLORS = {50.0: (255, 60, 60), 40.0: (255, 170, 0), 25.0: (60, 200, 255), 20.0: (255, 0, 255)}


def draw_graph(image: Image.Image, graph: RoadGraph, mask: np.ndarray | None = None, points: dict | None = None) -> Image.Image:
    base = image.convert("RGB")
    if mask is not None:
        arr = np.asarray(base).astype(float)
        arr[mask] = arr[mask] * 0.7 + np.array([255, 255, 255]) * 0.3
        base = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(base)
    for e in graph.edges:
        a, b = graph.nodes[e.u], graph.nodes[e.v]
        color = SPEED_COLORS.get(e.speed_kmh, (255, 255, 0))
        d.line([tuple(a), tuple(b)], fill=color, width=3)
    for x, y in graph.nodes:
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 255, 255))
    for label, (x, y) in (points or {}).items():
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(255, 255, 0), outline=(0, 0, 0))
        d.text((x + 11, y - 6), label, fill=(255, 255, 255))
    return base
