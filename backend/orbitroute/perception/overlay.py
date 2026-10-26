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


ROUTE_COLORS = [(230, 25, 75), (0, 130, 200), (60, 180, 75), (245, 130, 48), (145, 30, 180), (0, 128, 128)]
ZONE_COLORS = {"industrial": (255, 0, 0), "commercial": (255, 170, 0), "residential": (0, 120, 255), "park_forest": (0, 200, 0), "other": (150, 150, 150)}


def draw_plan(image, graph, scenario, plan, matrix, avoid_zones=()):
    """Routes (one color per truck), depot, numbered stops, and the avoided zones."""
    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for z in avoid_zones:
        d.polygon(list(z.polygon.exterior.coords), fill=ZONE_COLORS.get(z.kind, (255, 0, 0)) + (70,), outline=ZONE_COLORS.get(z.kind, (255, 0, 0)) + (255,))
    for r in plan.routes:
        color = ROUTE_COLORS[r.vehicle % len(ROUTE_COLORS)]
        order_rows = [0] + [s.order for s in r.stops] + [0]
        for a, b in zip(order_rows, order_rows[1:]):
            path = matrix.paths.get((a, b), [])
            d.line([tuple(graph.nodes[n]) for n in path], fill=color + (255,), width=5)
    for r in plan.routes:
        color = ROUTE_COLORS[r.vehicle % len(ROUTE_COLORS)]
        for k, s in enumerate(r.stops, 1):
            x, y = graph.nodes[s.node]
            d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color + (255,), outline=(255, 255, 255, 255))
            d.text((x - 4, y - 5), str(k), fill=(255, 255, 255, 255))
    x, y = graph.nodes[scenario.depot_node]
    d.rectangle((x - 13, y - 13, x + 13, y + 13), fill=(0, 0, 0, 255), outline=(255, 255, 0, 255), width=3)
    return Image.alpha_composite(base, layer).convert("RGB")
