# Data sources and licenses

Only open-licensed or public-domain data is used. No screenshots from Google / Yandex / Bing; no Maxar / Planet imagery.

| File | Source | License | Notes |
|---|---|---|---|
| `data/samples/columbus.jpg` | USGS National Agriculture Imagery Program (NAIP), via the USGS National Map ImageServer (`imagery.nationalmap.gov`) | Public domain (US federal government work); credit: "Imagery: USGS NAIP" | Columbus, OH, centred on 39.95 N, -83.10 E: a 1.5 km × 1.5 km ground square (lon/lat `-83.108789,39.943262,-83.091211,39.956737`), 1536×1536 px with square pixels of 0.977 m. Requested in Web Mercator (EPSG:3857) so that the pixels are square on the ground; the box is stored as `bbox_mercator` in the sidecar JSON. Fetched with `scripts/fetch_naip.py`. |
| `data/samples/memphis.jpg` | USGS NAIP, same service | Public domain; credit: "Imagery: USGS NAIP" | Memphis, TN, centred on 35.05 N, -89.93 E; same size, projection and pixel size. |

OpenStreetMap data is © OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright). It is used in two ways. As the road graph of the product: the drivable ways of a photo's 1.5 km square are read from public Overpass API servers at run time (all asked at once, the first good answer wins, at most 40 s), cached, and shown with the attribution "Roads: © OpenStreetMap contributors (ODbL)" in the interface; `data/prewarmed/osm_<photo>.json` holds a trimmed copy (drivable ways, a few tags) for the four bundled photos, written by `scripts/prewarm_osm.py` from the Overpass API (the date of the data is in each file under `osm3s.timestamp_osm_base`), so that they run without a network; these files are a database extract under the ODbL and carry the same attribution. And as a yardstick for the evaluations (`scripts/eval_roads.py`, `eval_cities.py`, `eval_scene_osm.py`); those raw downloads are cached locally and not committed. The names and kinds of schools, hospitals, churches, town halls, libraries and large stores of a photo's square (`data/prewarmed/osm_places_<photo>.json`, the same ODbL extract and attribution) only label large buildings in the shelter list. Nominatim (OpenStreetMap) is used for the place search on the map.

## Disaster imagery

| File | Source | License | Notes |
|---|---|---|---|
| `data/samples/houston-harvey.jpg`, `data/samples/houston-harvey-b.jpg` | NOAA National Geodetic Survey, Emergency Response Imagery, Hurricane Harvey, dataset `20170830-rgb` (collected 30 Aug 2017), open data at `noaa-eri-pds.s3.amazonaws.com` and web tiles at `stormscdn.ngs.noaa.gov` | Public domain (US federal government work); credit: "Imagery: NOAA National Geodetic Survey, Emergency Response Imagery" | West Houston, TX, centred on 29.77224 N -95.69697 E and 29.77224 N -95.63556 E. Each is a 1.5 km x 1.5 km ground square assembled from web-map tiles (zoom 18) with `scripts/fetch_storm.py`, 1536x1536 px, square pixels. NOAA states the imagery is not intended for mapping, charting or navigation; it is used here for a demonstration only. |

