"""OrbitRoute on Modal: the FastAPI app and the built interface as one web function.

Setup, once:
    uv export --no-hashes --no-dev --no-emit-project --frozen | grep -v '^#' > deploy/requirements-modal.txt
    (cd frontend && npm run build)
    scripts/make_deploy_secret.sh                               # the provider keys from .env + an access code + low caps of their own (prints the code)
Check the image and the volume without publishing anything (needs no secret):
    ORBITROUTE_SELFTEST=1 modal run modal_app.py
Publish (gives a public URL; spends credits only while it serves requests):
    modal deploy modal_app.py

One container serves everything (`max_containers=1`): the rate limiters live in memory and the spend counter is a file, so
a single process keeps both exact. What the app learns (spend counters, model answers, downloaded map areas) lives on the
volume `orbitroute-state`, so a restart does not reset the budget guard.
"""

import os

import modal

STATE = "/state"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("deploy/requirements-modal.txt")
    .env(
        {
            "ORBITROUTE_STATE_DIR": STATE,
            "BUDGET_STATE_PATH": f"{STATE}/budget_state.json",
            "BASETEN_BUDGET_STATE_PATH": f"{STATE}/budget_state_baseten.json",
            "MODAL_BUDGET_STATE_PATH": f"{STATE}/budget_state_modal.json",
            "TRUST_PROXY": "1",  # the caller's address is the last entry of X-Forwarded-For (one proxy in front)
            "TRUSTED_PROXY_HOPS": "1",
            "PYTHONPATH": "/app/backend",
        }
    )
    .add_local_dir("backend", "/app/backend", ignore=["**/__pycache__", "**/tests"])
    .add_local_dir("frontend/dist", "/app/frontend/dist")
    .add_local_dir("data/samples", "/app/data/samples")
    .add_local_dir("data/prewarmed", "/app/data/prewarmed")
)
state = modal.Volume.from_name("orbitroute-state", create_if_missing=True)
app = modal.App("orbitroute", image=image)


def _commit_in_background() -> None:
    """Volume writes become durable on commit; do it often, so a restart loses at most a few seconds of the spend counter."""
    import threading
    import time

    def loop() -> None:
        while True:
            time.sleep(15)
            try:
                state.commit()
            except Exception:  # a failed commit is retried on the next round
                pass

    threading.Thread(target=loop, daemon=True).start()


# The self-test runs without keys: with ORBITROUTE_SELFTEST set, the web function does not ask for the secret.
SECRETS = [] if os.environ.get("ORBITROUTE_SELFTEST") else [modal.Secret.from_name("orbitroute-keys")]


@app.function(
    secrets=SECRETS,
    volumes={STATE: state},
    max_containers=1,
    scaledown_window=300,  # stays warm for five minutes after the last request, then sleeps (and stops costing)
    timeout=900,
    cpu=2.0,
    memory=2048,
)
@modal.concurrent(max_inputs=16)
@modal.asgi_app()
def web():
    _commit_in_background()
    from orbitroute.api import app as fastapi_app

    return fastapi_app


@app.function(volumes={STATE: state}, timeout=300)
def selftest() -> dict:
    """The image, the interface and the volume work, without keys and without a public URL."""
    from fastapi.testclient import TestClient

    from orbitroute.api import app as fastapi_app

    client = TestClient(fastapi_app)
    health = client.get("/api/health").json()
    samples = client.get("/api/samples").json()
    page = client.get("/")
    tile = client.get(samples[0]["image"])
    with open(f"{STATE}/selftest.txt", "w") as f:
        f.write("ok")
    state.commit()
    return {
        "health": health,
        "samples": [s["name"] for s in samples],
        "index_html": page.status_code == 200 and "OrbitRoute" in page.text,
        "sample_image": f"{tile.status_code} {tile.headers.get('content-type')}",
        "volume_write": os.path.exists(f"{STATE}/selftest.txt"),
        "state_dir": os.environ.get("ORBITROUTE_STATE_DIR"),
    }


@app.local_entrypoint()
def main():
    for key, value in selftest.remote().items():
        print(f"{key}: {value}")
