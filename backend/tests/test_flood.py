import io

import httpx
import numpy as np
import pytest
from PIL import Image

import orbitroute.perception.flood as flood
from orbitroute.naip import NoImagery
from orbitroute.perception.flood import flood_cache_names, flood_zones, segment_floods
from orbitroute.storm import fetch_storm_tile
from orbitroute.understanding.constraints import ParsedRequest, resolve


def blob(shape=(400, 400), boxes=()):
    m = np.zeros(shape, bool)
    for y0, y1, x0, x1 in boxes:
        m[y0:y1, x0:x1] = True
    return m


def test_a_patch_of_water_becomes_a_slightly_enlarged_zone():
    zones = flood_zones(blob(boxes=[(100, 200, 100, 250)]), m_per_px=1.0, margin_m=6)
    assert len(zones) == 1 and zones[0].kind == "flooded"
    minx, miny, maxx, maxy = zones[0].polygon.bounds
    assert minx == pytest.approx(94, abs=2) and maxx == pytest.approx(256, abs=2)  # 100..250 plus the margin
    assert miny == pytest.approx(94, abs=2) and maxy == pytest.approx(206, abs=2)
    assert zones[0].contains(150, 150) and not zones[0].contains(50, 50)


def test_puddles_are_ignored_and_dry_spots_inside_the_flood_are_filled():
    m = blob(boxes=[(100, 200, 100, 250), (300, 304, 300, 304)])  # one real flood, one 16 m2 puddle
    m[140:150, 150:160] = False  # a dry spot inside the flood
    zones = flood_zones(m, m_per_px=1.0)
    assert len(zones) == 1 and zones[0].contains(155, 145)


def test_separate_patches_are_separate_zones_and_pixel_size_scales_the_area_limit():
    m = blob(boxes=[(20, 80, 20, 80), (200, 260, 200, 260)])
    assert len(flood_zones(m, m_per_px=1.0)) == 2
    assert flood_zones(m, m_per_px=4.0) != []  # 60x60 px of 4 m is a lot of water
    assert flood_zones(blob(boxes=[(20, 30, 20, 30)]), m_per_px=1.0) == []  # 100 m2 is below the 250 m2 limit


def test_segment_floods_unites_the_concepts_and_names_their_caches(monkeypatch):
    seen = []

    def fake(client, image_bytes, concept, *, n, overlap, run, use_cache):
        seen.append((concept, n, overlap))
        m = np.zeros((4, 4), bool)
        m[len(seen) - 1, :] = True
        return m

    monkeypatch.setattr(flood, "segment_concept", fake)
    mask = segment_floods(None, b"x")
    assert [s[0] for s in seen] == list(flood.FLOOD_CONCEPTS) and mask.sum() == 8
    names = flood_cache_names(b"x")
    assert len(names) == len(flood.FLOOD_CONCEPTS) and all(n.startswith("sam_") for n in names)


def jpeg(size=256):
    buf = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(30, 220, (size, size, 3), dtype=np.uint8)).save(buf, "JPEG")
    return buf.getvalue()


def test_storm_tiles_are_assembled_into_a_square_picture():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=jpeg(), headers={"content-type": "binary/octet-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    data, bbox = fetch_storm_tile("20170830-rgb", -95.69, 29.77, span_m=300, px=200, client=client)
    assert Image.open(io.BytesIO(data)).size == (200, 200) and len(bbox) == 4
    assert seen and all(p.startswith("/20170830-rgb/18/") for p in seen)


def test_missing_storm_imagery_is_reported_clearly():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302, content=b"")))
    with pytest.raises(NoImagery, match="no photo"):
        fetch_storm_tile("20170830a-rgb", -95.69, 29.77, span_m=300, px=100, client=client)


def test_flooded_is_a_valid_thing_to_avoid():
    p = resolve(ParsedRequest(n_orders=5, n_vehicles=2, deadline="14:00", avoid_zone_kinds=["flooded"]))
    assert p.avoid_zone_kinds == ["flooded"]
