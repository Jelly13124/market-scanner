"""NotificationDispatcher — fans pipeline-completion events to handlers.

Single entry-point used by both the scheduler (`_run_pipeline_job`) and
the `/notifications/subscriptions/{id}/test` route:

    dispatcher = NotificationDispatcher(session_factory)
    dispatcher.dispatch(run_id="abc...")           # all enabled subs
    dispatcher.dispatch_to(sub_id, run_id="abc")   # single sub (test send)

The dispatcher loads the PipelineRun + subscriptions in one short-lived
session, dispatches sequentially (channels are independent and slow ones
shouldn't fan into a thread pool for what's a daily cron), and records
every attempt to NotificationDelivery. It NEVER raises — a misbehaving
handler is logged but won't break the caller (scheduler cron must not
die on a Resend hiccup).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.backend.database.models import (
    NotificationSubscription,
    PipelineRun,
)
from app.backend.repositories.notification_repository import (
    DeliveryRepository,
    SubscriptionRepository,
)
from app.backend.repositories.pipeline_repository import (
    PipelineScheduleRepository,
)
from app.backend.services.notifications.bundled_email import (
    render_bundled_research_html, render_bundled_research_text,
)
from app.backend.services.notifications.email_handler import EmailHandler
from app.backend.services.notifications.gist import generate_gists
from app.backend.services.notifications.render import (
    render_pipeline_html, render_pipeline_text,
    render_research_html, render_research_text,
    render_screener_match_html, render_screener_match_text,
)
from app.backend.services.notifications.webhook_handler import WebhookHandler

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Loads subs + run, fans out to handlers, records attempts."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        email_handler: EmailHandler | None = None,
        webhook_handler: WebhookHandler | None = None,
    ) -> None:
        self._session_factory = session_factory
        # Handlers are cheap to construct; allow injection for tests.
        self._email = email_handler
        self._webhook = webhook_handler

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _render_for_event(self, event_type: str, run) -> tuple[str, str]:
        """Pick the (html, text) renderer pair for the given event_type.

        Phase 1 ships pipeline.completed; Phase 3 adds research.completed.
        Phase 5E adds research.bundled — here ``run`` is interpreted as a
        ``list[ResearchReport]`` rather than a single row.
        Unknown event_types fall back to pipeline render (safe default).
        """
        if event_type == "research.bundled":
            return (
                render_bundled_research_html(run),
                render_bundled_research_text(run),
            )
        if event_type == "research.completed":
            return render_research_html(run), render_research_text(run)
        if event_type == "screener.match":
            return (
                render_screener_match_html(run),
                render_screener_match_text(run),
            )
        return render_pipeline_html(run), render_pipeline_text(run)

    def dispatch(
        self,
        *,
        run_id: str,
        event_type: str = "pipeline.completed",
    ) -> int:
        """Send the event to every enabled subscription matching event_type.

        Returns the count of dispatch attempts (success + failure).
        """
        with self._session_factory() as session:
            run = _load_run(session, run_id)
            if run is None:
                logger.warning(
                    "Dispatcher: PipelineRun %s not found; skipping all subscriptions",
                    run_id,
                )
                return 0
            subs = SubscriptionRepository(session).list_enabled_for_event(event_type)
            if not subs:
                logger.debug(
                    "Dispatcher: no enabled subscriptions for event %r; nothing to send",
                    event_type,
                )
                return 0

            # Snapshot subs as detached duck-typed copies — we drop the
            # session before doing slow HTTP and don't want the handler
            # holding a live DB connection.
            sub_snapshots = [_snapshot(s) for s in subs]
            # Snapshot run too — same reason.
            run_snapshot = _snapshot_run(run)
            # Read model config from the pipeline_schedule singleton for the
            # gist LLM call. Falls back to (None, None) if the row is
            # missing — generate_gists will just produce an empty map.
            schedule = PipelineScheduleRepository(session).get()
            model_name = schedule.model_name if schedule else None
            model_provider = schedule.model_provider if schedule else None

        # Attach the precomputed gist_map once — every sub for this dispatch
        # reuses it. Costs N×LLM calls (N tickers), not subs×N. Email
        # subs read it; webhook subs ignore it.
        run_snapshot.gist_map = _try_gist(
            run_snapshot, model_name=model_name, model_provider=model_provider,
        )

        attempts = 0
        for sub in sub_snapshots:
            self._dispatch_one(sub, run_snapshot)
            attempts += 1
        return attempts

    def dispatch_bundled(
        self,
        *,
        event_type: str,
        reports: list,
        scan_run_id: int | None = None,
    ) -> int:
        """Phase 5E: fan a single bundled email out to every enabled sub for
        ``event_type``. ``reports`` is the list[ResearchReport] payload —
        handlers read it directly (no PipelineRun involvement). Each
        attempt is recorded in NotificationDelivery using
        ``scan_run_id`` (cast to str) as the run_id surrogate.

        Returns the count of dispatch attempts.
        """
        if not reports:
            logger.info(
                "dispatch_bundled: no reports to send for event=%s scan_run_id=%s",
                event_type, scan_run_id,
            )
            return 0
        with self._session_factory() as session:
            subs = SubscriptionRepository(session).list_enabled_for_event(event_type)
            if not subs:
                logger.debug(
                    "dispatch_bundled: no enabled subscriptions for event %r",
                    event_type,
                )
                return 0
            sub_snapshots = [_snapshot(s) for s in subs]

        # ``run`` for the handler is a list[ResearchReport] subclass that
        # also carries an ``.id`` attribute so _dispatch_one's audit log
        # gets the scan_run_id as its run_id surrogate. The bundled
        # renderer iterates the list normally.
        run_surrogate = _BundledRun(reports)
        run_surrogate.id = (
            str(scan_run_id) if scan_run_id is not None else None
        )

        attempts = 0
        for sub in sub_snapshots:
            # Force the event_type on the snapshot so EmailHandler reads
            # it correctly even if the sub row was created with a
            # different default.
            sub.event_type = event_type
            self._dispatch_one(sub, run_surrogate)
            attempts += 1
        return attempts

    def dispatch_screener_match(
        self,
        *,
        payload: dict,
        event_type: str = "screener.match",
        user_id: int | None = None,
    ) -> int:
        """Fan a screener preset match out to enabled subs for ``event_type``.

        ``payload`` is a plain dict (preset_name, match_count, snapshot_date,
        rows). No PipelineRun involved.

        ``user_id`` scopes the fan-out to a single owner's subscriptions —
        the preset cron passes the matched preset's owner so a user's match
        never notifies another tenant. When ``None`` the fan-out is global
        (legacy/test behaviour).
        """
        with self._session_factory() as session:
            repo = SubscriptionRepository(session)
            subs = (
                repo.list_enabled_for_event_and_user(event_type, user_id=user_id)
                if user_id is not None
                else repo.list_enabled_for_event(event_type)
            )
            if not subs:
                logger.debug(
                    "dispatch_screener_match: no enabled subscriptions for event %r",
                    event_type,
                )
                return 0
            sub_snapshots = [_snapshot(s) for s in subs]

        class _ScreenerMatchRun:
            def __init__(self, p: dict) -> None:
                self.payload = p
                self.id = f"screener-{p.get('preset_id', '')}"

        surrogate = _ScreenerMatchRun(payload)

        attempts = 0
        for sub in sub_snapshots:
            sub.event_type = event_type
            self._dispatch_one(sub, surrogate)
            attempts += 1
        return attempts

    def dispatch_to(
        self,
        *,
        subscription_id: int,
        run_id: str | None,
    ) -> dict[str, Any] | None:
        """One-off send to a single subscription regardless of enabled flag.

        Used by the ``/test`` route. ``run_id=None`` is allowed — the
        dispatcher will pick the latest PipelineRun automatically; if
        none exist a synthetic empty-watchlist run is fabricated so the
        recipient still sees a sample email.

        Returns the dispatch result dict (also recorded in
        NotificationDelivery) or None if the subscription doesn't exist.
        """
        with self._session_factory() as session:
            sub = SubscriptionRepository(session).get_unscoped(subscription_id)
            if sub is None:
                return None
            run = (
                _load_run(session, run_id) if run_id
                else _load_latest_run(session)
            )
            if run is None:
                run = _synthetic_run()
            sub_snapshot = _snapshot(sub)
            run_snapshot = _snapshot_run(run)
            schedule = PipelineScheduleRepository(session).get()
            model_name = schedule.model_name if schedule else None
            model_provider = schedule.model_provider if schedule else None

        # Same precompute path as dispatch() — keeps /test send output
        # consistent with the daily cron output.
        run_snapshot.gist_map = _try_gist(
            run_snapshot, model_name=model_name, model_provider=model_provider,
        )

        return self._dispatch_one(sub_snapshot, run_snapshot)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _dispatch_one(self, sub: Any, run: Any) -> dict[str, Any]:
        """Pick handler, call send(), record attempt. Returns result dict."""
        handler = self._handler_for(sub.channel)
        if handler is None:
            result = {
                "status": "error",
                "http_code": None,
                "error_text": f"unknown channel {sub.channel!r}",
                "latency_ms": 0,
            }
        else:
            try:
                result = handler.send(sub, run)
            except Exception as e:
                # Handlers shouldn't raise but defend the cron just in case.
                logger.exception(
                    "Dispatcher: handler for channel=%s raised", sub.channel,
                )
                result = {
                    "status": "error",
                    "http_code": None,
                    "error_text": f"handler raised {type(e).__name__}: {e}",
                    "latency_ms": 0,
                }

        # Record the attempt in its own short session.
        try:
            with self._session_factory() as session:
                DeliveryRepository(session).record(
                    subscription_id=sub.id,
                    run_id=getattr(run, "id", None),
                    status=result.get("status", "error"),
                    http_code=result.get("http_code"),
                    error_text=result.get("error_text"),
                    latency_ms=result.get("latency_ms"),
                )
        except Exception:
            logger.exception("Dispatcher: failed to record delivery row")

        if result.get("status") == "ok":
            logger.info(
                "Dispatcher: sub=%s channel=%s → ok (http=%s, %sms)",
                sub.id, sub.channel,
                result.get("http_code"), result.get("latency_ms"),
            )
        else:
            logger.warning(
                "Dispatcher: sub=%s channel=%s → error: %s",
                sub.id, sub.channel, result.get("error_text"),
            )
        return result

    def _handler_for(self, channel: str) -> Any:
        if channel == "email":
            if self._email is None:
                self._email = EmailHandler()
            return self._email
        if channel == "webhook":
            if self._webhook is None:
                self._webhook = WebhookHandler()
            return self._webhook
        return None


# ----------------------------------------------------------------------
# Session helpers
# ----------------------------------------------------------------------


def _load_run(session: Session, run_id: str) -> PipelineRun | None:
    return session.query(PipelineRun).filter(PipelineRun.id == run_id).first()


def _load_latest_run(session: Session) -> PipelineRun | None:
    return (
        session.query(PipelineRun)
        .order_by(PipelineRun.created_at.desc())
        .first()
    )


class _BundledRun(list):
    """list[ResearchReport] subclass that carries an ``.id`` attribute so
    NotificationDispatcher._dispatch_one's audit log gets a stable
    run_id surrogate (the scan_run_id) when dispatching a bundled
    research email. The bundled renderer iterates this exactly like a
    normal list."""
    pass


def _snapshot(sub: NotificationSubscription) -> Any:
    """Detached duck-typed copy — safe to use after session close."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=sub.id, channel=sub.channel, target=sub.target,
        label=sub.label, enabled=sub.enabled, event_type=sub.event_type,
        auth_header=sub.auth_header,
    )


