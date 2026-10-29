"""The road graph from OpenStreetMap, for the square of a photo.

A map knows the roads as they were mapped; the photo shows what is there now. The graph the trucks drive on comes from OSM
(© OpenStreetMap contributors, ODbL), including the dirt tracks an aerial photo hides, and the photo is used afterwards to
say which stretches it confirms and which it does not (`perception/evidence.py`).

Only ways a truck can use are kept: footways, cycleways, steps, parking aisles and driveways are dropped, and so are ways
mapped as private or closed to motor vehicles. Positions are image pixels, like everywhere else.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed

import httpx
import networkx as nx
import numpy as np

from orbitroute.config import CACHE_DIR, resolve_cached
from orbitroute.naip import to_mercator
from orbitroute.perception.graph import Edge, RoadGraph, _resample

# Public servers differ a lot in speed from day to day (0.8 s to 30 s on the same query), so all are asked at once and the first good answer wins.
OVERPASS = ("https://overpass.openstreetmap.fr/api/interpreter", "https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
log = logging.getLogger("orbitroute")
USER_AGENT = "OrbitRoute/0.1 (hackathon project; roads for delivery planning)"

# km/h used for planning on a class of road, and a typical width in metres (the verifier only needs the speed).
CLASSES: dict[str, tuple[float, float]] = {
    "motorway": (70, 14), "motorway_link": (50, 7), "trunk": (60, 14), "trunk_link": (45, 7),
    "primary": (50, 12), "primary_link": (40, 7), "secondary": (45, 10), "secondary_link": (35, 7),
    "tertiary": (40, 9), "tertiary_link": (30, 6), "unclassified": (35, 7), "residential": (30, 7),
    "living_street": (15, 5), "service": (20, 4), "track": (15, 3.5),
}
NOT_FOR_DELIVERY = {"parking_aisle", "driveway", "drive-through"}  # ways of the service class that no delivery truck takes
CLOSED = {"no", "private"}


class OsmUnavailable(RuntimeError):
    """OpenStreetMap could not be read for this place."""


def drivable(tags: dict) -> bool:
    kind = tags.get("highway")
    if kind not in CLASSES:
        return False
    if tags.get("access") in CLOSED or tags.get("motor_vehicle") in CLOSED or tags.get("vehicle") in CLOSED:
        return False
    return not (kind == "service" and tags.get("service") in NOT_FOR_DELIVERY)


KEEP_TAGS = ("highway", "service", "access", "motor_vehicle", "vehicle", "maxspeed", "oneway", "name", "surface", "tracktype")


def trim(osm: dict) -> dict:
    """Only what the graph needs: drivable ways, a few tags, no author data. Keeps the cache small and the committed copy light."""
    elements = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") == "way" and "geometry" in el and drivable(tags):
            elements.append({"type": "way", "id": el["id"], "nodes": el.get("nodes", []), "geometry": el["geometry"], "tags": {k: tags[k] for k in KEEP_TAGS if k in tags}})
    return {"version": osm.get("version"), "osm3s": {"timestamp_osm_base": osm.get("osm3s", {}).get("timestamp_osm_base"), "copyright": "© OpenStreetMap contributors, ODbL"}, "elements": elements}


def cache_name(name: str) -> str:
    return f"osm_{name}.json"


def _race(query: str, path, trim_fn, what: str, *, client: httpx.Client | None, deadline_s: float) -> dict:
    """Ask every Overpass server at once and keep (and cache at `path`) the first good answer; at most `deadline_s` in all."""
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT})
    started = time.monotonic()

    def ask(url: str) -> dict:
        resp = http.post(url, data={"data": query}, timeout=min(deadline_s, 30.0))
        data = resp.json() if resp.status_code == 200 else None
        if isinstance(data, dict) and "elements" in data and not data.get("remark"):
            return {"url": url, "data": data}
        raise RuntimeError(f"{url} answered {resp.status_code}")

    last: Exception | None = None
    pool = ThreadPoolExecutor(max_workers=len(OVERPASS))
    try:
        futures = [pool.submit(ask, url) for url in OVERPASS]
        try:
            for done in as_completed(futures, timeout=deadline_s):
                try:
                    got = done.result()
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    last = exc
                    continue
                data = trim_fn(got["data"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
                log.info("OSM %s read from %s in %.1f s (%d elements)", what, got["url"], time.monotonic() - started, len(data["elements"]))
                return data
        except FuturesTimeout:
            last = TimeoutError(f"no server answered within {deadline_s:.0f} s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a slow server is not waited for
        if client is None:
            http.close()
    log.warning("OSM %s not read after %.1f s: %s", what, time.monotonic() - started, last)
    raise OsmUnavailable(f"OpenStreetMap did not answer ({last})")


def fetch_roads(name: str, bbox_lonlat: list[float], *, client: httpx.Client | None = None, deadline_s: float = 40.0) -> dict:
    """Every way tagged `highway` inside the box, with geometry. Read from the cache (or the committed copy) when there is one; otherwise
    the public Overpass servers are asked, within `deadline_s` in all, so that a busy server never holds a run for minutes:
    the caller falls back to the roads read from the photo."""
    path = resolve_cached(CACHE_DIR, cache_name(name))
    if path.exists():
        return json.loads(path.read_text())
    w, s, e, n = bbox_lonlat
    query = f'[out:json][timeout:25];way["highway"]({s},{w},{n},{e});out geom;'
    return _race(query, CACHE_DIR / cache_name(name), trim, f"roads for {name}", client=client, deadline_s=deadline_s)


PLACES = "school|college|university|hospital|clinic|community_centre|place_of_worship|townhall|fire_station|library"
SHOPS = "mall|supermarket|department_store"


def places_cache_name(name: str) -> str:
    return f"osm_places_{name}.json"


def trim_places(osm: dict) -> dict:
    """Places a crowd could go to: kind, name and the centre of each (a point is enough to match a building)."""
    out = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        kind = tags.get("amenity") or tags.get("shop")
        if not kind:
            continue
        c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        if c:
            out.append({"kind": kind, "name": tags.get("name", ""), "lat": c["lat"], "lon": c["lon"]})
    return {"osm3s": {"timestamp_osm_base": osm.get("osm3s", {}).get("timestamp_osm_base"), "copyright": "© OpenStreetMap contributors, ODbL"}, "elements": out}


def fetch_places(name: str, bbox_lonlat: list[float], *, client: httpx.Client | None = None, deadline_s: float = 20.0) -> list[dict]:
    """Schools, hospitals, shops of a kind that holds a crowd, inside the box; [] when the map does not answer (they only label buildings)."""
    path = resolve_cached(CACHE_DIR, places_cache_name(name))
    if path.exists():
        return json.loads(path.read_text())["elements"]
    w, s, e, n = bbox_lonlat
    box = f"({s},{w},{n},{e})"
    query = f'[out:json][timeout:20];(nwr["amenity"~"^({PLACES})$"]{box};nwr["shop"~"^({SHOPS})$"]{box};);out center;'
    try:
        return _race(query, CACHE_DIR / places_cache_name(name), trim_places, f"places for {name}", client=client, deadline_s=deadline_s)["elements"]
    except OsmUnavailable:
        return []


def to_pixels(meta: dict):
    """Function (lon, lat) -> image pixel for the photo described by `meta` (Web Mercator box, square pixels)."""
    width, height = meta["width_px"], meta["height_px"]
    x0, y0, x1, y1 = meta["bbox_mercator"]

    def px(lon: float, lat: float) -> tuple[float, float]:
        x, y = to_mercator(lon, lat)
        return (x - x0) / (x1 - x0) * width, (y1 - y) / (y1 - y0) * height

    return px


def _clip(a: tuple[float, float], b: tuple[float, float], width: float, height: float) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The part of segment a-b inside the image (Liang-Barsky), or None."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0]), (dx, width - a[0]), (-dy, a[1]), (dy, height - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _speed(tags: dict, base: float) -> float:
    """The posted limit when it is a plain number (km/h or mph) and not absurd for the class; otherwise the class default."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*(mph)?\s*", tags.get("maxspeed", ""))
    if not m:
        return base
    value = float(m.group(1)) * (1.609 if m.group(2) else 1.0)
    return min(max(value, 10.0), 90.0) if 0.5 * base <= value <= 2.0 * base else base


