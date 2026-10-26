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
- Delivery scenarios, graph cost matrices and a PyVRP capacitated VRP-with-time-windows solver (`routing/`); `scripts/plan.py` runs the pipeline end to end without verification.
- **The agent** (`agent/`, `verifier/`): an independent verifier re-simulates every route on the road graph (coverage, fleet, capacity, real-road paths, deadline, avoided zones). A bounded loop repairs violations: Muse Spark picks the repair action (forbid the violating road segments, forbid the whole zone, exclude unreachable orders, search longer, or compute the smallest relaxation); a deterministic policy is the fallback. Every relaxation option it proposes comes with a plan that passes verification. Run it with `scripts/agent.py`.

- **Web app** (`frontend/`, `backend/orbitroute/api.py`): FastAPI streams the agent run as server-sent events to a React + TypeScript UI. A map with toggleable layers (road mask, graph, zones, orders, routes), plan-by-plan tabs that show the failed plan next to the repaired one, a live six-point verification checklist and the agent's log.

## Evaluation

20 fixed scenarios on two NAIP tiles, plus 20 free-form request phrasings (`eval/RESULTS.md`, reproducible with `scripts/run_eval.py`):

- A plain solver reported **15** plans as feasible; an independent audit found **6 of them (40%) broke a constraint** (7 scenarios entered an avoided zone, 3 missed the deadline, 2 overloaded a truck).
- The agent returned only plans that passed the same audit: **15/20 verified**, the other **5 flagged as infeasible as stated, each with a verified relaxation** (all 4 provably infeasible requests were caught).
- Muse Spark parsed **20/20** free-form requests exactly (author-written phrasings; mean 4.2 s).
- Muse Spark as the repair planner chose the same actions as the deterministic policy in 6/6 runs (~$0.003 per run).

## Open-weight path

Text reasoning (request parsing and repair decisions) can run on the open-weight Muse Spark Open served by Baseten: set `REASONING_PROVIDER=baseten` and `BASETEN_API_KEY` in `.env`. SAM 3.1 and the vision step stay on the Meta Model API.

## Run the app locally

```bash
uv sync
cp .env.example .env              # then set MODEL_API_KEY
uv run uvicorn orbitroute.api:app --app-dir backend --port 8000
# in another terminal, for development with hot reload:
cd frontend && npm install && npm run dev      # http://localhost:5173
# or build once and let FastAPI serve it at http://localhost:8000:
cd frontend && npm run build
```

## Run the tests

```bash
uv sync
uv run pytest
```

Copy `.env.example` to `.env` and set `MODEL_API_KEY` to call the API.

## Data sources and licenses

See [data/SOURCES.md](data/SOURCES.md). Imagery: USGS NAIP (public domain). OpenStreetMap data, if used, is © OpenStreetMap contributors (ODbL).
