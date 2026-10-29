"""The roads come from the map and the photo says what it confirms: the OSM graph, the evidence per edge, the planner's preference
for confirmed roads, the report of what a plan drives on without confirmation, and the model's look at those stretches."""

import dataclasses
import json
import math

import numpy as np
import pytest
from shapely.geometry import box

import orbitroute.agent.inspection as inspection
from orbitroute.agent.inspection import inspect_plan, unconfirmed_runs, verdict_of
from orbitroute.naip import EARTH_R, from_mercator
from orbitroute.perception import osm
from orbitroute.perception.evidence import annotate
from orbitroute.perception.graph import Edge, RoadGraph
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, Route, Stop
from orbitroute.understanding.constraints import Problem
from orbitroute.understanding.scene import Scene, Zone
from orbitroute.verifier.checks import verify

# A 1000 x 1000 px photo, 1 m per pixel, with its Web Mercator box near the equator so that pixels map to degrees simply.
META = {"width_px": 1000, "height_px": 1000, "m_per_px": 1.0, "bbox_mercator": [0.0, 0.0, 1000.0, 1000.0]}


def lonlat(x: float, y: float) -> dict:
    """Image pixel -> the OSM geometry point (the image y axis points down)."""
    lon, lat = from_mercator(x, 1000.0 - y)
    return {"lon": lon, "lat": lat}


def way(wid: int, pixels: list[tuple[float, float]], nodes: list[int], **tags) -> dict:
    return {"type": "way", "id": wid, "nodes": nodes, "geometry": [lonlat(*p) for p in pixels], "tags": tags}


STREETS = {
    "elements": [
        way(1, [(100, 500), (500, 500)], [1, 2], highway="residential"),
        way(2, [(500, 500), (900, 500)], [2, 3], highway="residential"),
        way(3, [(500, 100), (500, 500)], [4, 2], highway="track"),  # joins at node 2: a dirt track off the junction
        way(4, [(100, 700), (900, 700)], [5, 6], highway="footway"),  # not for trucks
        way(5, [(100, 800), (900, 800)], [7, 8], highway="residential", access="private"),
        way(6, [(120, 900), (160, 900)], [9, 10], highway="service", service="driveway"),
        way(7, [(900, 900), (1300, 900)], [11, 12], highway="residential"),  # leaves the photo to the right
    ]
}


def test_only_ways_a_truck_can_use_are_kept():
    g = osm.build_osm_graph(STREETS, META)
    classes = {e.highway for e in g.edges}
    assert classes == {"residential", "track"}  # no footway, no private way, no driveway
    assert g.stats["source"] == "osm" and g.stats["track_km"] > 0.3


def test_ways_that_share_an_osm_node_are_joined_and_a_long_stretch_gets_nodes_along_it():
    g = osm.build_osm_graph(STREETS, META, densify_px=40)
    gx = g.to_networkx()
    assert len(list(__import__("networkx").connected_components(gx))) == 1  # the three ways meet at node 2
    near = [d for _, d in (g.nearest_node(300, 500), g.nearest_node(500, 300))]
    assert max(near) < 25  # a point on a long way is never far from a node
    assert g.stats["road_km"] == pytest.approx(1.2, abs=0.05)


def test_a_way_leaving_the_photo_is_cut_at_its_border():
    g = osm.build_osm_graph({"elements": [STREETS["elements"][6], way(8, [(500, 900), (900, 900)], [13, 11], highway="residential")]}, META)
    assert g.nodes[:, 0].max() <= 1000.0 + 1e-6
    assert g.stats["road_km"] == pytest.approx(0.5, abs=0.02)  # 400 m inside the photo, the rest outside is dropped


def test_a_small_piece_not_connected_to_the_rest_is_dropped_and_a_big_one_kept():
    crumb = way(9, [(50, 50), (80, 50)], [20, 21], highway="residential")  # 30 m
    quarter = way(10, [(100, 200), (600, 200)], [30, 31], highway="residential")  # 500 m, joined to nothing
    g = osm.build_osm_graph({"elements": [*STREETS["elements"][:3], crumb, quarter]}, META)
    assert g.stats["pieces_kept"] == 2 and g.stats["road_km"] == pytest.approx(1.7, abs=0.05)


