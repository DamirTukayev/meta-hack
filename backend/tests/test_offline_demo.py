"""The demo must run without any API key: the bundled samples with their example sentences use only recorded answers."""

import json

import pytest
from fastapi.testclient import TestClient

import orbitroute.api as api
import orbitroute.perception.segment as segment
import orbitroute.understanding.request as request_mod
import orbitroute.understanding.scene as scene_mod
from orbitroute.limits import RateLimiter


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """No key, and an empty live cache: whatever runs must come from the committed pre-warmed answers."""
    monkeypatch.setattr(api, "offline_demo", True)
    for module in (segment, scene_mod, request_mod):
        monkeypatch.setattr(module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(api, "run_limit_ip", RateLimiter(1000, 60))
    monkeypatch.setattr(api, "run_limit_day", RateLimiter(1000, 60))
    return TestClient(api.app)


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def run(client, sample, sentence, **extra):
    body = {"sample": sample, "request": sentence, "auto_orders": 12, "trucks": 3, **extra}
    return events(client.post("/api/run", json=body).text)


def samples_with_examples():
    return [(s["name"], ex) for s in TestClient(api.app).get("/api/samples").json() for ex in s["examples"]]


def test_health_says_it_is_the_offline_demo(offline):
    assert offline.get("/api/health").json()["offline_demo"] is True


@pytest.mark.parametrize("sample,sentence", samples_with_examples())
def test_every_bundled_sample_runs_with_each_of_its_examples_without_a_key(offline, sample, sentence):
    got = run(offline, sample, sentence)
    kinds = [k for k, _ in got]
    assert "failure" not in kinds, [d for k, d in got if k == "failure"]
    result = next(d for k, d in got if k == "event" and d["type"] == "result")
    assert result["data"]["status"] in ("verified", "verified_partial", "needs_relaxation")
    assert result["data"]["paid_calls"] == 0 and result["data"]["cost_usd"] == 0  # not a single model call


def test_other_counts_still_use_the_recorded_answer(offline):
    got = run(offline, "columbus", "by 12:00, avoid the residential area", auto_orders=25, trucks=4)
    result = next(d for k, d in got if k == "event" and d["type"] == "result")
    assert result["data"]["paid_calls"] == 0
    problem = next(d for k, d in got if k == "event" and d["type"] == "problem")["data"]["problem"]
    assert problem["n_orders"] == 25 and problem["n_vehicles"] == 4


def test_a_sentence_of_your_own_is_refused_with_a_clear_message(offline):
    got = run(offline, "columbus", "by 13:30, avoid the park please")
    failure = next(d for k, d in got if k == "failure")
    assert "Demo mode" in failure["message"] and "MODEL_API_KEY" in failure["message"]


def test_new_areas_and_voice_need_a_key(offline):
    assert offline.post("/api/areas", json={"lat": 33.75, "lon": -84.39}).status_code == 503
    assert offline.post("/api/transcribe", content=b"RIFFxxxx").status_code == 503
