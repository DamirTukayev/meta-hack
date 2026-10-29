"""Sharing a link must not hand out the credits behind the keys: with an access code only its holders get live model calls,
everyone else gets the recorded demo, and after PAID_CALLS_UNTIL nobody does."""

import dataclasses
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import orbitroute.api as api
import orbitroute.perception.segment as segment
import orbitroute.understanding.request as request_mod
import orbitroute.understanding.scene as scene_mod
from orbitroute.config import _utc
from orbitroute.limits import RateLimiter

CODE = "friends-only-code"


@pytest.fixture
def gated(tmp_path, monkeypatch):
    """Keys are set (not the offline demo) but live mode needs the code; the live cache is empty, so only recorded answers exist."""
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, access_code=CODE))
    for module in (segment, scene_mod, request_mod):
        monkeypatch.setattr(module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(api, "run_limit_ip", RateLimiter(1000, 60))
    monkeypatch.setattr(api, "run_limit_day", RateLimiter(1000, 60))
    monkeypatch.setattr(api, "access_limit_ip", RateLimiter(8, 3600))
    return TestClient(api.app)


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def run(client, sentence, **headers):
    body = {"sample": "columbus", "request": sentence, "auto_orders": 12, "trucks": 3}
    return events(client.post("/api/run", json=body, headers=headers).text)


def test_health_says_a_code_is_needed(gated):
    h = gated.get("/api/health").json()
    assert h["access_code_required"] is True and h["paid_window_open"] is True


def test_only_the_right_code_unlocks_live_mode(gated):
    assert gated.get("/api/access").json()["live"] is False
    assert gated.get("/api/access", headers={"X-Access-Code": "wrong"}).json()["live"] is False
    ok = gated.get("/api/access", headers={"X-Access-Code": CODE}).json()
    assert ok["live"] is True and ok["required"] is True and ok["message"] == ""


def test_without_the_code_the_bundled_examples_still_run_for_free(gated):
    got = run(gated, "by 12:00, avoid the residential area")
    assert "failure" not in [k for k, _ in got]
    result = next(d for k, d in got if k == "event" and d["type"] == "result")
    assert result["data"]["paid_calls"] == 0 and result["data"]["cost_usd"] == 0


def test_without_the_code_a_sentence_of_your_own_is_refused_and_says_why(gated):
    failure = next(d for k, d in run(gated, "by 13:30, avoid the park please") if k == "failure")
    assert "access code" in failure["message"]


def test_a_wrong_code_gets_the_same_recorded_demo(gated):
    failure = next(d for k, d in run(gated, "by 13:30, avoid the park please", **{"X-Access-Code": "wrong"}) if k == "failure")
    assert "access code" in failure["message"]


def test_voice_and_new_areas_need_the_code(gated):
    assert gated.post("/api/transcribe", content=b"RIFFxxxx").status_code == 403
    r = gated.post("/api/areas", json={"lat": 33.75, "lon": -84.39})
    assert r.status_code == 403 and "access code" in r.json()["detail"]


def test_guessing_the_code_is_slow(gated):
    codes = [gated.get("/api/access", headers={"X-Access-Code": f"guess-{i}"}).status_code for i in range(10)]
    assert codes[:8] == [200] * 8 and codes[8:] == [429, 429]
    assert gated.get("/api/access", headers={"X-Access-Code": CODE}).json()["live"] is True  # the right code is never held up


def test_after_paid_calls_until_nobody_is_live_even_with_the_code(gated, monkeypatch):
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, paid_calls_until=datetime.now(timezone.utc) - timedelta(minutes=1)))
    got = gated.get("/api/access", headers={"X-Access-Code": CODE}).json()
    assert got["live"] is False and "closed" in got["message"]
    assert gated.get("/api/health").json()["paid_window_open"] is False
    failure = next(d for k, d in run(gated, "by 13:30, avoid the park please", **{"X-Access-Code": CODE}) if k == "failure")
    assert "closed" in failure["message"]


def test_without_a_code_setting_everyone_is_live(monkeypatch):
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, access_code=""))
    got = TestClient(api.app).get("/api/access").json()
    assert got == {"required": False, "live": True, "window_open": True, "message": ""}


def test_the_paid_until_date_reads_iso_with_or_without_a_zone():
    assert _utc("") is None
    assert _utc("2026-11-04T12:00:00Z") == datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    assert _utc("2026-11-04T12:00:00") == datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        _utc("next tuesday")
