"""JSON-friendly views of the pipeline objects, in image-pixel coordinates, for the web UI."""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from orbitroute.perception.graph import RoadGraph
from orbitroute.routing.matrix import CostMatrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan
from orbitroute.understanding.scene import Scene
from orbitroute.verifier.checks import Report


def _xy(p) -> list[float]:
    return [round(float(p[0]), 1), round(float(p[1]), 1)]


def mask_png(mask: np.ndarray) -> str:
    """Road mask as a translucent white RGBA PNG data URL."""
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = (255, 255, 255, 110)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def graph_json(graph: RoadGraph) -> dict:
    return {
        "nodes": [_xy(p) for p in graph.nodes],
        "edges": [[e.u, e.v, e.speed_kmh, int(e.bridge)] for e in graph.edges],
        "stats": graph.stats,
    }


def scene_json(scene: Scene) -> dict:
    return {
        "zones": [{"kind": z.kind, "polygon": [_xy(p) for p in z.polygon.exterior.coords]} for z in scene.zones],
        "warehouses": [_xy(w) for w in scene.warehouses],
    }


def scenario_json(sc: Scenario) -> dict:
    out = {"depot": _xy(sc.graph.nodes[sc.depot_node]), "orders": [_xy(sc.graph.nodes[n]) for n in sc.order_nodes]}
    if sc.order_targets:  # the building behind each order (null where the order is just a point on a road)
        out["order_targets"] = [_xy(t) if t else None for t in sc.order_targets]
    return out


def plan_json(sc: Scenario, plan: Plan, matrix: CostMatrix | None = None) -> dict:
    g = sc.graph
    routes = []
    for r in plan.routes:
        if not r.stops:
            continue
        poly: list[list[float]] = []
        legs: list[list[list[float]]] = []
        for leg in r.legs:
            pts = [_xy(g.nodes[n]) for n in leg]
            legs.append(pts)  # leg k leads to stop k+1; the last leg returns to the depot
            poly.extend(pts if not poly else pts[1:])
        routes.append(
            {
                "vehicle": r.vehicle,
                "polyline": poly,
                "legs": legs,
                "stops": [{"order": s.order, "xy": _xy(g.nodes[s.node]), "arrive_s": s.arrive_s} for s in r.stops],
                "start_s": r.start_s,
                "end_s": r.end_s,
                "distance_m": r.distance_m,
            }
        )
    return {"routes": routes, "served": plan.served, "unserved": plan.unserved}


def report_json(sc: Scenario, report: Report) -> dict:
    g = sc.graph
    violations = []
    for v in report.violations:
        item = {"kind": v.kind, "message": v.message, "route": v.route}
        if v.kind == "zones":
            item["segments"] = [[_xy(g.nodes[a]), _xy(g.nodes[b])] for a, b in v.data["edges"]]
        violations.append(item)
    return {
        "ok": report.ok,
        "checks": [{"kind": c.kind, "title": c.title, "passed": c.passed, "detail": c.detail} for c in report.checks],
        "violations": violations,
        "metrics": report.metrics,
        "excluded": {str(k): v for k, v in report.excluded.items()},
        "unconfirmed": [[_xy(g.nodes[a]), _xy(g.nodes[b])] for a, b in report.unconfirmed],  # driven links the photo does not show
    }
