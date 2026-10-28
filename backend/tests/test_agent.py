from dataclasses import replace

from shapely.geometry import box

from orbitroute.agent.events import Event
from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import Decision, DecisionContext, ModelDecider, PolicyDecider, allowed_actions
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, Route, Stop, solve_vrp
from orbitroute.understanding.constraints import ParsedRequest, resolve
from orbitroute.understanding.scene import Scene, Zone
from orbitroute.verifier.checks import verify

from helpers import grid_graph


def problem(**kw):
    base = dict(n_orders=2, n_vehicles=1, deadline="12:00", shift_start="08:00", service_minutes=3, vehicle_capacity=4, avoid_zone_kinds=["industrial"])
    return resolve(ParsedRequest(**{**base, **kw}))


def make_scenario_at(zone, order_pts, depot_pt=(100, 200), **kw) -> Scenario:
    graph = grid_graph()
    scene = Scene(400, 400, [Zone("industrial", zone)], warehouses=[])
    nodes = [graph.nearest_node(x, y)[0] for x, y in order_pts]
    depot = graph.nearest_node(*depot_pt)[0]
    return Scenario(graph, scene, problem(n_orders=len(order_pts), **kw), depot_node=depot, order_nodes=nodes, seed=0)


def crossing_scenario(**kw) -> Scenario:
    """Depot on the left of a central industrial block, two orders on the right: the shortest way crosses the block."""
    return make_scenario_at(box(130, 130, 270, 270), [(300, 200), (300, 300)], **kw)


def test_first_pass_enters_the_zone_and_verifier_catches_it():
    sc = crossing_scenario()
    plan = solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0)
    report = verify(sc, plan)
    assert plan.feasible  # the solver is happy ...
    assert report.of_kind("zones")  # ... the verifier is not
    assert not next(c for c in report.checks if c.kind == "zones").passed
    assert report.of_kind("zones")[0].data["inside_m"] > 10


def test_agent_repairs_the_zone_violation_and_returns_a_verified_plan():
    events: list[Event] = []
    result = run_agent(crossing_scenario(), emit=events.append, time_limit_s=1.0)
    assert result.status == "verified"
    assert result.report.ok and all(c.passed for c in result.report.checks)
    assert len(result.iterations) >= 2
    assert result.iterations[0].action == "ban_violating_edges"
    assert not result.iterations[0].report.ok and result.iterations[-1].report.ok
    kinds = [e.type for e in events]
    assert kinds[0] == "start" and "decision" in kinds and kinds[-1] == "final"
    # repaired routes are longer than the illegal shortcut
    first, last = result.iterations[0].report.metrics["total_km"], result.report.metrics["total_km"]
    assert last > first


def test_without_verifier_the_illegal_plan_is_returned_as_is():
    result = run_agent(crossing_scenario(), time_limit_s=1.0, verify_plan=False)
    assert result.status == "unverified"
    assert not result.report.ok  # checked afterwards, only to score the ablation


def test_impossible_deadline_yields_verified_relaxation_options():
    sc = crossing_scenario(n_vehicles=1)
    # one truck needs ~7.5 min for both orders; a 5 minute window is impossible for it
    sc = replace(sc, problem=sc.problem.model_copy(update={"deadline_s": sc.problem.shift_start_s + 5 * 60}))
    result = run_agent(sc, time_limit_s=1.0)
    assert result.status == "needs_relaxation"
    assert result.relaxations
    for opt in result.relaxations:
        assert opt.report.ok  # every proposed relaxation comes with a plan that passes verification
    assert any(o.kind in ("add_vehicles", "extend_deadline") for o in result.relaxations)
    assert result.report.ok


def test_the_trucks_option_covers_what_capacity_alone_requires():
    pts = [(300, 100), (300, 150), (300, 200), (300, 250), (300, 300), (300, 350), (200, 350), (150, 350)]
    sc = make_scenario_at(box(130, 130, 270, 270), pts, n_vehicles=1, vehicle_capacity=1, deadline="14:00")
    result = run_agent(sc, time_limit_s=1.0)  # eight orders, one per truck: needs 8 trucks, far more than a few extra
    assert result.status == "needs_relaxation"
    options = [o for o in result.relaxations if o.kind == "add_vehicles"]
    assert options and options[0].scenario.problem.n_vehicles >= 8 and options[0].report.ok


