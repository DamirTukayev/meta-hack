import json
from pathlib import Path

from orbitroute.perception.sam import parse_instances, response_text

FIXTURE = Path(__file__).parent / "fixtures" / "sam_road_response.json"


def test_parse_real_sam_response_into_full_image_mask():
    text = response_text(json.loads(FIXTURE.read_text()))
    instances = parse_instances(text, "road", width=1536, height=1536)

    assert len(instances) == 1
    road = instances[0]
    assert road.concept == "road"
    assert road.confidence == 0.507692277431488
    assert road.box == (0, 397, 1492, 504)  # half-open: the parser adds 1 to x2/y2
    assert road.mask.shape == (1536, 1536)
    # Mask is box-local: nothing outside the (rounded) box may be set.
    ys, xs = road.mask.nonzero()
    assert ys.min() >= 397 and ys.max() <= 504 and xs.min() >= 0 and xs.max() <= 1492
    assert road.mask.sum() > 10_000


def test_empty_output_means_no_instances():
    assert parse_instances("", "road", width=100, height=100) == []
