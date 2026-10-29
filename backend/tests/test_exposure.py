"""What the water touches and where a crowd could go: counted from the buildings and the water SAM finds, with the roads to a shelter
never allowed to pass through the water."""

import numpy as np
import pytest
from PIL import Image
from shapely.geometry import box

import orbitroute.perception.exposure as exposure
from orbitroute.perception.exposure import assess, look_at_building, wet_mask
from orbitroute.perception.graph import Edge, RoadGraph
from orbitroute.understanding.scene import Zone

META = {"width_px": 400, "height_px": 400, "m_per_px": 1.0, "bbox_mercator": [0.0, 0.0, 400.0, 400.0]}


def road(step=50.0):
    """A street along y = 200 from x = 50 to x = 350; node i sits at x = 50 + 50 i."""
    nodes = np.array([(50.0 + step * i, 200.0) for i in range(7)])
    return RoadGraph(nodes, [Edge(i, i + 1, step, 7.0, 36.0) for i in range(6)], 1.0)


def city():
    mask = np.zeros((400, 400), bool)
    for x, y in [(60, 60), (130, 60), (300, 60), (30, 100)]:  # four houses, 10 x 10 m
        mask[y - 5 : y + 5, x - 5 : x + 5] = True
    mask[180:220, 275:325] = True  # one large building, 50 x 40 m
    return mask


WATER = Zone("flooded", box(0, 0, 120, 130))
COMMERCIAL = Zone("commercial", box(20, 90, 45, 115))  # the house at (30, 100) stands in it


def test_only_flooded_zones_make_water():
    m = wet_mask([WATER, Zone("residential", box(200, 200, 300, 300))], (400, 400))
    assert m[60, 60] and not m[250, 250]


def test_houses_in_the_water_and_beside_it_are_counted_and_commercial_ground_is_left_out_of_the_people():
    x = assess(city(), [WATER, COMMERCIAL], road(), 0, META)
    assert (x["in_water"], x["surrounded"]) == (2, 1) and x["buildings"] >= 4  # (60,60) and (30,100) in the water, (130,60) within 15 m of it
    assert x["people_low"] == 3 and x["people_high"] == 5  # 1 home in the water x 2.5, rounded up; plus the surrounded one: 2 x 2.5  # (30,100) is in a commercial zone: not a home; the others 1 + 1 surrounded
    assert "2.5 people per building" in x["assumption"]


def test_no_water_means_nothing_to_say():
    assert assess(city(), [Zone("residential", box(0, 0, 100, 100))], road(), 0, META) is None


def test_a_large_dry_building_by_a_dry_road_is_a_candidate_with_time_and_capacity():
    x = assess(city(), [WATER], road(), 0, META)
    (s,) = x["shelters"]
    assert s["area_m2"] == 2000 and s["capacity"] == 570  # 2000 / 3.5 people on the ground floor, rounded down to tens
    assert s["minutes"] == pytest.approx(250 / 10 / 60, abs=0.2)  # 250 m at 36 km/h from the depot at node 0 to the node under it
    assert s["kind"] is None and s["name"] is None


def test_a_building_the_water_cuts_off_from_the_depot_is_not_offered():
    band = Zone("flooded", box(145, 185, 205, 215))  # the street is under water between x = 145 and x = 205
    x = assess(city(), [WATER, band], road(), 0, META)
    assert x["shelters"] == [] and x["cut_off_by_water"] == 1


def test_a_building_cut_by_the_edge_of_the_photo_is_not_a_shelter():
    mask = city()
    mask[180:220, 360:400] = True  # runs off the right edge: its size is unknown
    assert len(assess(mask, [WATER], road(), 0, META)["shelters"]) == 1


def test_a_building_beside_the_water_is_not_a_shelter():
    x = assess(city(), [WATER, Zone("flooded", box(325, 150, 360, 250))], road(), 0, META)  # water 0 m from the large building's side
    assert x["shelters"] == [] and x["wet_or_surrounded"] == 1


def test_the_model_takes_blocks_of_flats_out_and_names_what_is_left():
    image = Image.new("RGB", (400, 400), (90, 120, 90))
    asked = []

    def look(crop):
        asked.append(len(crop))
        return {"kind": "apartment_block", "confidence": 0.9}

    out = assess(city(), [WATER], road(), 0, META, image=image, look=look)
    assert out["shelters"] == [] and out["not_shelters"] == {"apartment_block": 1} and len(asked) == 1

    named = assess(city(), [WATER], road(), 0, META, image=image, look=lambda crop: {"kind": "store_or_mall", "confidence": 0.8})
    assert named["shelters"][0]["kind"] == "store_or_mall"

    unsure = assess(city(), [WATER], road(), 0, META, image=image, look=lambda crop: {"kind": "houses", "confidence": 0.3})
    assert len(unsure["shelters"]) == 1 and unsure["shelters"][0]["kind"] is None  # not sure enough to take it out or to name it
    assert unsure["shelters"][0]["guess"] == "houses"  # but the guess is kept, to be shown as one


def test_a_model_that_fails_leaves_the_building_in_the_list():
    def broken(crop):
        raise RuntimeError("no model")

    out = assess(city(), [WATER], road(), 0, META, image=Image.new("RGB", (400, 400)), look=broken)
    assert len(out["shelters"]) == 1


def test_an_osm_school_at_the_building_names_it():
    from orbitroute.naip import from_mercator

    lon, lat = from_mercator(300.0, 400.0 - 200.0)  # the building's centre in this photo's Mercator box
    out = assess(city(), [WATER], road(), 0, META, [{"kind": "school", "name": "Lincoln Elementary", "lat": lat, "lon": lon}])
    assert out["shelters"][0]["kind"] == "school" and out["shelters"][0]["name"] == "Lincoln Elementary"


class Looker:
    def __init__(self):
        self.calls = 0

    def chat_json(self, messages, name, schema, **kw):
        self.calls += 1
        return {"kind": "school", "confidence": 0.9}, None


def test_the_same_building_is_asked_about_once(monkeypatch, tmp_path):
    monkeypatch.setattr(exposure, "CACHE_DIR", tmp_path)
    looker = Looker()
    crop = exposure.building_crop(Image.new("RGB", (400, 400), (80, 90, 80)), 300, 200, 2000)
    assert look_at_building(looker, crop)["kind"] == "school" and look_at_building(looker, crop)["kind"] == "school" and looker.calls == 1
