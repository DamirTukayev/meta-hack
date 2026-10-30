"""A new build must reach a browser at once: the page is always asked for again, the hashed files may be kept."""

from fastapi.testclient import TestClient

import orbitroute.api as api


def test_the_page_is_never_kept_and_the_hashed_files_are(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>OrbitRoute</html>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    # the same middleware on a small app that serves a copy of the build
    small = FastAPI()
    small.middleware("http")(api.keep_the_page_fresh)
    small.mount("/", StaticFiles(directory=dist, html=True), name="web")
    client = TestClient(small)
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/index.html").headers["cache-control"] == "no-cache"
    assert "immutable" in client.get("/assets/index-abc123.js").headers["cache-control"]


def test_the_api_answers_are_left_alone():
    client = TestClient(api.app)
    assert "cache-control" not in client.get("/api/health").headers
