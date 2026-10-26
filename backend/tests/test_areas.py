import io

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import orbitroute.api as api
import orbitroute.areas as areas
from orbitroute.limits import RateLimiter
from orbitroute.naip import NoImagery, bbox_around, fetch_tile, has_imagery, in_us


def jpeg(array) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(array.astype("uint8")).convert("RGB").save(buf, "JPEG")
    return buf.getvalue()


def textured(size=64):
    rng = np.random.default_rng(0)
    return jpeg(rng.integers(30, 220, (size, size, 3)))


BLACK = jpeg(np.zeros((64, 64, 3)))


def client_returning(body: bytes, content_type="image/jpeg", seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(dict(request.url.params))
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_bbox_is_a_square_of_the_requested_size_in_metres():
    w, s, e, n = bbox_around(-83.1, 39.95, 1500)
    height_m = (n - s) * 111_320
    width_m = (e - w) * 111_320 * np.cos(np.radians(39.95))
    assert height_m == pytest.approx(1500, rel=1e-3) and width_m == pytest.approx(1500, rel=1e-3)


def test_us_extent_and_imagery_detection():
    assert in_us(39.95, -83.1) and in_us(61.2, -149.9) and in_us(21.3, -157.8)
    assert not in_us(48.85, 2.35) and not in_us(35.7, 139.7)  # Paris, Tokyo
    # the extent is deliberately rough (Mexico City passes); the black-image check below catches such places
    assert in_us(19.4, -99.1)
    assert has_imagery(textured()) and not has_imagery(BLACK)


def test_fetch_tile_sends_the_expected_request_and_returns_the_picture():
    seen: list = []
    data, bbox = fetch_tile(-83.1, 39.95, px=64, client=client_returning(textured(), seen=seen))
    assert has_imagery(data) and len(bbox) == 4
    assert seen[0]["size"] == "64,64" and seen[0]["bboxSR"] == "4326" and seen[0]["f"] == "image"


def test_places_without_coverage_raise_a_clear_error():
    with pytest.raises(NoImagery, match="United States"):
        fetch_tile(2.35, 48.85, client=client_returning(textured()))  # Paris: rejected before any request
    with pytest.raises(NoImagery, match="No aerial imagery"):
        fetch_tile(-83.1, 39.95, client=client_returning(BLACK))  # USGS answers with black where it has no data
    with pytest.raises(NoImagery):
        fetch_tile(-83.1, 39.95, client=client_returning(b"<html>", content_type="text/html"))


def test_area_ids_are_stable_and_nearby_picks_share_a_tile():
    assert areas.area_id(39.95001, -83.1) == areas.area_id(39.95004, -83.1)
    assert areas.area_id(39.95, -83.1) != areas.area_id(40.5, -83.1)
    assert areas.area_id(1, 2).startswith("area-")


def test_ensure_area_downloads_once_then_reuses_the_stored_tile(tmp_path, monkeypatch):
    monkeypatch.setattr(areas, "AREAS_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(areas, "fetch_tile", lambda lon, lat, **kw: (calls.append(1) or textured(), (0.0, 0.0, 1.0, 1.0)))
    first = areas.ensure_area(39.95, -83.1)
    second = areas.ensure_area(39.95, -83.1)
    assert first.created and not second.created and len(calls) == 1
    assert (tmp_path / f"{first.name}.jpg").exists() and (tmp_path / f"{first.name}.json").exists()


def test_rate_limiter_blocks_after_the_limit_and_recovers():
    now = [0.0]
    lim = RateLimiter(2, 60, clock=lambda: now[0])
    assert lim.check("a") == 0 and lim.check("a") == 0
    assert lim.check("a") == pytest.approx(60)
    assert lim.check("b") == 0  # other keys are independent
    now[0] = 61
    assert lim.check("a") == 0


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(areas, "AREAS_DIR", tmp_path)
    monkeypatch.setattr(api, "AREAS_DIR", tmp_path)
    import orbitroute.pipeline as pipeline

    monkeypatch.setattr(pipeline, "get_sample", pipeline.get_sample)  # real lookup, but over tmp_path below
    monkeypatch.setattr("orbitroute.areas.AREAS_DIR", tmp_path)
    monkeypatch.setattr(areas, "fetch_tile", lambda lon, lat, **kw: (textured(), (lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01)))
    monkeypatch.setattr(api, "area_limit_ip", RateLimiter(2, 3600))
    monkeypatch.setattr(api, "area_limit_all", RateLimiter(50, 3600))
    return TestClient(api.app)


def test_choosing_an_area_returns_a_sample_that_can_be_used_and_viewed(web):
    r = web.post("/api/areas", json={"lat": 33.75, "lon": -84.39})
    assert r.status_code == 200
    s = r.json()
    assert s["name"].startswith("area-") and s["m_per_px"] == pytest.approx(1500 / 1536) and s["examples"]
    assert web.get(s["image"]).status_code == 200


def test_cached_areas_do_not_count_against_the_rate_limit(web):
    for _ in range(5):
        assert web.post("/api/areas", json={"lat": 33.75, "lon": -84.39}).status_code == 200


def test_new_areas_are_rate_limited_per_ip(web):
    assert web.post("/api/areas", json={"lat": 30.0, "lon": -90.0}).status_code == 200
    assert web.post("/api/areas", json={"lat": 31.0, "lon": -90.0}).status_code == 200
    r = web.post("/api/areas", json={"lat": 32.0, "lon": -90.0})
    assert r.status_code == 429 and "Try again" in r.json()["detail"]


def test_outside_the_us_and_bad_coordinates_are_rejected(web, monkeypatch):
    monkeypatch.undo()  # use the real fetch_tile, which refuses non-US points before any request
    c = TestClient(api.app)
    assert c.post("/api/areas", json={"lat": 48.85, "lon": 2.35}).status_code == 422
    assert c.post("/api/areas", json={"lat": 120, "lon": 0}).status_code == 422
