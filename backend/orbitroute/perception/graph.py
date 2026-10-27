"""Road mask -> routable graph.

mask -> clean -> skeleton -> junction/endpoint nodes + traced edges -> spur pruning
     -> densify (a node every few tens of pixels, so points can snap close to the road)
     -> bridge small gaps between components -> keep the largest connected component.

Positions are (x, y) in image pixels; lengths are converted to meters with `m_per_px`.
Road width (from the distance transform) gives a crude speed class.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.morphology import (
    disk,
    remove_small_holes,
    remove_small_objects,
    skeletonize,
)

N8 = [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]


@dataclass
class Edge:
    u: int
    v: int
    length_m: float
    width_m: float
    speed_kmh: float
    bridge: bool = False

    @property
    def time_s(self) -> float:
        return self.length_m / (self.speed_kmh / 3.6)


@dataclass
class RoadGraph:
    nodes: np.ndarray  # (N, 2) float, (x, y) pixels
    edges: list[Edge]
    m_per_px: float
    stats: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._tree = cKDTree(self.nodes) if len(self.nodes) else None

    def nearest_node(self, x: float, y: float) -> tuple[int, float]:
        """Closest graph node to a pixel and the distance to it in meters."""
        dist, idx = self._tree.query([x, y])
        return int(idx), float(dist) * self.m_per_px

    def to_networkx(self) -> nx.Graph:
        g = nx.Graph()
        for i, (x, y) in enumerate(self.nodes):
            g.add_node(i, x=float(x), y=float(y))
        for e in self.edges:
            # parallel edges: keep the faster one
            if g.has_edge(e.u, e.v) and g[e.u][e.v]["time_s"] <= e.time_s:
                continue
            g.add_edge(e.u, e.v, length_m=e.length_m, time_s=e.time_s, width_m=e.width_m, bridge=e.bridge)
        return g


def speed_for_width(width_m: float) -> float:
    """Heuristic urban speed (km/h) from the painted road width."""
    if width_m >= 14:
        return 50.0
    if width_m >= 8:
        return 40.0
    return 25.0


def clean_mask(mask: np.ndarray, close_radius: int = 3, min_component_px: int = 400) -> np.ndarray:
    m = ndi.binary_closing(mask, structure=disk(close_radius))
    m = remove_small_holes(m, max_size=149)
    return remove_small_objects(m, max_size=min_component_px - 1)


def _trace(coords: np.ndarray, start_xy: tuple[float, float]) -> list[tuple[int, int]]:
    """Order the pixels of a one-pixel-wide path, starting nearest to start_xy. Returns (x, y)."""
    pts = {(int(y), int(x)) for y, x in coords}
    cur = min(pts, key=lambda p: (p[1] - start_xy[0]) ** 2 + (p[0] - start_xy[1]) ** 2)
    path = [cur]
    pts.discard(cur)
    while pts:
        nxt = next(((cur[0] + dy, cur[1] + dx) for dy, dx in N8 if (cur[0] + dy, cur[1] + dx) in pts), None)
        if nxt is None:
            break
        path.append(nxt)
        pts.discard(nxt)
        cur = nxt
    return [(x, y) for y, x in path]


def _polyline_length(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _skeleton_graph(mask: np.ndarray, dt: np.ndarray) -> tuple[dict[int, tuple[float, float]], list[dict]]:
    """Nodes (junction clusters + endpoints) and traced edges of the skeleton."""
    skel = skeletonize(mask)
    nbr = ndi.convolve(skel.astype(np.uint8), np.ones((3, 3), np.uint8), mode="constant") - skel
    junction = skel & (nbr >= 3)
    endpoint = skel & (nbr == 1)

    j_lab, n_j = ndi.label(ndi.binary_dilation(junction, np.ones((3, 3))))
    node_label = np.where(skel, j_lab, 0)
    ep_ys, ep_xs = np.nonzero(endpoint & (node_label == 0))
    for k, (y, x) in enumerate(zip(ep_ys, ep_xs)):
        node_label[y, x] = n_j + 1 + k
    n_nodes = n_j + len(ep_ys)

    nodes: dict[int, tuple[float, float]] = {}
    ys, xs = np.nonzero(node_label)
    labels = node_label[ys, xs]
    for lab in np.unique(labels):
        sel = labels == lab
        nodes[int(lab)] = (float(xs[sel].mean()), float(ys[sel].mean()))
    assert len(nodes) <= n_nodes

    edge_pix = skel & (node_label == 0)
    e_lab, n_e = ndi.label(edge_pix, structure=np.ones((3, 3)))
    padded = np.pad(node_label, 1)
    edges: list[dict] = []
    for comp in range(1, n_e + 1):
        coords = np.argwhere(e_lab == comp)
        py, px = coords[:, 0] + 1, coords[:, 1] + 1
        touched: set[int] = set()
        for dy, dx in N8:
            v = padded[py + dy, px + dx]
            touched |= set(v[v > 0].tolist())
        touched.discard(0)
        if len(touched) < 2:
            continue  # isolated loop or dangling piece with no node at one end
        ends = sorted(touched)
        width_m_px = float(np.median(2 * dt[coords[:, 0], coords[:, 1]]))
        if len(ends) == 2:
            a, b = ends
            path = _trace(coords, nodes[a])
            poly = [nodes[a]] + [(float(x), float(y)) for x, y in path] + [nodes[b]]
            edges.append({"u": a, "v": b, "poly": poly, "width_px": width_m_px})
        else:
            # rare: a piece touching 3+ nodes; connect each to the first with a straight line
            a = ends[0]
            for b in ends[1:]:
                edges.append({"u": a, "v": b, "poly": [nodes[a], nodes[b]], "width_px": width_m_px})
    return nodes, edges


def _prune_spurs(nodes: dict, edges: list[dict], spur_px: float, rounds: int = 2) -> None:
    for _ in range(rounds):
        deg: dict[int, int] = {}
        for e in edges:
            deg[e["u"]] = deg.get(e["u"], 0) + 1
            deg[e["v"]] = deg.get(e["v"], 0) + 1
        drop = [
            e
            for e in edges
            if _polyline_length(e["poly"]) < spur_px
            and ((deg[e["u"]] == 1 and deg[e["v"]] >= 3) or (deg[e["v"]] == 1 and deg[e["u"]] >= 3))
        ]
        if not drop:
            return
        for e in drop:
            edges.remove(e)


def _resample(poly: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    """Points along a polyline every ~spacing px, always including both ends."""
    total = _polyline_length(poly)
    if total <= spacing:
        return [poly[0], poly[-1]]
    k = max(int(round(total / spacing)), 1)
    targets = [total * i / k for i in range(k + 1)]
    out, acc, seg = [poly[0]], 0.0, 0
    for t in targets[1:-1]:
        while seg < len(poly) - 1 and acc + math.dist(poly[seg], poly[seg + 1]) < t:
            acc += math.dist(poly[seg], poly[seg + 1])
            seg += 1
        a, b = poly[seg], poly[min(seg + 1, len(poly) - 1)]
        d = math.dist(a, b) or 1.0
        f = (t - acc) / d
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    out.append(poly[-1])
    return out


def build_road_graph(
    mask: np.ndarray,
    m_per_px: float,
    *,
    close_radius: int = 3,
    min_component_px: int = 400,
    spur_px: float = 25,
    densify_px: float = 40,
    bridge_px: float = 110,
) -> RoadGraph:
    clean = clean_mask(mask, close_radius, min_component_px)
    dt = ndi.distance_transform_edt(clean)
    nodes, raw_edges = _skeleton_graph(clean, dt)
    _prune_spurs(nodes, raw_edges, spur_px)

    # densify: one node every ~densify_px along every traced edge
    pts: list[tuple[float, float]] = []
    index: dict[tuple[int, int], int] = {}
    edges: list[Edge] = []

    def node_id(p: tuple[float, float]) -> int:
        key = (round(p[0] * 4), round(p[1] * 4))
        if key not in index:
            index[key] = len(pts)
            pts.append(p)
        return index[key]

    for e in raw_edges:
        width_m = e["width_px"] * m_per_px
        speed = speed_for_width(width_m)
        ring = _resample(e["poly"], densify_px)
        for a, b in zip(ring, ring[1:]):
            u, v = node_id(a), node_id(b)
            if u != v:
                edges.append(Edge(u, v, math.dist(a, b) * m_per_px, width_m, speed))

    # bridge small gaps: every dead end tries to join the nearest node of another component
    g = nx.Graph()
    g.add_nodes_from(range(len(pts)))
    g.add_edges_from((e.u, e.v) for e in edges)
    comp_of = {n: i for i, c in enumerate(nx.connected_components(g)) for n in c}
    arr = np.array(pts) if pts else np.zeros((0, 2))
    bridges = 0
    if len(arr):
        tree = cKDTree(arr)
        for n in [n for n in g.nodes if g.degree(n) == 1]:
            near = [i for i in tree.query_ball_point(arr[n], bridge_px) if comp_of[i] != comp_of[n]]
            if not near:
                continue
            m = min(near, key=lambda i: math.dist(arr[n], arr[i]))
            edges.append(Edge(n, m, math.dist(arr[n], arr[m]) * m_per_px, 6.0, 20.0, bridge=True))
            g.add_edge(n, m)
            bridges += 1
            old, new = comp_of[m], comp_of[n]
            for k, c in comp_of.items():  # merge, so the other side of the gap does not bridge back
                if c == old:
                    comp_of[k] = new

    # keep the largest connected component and renumber
    components = sorted(nx.connected_components(g), key=len, reverse=True)
    keep = sorted(components[0]) if components else []
    remap = {old: new for new, old in enumerate(keep)}
    kept_edges = [Edge(remap[e.u], remap[e.v], e.length_m, e.width_m, e.speed_kmh, e.bridge) for e in edges if e.u in remap and e.v in remap]
    total_m = sum(e.length_m for e in edges)
    kept_m = sum(e.length_m for e in kept_edges)
    stats = {
        "nodes": len(keep),
        "edges": len(kept_edges),
        "bridges": bridges,
        "components_before_keep": len(components),
        "road_km": round(kept_m / 1000, 2),
        "dropped_road_km": round((total_m - kept_m) / 1000, 2),
    }
    return RoadGraph(nodes=arr[keep] if keep else arr, edges=kept_edges, m_per_px=m_per_px, stats=stats)