def build_osm_graph(osm: dict, meta: dict, *, densify_px: float = 40.0, min_piece_m: float = 300.0) -> RoadGraph:
    """Routable graph from the ways of `osm` inside the photo: one node per OSM junction or vertex, plus a node every ~densify_px
    along long straight stretches so that orders can snap close to the road. Pieces of road that the map does not connect to the
    rest inside the photo are kept when they are at least `min_piece_m` long (a quarter reached only from outside the photo is still
    a place to deliver to); shorter crumbs are dropped."""
    px = to_pixels(meta)
    width, height, mpp = float(meta["width_px"]), float(meta["height_px"]), meta["m_per_px"]
    index: dict[object, int] = {}
    pts: list[tuple[float, float]] = []

    def node(key: object, p: tuple[float, float]) -> int:
        if key not in index:
            index[key] = len(pts)
            pts.append(p)
        return index[key]

    edges: list[Edge] = []
    ways = 0
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") != "way" or not drivable(tags) or "geometry" not in el:
            continue
        speed, w_m = CLASSES[tags["highway"]]
        speed = _speed(tags, speed)
        ids = el.get("nodes") or [None] * len(el["geometry"])
        path = [px(p["lon"], p["lat"]) for p in el["geometry"]]
        used = False
        for (a, b), (ia, ib) in zip(zip(path, path[1:]), zip(ids, ids[1:])):
            clipped = _clip(a, b, width, height)
            if clipped is None:
                continue
            ca, cb = clipped
            if math.dist(ca, cb) < 1.0:
                continue
            # a vertex keeps its OSM id (so crossing ways join); a point cut at the image border gets a key of its own
            ka = ia if ia is not None and ca == a else ("cut", round(ca[0] * 4), round(ca[1] * 4))
            kb = ib if ib is not None and cb == b else ("cut", round(cb[0] * 4), round(cb[1] * 4))
            ring = _resample([ca, cb], densify_px)
            keys = [ka, *[("mid", len(pts) + i, round(p[0] * 4), round(p[1] * 4)) for i, p in enumerate(ring[1:-1])], kb]
            ids_ring = [node(k, p) for k, p in zip(keys, ring)]
            for (u, v), (p, q) in zip(zip(ids_ring, ids_ring[1:]), zip(ring, ring[1:])):
                if u != v:
                    edges.append(Edge(u, v, math.dist(p, q) * mpp, w_m, speed, highway=tags["highway"], oneway=tags.get("oneway") in ("yes", "1", "true")))
                    used = True
        ways += used

    g = nx.Graph()
    g.add_nodes_from(range(len(pts)))
    g.add_edges_from((e.u, e.v) for e in edges)
    length_of = {n: 0.0 for n in g.nodes}
    for e in edges:  # half of each edge to each end, so a piece's length is the sum over its nodes
        length_of[e.u] += e.length_m / 2
        length_of[e.v] += e.length_m / 2
    components = sorted(nx.connected_components(g), key=len, reverse=True)
    keep = sorted(n for c in components if sum(length_of[n] for n in c) >= min_piece_m for n in c)
    remap = {old: new for new, old in enumerate(keep)}
    arr = np.array(pts) if pts else np.zeros((0, 2))
    kept = [Edge(remap[e.u], remap[e.v], e.length_m, e.width_m, e.speed_kmh, False, e.highway, e.oneway) for e in edges if e.u in remap and e.v in remap]
    total_m = sum(e.length_m for e in edges)
    kept_m = sum(e.length_m for e in kept)
    stats = {
        "source": "osm", "ways": ways, "nodes": len(keep), "edges": len(kept), "bridges": 0, "components_before_keep": len(components), "pieces_kept": sum(1 for c in components if sum(length_of[n] for n in c) >= min_piece_m),
        "road_km": round(kept_m / 1000, 2), "dropped_road_km": round((total_m - kept_m) / 1000, 2),
        "track_km": round(sum(e.length_m for e in kept if e.highway == "track") / 1000, 2),
    }
    return RoadGraph(nodes=arr[keep] if keep else arr, edges=kept, m_per_px=mpp, stats=stats)


def osm_graph(name: str, meta: dict, *, client: httpx.Client | None = None) -> RoadGraph:
    """The OSM road graph of the photo `name`, fetching (and caching) the ways when needed."""
    return build_osm_graph(fetch_roads(name, meta["bbox_lonlat"], client=client), meta)