LEFT = [(100, 100), (100, 150), (100, 250), (100, 300), (100, 350), (200, 100), (200, 300), (150, 100), (150, 300)]


def test_a_few_orders_cut_off_by_the_zone_are_excluded_and_reported():
    # 9 orders on the left, 1 inside the avoided zone: it can never be reached legally, 10% is acceptable to drop
    sc = make_scenario_at(box(250, 0, 400, 400), [*LEFT, (300, 200)], vehicle_capacity=12)
    result = run_agent(sc, time_limit_s=1.0)
    assert result.status == "verified_partial"
    assert set(result.excluded) == {10}
    assert result.report.ok and result.report.excluded == result.excluded
    assert sorted(s.order for r in result.plan.routes for s in r.stops) == list(range(1, 10))


def test_when_most_orders_are_cut_off_the_agent_refuses_and_offers_to_stop_avoiding_the_zone():
    sc = make_scenario_at(box(250, 0, 400, 400), [(100, 100), (100, 300), (300, 200), (300, 300)], vehicle_capacity=4)
    result = run_agent(sc, time_limit_s=1.0)
    assert result.status == "needs_relaxation" and not result.excluded
    option = next(o for o in result.relaxations if o.kind == "allow_zone")
    assert option.report.ok  # the relaxed plan is verified ...
    zone_check = next(c for c in option.report.checks if c.kind == "zones")
    assert not zone_check.passed and "relaxed" in zone_check.title  # ... and the zone check says honestly it is off
    assert option.amount > 0 and "drives" in option.description  # ... and says how far it drives through the zone
    assert sorted(s.order for r in option.plan.routes for s in r.stops) == [1, 2, 3, 4]


def test_a_mostly_cut_off_request_also_offers_to_serve_the_reachable_orders_without_breaking_any_rule():
    sc = make_scenario_at(box(250, 0, 400, 400), [(100, 100), (100, 300), (300, 200), (300, 300)], vehicle_capacity=4)
    result = run_agent(sc, time_limit_s=1.0)
    option = next(o for o in result.relaxations if o.kind == "serve_reachable")
    assert option.report.ok and option.report.excluded == {3: option.report.excluded[3], 4: option.report.excluded[4]}
    assert all("cut off" in why for why in option.report.excluded.values())
    assert sorted(s.order for r in option.plan.routes for s in r.stops) == [1, 2]  # the zone is still avoided
    assert next(c for c in option.report.checks if c.kind == "zones").passed
    assert "2 reachable orders" in option.description and "#3" in option.description and "#4" in option.description


def split_scenario():
    """A vertical forbidden band: the depot and one order on its left, three orders on its right."""
    return make_scenario_at(box(180, 0, 220, 400), [(100, 100), (300, 100), (300, 200), (300, 300)], depot_pt=(100, 200), vehicle_capacity=4)


def test_when_the_zone_cuts_the_depot_off_the_agent_offers_to_move_the_depot_to_where_the_orders_are():
    result = run_agent(split_scenario(), time_limit_s=1.0)
    assert result.status == "needs_relaxation"
    option = next(o for o in result.relaxations if o.kind == "move_depot")
    assert option.report.ok and option.report.excluded.keys() == {1}  # three of four orders, order 1 stays cut off
    assert sorted(s.order for r in option.plan.routes for s in r.stops) == [2, 3, 4]
    assert option.scenario.graph.nodes[option.scenario.depot_node][0] > 220  # the depot is now on the right of the band
    assert next(c for c in option.report.checks if c.kind == "zones").passed  # no rule is broken
    assert "3 of 4 orders" in option.description