def test_a_posted_limit_is_used_only_when_it_is_believable_for_the_class():
    assert osm._speed({"maxspeed": "25 mph"}, 30) == pytest.approx(40.2, abs=0.1)
    assert osm._speed({"maxspeed": "130"}, 30) == 30  # not a residential street
    assert osm._speed({"maxspeed": "signals"}, 30) == 30


def test_the_trimmed_copy_keeps_only_what_the_graph_needs():
    raw = {"version": 0.6, "osm3s": {"timestamp_osm_base": "t"}, "elements": [dict(STREETS["elements"][0], tags={"highway": "residential", "tiger:county": "x"}), STREETS["elements"][3]]}
    trimmed = osm.trim(raw)
    assert len(trimmed["elements"]) == 1 and trimmed["elements"][0]["tags"] == {"highway": "residential"}
    assert "OpenStreetMap" in trimmed["osm3s"]["copyright"]


# --- evidence -------------------------------------------------------------------------------------------------------------------


def chain_graph(n=5, step=40.0):
    nodes = np.array([(100.0 + step * i, 100.0) for i in range(n)])
    return RoadGraph(nodes, [Edge(i, i + 1, step, 7.0, 30.0) for i in range(n - 1)], 1.0)


def test_edges_get_seen_unseen_or_water():
    g = chain_graph()
    mask = np.zeros((200, 400), bool)
    mask[95:105, 90:190] = True  # the road mask follows the first two edges
    pool = Zone("flooded", box(220, 80, 300, 120))  # standing water over the last one
    totals = annotate(g, mask, [pool])
    assert [e.risk for e in g.edges] == ["seen", "seen", "unseen", "water"]  # the mask covers only a quarter of the third edge
    assert totals["water"] == pytest.approx(40.0)


def test_without_a_road_mask_nothing_is_confirmed_and_a_grazed_edge_is_not_water():
    g = chain_graph(3)
    annotate(g, None, [Zone("flooded", box(100, 0, 105, 200))])  # 5 m inside an edge: a graze, the zone rule lets it pass
    assert [e.risk for e in g.edges] == ["unseen", "unseen"]


# --- routing prefers confirmed roads, the time stays real ---------------------------------------------------------------------------


def two_way_graph():
    """Two ways from node 0 to node 3: the short one (via 1) unconfirmed, the longer one (via 2) confirmed."""
    nodes = np.array([(0.0, 0.0), (50.0, -10.0), (50.0, 10.0), (100.0, 0.0)])
    short = [Edge(0, 1, 100.0, 7.0, 36.0, risk="unseen"), Edge(1, 3, 100.0, 7.0, 36.0, risk="unseen")]
    long = [Edge(0, 2, 120.0, 7.0, 36.0), Edge(2, 3, 120.0, 7.0, 36.0)]
    return RoadGraph(nodes, short + long, 1.0)


def test_the_router_takes_the_confirmed_way_when_it_costs_little_and_reports_the_real_time():
    g = two_way_graph()
    m = build_matrix(g, [0, 3])
    assert m.paths[(0, 1)] == [0, 1, 3]  # 200 m x 1.15 = 230 is still cheaper than 240 m (matrix rows: 0 = node 0, 1 = node 3)
    assert m.time_s[0, 1] == 20  # real time: 200 m at 10 m/s, not the cost
    for e in g.edges[:2]:
        e.risk = "blocked"
    m = build_matrix(g, [0, 3])
    assert m.paths[(0, 1)] == [0, 2, 3] and m.time_s[0, 1] == 24


# --- the report ------------------------------------------------------------------------------------------------------------------


