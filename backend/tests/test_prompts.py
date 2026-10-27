import io

import numpy as np
import pytest
from PIL import Image
from shapely.geometry import box

import orbitroute.understanding.scene as scene_mod
from orbitroute import prompts
from orbitroute.eval.grounding import agreement, excess_green, greenness_by_kind, overlap_share, rasterize
from orbitroute.understanding.scene import Scene, Zone, analyze_scene


def test_every_prompt_has_an_active_version_that_exists():
    for name in ("scene", "request", "repair"):
        version, text = prompts.load(name)
        assert version in prompts.versions(name) and len(text) > 50


def test_prompt_versions_can_be_listed_and_loaded_by_name():
    assert prompts.versions("scene") == ["v1", "v2"]
    assert prompts.load("scene", "v2")[1] != prompts.load("scene", "v1")[1]
    with pytest.raises(KeyError, match="no prompt"):
        prompts.load("scene", "v99")


def test_the_prompts_still_carry_the_rules_the_code_relies_on():
    assert "never invent" in prompts.load("request")[1]
    assert "HH:MM" in prompts.load("request")[1]
    assert "exactly one action" in prompts.load("repair")[1]
    assert "0-1000" in prompts.load("scene", "v1")[1] and "0-1000" in prompts.load("scene", "v2")[1]  # the grid the code converts from


class FakeClient:
    def __init__(self):
        self.seen = []

    def chat_json(self, messages, name, schema, **kw):
        self.seen.append(messages[0]["content"][0]["text"])
        return {"zones": [{"kind": "industrial", "polygon": [{"x": 0, "y": 0}, {"x": 500, "y": 0}, {"x": 500, "y": 500}]}], "warehouses": []}, None


def png(size=64):
    buf = io.BytesIO()
    Image.fromarray(np.full((size, size, 3), 90, np.uint8)).save(buf, "JPEG")
    return buf.getvalue()


def test_the_scene_cache_is_keyed_by_prompt_version_and_the_version_reaches_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_mod, "CACHE_DIR", tmp_path)
    client, img = FakeClient(), png()
    analyze_scene(client, img, prompt_version="v1")
    analyze_scene(client, img, prompt_version="v2")
    analyze_scene(client, img, prompt_version="v2")  # served from the cache
    names = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(names) == 2 and sum(n.endswith("_v2.json") for n in names) == 1  # v1 keeps the original file name
    assert len(client.seen) == 2 and client.seen[0] == prompts.load("scene", "v1")[1] and client.seen[1] == prompts.load("scene", "v2")[1]


def scene(*zones):
    return Scene(100, 100, [Zone(k, p) for k, p in zones], [])


def test_rasterize_labels_cells_and_first_polygon_wins_on_overlap():
    s = scene(("industrial", box(0, 0, 50, 100)), ("residential", box(25, 0, 100, 100)))
    m = rasterize(s, grid=10)
    assert (m[:, 0] == 1).all() and (m[:, 9] == 3).all()  # industrial = 1, residential = 3
    assert (m[:, 3] == 1).all()  # cells in both polygons keep the first one


def test_overlap_share_counts_only_different_kinds():
    same = scene(("industrial", box(0, 0, 60, 100)), ("industrial", box(40, 0, 100, 100)))
    different = scene(("industrial", box(0, 0, 60, 100)), ("residential", box(40, 0, 100, 100)))
    assert overlap_share(same, grid=20) == 0.0
    assert overlap_share(different, grid=20) == pytest.approx(0.2, abs=0.01)  # 20 of 100 units are covered twice


def test_agreement_is_measured_over_the_union_of_outlined_cells():
    a = np.array([[1, 1, 0, 0]])
    b = np.array([[1, 2, 2, 0]])
    assert agreement(a, b) == pytest.approx(1 / 3)  # cells 0, 1, 2 are outlined by someone; only cell 0 matches
    assert agreement(np.zeros((2, 2), int), np.zeros((2, 2), int)) == 1.0


def test_vegetation_index_is_higher_for_green_cells():
    arr = np.zeros((20, 20, 3), np.uint8)
    arr[:, :10] = (30, 200, 30)  # green left half
    arr[:, 10:] = (140, 140, 140)  # grey right half
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    exg = excess_green(buf.getvalue(), grid=20)
    labels = np.zeros((20, 20), np.int8)
    labels[:, :10], labels[:, 10:] = 4, 1  # park_forest left, industrial right
    g = greenness_by_kind(labels, exg)
    assert g["park_forest"] > 100 and abs(g["industrial"]) < 5


def test_committed_prewarmed_answers_cover_the_bundled_samples():
    import hashlib

    from orbitroute.config import PREWARMED_DIR, ROOT, resolve_cached
    from orbitroute.perception.segment import cache_names

    for jpg in (ROOT / "data" / "samples").glob("*.jpg"):
        h = hashlib.sha256(jpg.read_bytes()).hexdigest()[:16]
        for name in (*cache_names(jpg.read_bytes()), f"scene_{h}.json"):
            assert (PREWARMED_DIR / name).exists(), f"{name} is not pre-warmed for {jpg.stem}"


def test_resolve_cached_prefers_the_live_cache_then_the_shipped_copy(tmp_path, monkeypatch):
    import orbitroute.config as cfg

    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "a.json").write_text("{}")
    monkeypatch.setattr(cfg, "PREWARMED_DIR", shipped)
    live = tmp_path / "live"
    live.mkdir()
    assert cfg.resolve_cached(live, "a.json") == shipped / "a.json"  # only shipped has it
    (live / "a.json").write_text("{}")
    assert cfg.resolve_cached(live, "a.json") == live / "a.json"  # live wins
    assert cfg.resolve_cached(live, "new.json") == live / "new.json"  # to be written to the live cache