def test_no_depot_move_is_offered_when_the_depot_already_reaches_the_most_orders():
    result = run_agent(make_scenario_at(box(250, 0, 400, 400), [(100, 100), (100, 300), (300, 200), (300, 300)], vehicle_capacity=4), time_limit_s=1.0)
    assert not any(o.kind == "move_depot" for o in result.relaxations)


def test_the_policy_recommends_the_safe_option_that_serves_the_most_orders():
    result = run_agent(split_scenario(), time_limit_s=1.0)
    rec = PolicyDecider().recommend(result.relaxations, result.scenario.problem)
    chosen = result.relaxations[rec.index]
    assert not chosen.kind.startswith("allow_zone") and chosen.kind == "move_depot" and rec.source == "policy"
    assert result.recommendation.index == rec.index  # the loop used it (the default decider is the policy)


class FakeJSON:
    def __init__(self, raw=None, raises=None):
        self.raw, self.raises = raw, raises
        self.messages = None

    def chat_json(self, messages, name, schema, **kw):
        self.messages = messages
        if self.raises:
            raise self.raises
        return self.raw, None


def test_the_model_recommendation_is_used_when_it_is_sensible_and_overruled_when_it_is_not():
    from orbitroute.llm.client import ApiError

    result = run_agent(split_scenario(), time_limit_s=1.0)
    options, problem = result.relaxations, result.scenario.problem
    safe = next(i for i, o in enumerate(options) if o.kind == "serve_reachable")
    unsafe = next(i for i, o in enumerate(options) if o.kind.startswith("allow_zone"))
    ok = ModelDecider(FakeJSON({"index": safe, "reason": "Keeps every rule."})).recommend(options, problem)
    assert (ok.index, ok.source, ok.reason) == (safe, "model", "Keeps every rule.")
    # it must not recommend driving through the forbidden zone while an option that keeps every rule exists
    rejected = ModelDecider(FakeJSON({"index": unsafe, "reason": "Fastest."})).recommend(options, problem)
    assert rejected.source == "policy" and "policy used" in rejected.reason and not options[rejected.index].kind.startswith("allow_zone")
    for bad in (FakeJSON({"index": 99, "reason": "x"}), FakeJSON({"index": 0, "reason": " "}), FakeJSON(raises=ApiError(500, "down"))):
        assert ModelDecider(bad).recommend(options, problem).source == "policy"
    fake = FakeJSON({"index": safe, "reason": "ok"})
    ModelDecider(fake).recommend(options, problem)
    sent = fake.messages[1]["content"]
    assert "drives_through_avoided_zone" in sent and "orders_served" in sent


def test_policy_drops_a_few_unreachable_orders_but_not_most_of_them():
    from orbitroute.verifier.checks import Report, Violation

    report = Report(checks=[], violations=[Violation("zones", "x", route=0, data={"edges": []})], metrics={})
    few = DecisionContext(report, 1, [], unreachable_orders=[3], total_orders=20)
    many = DecisionContext(report, 1, [], unreachable_orders=[1, 2, 3, 4, 5], total_orders=20)
    assert PolicyDecider().decide(few).action == "exclude_unreachable"
    assert PolicyDecider().decide(many).action == "propose_relaxation"


def test_policy_escalates_from_targeted_to_full_zone_ban():
    sc = crossing_scenario()
    plan = solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0)
    report = verify(sc, plan)
    ctx = DecisionContext(report, 3, ["ban_violating_edges", "ban_violating_edges"])
    assert PolicyDecider().decide(ctx).action == "ban_all_zone_edges"
    assert PolicyDecider().decide(DecisionContext(report, 1, [])).action == "ban_violating_edges"


class FakeClient:
    def __init__(self, raw=None, raises=None):
        self.raw, self.raises = raw, raises

    def chat_json(self, messages, name, schema, **kw):
        if self.raises:
            raise self.raises
        return self.raw, None


def test_model_decider_uses_a_valid_model_choice():
    sc = crossing_scenario()
    report = verify(sc, solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0))
    ctx = DecisionContext(report, 1, [])
    d = ModelDecider(FakeClient({"action": "ban_all_zone_edges", "reason": "be safe"})).decide(ctx)
    assert (d.action, d.source) == ("ban_all_zone_edges", "model")


