import json

from fastapi.testclient import TestClient

import orbitroute.api as api
from orbitroute.agent.events import Event
from orbitroute.serialize import plan_json, report_json, scene_json, scenario_json
from orbitroute.routing.matrix import build_matrix
from orbitroute.routing.solver import solve_vrp
from orbitroute.verifier.checks import verify

from test_agent import crossing_scenario


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_samples_endpoint_lists_bundled_images_with_examples():
    client = TestClient(api.app)
    data = client.get("/api/samples").json()
    names = {s["name"] for s in data}
    assert {"columbus", "memphis"} <= names
    columbus = next(s for s in data if s["name"] == "columbus")
    assert columbus["examples"] and columbus["image"].endswith("/image")
    assert client.get(columbus["image"]).headers["content-type"] == "image/jpeg"


def test_unknown_sample_is_404_and_overlong_request_is_rejected():
    client = TestClient(api.app)
    assert client.get("/api/run", params={"sample": "nope", "request": "x"}).status_code == 404
    assert client.get("/api/run", params={"sample": "columbus", "request": "x" * 401}).status_code == 422


def test_run_streams_pipeline_events_then_done(monkeypatch):
    def fake_pipeline(sample, request, *, emit, **kw):
        emit(Event("stage", "step one", {"stage": "perception"}))
        emit(Event("result", "verified", {"status": "verified"}))

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(api, "get_client", lambda: object())
    r = TestClient(api.app).get("/api/run", params={"sample": "columbus", "request": "30 orders"})
    kinds = [k for k, _ in sse_events(r.text)]
    assert kinds == ["event", "event", "done"]
    assert sse_events(r.text)[0][1]["type"] == "stage"


def test_pipeline_errors_become_a_failure_event_not_a_crash(monkeypatch):
    from orbitroute.llm.budget import BudgetExceeded

    def boom(*a, **kw):
        raise BudgetExceeded("global cap reached")

    monkeypatch.setattr(api, "run_pipeline", boom)
    monkeypatch.setattr(api, "get_client", lambda: object())
    r = TestClient(api.app).get("/api/run", params={"sample": "columbus", "request": "30 orders"})
    events = sse_events(r.text)
    assert events[0][0] == "failure" and "global cap" in events[0][1]["message"]
    assert events[-1][0] == "done"


def test_serializers_produce_json_with_pixel_geometry_and_violating_segments():
    sc = crossing_scenario()
    matrix = build_matrix(sc.graph, sc.location_nodes)
    plan = solve_vrp(sc, matrix, time_limit_s=1.0)
    report = verify(sc, plan)
    pj, rj = plan_json(sc, plan), report_json(sc, report)
    json.dumps([pj, rj, scene_json(sc.scene), scenario_json(sc)])  # everything must be serialisable
    route = pj["routes"][0]
    assert len(route["polyline"]) > 2 and route["stops"][0]["order"] in (1, 2)
    zone = next(v for v in rj["violations"] if v["kind"] == "zones")
    assert zone["segments"] and len(zone["segments"][0]) == 2 and len(zone["segments"][0][0]) == 2
    assert [c["kind"] for c in rj["checks"]] == ["coverage", "fleet", "capacity", "paths", "deadline", "zones"]
