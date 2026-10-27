import numpy as np
import pytest
from shapely.geometry import box

from orbitroute.perception.buildings import building_cache_name, building_points
from orbitroute.routing.scenario import make_scenario
from orbitroute.understanding.scene import Scene, Zone

from helpers import grid_graph, grid_scene
from test_routing import problem


def roofs(*rects, shape=(400, 400)):
    m = np.zeros(shape, bool)
    for y0, y1, x0, x1 in rects:
        m[y0:y1, x0:x1] = True
    return m


def test_each_roof_gives_one_point_even_when_a_row_of_houses_merges_into_one_blob():
    single = roofs((100, 112, 100, 112))
    assert len(building_points(single, m_per_px=1.0)) == 1
    houses = [(200, 212, x, x + 12) for x in (50, 70, 90, 110)]  # 12 m roofs on a 20 m pitch ...
    necks = [(204, 208, x + 12, x + 20) for x in (50, 70, 90)]  # ... that SAM has joined by thin bridges
    pts = building_points(roofs(*houses, *necks), m_per_px=1.0)
    assert len(pts) == 4  # one per roof, not one per blob
    xs = sorted(round(x) for x, _ in pts)
    assert xs[0] < 70 and xs[-1] > 100


def test_sheds_and_huge_blobs_are_not_delivery_addresses():
    mask = roofs((10, 14, 10, 14), (100, 400, 100, 400))  # a 16 m2 shed and a 90 000 m2 slab
    assert building_points(mask, m_per_px=1.0) == []


def test_cache_name_depends_on_the_image():
    assert building_cache_name(b"a") != building_cache_name(b"b") and building_cache_name(b"a").endswith(".npz")


def test_orders_are_placed_at_buildings_and_served_from_the_nearest_allowed_road_node():
    graph, scene, prob = grid_graph(), grid_scene(), problem(n_orders=4, avoid_zone_kinds=[])
    targets = [(110.0, 130.0), (310.0, 130.0), (130.0, 310.0), (310.0, 310.0), (200.0, 90.0), (90.0, 200.0)]
    sc = make_scenario(graph, scene, prob, seed=1, targets=targets)
    assert len(sc.order_nodes) == 4 and len(sc.order_targets) == 4 and all(t in targets for t in sc.order_targets)
    for node, t in zip(sc.order_nodes, sc.order_targets):
        assert graph.nearest_node(*t)[0] == node


def test_buildings_in_an_avoided_zone_or_far_from_any_road_are_skipped_and_roads_fill_the_gap():
    graph = grid_graph()
    scene = Scene(400, 400, [Zone("industrial", box(0, 0, 190, 190))], warehouses=[(300.0, 100.0)])
    prob = problem(n_orders=3, avoid_zone_kinds=["industrial"])
    targets = [(100.0, 100.0), (150.0, 150.0), (300.0, 300.0), (1000.0, 1000.0)]  # two inside the zone, one off the map
    sc = make_scenario(graph, scene, prob, seed=0, targets=targets)
    assert len(sc.order_nodes) == 3 and len(set(sc.order_nodes)) == 3
    assert sc.order_targets is not None and sc.order_targets.count(None) == 2 and (300.0, 300.0) in sc.order_targets
    for n in sc.order_nodes:
        assert "industrial" not in scene.kinds_at(*graph.nodes[n])


def test_without_targets_nothing_changes():
    graph, scene, prob = grid_graph(), grid_scene(), problem()
    a = make_scenario(graph, scene, prob, seed=3)
    assert a.order_targets is None
    assert a.order_nodes == make_scenario(graph, scene, prob, seed=3, targets=None).order_nodes