def test_model_decider_falls_back_on_an_action_that_is_not_allowed_or_a_failure():
    sc = crossing_scenario()
    report = verify(sc, solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0))
    ctx = DecisionContext(report, 1, [])
    assert "propose_relaxation" not in allowed_actions(ctx)
    bad = ModelDecider(FakeClient({"action": "propose_relaxation", "reason": "give up"})).decide(ctx)
    assert (bad.action, bad.source) == ("ban_violating_edges", "policy")
    boom = ModelDecider(FakeClient(raises=ValueError("bad json"))).decide(ctx)
    assert boom.source == "policy"


def test_verifier_flags_capacity_coverage_and_broken_paths():
    sc = make_scenario_at(box(130, 130, 270, 270), [(300, 200), (300, 300), (100, 100), (100, 300)], vehicle_capacity=2)
    matrix = build_matrix(sc.graph, sc.location_nodes)
    plan = solve_vrp(sc, matrix, time_limit_s=1.0)
    # a plan that puts all four orders on one truck (capacity 2), skips order 4's duplicate and breaks a leg
    stops = [Stop(i, sc.order_nodes[i - 1], 0, 0) for i in (1, 2, 3, 3)]
    r = Route(0, stops, sc.problem.shift_start_s, sc.problem.shift_start_s + 60, 0, 0, legs=[[sc.depot_node, 999999]] + [matrix.paths[(0, 1)]] * 4)
    report = verify(sc, Plan([r], True, 0.0, 0))
    kinds = report.summary()
    assert {"capacity", "coverage", "paths"} <= set(kinds)
    assert not report.ok


def test_policy_does_not_waste_a_search_round_on_a_capacity_violation():
    from orbitroute.verifier.checks import Report, Violation

    report = Report(checks=[], violations=[Violation("capacity", "truck 0: 6 units, capacity 3", route=0)], metrics={})
    assert PolicyDecider().decide(DecisionContext(report, 1, [])).action == "propose_relaxation"
    late = Report(checks=[], violations=[Violation("deadline", "truck 0 finishes late", route=0)], metrics={})
    assert PolicyDecider().decide(DecisionContext(late, 1, [])).action == "resolve_longer"  # a deadline miss may just need more search


def test_when_the_zone_is_not_the_only_problem_the_relaxation_combines_fixes():
    # one truck, orders on both sides of a wall-like zone, and a deadline one truck cannot meet even without the zone
    sc = make_scenario_at(box(250, 0, 400, 400), [(100, 100), (100, 300), (300, 200), (300, 300), (300, 100), (100, 350)], n_vehicles=1, vehicle_capacity=6)
    sc = replace(sc, problem=sc.problem.model_copy(update={"deadline_s": sc.problem.shift_start_s + 12 * 60}))
    result = run_agent(sc, time_limit_s=1.0)
    assert result.status == "needs_relaxation"
    combined = [o for o in result.relaxations if o.kind.startswith("allow_zone")]
    assert combined and combined[0].report.ok


def test_a_plan_driving_on_links_drawn_across_gaps_says_so_but_stays_valid():
    sc = crossing_scenario(avoid_zone_kinds=[])
    plan = solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0)
    clean = verify(sc, plan)
    assert clean.ok and clean.metrics["unconfirmed_m"] == 0 and clean.unconfirmed == []
    g = sc.graph
    drawn = replace(g, edges=[replace(e, bridge=True) for e in g.edges])  # every link is one the graph drew itself (60+ m long here)
    sc2 = replace(sc, graph=drawn)
    plan2 = solve_vrp(sc2, build_matrix(sc2.graph, sc2.location_nodes), time_limit_s=1.0)
    report = verify(sc2, plan2)
    assert report.ok  # a note, not a failed check
    assert report.metrics["unconfirmed_m"] > 0 and 0 < report.metrics["unconfirmed_share"] <= 1 and report.unconfirmed
