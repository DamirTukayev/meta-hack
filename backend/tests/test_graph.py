import networkx as nx
import numpy as np

from orbitroute.perception.graph import build_road_graph, speed_for_width

M_PER_PX = 1.0


def band_mask(h=300, w=300, horizontal=(), vertical=(), thick=10):
    m = np.zeros((h, w), bool)
    for y, x0, x1 in horizontal:
        m[y - thick // 2 : y + thick // 2, x0:x1] = True
    for x, y0, y1 in vertical:
        m[y0:y1, x - thick // 2 : x + thick // 2] = True
    return m


def test_cross_becomes_one_connected_component_with_a_junction():
    mask = band_mask(horizontal=[(150, 20, 280)], vertical=[(150, 20, 280)])
    g = build_road_graph(mask, M_PER_PX)
    nxg = g.to_networkx()
    assert nx.is_connected(nxg)
    assert max(d for _, d in nxg.degree()) >= 3  # the crossing
    assert g.stats["road_km"] * 1000 > 400  # two crossing 260 px bands


def test_road_length_is_close_to_true_length():
    mask = band_mask(horizontal=[(150, 20, 280)])
    g = build_road_graph(mask, M_PER_PX)
    total = sum(e.length_m for e in g.edges)
    assert 220 < total < 280  # a 260 px band, minus skeleton end shrinkage


def test_small_gap_is_bridged_but_large_gap_is_not():
    near = band_mask(horizontal=[(150, 20, 130), (150, 150, 280)])  # 20 px gap
    far = band_mask(horizontal=[(150, 20, 100), (150, 230, 290)], w=320)  # 130 px gap
    g_near = build_road_graph(near, M_PER_PX)
    assert nx.is_connected(g_near.to_networkx())
    assert g_near.stats["bridges"] == 1
    assert any(e.bridge for e in g_near.edges)

    g_far = build_road_graph(far, M_PER_PX)
    assert g_far.stats["bridges"] == 0
    assert g_far.stats["components_before_keep"] == 2  # only the larger piece is kept


def test_short_spur_is_pruned():
    mask = band_mask(horizontal=[(150, 20, 280)], vertical=[(150, 141, 150)], thick=10)  # stub of ~9 px
    g = build_road_graph(mask, M_PER_PX)
    xs = g.nodes[:, 1]
    assert xs.max() - xs.min() < 15  # no node sticks out of the horizontal road


def test_nearest_node_snaps_to_road():
    mask = band_mask(horizontal=[(150, 20, 280)])
    g = build_road_graph(mask, M_PER_PX)
    node, dist_m = g.nearest_node(150, 160)
    assert dist_m < 20
    assert abs(g.nodes[node][1] - 150) < 3


def test_wider_roads_are_faster():
    assert speed_for_width(16) > speed_for_width(10) > speed_for_width(5)


def test_tiles_cover_the_whole_image_with_overlap():
    from orbitroute.perception.segment import tile_windows

    wins = tile_windows(1536, 1536, 6, 48)
    assert len(wins) == 36
    covered = np.zeros((1536, 1536), int)
    for l, t, r, b in wins:
        covered[t:b, l:r] += 1
    assert covered.min() >= 1 and covered.max() >= 2  # no gaps, and neighbours overlap
    assert all(r - l <= 256 + 96 and b - t <= 256 + 96 for l, t, r, b in wins)


def test_gap_windows_stay_inside_the_image_and_cover_the_link():
    import numpy as np

    from orbitroute.perception.gaps import MIN_WINDOW_PX, _window

    for a, b in [((10, 10), (90, 40)), ((1500, 1500), (1450, 1520)), ((700, 100), (700, 210))]:
        left, top, right, bottom = _window(np.array(a, float), np.array(b, float), 1536, 1536)
        assert 0 <= left < right <= 1536 and 0 <= top < bottom <= 1536
        assert right - left >= MIN_WINDOW_PX and bottom - top >= MIN_WINDOW_PX
        assert all(left <= p[0] <= right and top <= p[1] <= bottom for p in (a, b))
