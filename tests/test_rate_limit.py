"""Rate-limiting (slowapi) tests for the public deploy surface.

Covers three things:

1. ``test_login_rate_limited`` / ``test_register_rate_limited`` — the limiter
   mechanism on the REAL production app (``main.app``), rebuilt with limiting
   ENABLED and a tiny ``2/minute`` auth limit. The 3rd ``POST /auth/login``
   (resp. ``/auth/register``) returns 429 while the first two do not.

2. ``test_disabled_limiter_is_inert`` — the existing-test-safety guarantee:
   with ``RATE_LIMIT_ENABLED`` unset/false (the default the 1113 existing
   tests run under), the decorated routes are fully inert and NEVER 429, even
   on an app that mounts the routers WITHOUT main.py's middleware/handler/state
   (which is exactly how tests/auth/conftest.py builds its apps).

3. ``test_main_app_has_limiter_wired`` — the production app carries the limiter
   state + the ``SlowAPIMiddleware``, so limiting is genuinely active in prod.

How the env takes effect
------------------------
Per-route limit *values* are resolved to plain strings at decoration (import)
time, and the limiter's ``enabled`` flag is fixed at construction. So a test
sets ``RATE_LIMIT_ENABLED`` / ``RATE_LIMIT_AUTH`` via ``monkeypatch.setenv``
and then reloads, in order, ``app.backend.rate_limit`` (rebuilds the limiter),
the decorated route submodules + the ``routes`` package (re-registers every
route's limit on the fresh limiter), and ``app.backend.main`` (re-wires state +
handler + middleware onto a fresh ``app``). See ``_reload_rate_limit_stack`` for
why the submodules are reloaded explicitly and how duplicate registrations from
reloading are normalised away.

Static string limits (vs a callable) are deliberate: they land in slowapi's
``_route_limits`` registry, which ``SlowAPIMiddleware`` exempts ("there's a
decorator for this route, let it handle it"). A callable limit would instead
land in ``_dynamic_route_limits`` — NOT exempted — so the middleware AND the
decorator would each count every request and ``2/minute`` would throttle after
a single hit.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database import get_db
from app.backend.database.models import Base


def _make_db_override():
    """In-memory SQLite override mirroring tests/auth/conftest.py."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    return _override


def _reload_rate_limit_stack():
    """Reload rate_limit then every module that decorates a route with it.

    The route submodules close over the ``limiter`` instance present when they
    last executed, and the limit *string* is read then too. Reloading the
    ``routes`` package alone re-runs only ``routes/__init__`` — a cached
    ``from .auth import router`` does NOT re-execute auth.py — so the decorated
    routers would keep pointing at a stale limiter. We therefore reload the
    decorated submodules explicitly, then the package, so the fresh
    (env-derived) limiter is the one actually enforcing.
    """
    import app.backend.rate_limit as rate_limit

    importlib.reload(rate_limit)
    import app.backend.routes.auth as auth_module
    import app.backend.routes.research as research_module
    import app.backend.routes.scanner as scanner_module

    importlib.reload(auth_module)
    importlib.reload(research_module)
    importlib.reload(scanner_module)
    import app.backend.routes as routes_pkg

    importlib.reload(routes_pkg)

    # Reloading can stack a duplicate limit on a route (a not-yet-cached
    # ``import X`` executes its decorators, then ``reload(X)`` executes them
    # again on the same fresh limiter). Each registration counts independently,
    # so two identical "2/minute" limits would throttle after a single request.
    # Collapse each route's registered limits to one. Production imports every
    # module exactly once and never stacks, so this normalisation is a
    # test-reload concern only.
    for limits in rate_limit.limiter._route_limits.values():
        del limits[1:]
    return routes_pkg


def _reload_main_with_env():
    """Reload the rate-limit stack -> main so the just-set env takes effect.

    Returns the freshly-reloaded ``main`` module. Its ``main.app`` is wired
    exactly as production (state + RateLimitExceeded handler + middleware) but
    with the limiter rebuilt from the current env. An in-memory ``get_db``
    override is installed so the auth routes can run without the real DB.
    """
    _reload_rate_limit_stack()
    from app.backend import main

    importlib.reload(main)

    # Clear any rate-limit counters left over from a previous test in this same
    # process so the per-test window starts at zero (slowapi's in-memory store
    # otherwise carries counts forward and a fresh "2/minute" would already be
    # exhausted). Reset the limiter the app actually enforces with.
    main.app.state.limiter.reset()
    main.app.dependency_overrides[get_db] = _make_db_override()
    return main


def test_login_rate_limited(monkeypatch):
    """With a 2/minute auth limit, the 3rd login attempt is 429."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH", "2/minute")

    main = _reload_main_with_env()
    client = TestClient(main.app)
    body = {"email": "nobody@example.com", "password": "wrong-password"}

    # First two attempts: not throttled (they 401 on bad creds — fine, we only
    # assert they are NOT 429).
    r1 = client.post("/auth/login", json=body)
    r2 = client.post("/auth/login", json=body)
    assert r1.status_code != 429, r1.text
    assert r2.status_code != 429, r2.text

    # Third attempt within the window: throttled.
    r3 = client.post("/auth/login", json=body)
    assert r3.status_code == 429, r3.text


def test_register_rate_limited(monkeypatch):
    """The same tight auth limit guards /auth/register against signup spam."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH", "2/minute")

    main = _reload_main_with_env()
    client = TestClient(main.app)

    # Distinct emails so a duplicate-email 409 can't be confused with a 429.
    codes = [client.post("/auth/register", json={"email": f"u{i}@example.com", "password": "pw123456"}).status_code for i in range(3)]
    assert codes[0] != 429, codes
    assert codes[1] != 429, codes
    assert codes[2] == 429, codes


def test_disabled_limiter_is_inert(monkeypatch):
    """Default (RATE_LIMIT_ENABLED unset/false): decorators never 429.

    This is the guarantee that keeps the existing 1113 tests green — their
    conftest apps include the decorated routers but don't enable limiting and
    don't add the middleware/handler/state. We mimic that exactly here.
    """
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("RATE_LIMIT_AUTH", "2/minute")  # tiny limit, but disabled

    routes_pkg = _reload_rate_limit_stack()
    import app.backend.rate_limit as rate_limit

    rate_limit.limiter.reset()  # clear any leftover counters from prior tests
    assert rate_limit.limiter.enabled is False

    # Mimic the conftest apps: include the router but add NO middleware, NO
    # handler, NO app.state.limiter.
    app = FastAPI()
    app.include_router(routes_pkg.auth_router)
    app.dependency_overrides[get_db] = _make_db_override()
    client = TestClient(app)

    body = {"email": "nobody@example.com", "password": "wrong-password"}
    codes = [client.post("/auth/login", json=body).status_code for _ in range(6)]
    assert 429 not in codes, codes


def test_main_app_has_limiter_wired(monkeypatch):
    """The production app (main.app) carries the limiter state + middleware."""
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    main = _reload_main_with_env()

    assert getattr(main.app.state, "limiter", None) is not None
    mw_names = {m.cls.__name__ for m in main.app.user_middleware}
    assert "SlowAPIMiddleware" in mw_names, mw_names


def teardown_module(module):
    """Restore the rate-limit stack + main to their default-env state so later
    test modules in the same process are unaffected (limiter back to disabled).

    ``RATE_LIMIT_ENABLED`` is unset by now (monkeypatch reverted it per-test),
    so the rebuilt limiter is disabled and every decorated route is inert.
    """
    _reload_rate_limit_stack()
    from app.backend import main

    importlib.reload(main)
