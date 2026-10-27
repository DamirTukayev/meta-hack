"""The verifier and the separately written audit must reach the same verdicts, plan by plan and kind by kind."""

from copy import deepcopy
from dataclasses import replace

import pytest

from orbitroute.agent.loop import run_agent
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.solver import solve_vrp
from orbitroute.verifier.checks import verify
from orbitroute.verifier.independent import audit_plan, disagreements

from test_agent import crossing_scenario, make_scenario_at
from shapely.geometry import box


def solved(sc, **kw):
    return solve_vrp(sc, build_matrix(sc.graph, sc.location_nodes), time_limit_s=1.0, **kw)


def agree(sc, plan, excluded=None):
    report, audit = verify(sc, plan, excluded=excluded), audit_plan(sc, plan, excluded=excluded)
    assert disagreements(report, audit) == [], (sorted({v.kind for v in report.violations}), audit.failed)
    return report, audit


def test_both_find_the_zone_crossing_of_a_first_pass_plan_and_accept_the_repaired_plan():
    sc = crossing_scenario()
    report, audit = agree(sc, solved(sc))
    assert audit.fails("zones") and report.of_kind("zones")
    result = run_agent(sc, time_limit_s=1.0)
    report, audit = agree(result.scenario, result.plan, result.excluded)
    assert audit.ok and report.ok


def test_both_accept_a_clean_plan_without_zones():
    sc = make_scenario_at(box(0, 0, 10, 10), [(100, 100), (300, 300)])
    report, audit = agree(sc, solved(sc))
    assert audit.ok and report.ok


def mutate(sc, plan, how):
    plan = deepcopy(plan)
    r = next(x for x in plan.routes if x.stops)
    if how == "drop_stop":
        r.stops.pop()
    elif how == "duplicate_stop":
        r.stops.append(r.stops[0])
    elif how == "broken_leg":
        r.legs[0] = [r.legs[0][0], r.legs[0][-1]]  # a jump that is not a road segment
    elif how == "extra_truck":
        plan.routes.extend(deepcopy(plan.routes) * (sc.problem.n_vehicles + 1))
    elif how == "unknown_order":
        r.stops[0] = replace(r.stops[0], order=99)
    return plan


@pytest.mark.parametrize("how", ["drop_stop", "duplicate_stop", "broken_leg", "extra_truck", "unknown_order"])
def test_both_agree_on_corrupted_plans(how):
    sc = make_scenario_at(box(0, 0, 10, 10), [(100, 100), (300, 300), (300, 100), (100, 300)], vehicle_capacity=4)
    plan = solved(sc)
    report, audit = agree(sc, mutate(sc, plan, how))
    assert not audit.ok and not report.ok  # and both noticed


def test_both_agree_when_the_deadline_or_the_capacity_is_too_tight():
    base = make_scenario_at(box(0, 0, 10, 10), [(100, 100), (300, 300), (300, 100), (100, 300)], vehicle_capacity=4)
    plan = solved(base)
    for update, kind in (({"deadline_s": base.problem.shift_start_s + 60}, "deadline"), ({"capacity": 1}, "capacity")):
        tight = replace(base, problem=base.problem.model_copy(update=update))
        report, audit = agree(tight, plan)
        assert audit.fails(kind) and report.of_kind(kind)


def test_both_agree_that_excluded_orders_need_not_be_served():
    sc = make_scenario_at(box(0, 0, 10, 10), [(100, 100), (300, 300), (300, 100)], vehicle_capacity=3)
    plan = solved(sc, excluded=frozenset({3}))
    _, audit = agree(sc, plan, excluded={3: "cut off"})
    assert audit.ok
    _, audit = agree(sc, plan)  # without the exclusion order 3 is missing, and both say so
    assert audit.fails("coverage")
