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
    assert client.post("/api/run", json={"sample": "nope", "request": "x"}).status_code == 404
    assert client.post("/api/run", json={"sample": "columbus", "request": "x" * 401}).status_code == 422
    too_many = {"orders": [[10, 10]] * 101}
    assert client.post("/api/run", json={"sample": "columbus", "request": "x", "custom": too_many}).status_code == 422
    assert client.post("/api/run", json={"sample": "columbus", "request": "x", "custom": {"depot": [1, "nan"]}}).status_code == 422


def test_run_streams_pipeline_events_then_done(monkeypatch):
    def fake_pipeline(sample, request, *, emit, **kw):
        emit(Event("stage", "step one", {"stage": "perception"}))
        emit(Event("result", "verified", {"status": "verified"}))

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(api, "get_client", lambda: object())
    r = TestClient(api.app).post("/api/run", json={"sample": "columbus", "request": "30 orders"})
    kinds = [k for k, _ in sse_events(r.text)]
    assert kinds == ["event", "event", "done"]
    assert sse_events(r.text)[0][1]["type"] == "stage"


def test_custom_points_reach_the_pipeline(monkeypatch):
    seen = {}

    def fake_pipeline(sample, request, *, emit, custom=None, **kw):
        seen["custom"] = custom

    monkeypatch.setattr(api, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(api, "get_client", lambda: object())
    body = {"sample": "columbus", "request": "3 trucks", "custom": {"depot": [100, 200], "orders": [[300, 200], [300, 300]], "zone": [[0, 0], [50, 0], [50, 50]]}}
    TestClient(api.app).post("/api/run", json=body)
    assert seen["custom"].depot == (100, 200) and len(seen["custom"].orders) == 2 and len(seen["custom"].zone) == 3


def test_pipeline_errors_become_a_failure_event_not_a_crash(monkeypatch):
    from orbitroute.llm.budget import BudgetExceeded

    def boom(*a, **kw):
        raise BudgetExceeded("global cap reached")

    monkeypatch.setattr(api, "run_pipeline", boom)
    monkeypatch.setattr(api, "get_client", lambda: object())
    r = TestClient(api.app).post("/api/run", json={"sample": "columbus", "request": "30 orders"})
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
    # one leg per stop plus the return to the depot; each leg starts where the previous one ended
    assert len(route["legs"]) == len(route["stops"]) + 1
    assert all(a[-1] == b[0] for a, b in zip(route["legs"], route["legs"][1:]))
    assert route["legs"][0][0] == route["polyline"][0] and route["legs"][-1][-1] == route["polyline"][-1]
    zone = next(v for v in rj["violations"] if v["kind"] == "zones")
    assert zone["segments"] and len(zone["segments"][0]) == 2 and len(zone["segments"][0][0]) == 2
    assert [c["kind"] for c in rj["checks"]] == ["coverage", "fleet", "capacity", "paths", "deadline", "zones"]


def test_request_text_states_the_order_count_from_the_clicks_or_the_auto_count():
    from orbitroute.custom import CustomInputs
    from orbitroute.pipeline import request_text

    assert request_text("3 trucks", CustomInputs(orders=[(1, 1), (2, 2)]), None) == "2 orders. 3 trucks"
    assert request_text("3 trucks", None, 25) == "25 orders. 3 trucks"
    assert request_text("3 trucks", CustomInputs(depot=(1, 1)), 25) == "25 orders. 3 trucks"
    assert request_text("30 orders, 3 trucks", None, None) == "30 orders, 3 trucks"  # API clients may still put the count in the text


def test_auto_orders_is_validated_and_forwarded(monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "run_pipeline", lambda sample, request, *, emit, auto_orders=None, **kw: seen.update(n=auto_orders))
    monkeypatch.setattr(api, "get_client", lambda: object())
    c = TestClient(api.app)
    assert c.post("/api/run", json={"sample": "columbus", "request": "x", "auto_orders": 0}).status_code == 422
    assert c.post("/api/run", json={"sample": "columbus", "request": "x", "auto_orders": 101}).status_code == 422
    c.post("/api/run", json={"sample": "columbus", "request": "3 trucks", "auto_orders": 12})
    assert seen["n"] == 12


def test_request_text_states_the_truck_count_from_its_own_field():
    from orbitroute.custom import CustomInputs
    from orbitroute.pipeline import request_text

    assert request_text("by 12:00", CustomInputs(orders=[(1, 1)] * 5), None, 4) == "5 orders. 4 trucks. by 12:00"
    assert request_text("by 12:00", None, None, 2) == "2 trucks. by 12:00"


def test_trucks_field_is_validated_and_forwarded(monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "run_pipeline", lambda sample, request, *, emit, trucks=None, **kw: seen.update(t=trucks))
    monkeypatch.setattr(api, "get_client", lambda: object())
    c = TestClient(api.app)
    assert c.post("/api/run", json={"sample": "columbus", "request": "x", "trucks": 0}).status_code == 422
    assert c.post("/api/run", json={"sample": "columbus", "request": "x", "trucks": 31}).status_code == 422
    c.post("/api/run", json={"sample": "columbus", "request": "by 12:00", "trucks": 4})
    assert seen["t"] == 4


def test_a_bad_point_is_reported_with_the_marker_to_highlight(monkeypatch):
    from orbitroute.custom import PlacementError

    def bad(*a, **kw):
        raise PlacementError("The order 3 is 202 m from the nearest road", "order", 2)

    monkeypatch.setattr(api, "run_pipeline", bad)
    monkeypatch.setattr(api, "get_client", lambda: object())
    r = TestClient(api.app).post("/api/run", json={"sample": "columbus", "request": "by 12:00"})
    kind, data = sse_events(r.text)[0]
    assert kind == "failure" and data["point"] == {"kind": "order", "index": 2}


def _fast_pipeline(monkeypatch):
    monkeypatch.setattr(api, "run_pipeline", lambda sample, request, *, emit, **kw: emit(Event("result", "ok", {})))
    monkeypatch.setattr(api, "get_client", lambda: object())
    monkeypatch.setattr(api, "run_limit_day", api.RateLimiter(1000, 86400))


def test_runs_are_limited_per_ip(monkeypatch):
    _fast_pipeline(monkeypatch)
    monkeypatch.setattr(api, "run_limit_ip", api.RateLimiter(2, 3600))
    c = TestClient(api.app)
    body = {"sample": "columbus", "request": "by 12:00"}
    assert c.post("/api/run", json=body).status_code == 200
    assert c.post("/api/run", json=body).status_code == 200
    r = c.post("/api/run", json=body)
    assert r.status_code == 429 and "Try again" in r.json()["detail"] and "retry-after" in r.headers


def test_runs_have_a_daily_ceiling_for_everyone(monkeypatch):
    _fast_pipeline(monkeypatch)
    monkeypatch.setattr(api, "run_limit_ip", api.RateLimiter(1000, 3600))
    monkeypatch.setattr(api, "run_limit_day", api.RateLimiter(1, 86400))
    c = TestClient(api.app)
    body = {"sample": "columbus", "request": "by 12:00"}
    assert c.post("/api/run", json=body).status_code == 200
    assert c.post("/api/run", json=body).status_code == 429


def test_the_pause_switch_stops_runs_before_anything_is_spent(monkeypatch):
    _fast_pipeline(monkeypatch)
    monkeypatch.setattr(api.guard, "paid_calls_enabled", False)
    r = TestClient(api.app).post("/api/run", json={"sample": "columbus", "request": "by 12:00"})
    assert r.status_code == 503 and "paused" in r.json()["detail"]


def test_concurrent_runs_are_capped_and_the_slot_is_released_afterwards(monkeypatch):
    _fast_pipeline(monkeypatch)
    monkeypatch.setattr(api, "run_limit_ip", api.RateLimiter(1000, 3600))
    c = TestClient(api.app)
    body = {"sample": "columbus", "request": "by 12:00"}
    monkeypatch.setitem(api._active, "n", api.settings.max_concurrent_runs)  # all slots taken
    assert c.post("/api/run", json=body).status_code == 429
    monkeypatch.setitem(api._active, "n", 0)
    assert c.post("/api/run", json=body).status_code == 200
    assert api._active["n"] == 0  # the finished run gave its slot back


def test_client_ip_trusts_only_the_entries_a_proxy_wrote(monkeypatch):
    from types import SimpleNamespace

    def ip(header, hops=1, trust=True):
        object.__setattr__(api.settings, "trust_proxy", trust)
        object.__setattr__(api.settings, "trusted_proxy_hops", hops)
        req = SimpleNamespace(headers={"x-forwarded-for": header}, client=SimpleNamespace(host="10.0.0.1"))
        return api.client_ip(req)

    try:
        assert ip("203.0.113.9", trust=False) == "10.0.0.1"  # not behind a proxy: the header is ignored
        assert ip("203.0.113.9") == "203.0.113.9"
        assert ip("1.2.3.4, 203.0.113.9") == "203.0.113.9"  # a caller-written first entry cannot pick the bucket
        assert ip("203.0.113.9, 198.51.100.7", hops=2) == "203.0.113.9"  # two proxies (CDN + load balancer)
        assert ip("", hops=1) == "10.0.0.1" and ip("198.51.100.7", hops=2) == "10.0.0.1"  # too short: fall back to the peer
    finally:
        object.__setattr__(api.settings, "trust_proxy", False)
        object.__setattr__(api.settings, "trusted_proxy_hops", 1)


def test_the_area_limit_is_counted_per_client_address_behind_a_proxy(monkeypatch, tmp_path):
    import orbitroute.areas as areas
    from orbitroute.limits import RateLimiter
    from test_areas import textured

    monkeypatch.setattr(areas, "AREAS_DIR", tmp_path)
    monkeypatch.setattr(api, "AREAS_DIR", tmp_path)
    monkeypatch.setattr(areas, "fetch_tile", lambda lon, lat, **kw: (textured(), (0.0, 0.0, 1.0, 1.0)))
    monkeypatch.setattr(api, "area_limit_ip", RateLimiter(1, 3600))
    monkeypatch.setattr(api, "area_limit_all", RateLimiter(50, 3600))
    object.__setattr__(api.settings, "trust_proxy", True)
    try:
        c = TestClient(api.app)
        a, b = {"x-forwarded-for": "198.51.100.1"}, {"x-forwarded-for": "198.51.100.2"}
        assert c.post("/api/areas", json={"lat": 30.0, "lon": -90.0}, headers=a).status_code == 200
        assert c.post("/api/areas", json={"lat": 31.0, "lon": -90.0}, headers=a).status_code == 429  # same caller
        assert c.post("/api/areas", json={"lat": 32.0, "lon": -90.0}, headers=b).status_code == 200  # another caller is not blocked
    finally:
        object.__setattr__(api.settings, "trust_proxy", False)


def test_an_oversized_recording_is_refused_without_reading_it_all(monkeypatch):
    monkeypatch.setattr(api, "asr_limit_ip", api.RateLimiter(100, 60))
    monkeypatch.setattr(api, "asr_limit_all", api.RateLimiter(100, 60))
    c = TestClient(api.app)
    big = b"x" * (api.MAX_AUDIO_BYTES + 1)
    assert c.post("/api/transcribe", content=big).status_code == 413
    # a chunked upload with no Content-Length is cut off at the limit as well
    assert c.post("/api/transcribe", content=(big[i : i + 65536] for i in range(0, len(big), 65536))).status_code == 413


def test_a_run_is_abandoned_when_the_client_goes_away(monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()
    seen = {}

    def slow_pipeline(sample, request, *, emit, **kw):
        emit(Event("stage", "one", {}))
        started.set()
        release.wait(5)
        try:
            emit(Event("stage", "two", {}))  # reached after the disconnect
            seen["finished"] = True
        except api.RunCancelled:
            seen["cancelled"] = True
            raise

    monkeypatch.setattr(api, "run_pipeline", slow_pipeline)
    monkeypatch.setattr(api, "get_client", lambda: object())
    monkeypatch.setattr(api, "run_limit_ip", api.RateLimiter(100, 60))
    monkeypatch.setattr(api, "run_limit_day", api.RateLimiter(100, 60))
    c = TestClient(api.app)
    with c.stream("POST", "/api/run", json={"sample": "columbus", "request": "30 orders"}) as r:
        next(r.iter_lines())  # the first event arrives, then the "browser" closes the connection
    release.set()
    for _ in range(50):
        if seen:
            break
        threading.Event().wait(0.1)
    assert seen == {"cancelled": True}


def test_transcribe_endpoint_returns_text_and_enforces_limits(monkeypatch):
    class Fake:
        def transcribe(self, audio):
            if audio == b"bad":
                raise ValueError("not a valid WAV file: nope")
            return "by noon, avoid the residential area"

    monkeypatch.setattr(api, "get_client", lambda: Fake())
    monkeypatch.setattr(api, "asr_limit_ip", api.RateLimiter(3, 3600))
    monkeypatch.setattr(api, "asr_limit_all", api.RateLimiter(100, 86400))
    c = TestClient(api.app)
    ok = c.post("/api/transcribe", content=b"RIFFxxxx", headers={"content-type": "audio/wav"})
    assert ok.status_code == 200 and ok.json() == {"text": "by noon, avoid the residential area"}
    assert c.post("/api/transcribe", content=b"bad").status_code == 400
    assert c.post("/api/transcribe", content=b"").status_code == 400
    assert c.post("/api/transcribe", content=b"x" * (api.MAX_AUDIO_BYTES + 1)).status_code in (413, 429)
    assert c.post("/api/transcribe", content=b"RIFFxxxx").status_code == 429  # the per-IP limit of 3 is used up
