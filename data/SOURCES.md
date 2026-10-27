# Data sources and licenses

Only open-licensed or public-domain data is used. No screenshots from Google / Yandex / Bing; no Maxar / Planet imagery.

| File | Source | License | Notes |
|---|---|---|---|
| `data/samples/columbus.jpg` | USGS National Agriculture Imagery Program (NAIP), via the USGS National Map ImageServer (`imagery.nationalmap.gov`) | Public domain (US federal government work); credit: "Imagery: USGS NAIP" | Columbus, OH, centred on 39.95 N, -83.10 E: a 1.5 km × 1.5 km ground square (lon/lat `-83.108789,39.943262,-83.091211,39.956737`), 1536×1536 px with square pixels of 0.977 m. Requested in Web Mercator (EPSG:3857) so that the pixels are square on the ground; the box is stored as `bbox_mercator` in the sidecar JSON. Fetched with `scripts/fetch_naip.py`. |
| `data/samples/memphis.jpg` | USGS NAIP, same service | Public domain; credit: "Imagery: USGS NAIP" | Memphis, TN, centred on 35.05 N, -89.93 E; same size, projection and pixel size. |

OpenStreetMap data is © OpenStreetMap contributors, ODbL. It is used only as a yardstick in `scripts/eval_roads.py` (results in `eval/ROADS.md`); the raw download is cached locally and not committed, and no OSM data is part of the product.
