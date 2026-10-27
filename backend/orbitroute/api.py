"""Web API: sample images, and a server-sent-events stream of one agent run."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from orbitroute.agent.events import Event
from orbitroute.areas import AREAS_DIR, area_id, ensure_area
from orbitroute.config import ROOT, Settings
from orbitroute.custom import CustomInputs, PlacementError
from orbitroute.llm.budget import BudgetExceeded, BudgetGuard
from orbitroute.limits import RateLimiter
from orbitroute.llm.client import ApiError, FailoverClient, MetaClient, guard_for
from orbitroute.naip import NoImagery
from orbitroute.pipeline import get_sample, list_samples, run_pipeline

# Orders are clicked on the map and trucks have their own field, so the sentences describe only the time and what to avoid.
EXAMPLES = {
    "columbus": [
        "by 12:00, avoid the residential area",
        "by 12:00, avoid the industrial zone",
        "by 09:00, avoid the residential area",
    ],
    "memphis": ["by 12:00, avoid the industrial zone", "by 11:00, avoid the residential area"],
}
LABELS = {"columbus": "Columbus, OH — mixed commercial / residential", "memphis": "Memphis, TN — logistics district"}
MAX_REQUEST_CHARS = 400
settings = Settings.load()
log = logging.getLogger("orbitroute")
AREA_EXAMPLES = ["by 12:00, avoid the industrial zone", "by 12:00, avoid the residential area"]
# New map areas cost a download plus (on first use) about $0.45 of SAM calls (two tilings), so they are rate limited.
area_limit_ip = RateLimiter(max_events=4, window_s=3600)
area_limit_all = RateLimiter(max_events=12, window_s=3600)
# Every run costs model calls (about $0.006-0.02 on a bundled sample, about $0.5 on a new area), so runs are limited too.
run_limit_ip = RateLimiter(max_events=settings.run_limit_per_ip_hour, window_s=3600)
run_limit_day = RateLimiter(max_events=settings.run_limit_per_day, window_s=86400)
asr_limit_ip = RateLimiter(max_events=30, window_s=3600)
asr_limit_all = RateLimiter(max_events=400, window_s=86400)
MAX_AUDIO_BYTES = 2_000_000  # about 60 s of 16 kHz mono 16-bit PCM
_active = {"n": 0}
_active_lock = threading.Lock()

guard = BudgetGuard(settings.budget_state_path, settings.budget_hard_cap_usd, settings.paid_calls_enabled)
_client: MetaClient | None = None


_text_client = None


def client_ip(request: Request) -> str:
    """The caller's address. Behind a reverse proxy (TRUST_PROXY=1) the first X-Forwarded-For entry is used."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_client() -> MetaClient:
    global _client
    if _client is None:
        _client = MetaClient(settings, guard)
    return _client


def get_text_client() -> MetaClient:
    """Client for the text-reasoning steps: Muse Spark Open on Baseten when configured, else the Meta API."""
    global _text_client
    if settings.reasoning_provider != "baseten":
        return get_client()
    if _text_client is None:  # open-weight first, the Meta API as a safety net
        _text_client = FailoverClient(MetaClient(settings, guard_for(settings, "baseten"), provider="baseten"), get_client())
    return _text_client


app = FastAPI(title="OrbitRoute")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "paid_calls_enabled": guard.paid_calls_enabled, "spent_usd": round(guard.total_spent(), 4), "reasoning_provider": settings.reasoning_provider}


def sample_dict(s) -> dict:
    return {
        "name": s.name,
        "label": s.meta.get("label") or LABELS.get(s.name, s.name),
        "width": s.meta["width_px"],
        "height": s.meta["height_px"],
        "m_per_px": s.meta["m_per_px"],
        "examples": EXAMPLES.get(s.name, AREA_EXAMPLES),
        "image": f"/api/samples/{s.name}/image",
        "credit": "Imagery: USGS NAIP (public domain)",
    }


@app.post("/api/transcribe")
async def transcribe(request: Request) -> dict:
    """Speech to text for the request box: the browser records a short WAV, Muse Voice Transcribe turns it into text."""
    if not guard.paid_calls_enabled:
        raise HTTPException(503, "The demo is paused right now. Please try again later.")
    wait = max(asr_limit_ip.check(client_ip(request)), asr_limit_all.check("all"))
    if wait:
        raise HTTPException(429, f"Too many voice requests right now. Try again in {int(wait // 60) + 1} min.", headers={"Retry-After": str(int(wait) + 1)})
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio received.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "The recording is too long (limit about 60 seconds).")
    loop = asyncio.get_running_loop()
    try:
        text = await loop.run_in_executor(None, lambda: get_client().transcribe(audio))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except BudgetExceeded as exc:
        raise HTTPException(503, f"Budget guard: {exc}")
    except Exception:
        raise HTTPException(502, "Speech recognition did not answer. Please type the request instead.")
    return {"text": text}


