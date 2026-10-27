# OrbitRoute

An AI agent that turns a satellite image and a plain-English request into a **verified delivery plan**.

> Status: work in progress, built solo during the Meta Global AI Developer Hackathon (Push the Frontier, Indie track).

## What it does

1. **SAM 3.1** segments roads from a satellite image (two overlapping tilings, 6x6 and 12x12, united, so narrow streets are found) and the pixels become a road graph.
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
- **Speak the request:** a microphone button records a few seconds, the browser encodes a 16 kHz WAV, and Muse Voice Transcribe turns it into the request text (about $0.0002 per clip). Limited per IP and per day.
- **Edit the plan:** drag the depot or any order, add or remove points, then Replan; the old plan stays faded until you do.
- **Trucks are a field, not a sentence:** set the number of trucks with a stepper; the one-line request only carries the deadline and what to avoid.
- **You place the points:** click the depot, click the orders and (optionally) draw a zone to avoid directly on the satellite image — the agent does not invent them unless you tick "Place orders for me"; points snap to the nearest road, and anything the agent adjusts is listed as an assumption.
- **Web app** (`frontend/`, `backend/orbitroute/api.py`): FastAPI streams the agent run as server-sent events to a React + TypeScript UI. A map with toggleable layers (road mask, graph, zones, orders, routes), plan-by-plan tabs that show the failed plan next to the repaired one, a live six-point verification checklist and the agent's log.

## How accurate is the road graph?

The agent routes only on the roads SAM 3.1 finds, so we measured them against OpenStreetMap on both bundled tiles (`eval/ROADS.md`, `scripts/eval_roads.py`; OSM is used only as a yardstick, © OpenStreetMap contributors, ODbL). Within 15 m: **86-91% of the graph lies on a real mapped road**, and the graph covers **73-86% of the named streets** (48-53% when every service road is counted; parking aisles and driveways are mostly invisible at this resolution). So the graph is trustworthy but incomplete: it finds the street network, not every alley. Two tiles only, and OSM is itself incomplete.

How it got there (all measured with the same script, `eval/ROADS.md`): one 6x6 tiling found 66% of the named streets on average; other SAM prompts ("street", "driveway", "alley", "paved road") added nothing, because "road" is the only concept SAM answers well; finer tilings find different streets, so the union of a 6x6 and a 12x12 tiling reaches 77% at the same precision, and bridging gaps up to 110 px (instead of 70) adds a little more. The price is a new map area costing about $0.45 of SAM calls instead of $0.09, so new areas are rate limited more tightly; the two bundled samples ship pre-computed.

Imagery is requested in Web Mercator so that pixels are square on the ground (0.977 m each); an earlier version asked for a box in degrees, which the imagery service silently stretched by about 30% north-south, so lengths along north-south roads were underestimated. Found by comparing the graph with OSM, fixed, and every number below was recomputed afterwards.

## Evaluation

46 fixed scenarios on two NAIP tiles plus 20 free-form request phrasings (`eval/RESULTS.md`, reproducible with `scripts/run_eval.py`). Eighteen scenarios draw a square zone at each point of a fixed 3x3 grid and place the orders only where a legal route can reach them; eighteen use the same squares but place the orders anywhere, the way a user clicking freely on the map does (some are then cut off by the zone); the rest use zones found by Muse Spark plus four requests that are infeasible by arithmetic. The grid was fixed before running, and every square is reported.

- How often the plain solver's first plan breaks a rule depends on how the orders are placed: **3 of 18** when orders are placed only where a legal route reaches them, but **17 of 18** when they are placed freely. Across all 46 scenarios the solver reported 41 plans as feasible and an independent audit found **21 of them (51%) broke a constraint**, all of them avoided-zone violations. Counting every first-pass plan, the violations were zones 22, deadline 3, capacity 2.
- The agent returned only plans that passed the same audit. Of the 26 scenarios whose first plan was invalid, **15 ended verified automatically** (4 by re-routing around the zone; 11 by leaving 1-5 cut-off orders out, each listed with its reason, never silently dropped) and **11 were flagged as impossible as stated, each with a verified way out** (the 4 provably infeasible requests among them).
- Muse Spark parsed **20/20** free-form requests exactly (author-written phrasings; mean 2.3 s with prompt v2).
- Muse Spark as the repair planner chose the same actions as the deterministic policy in 6/6 runs (about $0.004 per run), so it adds readable explanations rather than different decisions.
- Caveats: the "audit" is the same verifier code the agent uses, applied to the plain solver's plan; a second independent implementation is still to do. An earlier version of this suite, run before the imagery geometry fix, reported 60% invalid plans; that number depended on where its squares happened to fall on a distorted image and is not reproduced here.

## Public demo safeguards

Runs are limited per IP (20/hour) and per day (300), at most 3 run at once, new map areas are limited separately, voice clips are capped at 60 s, and `DEMO_PAID_CALLS_ENABLED=false` pauses everything that costs money. The two bundled sample images ship with pre-computed SAM and zone answers (`data/prewarmed/`), so a fresh server pays nothing for them. Every provider has its own spend counter and cap (`/api/usage`).

## Prompts

The model prompts are versioned text files in `backend/orbitroute/prompts/` (`scene`, `request`, `repair`; `active.json` picks the version in use), not strings buried in code. `scripts/eval_grounding.py` compares scene-prompt versions on real runs (`eval/GROUNDING.md`). There are no human labels for land use, so it measures stability across repeated answers, overlap between zones of different kinds and a vegetation sanity check, not accuracy. Scene prompt v2 is more stable and cleaner on the current images: 76% vs 65% mean agreement over 3 repeats (78% / 74% against 70% / 60% on the two tiles), and zones of different kinds overlap in ~0-2% of the outlined area instead of 2-6%, at ~25% more tokens. v1 is still the active version because every number in the evaluation above was produced with it; switching to v2 means regenerating the scene answers and rerunning the suite.

## Open-weight path

The text-reasoning steps (turning the request into constraints, choosing the repair action) can run on the open-weight **Muse Spark Open**, served by Baseten: set `REASONING_PROVIDER=baseten` and `BASETEN_API_KEY` in `.env`. SAM 3.1 and the vision step stay on the Meta Model API. If Baseten fails or its separate budget runs out, the call falls back to the Meta API.

Measured on the 20 free-form requests (`eval/RESULTS.md`): with the first request prompt Muse Spark Open parsed 11/20 exactly (it defaulted to "shortest distance" and misread a few fields); after the field rules were spelled out in prompt v2 it parses **20/20**, in about 2.6 s per request, the same as Muse Spark 1.3. Its repair decisions were checked on four scenarios and matched the deterministic policy in all of them.

## Design

The interface uses an "Instrument" design system: black canvas, amber accent, hairline borders, square corners and a self-hosted monospace face (JetBrains Mono, OFL), so the satellite imagery and the routes carry the colour.

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