def scenario_on(g: RoadGraph, order_nodes: list[int]) -> Scenario:
    problem = Problem(n_orders=len(order_nodes), n_vehicles=1, capacity=10, shift_start_s=0, deadline_s=10**5, service_s=60, avoid_zone_kinds=[], objective="min_time", assumptions=[])
    return Scenario(g, Scene(1000, 1000, [], []), problem, 0, order_nodes, 0)


def plan_over(path: list[int], stop_node: int) -> Plan:
    back = list(reversed(path))
    route = Route(0, [Stop(1, stop_node, 100, 160)], 0, 400, 400, 0, legs=[path, back])
    return Plan([route], True, 0.0, 0)


def test_a_valid_plan_on_unconfirmed_roads_says_how_much(monkeypatch):
    g = two_way_graph()
    g.edges[1].risk = "water"
    sc = scenario_on(g, [3])
    rep = verify(sc, plan_over([0, 1, 3], 3))
    assert rep.ok  # a note, not a failed check
    assert rep.metrics["risk_m"] == {"unseen": 200, "water": 200}  # 100 m unseen then 100 m of water, out and back
    assert rep.metrics["flagged_share"] == 1.0
    assert {r for _, _, r in rep.flagged} == {"unseen", "water"}


# --- the model's look --------------------------------------------------------------------------------------------------------------


def test_only_a_confident_positive_sign_settles_a_stretch():
    assert verdict_of({"condition": "clear_road", "confidence": 0.9}) == "clear"
    assert verdict_of({"condition": "standing_water", "confidence": 0.9}) == "blocked"
    assert verdict_of({"condition": "debris", "confidence": 0.7}) == "blocked"
    assert verdict_of({"condition": "standing_water", "confidence": 0.5}) == "unseen"  # not sure enough
    assert verdict_of({"condition": "no_road_visible", "confidence": 0.99}) == "unseen"  # contradicts the map: a doubt, not a verdict
    assert verdict_of({"condition": "hidden_by_trees_or_shadow", "confidence": 0.99}) == "unseen"


class Looker:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def chat_json(self, messages, name, schema, **kw):
        self.calls += 1
        return self.answers.pop(0), None


@pytest.fixture
def photo(monkeypatch, tmp_path):
    from PIL import Image
    import io

    monkeypatch.setattr(inspection, "CACHE_DIR", tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (1000, 1000), (90, 120, 90)).save(buf, "JPEG")
    return buf.getvalue()


def test_the_longest_unconfirmed_runs_of_a_plan_are_found_in_driving_order():
    g = two_way_graph()
    sc = scenario_on(g, [3])
    runs = unconfirmed_runs(sc, plan_over([0, 1, 3], 3))
    assert runs == [[(0, 1), (1, 3)], [(3, 1), (1, 0)]]  # one run per leg: the way out and the way back
    assert unconfirmed_runs(sc, plan_over([0, 2, 3], 3)) == []


def test_a_stretch_the_model_finds_flooded_is_marked_blocked_and_a_clear_one_stops_being_a_doubt(photo):
    g = two_way_graph()
    for e in g.edges[2:]:
        e.risk = "unseen"  # both ways are unconfirmed: out via node 1, back via node 2
    plan = plan_over([0, 1, 3], 3)
    plan.routes[0].legs[1] = [3, 2, 0]
    sc = scenario_on(g, [3])
    findings = inspect_plan(Looker([{"condition": "standing_water", "confidence": 0.9}, {"condition": "clear_road", "confidence": 0.9}]), photo, sc, plan, max_looks=2)
    assert sorted(f.verdict for f in findings) == ["blocked", "clear"]
    assert {e.risk for e in g.edges[:2]} <= {"blocked", "clear"} and {e.risk for e in g.edges[2:]} <= {"blocked", "clear"}


def test_the_same_stretch_driven_twice_is_looked_at_once(photo):
    g = two_way_graph()
    looker = Looker([{"condition": "standing_water", "confidence": 0.9}])
    out = inspect_plan(looker, photo, scenario_on(g, [3]), plan_over([0, 1, 3], 3), max_looks=5)
    assert looker.calls == 1 and out[0].verdict == "blocked" and {e.risk for e in g.edges[:2]} == {"blocked"}
    assert {e.risk for e in g.edges[2:]} == {"seen"}


