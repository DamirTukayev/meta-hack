"""Quantum polishing: the path QUBO, decoding, rebuilding routes, and the stage inside the agent loop."""

import itertools
from dataclasses import replace

import numpy as np
import pytest

from orbitroute.agent import loop
from orbitroute.agent.events import Event
from orbitroute.agent.loop import run_agent
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.quantum import HARDWARE_NOTE, decode_path, path_arc_max, path_cost, path_qubo, polish_plan
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, rebuild_route, solve_vrp
from orbitroute.understanding.constraints import ParsedRequest, resolve
from orbitroute.understanding.scene import Scene

from helpers import grid_graph

GRID_POINTS = [(100, 100), (300, 100), (300, 300), (100, 300), (200, 100), (200, 300), (100, 200), (300, 200), (200, 200)]


def grid_scenario(n_orders=8, n_vehicles=1, deadline="18:00", objective="min_time", capacity=12) -> Scenario:
    graph = grid_graph()
    scene = Scene(400, 400, [], warehouses=[])
    p = resolve(ParsedRequest(n_orders=n_orders, n_vehicles=n_vehicles, deadline=deadline, shift_start="08:00", service_minutes=3, vehicle_capacity=capacity))
    p = p.model_copy(update={"objective": objective})
    depot = graph.nearest_node(30, 30)[0]
    nodes = [graph.nearest_node(x, y)[0] for x, y in GRID_POINTS[:n_orders]]
    return Scenario(graph, scene, p, depot_node=depot, order_nodes=nodes, seed=0)


def random_cost(n, seed):
    rng = np.random.default_rng(seed)
    C = rng.integers(10, 1000, size=(n, n))
    np.fill_diagonal(C, 0)
    return C


@pytest.mark.parametrize("m", [2, 3, 4])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_path_qubo_ground_state_is_the_brute_force_optimum(m, seed):
    C = random_cost(m + 2, seed)
    nodes, start, end = list(range(1, m + 1)), 0, m + 1
    q = path_qubo(nodes, start, end, C, 2.0 * path_arc_max(nodes, start, end, C))
    E = q.all_energies()
    z = int(np.argmin(E))
    order, ok = decode_path((z >> np.arange(q.n)) & 1, nodes)
    best = min(path_cost(p, start, end, C) for p in itertools.permutations(nodes))
    assert ok and path_cost(order, start, end, C) == best
    assert E[z] == pytest.approx(best)  # the penalties vanish on a permutation: energy = path cost


def test_decode_path_accepts_permutations_and_rejects_the_rest():
    nodes = [7, 8, 9]
    for perm in itertools.permutations(range(3)):
        x = np.zeros(9, dtype=int)
        for t, i in enumerate(perm):
            x[i * 3 + t] = 1
        order, ok = decode_path(x, nodes)
        assert ok and order == [nodes[i] for i in perm]
    assert decode_path(np.zeros(9, dtype=int), nodes) == ([], False)
    two_at_once = np.zeros(9, dtype=int)
    two_at_once[[0, 3, 7]] = 1  # stops 0 and 1 both at position 0
    assert decode_path(two_at_once, nodes)[1] is False


def test_rebuild_route_reproduces_pyvrp():
    sc = grid_scenario()
    m = build_matrix(sc.graph, sc.location_nodes)
    plan = solve_vrp(sc, m, time_limit_s=0.5)
    for r in plan.routes:
        again = rebuild_route(r, [s.order for s in r.stops], sc, m)
        assert abs(again.start_s - r.start_s) <= 1 and abs(again.end_s - r.end_s) <= 1
        assert abs(again.distance_m - r.distance_m) <= 1
        assert again.time_warp_s == r.time_warp_s == 0
        assert again.legs == r.legs
        for a, b in zip(again.stops, r.stops):
            assert a.order == b.order and abs(a.arrive_s - b.arrive_s) <= 1 and abs(a.leave_s - b.leave_s) <= 1


def scrambled_plan(sc, m):
    """A deliberately poor single-route plan (orders in index order), so polishing has something to improve."""
    plan = solve_vrp(sc, m, time_limit_s=0.3)
    r = plan.routes[0]
    order = sorted(s.order for rr in plan.routes for s in rr.stops)
    return replace(plan, routes=[rebuild_route(r, order, sc, m)])


