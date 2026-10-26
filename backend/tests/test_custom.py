import pytest
from shapely.geometry import box

from orbitroute.agent.loop import run_agent
from orbitroute.custom import CustomInputs, apply_custom
from orbitroute.understanding.constraints import ParsedRequest, resolve
from orbitroute.understanding.scene import Scene

from helpers import grid_graph


def base_problem(**kw):
    base = dict(n_orders=30, n_vehicles=2, deadline="12:00", shift_start="08:00", service_minutes=3, avoid_zone_kinds=[])
    return resolve(ParsedRequest(**{**base, **kw}))


def empty_scene():
    return Scene(400, 400, [], warehouses=[(300, 300)])


def test_orders_and_depot_are_snapped_and_override_the_count_in_the_request():
    graph = grid_graph()
    custom = CustomInputs(depot=(102, 198), orders=[(298, 203), (301, 296), (104, 99)])
    sc, problem, scene, notes = apply_custom(graph, empty_scene(), base_problem(), custom)
    assert problem.n_orders == 3 and len(sc.order_nodes) == 3
    assert any("3 orders you placed instead of the 30" in n for n in notes)
    assert abs(graph.nodes[sc.depot_node][0] - 100) < 8 and abs(graph.nodes[sc.depot_node][1] - 200) < 8
    # the capacity was only assumed, so it follows the new count: ceil(3 / 2 * 1.5) = 3
    assert problem.capacity == 3 and any("carries 3 units" in a for a in problem.assumptions)


def test_a_stated_capacity_is_kept_when_the_count_changes():
    graph = grid_graph()
    problem = base_problem(vehicle_capacity=7)
    _, p2, _, _ = apply_custom(graph, empty_scene(), problem, CustomInputs(orders=[(300, 200), (300, 300)]))
    assert p2.capacity == 7


def test_a_point_far_from_any_road_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError, match="nearest road"):
        apply_custom(grid_graph(), empty_scene(), base_problem(), CustomInputs(orders=[(0, 0)]))


def test_points_outside_the_image_are_rejected():
    with pytest.raises(ValueError, match="outside the image"):
        apply_custom(grid_graph(), empty_scene(), base_problem(), CustomInputs(orders=[(500, 10)]))


def test_drawn_zone_becomes_an_avoided_zone_and_is_validated():
    graph = grid_graph()
    poly = [(130, 130), (270, 130), (270, 270), (130, 270)]
    sc, problem, scene, notes = apply_custom(graph, empty_scene(), base_problem(n_orders=6), CustomInputs(zone=poly), seed=1)
    assert "custom" in problem.avoid_zone_kinds and any(z.kind == "custom" for z in scene.zones)
    # with no orders drawn, random ones are placed legally: none inside the drawn zone
    assert len(sc.order_nodes) == 6
    assert all("custom" not in scene.kinds_at(*graph.nodes[n]) for n in sc.order_nodes)
    with pytest.raises(ValueError, match="at least 3"):
        apply_custom(graph, empty_scene(), base_problem(), CustomInputs(zone=[(1, 1), (2, 2)]))
    with pytest.raises(ValueError, match="degenerate"):
        apply_custom(graph, empty_scene(), base_problem(), CustomInputs(zone=[(100, 100), (200, 200), (300, 300)]))


def test_depot_inside_the_drawn_zone_is_rejected():
    poly = [(130, 130), (270, 130), (270, 270), (130, 270)]
    with pytest.raises(ValueError, match="depot is inside"):
        apply_custom(grid_graph(), empty_scene(), base_problem(), CustomInputs(depot=(200, 200), zone=poly))


def test_agent_routes_around_a_zone_the_user_drew():
    graph = grid_graph()
    poly = [(130, 130), (270, 130), (270, 270), (130, 270)]
    custom = CustomInputs(depot=(100, 200), orders=[(300, 200), (300, 300)], zone=poly)
    sc, *_ = apply_custom(graph, empty_scene(), base_problem(n_vehicles=1, vehicle_capacity=4), custom)
    result = run_agent(sc, time_limit_s=1.0)
    assert result.status == "verified"
    assert len(result.iterations) >= 2 and not result.iterations[0].report.ok  # the direct way crosses the drawn zone
    assert result.report.ok
