# OrbitRoute

An AI agent that turns a satellite image and a plain-English request into a **verified delivery plan**.

> Status: work in progress, built solo during the Meta Global AI Developer Hackathon (Push the Frontier, Indie track).

## What it does

1. **SAM 3.1** segments roads from a satellite image (tiled) and the pixels become a road graph.
2. **Muse Spark** reads the request ("40 orders, 3 trucks, by 18:00, avoid the industrial zone") and the image, and produces formal routing constraints.
3. A vehicle-routing **solver** builds the routes.
4. The **agent verifies** the plan independently, repairs violated constraints and re-solves until the plan is valid, or explains why it cannot be.

## Built so far

- Budget-guarded client for the Meta Model API (`backend/orbitroute/llm`): required token caps, global and per-run spend caps, kill switch.
- SAM 3.1 output parser that turns box-local masks into full-image masks (`backend/orbitroute/perception/sam.py`).
- NAIP tile downloader (`scripts/fetch_naip.py`).
- Tiled SAM 3.1 road segmentation with overlap and an on-disk cache (`perception/segment.py`).
- Road mask → routable graph: skeleton, junction/endpoint nodes, spur pruning, densification, gap bridging, width-based speed classes, node snapping (`perception/graph.py`), plus a debug overlay (`scripts/build_graph.py`).
- Request parsing with Muse Spark into a typed routing problem; every default the user did not state is reported as an assumption (`understanding/`).
- Zone and warehouse grounding on the image with Muse Spark vision, cached (`understanding/scene.py`).
- Delivery scenarios, graph cost matrices and a PyVRP capacitated VRP-with-time-windows solver (`routing/`); `scripts/plan.py` runs the pipeline end to end (no verification yet).

## Run the tests

```bash
uv sync
uv run pytest
```

Copy `.env.example` to `.env` and set `MODEL_API_KEY` to call the API.

## Data sources and licenses

See [data/SOURCES.md](data/SOURCES.md). Imagery: USGS NAIP (public domain). OpenStreetMap data, if used, is © OpenStreetMap contributors (ODbL).
