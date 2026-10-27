import numpy as np

import orbitroute.perception.segment as seg


def test_segment_roads_unites_the_masks_of_every_tiling(monkeypatch):
    calls = []

    def fake(client, image_bytes, concept, *, n, overlap, run, use_cache):
        calls.append((concept, n, overlap))
        m = np.zeros((4, 4), bool)
        m[n % 4, :] = True  # a different row per tiling
        return m

    monkeypatch.setattr(seg, "segment_concept", fake)
    mask = seg.segment_roads(None, b"x", tilings=((1, 0), (2, 0)))
    assert calls == [("road", 1, 0), ("road", 2, 0)]
    assert mask.sum() == 8 and mask[1].all() and mask[2].all()


def test_default_tilings_are_cached_under_distinct_names():
    names = seg.cache_names(b"image")
    assert len(names) == len(seg.DEFAULT_TILINGS) == len(set(names))
    assert all(n.startswith("sam_") and "_road_" in n for n in names)
