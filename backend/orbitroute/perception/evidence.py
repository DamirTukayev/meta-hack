"""What the photo says about each stretch of the OSM road graph.

The map says a road is there; the photo says whether it can still be seen and whether water stands on it. Every edge gets one of:
`water`  it runs through standing water (zones of kind "flooded"), by the same rule that forbids it when a request says "avoid flooded areas";
`seen`   the road mask of SAM 3.1 follows it (within a few metres) along at least half of its length;
`unseen` neither: trees, shadow, a dirt track the model misses, or a real problem. SAM finds about half of the streets in a city photo,
         so this is a weak signal; it only makes routing prefer seen roads a little and puts the stretch in the plan's report.
Only the water forbids anything, and only through the request that says "avoid flooded areas".
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

from orbitroute.perception.graph import RoadGraph
from orbitroute.routing.zones import banned_edges, edge_key, inside_lengths
from orbitroute.understanding.scene import Zone

MASK_TOLERANCE_M = 8.0  # the road mask may sit this far from the mapped centre line (georeferencing, road width)
SEEN_SHARE = 0.5


def annotate(graph: RoadGraph, mask: np.ndarray | None, zones: list[Zone]) -> dict:
    """Set `risk` on every edge of `graph` and return the length in metres per class."""
    mpp = graph.m_per_px
    dist = ndi.distance_transform_edt(~mask) if mask is not None and mask.any() else None
    tol_px = MASK_TOLERANCE_M / mpp
    wet = banned_edges(inside_lengths(graph, [z for z in zones if z.kind == "flooded"]))
    height, width = (mask.shape if mask is not None else (0, 0))
    totals: dict[str, float] = {}
    for e in graph.edges:
        a, b = graph.nodes[e.u], graph.nodes[e.v]
        risk = "water" if edge_key(e.u, e.v) in wet else "seen"
        if risk == "seen":
            if dist is None:
                risk = "unseen"
            else:
                n = max(int(np.hypot(*(b - a)) / 3), 2)
                p = np.linspace(a, b, n)
                xs, ys = np.clip(p[:, 0].round().astype(int), 0, width - 1), np.clip(p[:, 1].round().astype(int), 0, height - 1)
                risk = "seen" if (dist[ys, xs] <= tol_px).mean() >= SEEN_SHARE else "unseen"
        e.risk = risk
        totals[risk] = totals.get(risk, 0.0) + e.length_m
    return {k: round(v, 1) for k, v in totals.items()}
