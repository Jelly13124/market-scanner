"""Shared slowapi rate limiter (IP-keyed) for the public deploy surface.

Lives in its own module so both ``main.py`` (which wires the middleware +
exception handler + ``app.state.limiter``) and the route files (which apply
``@limiter.limit(...)`` decorators) can import the SAME ``Limiter`` instance
without a circular import (``main`` imports the routers, the routers can't
import ``main``).

Existing-test safety
--------------------
``RATE_LIMIT_ENABLED`` defaults to ``"false"``. The auth/research/scanner test
apps build their own ``FastAPI`` via ``include_router(api_router)`` and never
run ``main.py``'s app-setup, so they get the decorated routes but NOT the
middleware/handler/state. When the limiter is disabled, slowapi's per-route
wrapper short-circuits before touching storage (it guards every branch on
``self.enabled``), so the decorators are completely inert there and cannot
emit a spurious 429. Production turns limiting on by setting
``RATE_LIMIT_ENABLED=true``.

Per-route limit values are resolved from the environment as PLAIN STRINGS at
decoration time (``auth_limit()`` / ``heavy_limit()`` return e.g. ``"10/minute"``).
String limits land in slowapi's ``_route_limits`` registry, which the
``SlowAPIMiddleware`` deliberately exempts ("there is a decorator for this
route, let the decorator handle it"). That avoids double-counting: with a
*callable* limit the route would instead land in ``_dynamic_route_limits``,
which the middleware does NOT exempt, so both the middleware and the decorator
would count each request and a ``2/minute`` limit would throttle after a single
hit. Because the value is read at decoration (import) time, a test must set the
env BEFORE (re)importing this module + the route modules — which the test does
via ``monkeypatch.setenv`` + ``importlib.reload``.
"""

from __future__ import annotations

import functools
import inspect
import os
from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_enabled() -> bool:
    """True iff RATE_LIMIT_ENABLED is truthy (defaults OFF for test safety)."""
    return os.getenv("RATE_LIMIT_ENABLED", "false").strip().lower() == "true"


def auth_limit() -> str:
    """Tight limit string for the auth endpoints (login/register). IP-keyed."""
    return os.getenv("RATE_LIMIT_AUTH", "10/minute")


def heavy_limit() -> str:
    """Modest limit string for the CPU-heavy endpoints (analyze / scan trigger)."""
    return os.getenv("RATE_LIMIT_HEAVY", "30/minute")


def build_limiter() -> Limiter:
    """Construct a ``Limiter`` whose enabled-state reflects the current env.

    Exposed (rather than only the module-level singleton) so a test can build
    a fresh limiter after setting ``RATE_LIMIT_ENABLED`` — the ``enabled`` flag
    is read once at construction, so the env must be set before this is called.
    """
    return Limiter(
        key_func=get_remote_address,
        enabled=_rate_limit_enabled(),
        default_limits=[],
    )


# Module-level singleton shared by main.py + the route decorators. Built at
# import time from the env present then; for the default (test) environment
# that means disabled -> inert decorators.
limiter = build_limiter()


def rate_limited(limit_value: str) -> Callable:
    """``@limiter.limit`` plus a signature repair for FastAPI compatibility.

    slowapi's ``limit`` decorator returns a ``(*args, **kwargs)`` wrapper. When
    the decorated route lives in a module using ``from __future__ import
    annotations`` (so all annotations are strings) AND takes a Pydantic body
    parameter, FastAPI introspects the wrapper and tries to resolve those
    string annotations against the WRAPPER's ``__globals__`` — which is
    slowapi's module, where the body model name is undefined. Resolution fails
    silently and FastAPI demotes the body parameter to a query parameter,
    yielding a 422 ("field required" in query) on every request.

    Fix: after wrapping, copy the ORIGINAL function's signature (with its
    annotations resolved against the ORIGINAL module's globals) onto the
    wrapper as ``__signature__``. FastAPI then sees real type objects and
    classifies body vs query correctly. Routes without a Pydantic body (auth
    login/register take ``request``/``response`` only; the scan trigger takes
    only path + ``Depends`` params) are unaffected, but applying this uniformly
    keeps the route decorators identical and future-proof.
    """

    def decorator(func: Callable) -> Callable:
        wrapped = limiter.limit(limit_value)(func)
        try:
            wrapped.__signature__ = inspect.signature(func, eval_str=True)
        except Exception:
            # Best-effort: if annotations can't be eval'd (e.g. a genuinely
            # missing name), leave slowapi's wrapper as-is rather than breaking
            # import. Routes without a stringized body param still work.
            functools.update_wrapper(wrapped, func)
        return wrapped

    return decorator
