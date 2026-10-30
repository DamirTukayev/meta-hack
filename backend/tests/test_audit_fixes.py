"""Things the audit of 30 October found: each one has a test so that it stays fixed."""

import json
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

import orbitroute.api as api
import orbitroute.perception.roads as roads
from orbitroute.config import write_atomic
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import ApiError
from orbitroute.perception import osm


# --- a photo with no road at all says so ---------------------------------------------------------------------------------------


def test_a_photo_without_any_road_is_refused_with_a_clear_message(monkeypatch):
    def no_map(name, meta):
        raise osm.OsmUnavailable("down")

    monkeypatch.setattr(roads, "osm_graph", no_map)
    monkeypatch.setattr(roads, "segment_roads", lambda *a, **k: np.zeros((200, 200), bool))

    class Sample:
        name, image_bytes = "x", b""
        meta = {"m_per_px": 1.0}

    with pytest.raises(ValueError, match="No roads were found"):
        roads.build_roads(None, Sample())


def test_an_error_in_sam_is_not_held_up_by_a_slow_map_server(monkeypatch):
    release = threading.Event()

    def slow_map(name, meta):
        release.wait(10)
        raise osm.OsmUnavailable("slow")

    def sam_fails(*a, **k):
        raise RuntimeError("SAM is down")

    monkeypatch.setattr(roads, "osm_graph", slow_map)
    monkeypatch.setattr(roads, "segment_roads", sam_fails)

    class Sample:
        name, image_bytes = "x", b""
        meta = {"m_per_px": 1.0}

    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="SAM is down"):
        roads.build_roads(None, Sample())
    release.set()
    assert time.monotonic() - t0 < 2


# --- the spend survives an unreadable state file -----------------------------------------------------------------------------------


def test_an_unreadable_state_file_does_not_reset_the_spend(tmp_path):
    guard = BudgetGuard(tmp_path / "state.json", 10.0)
    guard.record(3.0, "test")
    (tmp_path / "state.json").write_text("{not json")
    assert guard.total_spent() == pytest.approx(3.0)
    guard.record(1.0, "test")  # and it goes on counting from there, writing a good file again
    assert json.loads((tmp_path / "state.json").read_text())["total_usd"] == pytest.approx(4.0)


def test_a_cache_file_is_written_whole_or_not_at_all(tmp_path):
    path = tmp_path / "deep" / "answer.json"
    write_atomic(path, '{"a": 1}')
    assert json.loads(path.read_text()) == {"a": 1} and not list(path.parent.glob("*.tmp"))


# --- the api ---------------------------------------------------------------------------------------------------------------------------


def test_usage_and_spend_need_the_access_code_when_one_is_set(monkeypatch):
    import dataclasses

    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, access_code="secret-code"))
    client = TestClient(api.app)
    assert client.get("/api/usage").status_code == 403
    assert client.get("/api/health").json()["spent_usd"] is None
    assert client.get("/api/usage", headers={"X-Access-Code": "secret-code"}).status_code == 200
    assert client.get("/api/health", headers={"X-Access-Code": "secret-code"}).json()["spent_usd"] is not None


def test_without_a_code_setting_usage_is_open(monkeypatch):
    import dataclasses

    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, access_code=""))
    assert TestClient(api.app).get("/api/usage").status_code == 200


def test_the_providers_own_words_stay_off_the_page(monkeypatch):
    def failing_pipeline(sample, request, **kw):
        raise ApiError(401, "invalid key sk-live-123 for account acct_99")

    monkeypatch.setattr(api, "run_pipeline", failing_pipeline)
    monkeypatch.setattr(api, "get_client", lambda: object())
    text = TestClient(api.app).post("/api/run", json={"sample": "columbus", "request": "30 orders"}).text
    assert "sk-live-123" not in text and "acct_99" not in text and "status 401" in text


def test_a_busy_agent_does_not_use_up_the_callers_hourly_limit(monkeypatch):
    from orbitroute.limits import RateLimiter

    limiter = RateLimiter(2, 3600)
    monkeypatch.setattr(api, "run_limit_ip", limiter)
    monkeypatch.setattr(api, "run_limit_day", RateLimiter(1000, 3600))
    monkeypatch.setitem(api._active, "n", api.settings.max_concurrent_runs)  # every place taken
    client = TestClient(api.app)
    for _ in range(5):
        assert client.post("/api/run", json={"sample": "columbus", "request": "30 orders"}).status_code == 429
    monkeypatch.setitem(api._active, "n", 0)
    assert limiter.check("testclient") == 0  # the five turned-away calls cost the caller nothing
