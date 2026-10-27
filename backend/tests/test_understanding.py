import json
from pathlib import Path

import pytest

from orbitroute.understanding.constraints import ParsedRequest, hhmm_to_seconds, resolve, seconds_to_hhmm
from orbitroute.understanding.request import parse_request
from orbitroute.understanding.scene import scene_from_raw

FIXTURES = Path(__file__).parent / "fixtures"


def test_resolve_applies_and_reports_defaults():
    p = resolve(ParsedRequest(n_orders=40, n_vehicles=3, deadline="18:00", avoid_zone_kinds=["industrial"]))
    assert (p.n_orders, p.n_vehicles) == (40, 3)
    assert p.shift_start_s == hhmm_to_seconds("08:00") and p.deadline_s == hhmm_to_seconds("18:00")
    assert p.capacity == 20  # ceil(40 / 3 * 1.5)
    assert p.avoid_zone_kinds == ["industrial"]
    assert len(p.assumptions) == 3  # start time, service time, capacity were all defaulted


def test_stated_values_are_not_listed_as_assumptions():
    p = resolve(ParsedRequest(n_orders=10, n_vehicles=2, vehicle_capacity=6, shift_start="07:30", deadline="12:00", service_minutes=5))
    assert p.assumptions == []
    assert p.service_s == 300 and p.capacity == 6


def test_deadline_before_start_is_rejected():
    with pytest.raises(ValueError):
        resolve(ParsedRequest(n_orders=5, n_vehicles=1, shift_start="09:00", deadline="08:00"))


def test_insufficient_capacity_is_flagged():
    p = resolve(ParsedRequest(n_orders=10, n_vehicles=2, vehicle_capacity=3))
    assert any("infeasible" in a for a in p.assumptions)


def test_time_helpers_round_trip():
    assert seconds_to_hhmm(hhmm_to_seconds("17:05")) == "17:05"
    with pytest.raises(ValueError):
        hhmm_to_seconds("25:00")


class FakeClient:
    """Stands in for MetaClient: returns canned JSON and records the prompts."""

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def chat_json(self, messages, name, schema, **kw):
        self.calls.append(messages)
        return self.outputs.pop(0), None


GOOD = {"n_orders": 40, "n_vehicles": 3, "vehicle_capacity": None, "shift_start": None, "deadline": "18:00",
        "service_minutes": None, "avoid_zone_kinds": ["industrial"], "objective": "min_time", "notes": []}


def test_parse_request_maps_model_output_to_problem():
    problem = parse_request(FakeClient(GOOD), "40 orders, 3 trucks, by 18:00, avoid the industrial zone")
    assert problem.n_orders == 40 and problem.deadline_s == 18 * 3600 and problem.avoid_zone_kinds == ["industrial"]


def test_parse_request_retries_once_on_invalid_output_then_succeeds():
    bad = {**GOOD, "deadline": "6pm"}
    client = FakeClient(bad, GOOD)
    assert parse_request(client, "x").deadline_s == 18 * 3600
    assert "invalid" in client.calls[1][-1]["content"]


def test_parse_request_gives_up_after_two_invalid_outputs():
    with pytest.raises(ValueError):
        parse_request(FakeClient({**GOOD, "deadline": "soon"}, {**GOOD, "deadline": "soon"}), "x")


def test_scene_from_real_model_output():
    raw = json.loads((FIXTURES / "scene_columbus.json").read_text())
    scene = scene_from_raw(raw, 1536, 1536)
    kinds = {z.kind for z in scene.zones}
    assert {"industrial", "residential"} <= kinds
    assert scene.warehouses and all(0 <= x <= 1536 and 0 <= y <= 1536 for x, y in scene.warehouses)
    # the first warehouse the model reported (top-left big building) sits inside an industrial zone
    assert "industrial" in scene.kinds_at(*scene.warehouses[0])


def test_parse_request_asks_again_when_the_answer_is_not_json_at_all():
    import json

    class Flaky(FakeClient):
        def chat_json(self, messages, name, schema, **kw):
            if not self.outputs:
                raise json.JSONDecodeError("Expecting value", "", 0)
            return super().chat_json(messages, name, schema, **kw)

    class Empty:
        calls = 0

        def chat_json(self, *a, **kw):
            Empty.calls += 1
            if Empty.calls == 1:
                raise json.JSONDecodeError("Expecting value", "   ", 3)
            return GOOD, None

    assert parse_request(Empty(), "x").n_orders == 40 and Empty.calls == 2
