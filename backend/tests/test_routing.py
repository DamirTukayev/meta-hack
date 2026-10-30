import networkx as nx

from orbitroute.routing.matrix import build_matrix, edge_key, edges_in_zones
from orbitroute.routing.scenario import make_scenario
from orbitroute.routing.solver import solve_vrp
from orbitroute.understanding.constraints import ParsedRequest, resolve

from helpers import grid_graph, grid_scene


def problem(**kw):
    base = dict(n_orders=12, n_vehicles=2, deadline="12:00", shift_start="08:00", service_minutes=3, avoid_zone_kinds=["industrial"])
    return resolve(ParsedRequest(**{**base, **kw}))


def test_grid_graph_is_connected():
    assert nx.is_connected(grid_graph().to_networkx())


def test_scenario_is_deterministic_and_respects_avoided_zones():
    graph, scene, prob = grid_graph(), grid_scene(), problem()
    a = make_scenario(graph, scene, prob, seed=3)
    b = make_scenario(graph, scene, prob, seed=3)
    c = make_scenario(graph, scene, prob, seed=4)
    assert a.order_nodes == b.order_nodes and a.order_nodes != c.order_nodes
    assert len(set(a.order_nodes)) == prob.n_orders
    for node in [a.depot_node, *a.order_nodes]:
        assert "industrial" not in scene.kinds_at(*graph.nodes[node])


def test_depot_is_not_in_an_avoided_zone():
    graph, scene = grid_graph(), grid_scene()
    s = make_scenario(graph, scene, problem(), seed=0)
    x, y = graph.nodes[s.depot_node]
    assert x > 200 and y > 200  # nearest road node to the lone warehouse at (300, 300)


def test_matrix_paths_match_times_and_ban_makes_detour():
    graph, scene = grid_graph(), grid_scene()
    s = make_scenario(graph, scene, problem(), seed=0)
    m = build_matrix(graph, s.location_nodes)
    assert (m.time_s.diagonal() == 0).all()
    assert (m.time_s[0, 1:] > 0).all()
    banned = edges_in_zones(graph, scene.zones_of(["industrial"]))
    assert banned and all(isinstance(e, tuple) for e in banned)
    m2 = build_matrix(graph, s.location_nodes, banned)
    assert (m2.time_s >= m.time_s).all()  # removing edges never makes anything faster
    for path in m2.paths.values():
        assert not any(edge_key(a, b) in banned for a, b in zip(path, path[1:]))


def test_solver_serves_every_order_once_within_capacity_and_windows():
    graph, scene, prob = grid_graph(), grid_scene(), problem()
    s = make_scenario(graph, scene, prob, seed=1)
    m = build_matrix(graph, s.location_nodes)
    plan = solve_vrp(s, m, time_limit_s=1.0)
    assert plan.feasible and plan.unserved == []
    served = [st.order for r in plan.routes for st in r.stops]
    assert sorted(served) == list(range(1, prob.n_orders + 1))
    for r in plan.routes:
        assert len(r.stops) <= prob.capacity
        assert r.time_warp_s == 0
        assert r.start_s >= prob.shift_start_s and r.end_s <= prob.deadline_s
        for st in r.stops:
            assert prob.shift_start_s <= st.arrive_s <= prob.deadline_s - prob.service_s
            assert st.leave_s - st.arrive_s >= prob.service_s


def test_solver_reports_infeasible_when_deadline_is_impossible():
    graph, scene = grid_graph(), grid_scene()
    prob = problem(n_orders=20, n_vehicles=1, deadline="08:30", vehicle_capacity=20)  # 20 stops * 3 min > 30 min
    s = make_scenario(graph, scene, prob, seed=1)
    plan = solve_vrp(s, build_matrix(graph, s.location_nodes), time_limit_s=1.0)
    assert not plan.feasible


def test_orders_are_placed_only_where_a_truck_can_legally_go():
    from shapely.geometry import box

    from orbitroute.understanding.scene import Scene, Zone

    graph = grid_graph()
    # the zone is a wall across the middle: the top half is cut off from the depot at the bottom
    scene = Scene(400, 400, [Zone("industrial", box(0, 180, 400, 220))], warehouses=[(300, 300)])
    prob = problem(n_orders=8)
    legal = make_scenario(graph, scene, prob, seed=2)
    assert all(graph.nodes[n][1] > 220 for n in legal.order_nodes)
    stress = make_scenario(graph, scene, prob, seed=2, ensure_reachable=False)
    assert any(graph.nodes[n][1] < 180 for n in stress.order_nodes) or stress.order_nodes != legal.order_nodes


def test_prefer_connected_depot_avoids_a_pocket_cut_off_by_the_zone(monkeypatch):
    from orbitroute.routing import scenario as sc

    graph, scene, prob = grid_graph(), grid_scene(), problem()
    near_centre, far = (210.0, 210.0), (300.0, 300.0)
    scene.warehouses = [near_centre, far]
    pocket_node = graph.nearest_node(*near_centre)[0]
    monkeypatch.setattr(sc, "_legal_component_sizes", lambda g, s, p: {i: (1 if i == pocket_node else 40) for i in range(len(g.nodes))})
    assert sc.pick_depot(graph, scene, prob) == pocket_node  # default: nearest the centre
    assert sc.pick_depot(graph, scene, prob, prefer_connected=True) == graph.nearest_node(*far)[0]


def test_without_a_warehouse_the_depot_goes_to_the_largest_dry_piece_of_road(monkeypatch):
    from orbitroute.routing import scenario as sc

    graph, scene, prob = grid_graph(), grid_scene(), problem()
    scene.warehouses = []
    big = [i for i, (x, y) in enumerate(graph.nodes) if x > 250 and y > 250]  # the piece the "water" leaves connected
    sizes = {i: (len(big) if i in big else 3) for i in range(len(graph.nodes))}
    monkeypatch.setattr(sc, "_legal_component_sizes", lambda g, s, p: sizes)
    depot = sc.pick_depot(graph, scene, prob, prefer_connected=True)
    assert depot in big


def test_asking_for_more_orders_than_the_roads_can_hold_gives_a_message_a_user_can_act_on():
    import pytest

    graph, scene = grid_graph(), grid_scene()
    with pytest.raises(ValueError, match="room for only about .* orders") as err:
        make_scenario(graph, scene, problem(n_orders=250), seed=0)
    assert "Ask for fewer orders" in str(err.value)
