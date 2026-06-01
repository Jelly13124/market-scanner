"""Tests for serving the built SPA from FastAPI (single-origin deploy).

The API routers stay at root (no ``/api`` prefix). ``mount_spa`` adds a
catch-all that serves ``index.html`` for client-side routes WITHOUT shadowing
the API routes (those are registered earlier and win). When no build is present
(dev / CI) ``mount_spa`` is a no-op so the API runs unchanged.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.main import mount_spa


def test_spa_root_returns_index(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>APP_ROOT</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)")

    app = FastAPI()

    @app.get("/health")
    def h():
        return {"ok": True}

    mount_spa(app, dist)
    c = TestClient(app)

    assert "APP_ROOT" in c.get("/").text  # root -> index
    assert "APP_ROOT" in c.get("/some/client/route").text  # SPA fallback
    assert c.get("/health").json() == {"ok": True}  # API NOT shadowed
    assert c.get("/assets/app.js").status_code == 200  # static asset


def test_mount_spa_noop_without_build(tmp_path):
    app = FastAPI()

    @app.get("/health")
    def h():
        return {"ok": True}

    mount_spa(app, tmp_path / "nonexistent")  # no dist -> no SPA routes added
    c = TestClient(app)

    assert c.get("/").status_code in (404, 405)  # nothing serving root
    assert c.get("/health").json() == {"ok": True}