@pytest.mark.parametrize("solver", ["exact", "sa", "qaoa_p1"])
@pytest.mark.parametrize("objective", ["min_time", "min_distance"])
def test_polish_never_raises_cost_and_keeps_the_orders(solver, objective):
    sc = grid_scenario(objective=objective)
    m = build_matrix(sc.graph, sc.location_nodes)
    C = m.time_s if objective == "min_time" else m.dist_m
    plan = scrambled_plan(sc, m)
    polished, rep = polish_plan(plan, sc, m, solver=solver, m_seg=4, seed=0, sa_sweeps=200, shots=300)
    assert rep.cost_after <= rep.cost_before
    for s in rep.segments:
        assert s.cost_after <= s.cost_before and sorted(s.orders_after) == sorted(s.orders)
        assert s.qubits == len(s.orders) ** 2 <= 16
    for a, b in zip(plan.routes, polished.routes):
        assert a.vehicle == b.vehicle and sorted(x.order for x in a.stops) == sorted(x.order for x in b.stops)
        assert path_cost([x.order for x in b.stops], 0, 0, C) <= path_cost([x.order for x in a.stops], 0, 0, C)
    assert rep.note == HARDWARE_NOTE
    if solver == "exact":  # brute force on every segment: the scrambled order always has a better segment somewhere
        assert rep.accepted >= 1 and rep.cost_after < rep.cost_before and all(s.found_optimum for s in rep.segments)


def test_polish_refuses_segments_above_16_qubits():
    sc = grid_scenario()
    m = build_matrix(sc.graph, sc.location_nodes)
    plan = solve_vrp(sc, m, time_limit_s=0.3)
    with pytest.raises(ValueError, match="25 qubits"):
        polish_plan(plan, sc, m, solver="sa", m_seg=5)


def test_qaoa_reuses_angles_for_segments_of_the_same_size():
    sc = grid_scenario()
    m = build_matrix(sc.graph, sc.location_nodes)
    _, rep = polish_plan(scrambled_plan(sc, m), sc, m, solver="qaoa_p1", m_seg=4, shots=200)
    by_size = {}
    for s in rep.segments:
        by_size.setdefault(s.qubits, []).append(s.params_transferred)
    assert all(not flags[0] and all(flags[1:]) for flags in by_size.values())
    assert rep.params_transfer


def test_agent_with_quantum_off_is_unchanged():
    events: list[Event] = []
    res = run_agent(grid_scenario(), emit=events.append, time_limit_s=0.5)
    assert res.quantum is None and "quantum" not in [e.type for e in events]


def test_agent_with_quantum_returns_a_verified_plan_or_reverts():
    events: list[Event] = []
    res = run_agent(grid_scenario(), emit=events.append, time_limit_s=0.5, quantum="sa")
    assert res.status == "verified" and res.report.ok and res.quantum is not None
    kinds = [e.type for e in events]
    assert kinds.index("quantum") < len(kinds) - 1 and kinds[kinds.index("quantum") + 1] == "verify" and kinds[-1] == "final"
    assert HARDWARE_NOTE in next(e.message for e in events if e.type == "quantum")
    if res.quantum.reverted:
        assert res.iterations[-1].action == "revert_quantum"


def test_failed_polish_is_reverted_to_the_classical_plan(monkeypatch):
    """A polished plan the verifier rejects (here: a stop dropped) never reaches the user; the classical plan does."""
    real = loop.polish_plan

    def broken(plan, scenario, matrix, **kw):
        _, rep = real(plan, scenario, matrix, solver="exact")
        r = plan.routes[0]
        bad = rebuild_route(r, [s.order for s in r.stops][1:], scenario, matrix)
        rep.segments[0].accepted = True
        return Plan([bad, *plan.routes[1:]], plan.feasible, plan.solve_seconds, plan.cost), rep

    monkeypatch.setattr(loop, "polish_plan", broken)
    events: list[Event] = []
    res = run_agent(grid_scenario(), emit=events.append, time_limit_s=0.5, quantum="qaoa_p1")
    assert res.status == "verified" and res.report.ok
    assert res.quantum.reverted and "coverage" in res.quantum.failed_checks
    assert res.iterations[-1].action == "revert_quantum" and not res.iterations[-1].report.ok
    assert res.plan.served == 8
    assert any(e.type == "repair" and e.message.startswith("reverting quantum segments") for e in events)
