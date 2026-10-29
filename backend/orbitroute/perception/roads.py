"""Where the road graph comes from: the map when there is one, the photo when there is not.

With OpenStreetMap roads the graph is the map's, and the SAM road mask is kept as evidence of which stretches the photo confirms
(`perception/evidence.py`). A place the map hardly covers (a new district, a rural area) falls back to the graph read from the mask.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.perception.graph import RoadGraph, build_road_graph
from orbitroute.perception.osm import OsmUnavailable, osm_graph
from orbitroute.perception.segment import segment_roads

MIN_OSM_KM_PER_KM2 = 3.0  # below this the map has little to offer here (an aerial photo of open land gives 8-12)


@dataclass
class Roads:
    graph: RoadGraph
    mask: np.ndarray  # the SAM road mask: the graph itself in "sam" mode, evidence in "osm" mode
    source: str  # "osm" or "sam"
    notes: list[str] = field(default_factory=list)


def build_roads(client: MetaClient, sample, *, run: RunBudget | None = None, prefer: str = "osm") -> Roads:
    mpp = sample.meta["m_per_px"]
    notes: list[str] = []
    with ThreadPoolExecutor(max_workers=1) as pool:  # the map is read while SAM reads the photo, so a slow Overpass costs no extra time
        pending = pool.submit(osm_graph, sample.name, sample.meta) if prefer == "osm" else None
        mask = segment_roads(client, sample.image_bytes, run=run)
        graph = None
        if pending is not None:
            try:
                graph = pending.result()
            except OsmUnavailable:
                notes.append("OpenStreetMap did not answer, so the roads were read from the photo.")
    if prefer == "osm":
        if graph is not None:
            area_km2 = (mask.shape[1] * mpp / 1000) * (mask.shape[0] * mpp / 1000)
            if graph.stats["road_km"] / area_km2 >= MIN_OSM_KM_PER_KM2 and graph.stats["edges"]:
                return Roads(graph, mask, "osm", notes)
            notes.append("OpenStreetMap has few roads here, so the roads were read from the photo.")
    return Roads(build_road_graph(mask, mpp), mask, "sam", notes)
