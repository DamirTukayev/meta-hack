"""Web API: sample images, and a server-sent-events stream of one agent run."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from orbitroute.agent.events import Event
from orbitroute.config import ROOT, Settings
from orbitroute.llm.budget import BudgetExceeded, BudgetGuard
from orbitroute.llm.client import ApiError, MetaClient
from orbitroute.pipeline import get_sample, list_samples, run_pipeline

EXAMPLES = {
    "columbus": [
        "30 orders, 3 trucks, by 12:00, avoid the residential area",
        "40 orders, 3 trucks, by 12:00, avoid the industrial zone",
        "30 orders, 1 truck, by 09:00, avoid the residential area",
    ],
    "memphis": ["30 orders, 3 trucks, by 12:00, avoid the industrial zone"],
}
LABELS = {"columbus": "Columbus, OH — mixed commercial / residential", "memphis": "Memphis, TN — logistics district"}
MAX_REQUEST_CHARS = 400

settings = Settings.load()
guard = BudgetGuard(settings.budget_state_path, settings.budget_hard_cap_usd, settings.paid_calls_enabled)
_client: MetaClient | None = None


_text_client: MetaClient | None = None


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
    if _text_client is None:
        _text_client = MetaClient(settings, guard, provider="baseten")
    return _text_client


app = FastAPI(title="OrbitRoute")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "paid_calls_enabled": guard.paid_calls_enabled, "spent_usd": round(guard.total_spent(), 4), "reasoning_provider": settings.reasoning_provider}


@app.get("/api/samples")
def samples() -> list[dict]:
    return [
        {
            "name": s.name,
            "label": LABELS.get(s.name, s.name),
            "width": s.meta["width_px"],
            "height": s.meta["height_px"],
            "m_per_px": s.meta["m_per_px"],
            "examples": EXAMPLES.get(s.name, []),
            "image": f"/api/samples/{s.name}/image",
            "credit": "Imagery: USGS NAIP (public domain)",
        }
        for s in list_samples()
    ]


@app.get("/api/samples/{name}/image")
def sample_image(name: str) -> Response:
    try:
        return FileResponse(get_sample(name).path, media_type="image/jpeg")
    except KeyError:
        raise HTTPException(404, "unknown sample")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/run")
async def run(
    sample: str,
    request: str = Query(max_length=MAX_REQUEST_CHARS),
    seed: int = 0,
    decider: str = "model",
) -> StreamingResponse:
    try:
        smp = get_sample(sample)
    except KeyError:
        raise HTTPException(404, "unknown sample")
    q: queue.Queue = queue.Queue()
    done = object()

    def emit(e: Event) -> None:
        q.put(("event", {"type": e.type, "message": e.message, "data": e.data, "t": round(e.t, 3)}))

    def work() -> None:
        try:
            run_pipeline(
                smp, request, client=get_client(), text_client=get_text_client(), guard=guard, run_cap_usd=settings.run_cap_usd,
                seed=seed, use_model_decider=decider == "model", emit=emit,
            )
        except BudgetExceeded as exc:
            q.put(("failure", {"message": f"Budget guard: {exc}"}))
        except (ApiError, ValueError, RuntimeError) as exc:
            q.put(("failure", {"message": str(exc)}))
        finally:
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