def _snapshot_run(run: PipelineRun) -> Any:
    from types import SimpleNamespace
    return SimpleNamespace(
        id=run.id, scan_date=run.scan_date, template=run.template,
        top_n=run.top_n, universe=run.universe, status=run.status,
        duration_seconds=run.duration_seconds,
        watchlist_json=run.watchlist_json,
        agent_decisions_json=run.agent_decisions_json,
        analyst_signals_json=run.analyst_signals_json,
        # Filled in by ``_try_gist`` after the snapshot is built; set to
        # None up front so EmailHandler's ``getattr(run, "gist_map", None)``
        # works even before the LLM call.
        gist_map=None,
    )


def _try_gist(
    run_snapshot: Any,
    *,
    model_name: str | None,
    model_provider: str | None,
) -> dict[str, str]:
    """Generate per-ticker gists, swallowing any setup-level error.

    Returns an empty dict on missing model config or any unhandled
    exception during gist generation — render.py treats an empty map
    the same as no gists, so the email still goes out unmodified.
    """
    if not model_name or not model_provider:
        logger.debug("Gist: model not configured in pipeline_schedule; skipping")
        return {}
    try:
        return generate_gists(
            run_snapshot,
            model_name=model_name, model_provider=model_provider,
        )
    except Exception as e:
        logger.warning("Gist generation raised at the top level: %s", e)
        return {}


def _synthetic_run() -> Any:
    """A placeholder PipelineRun shape for /test sends when no real run
    exists yet. Sample shows the recipient the email layout without
    waiting for the first real pipeline."""
    from datetime import date
    from types import SimpleNamespace
    return SimpleNamespace(
        id="sample0000000000000000000000000",
        scan_date=date.today().isoformat(),
        template="quick",
        top_n=1,
        universe="nasdaq100",
        status="COMPLETE",
        duration_seconds=0.0,
        watchlist_json=[{"ticker": "DEMO", "rank": 1, "composite_score": 100}],
        agent_decisions_json={
            "DEMO": {
                "action": "buy", "quantity": 10, "confidence": 85,
                "reasoning": "Sample notification payload — this is a test send.",
            },
        },
        analyst_signals_json={
            "scanner_signal_agent": {
                "DEMO": {
                    "signal": "bullish", "confidence": 85,
                    "reasoning": "Sample analyst reasoning.",
                },
            },
        },
    )