@app.get("/api/usage")
def usage() -> dict:
    """Estimated spend per provider from our own counters. The providers' dashboards remain the source of truth."""
    return {"meta": guard.summary(), "baseten": guard_for(settings, "baseten").summary(), "reasoning_provider": settings.reasoning_provider}


@app.get("/api/samples")
def samples() -> list[dict]:
    return [sample_dict(s) for s in list_samples()]


class AreaRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


@app.post("/api/areas")
def choose_area(body: AreaRequest, request: Request) -> dict:
    """Fetch (once) the aerial image around a point picked on the map and register it as a sample."""
    name = area_id(body.lat, body.lon)
    if not (AREAS_DIR / f"{name}.jpg").exists():  # only new downloads count against the limits
        ip = request.client.host if request.client else "unknown"
        wait = max(area_limit_ip.check(ip), area_limit_all.check("all"))
        if wait:
            raise HTTPException(429, f"Too many new areas right now. Try again in {int(wait // 60) + 1} min, or pick one of the ready-made areas.")
    try:
        area = ensure_area(body.lat, body.lon)
    except NoImagery as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        raise HTTPException(502, "The imagery service did not answer. Try again in a moment.")
    return sample_dict(get_sample(area.name))


@app.get("/api/samples/{name}/image")
def sample_image(name: str) -> Response:
    try:
        return FileResponse(get_sample(name).path, media_type="image/jpeg")
    except KeyError:
        raise HTTPException(404, "unknown sample")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class RunRequest(BaseModel):
    sample: str
    request: str = Field(max_length=MAX_REQUEST_CHARS)
    seed: int = 0
    decider: Literal["model", "policy"] = "model"
    custom: CustomInputs | None = None
    auto_orders: int | None = Field(default=None, ge=1, le=100)  # "place the orders for me": how many
    trucks: int | None = Field(default=None, ge=1, le=30)  # the Trucks field; overrides the text


@app.post("/api/run")
async def run(body: RunRequest, request: Request) -> StreamingResponse:
    try:
        smp = get_sample(body.sample)
    except KeyError:
        raise HTTPException(404, "unknown sample")
    if not guard.paid_calls_enabled:
        raise HTTPException(503, "The demo is paused right now. Please try again later.")
    wait = max(run_limit_ip.check(client_ip(request)), run_limit_day.check("all"))
    if wait:
        raise HTTPException(429, f"Too many runs right now. Try again in {int(wait // 60) + 1} min.", headers={"Retry-After": str(int(wait) + 1)})
    with _active_lock:
        if _active["n"] >= settings.max_concurrent_runs:
            raise HTTPException(429, "The agent is busy with other runs. Try again in a few seconds.", headers={"Retry-After": "10"})
        _active["n"] += 1
    request, seed, decider, custom, auto_orders, trucks = body.request, body.seed, body.decider, body.custom, body.auto_orders, body.trucks
    q: queue.Queue = queue.Queue()
    done = object()

    def emit(e: Event) -> None:
        q.put(("event", {"type": e.type, "message": e.message, "data": e.data, "t": round(e.t, 3)}))

    def work() -> None:
        try:
            run_pipeline(
                smp, request, client=get_client(), text_client=get_text_client(), guard=guard, run_cap_usd=settings.run_cap_usd,
                seed=seed, use_model_decider=decider == "model", custom=custom, auto_orders=auto_orders, trucks=trucks, emit=emit,
            )
        except BudgetExceeded as exc:
            q.put(("failure", {"message": f"Budget guard: {exc}"}))
        except PlacementError as exc:
            q.put(("failure", {"message": str(exc), "point": {"kind": exc.kind, "index": exc.index}}))
        except (ApiError, ValueError, RuntimeError) as exc:
            q.put(("failure", {"message": str(exc)}))
        except Exception as exc:  # never leave the page waiting on a silent crash
            log.exception("run failed")
            q.put(("failure", {"message": f"Unexpected error ({type(exc).__name__}). The run was stopped; please try again."}))
        finally:
            with _active_lock:
                _active["n"] -= 1
            q.put(done)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is done:
                yield _sse("done", {})
                return
            kind, payload = item
            yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
