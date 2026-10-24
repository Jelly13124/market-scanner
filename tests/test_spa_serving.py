"""Tests for serving the built SPA from FastAPI (single-origin deploy).

The API routers stay at root (no ``/api`` prefix). ``mount_spa`` serves
``index.html`` at ``/`` and adds a 404 HANDLER (not a greedy ``/{path:path}``
catch-all) so client-side routes work WITHOUT shadowing API routes — including
trailing-slash collection redirects (e.g. ``/api-keys`` -> ``/api-keys/``). When
no build is present (dev / CI) ``mount_spa`` is a no-op so the API runs unchanged.
"""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.backend.main import mount_spa

_HTML = {"accept": "text/html"}  # simulate a browser navigation


def _app_with_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>APP_ROOT</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)")

    app = FastAPI()

    @app.get("/health")
    def h():
        return {"ok": True}

    # A trailing-slash collection route — exactly the kind a greedy catch-all
    # would shadow (GET /api-keys -> /api-keys/).
    coll = APIRouter()

    @coll.get("/")
    def _list():
        return {"items": []}

    app.include_router(coll, prefix="/api-keys")
    mount_spa(app, dist)
    return app


def test_spa_root_and_client_routes(tmp_path):
    c = TestClient(_app_with_dist(tmp_path))
    assert "APP_ROOT" in c.get("/").text                                   # root -> index
    assert "APP_ROOT" in c.get("/some/client/route", headers=_HTML).text   # browser nav -> SPA
    assert c.get("/health").json() == {"ok": True}                         # API not shadowed


def test_api_routes_not_shadowed(tmp_path):
    """The /api-keys collection (trailing slash) must return JSON, not the SPA —
    the regression the 404-handler approach fixes vs a greedy catch-all."""
    c = TestClient(_app_with_dist(tmp_path))
    r = c.get("/api-keys/")
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"items": []}
    # even a browser GET without the slash follows the API's 307 redirect -> JSON,
    # not the SPA.
    assert c.get("/api-keys", headers=_HTML).json() == {"items": []}


def test_xhr_404_stays_json(tmp_path):
    """An XHR (no text/html Accept) to an unknown path keeps its normal 404 —
    only browser navigations fall through to the SPA."""
    c = TestClient(_app_with_dist(tmp_path))
    r = c.get("/definitely/not/a/route", headers={"accept": "application/json"})
    assert r.status_code == 404
    assert "APP_ROOT" not in r.text


def test_static_asset(tmp_path):
    assert TestClient(_app_with_dist(tmp_path)).get("/assets/app.js").status_code == 200


def test_mount_spa_noop_without_build(tmp_path):
    app = FastAPI()

    @app.get("/health")
    def h():
        return {"ok": True}

    mount_spa(app, tmp_path / "nonexistent")  # no dist -> no SPA, no handler added
    c = TestClient(app)
    assert c.get("/", headers=_HTML).status_code in (404, 405)  # nothing serving root
    assert c.get("/health").json() == {"ok": True}
