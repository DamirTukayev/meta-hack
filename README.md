# OrbitRoute

An AI agent that turns a satellite image and a plain-English request into a **verified delivery plan**.

> Status: work in progress, built solo during the Meta Global AI Developer Hackathon (Push the Frontier, Indie track).

## What it does

1. **SAM 3.1** segments roads from a satellite image (36 overlapping tiles, so narrow streets are found) and the pixels become a road graph.
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

- **Choose any US area on a map:** pick a place (search or presets), and the app downloads the USGS NAIP aerial image of a 1.5 km square around it. Imagery is public domain; the map search uses OpenStreetMap's Nominatim (© OpenStreetMap contributors). Dense downtowns with tall shadows give sparser road graphs; suburban and industrial areas work best.
- **See how each truck drives:** arrows show the direction of travel, stops are numbered in visiting order, a per-truck card lists the sequence with arrival times, and "Replay the drive" animates the routes.
- **Edit the plan:** drag the depot or any order, add or remove points, then Replan; the old plan stays faded until you do.
- **Trucks are a field, not a sentence:** set the number of trucks with a stepper; the one-line request only carries the deadline and what to avoid.
- **You place the points:** click the depot, click the orders and (optionally) draw a zone to avoid directly on the satellite image — the agent does not invent them unless you tick "Place orders for me"; points snap to the nearest road, and anything the agent adjusts is listed as an assumption.
- **Web app** (`frontend/`, `backend/orbitroute/api.py`): FastAPI streams the agent run as server-sent events to a React + TypeScript UI. A map with toggleable layers (road mask, graph, zones, orders, routes), plan-by-plan tabs that show the failed plan next to the repaired one, a live six-point verification checklist and the agent's log.

## Evaluation

20 fixed scenarios on two NAIP tiles plus 20 free-form request phrasings (`eval/RESULTS.md`, reproducible with `scripts/run_eval.py`). Ten scenarios use squares drawn across the road network, the way a user would draw them on the map; the rest use zones found by Muse Spark, plus four requests that are infeasible by arithmetic.

- A plain solver reported **15** plans as feasible; an independent audit found **9 of them (60%) broke a constraint** (10 scenarios entered an avoided zone, 3 missed the deadline, 2 overloaded a truck).
- The agent returned only plans that passed the same audit: **14/20 verified**; the other **6 were flagged as impossible as stated, each with a verified way out** (4 provably infeasible requests, plus 2 where the avoided residential zone cuts off most streets, so it offers to stop avoiding it).
- Of the 14 scenarios whose first plan was invalid, 8 were repaired to a verified plan automatically.
- Muse Spark parsed **20/20** free-form requests exactly (author-written phrasings; mean 4.2 s).
- Muse Spark as the repair planner chose the same actions as the deterministic policy in 6/6 runs (~$0.002 per run), so it adds readable explanations rather than different decisions.

## Prompts

The model prompts are versioned text files in `backend/orbitroute/prompts/` (`scene`, `request`, `repair`; `active.json` picks the version in use), not strings buried in code. `scripts/eval_grounding.py` compares scene-prompt versions on real runs (`eval/GROUNDING.md`). There are no human labels for land use, so it measures stability across repeated answers, overlap between zones of different kinds and a vegetation sanity check, not accuracy. Scene prompt v2 is cleaner (zones of different kinds overlap in ~0-1% of the outlined area instead of 2-3%) and about equally or slightly more stable (73% vs 68% mean agreement over 3 repeats; within noise on one of the two images), at ~25% more tokens; v1 stays active so the published evaluation numbers remain reproducible.

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