def test_a_repeated_question_is_answered_from_disk(photo):
    looker = Looker([{"condition": "clear_road", "confidence": 0.9}])
    sc = scenario_on(two_way_graph(), [3])
    inspect_plan(looker, photo, sc, plan_over([0, 1, 3], 3))
    again = Looker([])  # would fail if asked
    inspect_plan(again, photo, scenario_on(two_way_graph(), [3]), plan_over([0, 1, 3], 3))
    assert again.calls == 0


# --- reading the map must never hold a run ---------------------------------------------------------------------------------------


def test_a_busy_overpass_is_given_up_on_within_the_deadline(monkeypatch, tmp_path):
    import time

    import httpx

    monkeypatch.setattr(osm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(osm, "resolve_cached", lambda d, n: d / n)
    calls = []

    def busy(request):
        calls.append(str(request.url))
        return httpx.Response(502, text="This Overpass API server is currently at capacity")

    t0 = time.monotonic()
    with pytest.raises(osm.OsmUnavailable):
        osm.fetch_roads("somewhere", [0, 0, 1, 1], client=httpx.Client(transport=httpx.MockTransport(busy)), deadline_s=20)
    assert time.monotonic() - t0 < 2 and len(calls) == len(osm.OVERPASS)  # each server asked once, all at the same time, no rounds of retries


def test_the_first_good_answer_wins_over_slow_and_broken_servers(monkeypatch, tmp_path):
    import threading
    import time

    import httpx

    monkeypatch.setattr(osm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(osm, "resolve_cached", lambda d, n: d / n)
    release = threading.Event()

    def mixed(request):
        host = request.url.host
        if "openstreetmap.fr" in host:
            return httpx.Response(200, json={"elements": [STREETS["elements"][0]]})
        if "mail.ru" in host:
            return httpx.Response(502, text="down")
        release.wait(5)  # the main server is slow
        return httpx.Response(200, json={"elements": []})

    t0 = time.monotonic()
    got = osm.fetch_roads("somewhere", [0, 0, 1, 1], client=httpx.Client(transport=httpx.MockTransport(mixed)), deadline_s=20)
    release.set()
    assert len(got["elements"]) == 1 and time.monotonic() - t0 < 2


def test_a_good_answer_is_trimmed_and_remembered(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr(osm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(osm, "resolve_cached", lambda d, n: d / n)
    answer = {"elements": [dict(STREETS["elements"][0], tags={"highway": "residential", "tiger:county": "x"})]}
    asked = []

    def ok(request):
        asked.append(1)
        return httpx.Response(200, json=answer)

    http = httpx.Client(transport=httpx.MockTransport(ok))
    first = osm.fetch_roads("somewhere", [0, 0, 1, 1], client=http)
    after_first = len(asked)
    again = osm.fetch_roads("somewhere", [0, 0, 1, 1], client=http)
    assert first == again and len(asked) == after_first and first["elements"][0]["tags"] == {"highway": "residential"}  # the second read is from disk


def test_roads_fall_back_to_the_photo_when_the_map_does_not_answer(monkeypatch):
    import orbitroute.perception.roads as roads

    mask = np.zeros((300, 300), bool)
    mask[140:160, 20:280] = True
    mask[20:280, 140:160] = True

    def no_map(name, meta):
        raise osm.OsmUnavailable("down")

    monkeypatch.setattr(roads, "osm_graph", no_map)
    monkeypatch.setattr(roads, "segment_roads", lambda *a, **k: mask)

    class Sample:
        name, image_bytes = "x", b""
        meta = {"m_per_px": 1.0}

    got = roads.build_roads(None, Sample())
    assert got.source == "sam" and any("did not answer" in n for n in got.notes) and got.graph.stats["road_km"] > 0.3
