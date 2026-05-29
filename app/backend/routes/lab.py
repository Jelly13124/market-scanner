"""Phase 6E: REST API for the AI strategy lab.

Endpoints (12):
  Strategies:
    GET    /lab/strategies
    POST   /lab/strategies
    GET    /lab/strategies/{id}
    PATCH  /lab/strategies/{id}
    DELETE /lab/strategies/{id}
  Chat:
    GET    /lab/strategies/{id}/chat
    POST   /lab/strategies/{id}/chat
    POST   /lab/strategies/{id}/chat/apply
  Backtest:
    POST   /lab/strategies/{id}/backtest
    GET    /lab/strategies/{id}/backtests
    GET    /lab/backtests/{id}
  Catalog:
    GET    /lab/catalog

Wave 4: every strategy/chat/backtest endpoint requires a valid Bearer token;
all repository calls are scoped to ``current_user.id``. Cross-tenant access
returns 404.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import User
from app.backend.models.lab_schemas import (
    BacktestResponse,
    BacktestRunRequest,
    ChatApplyRequest,
    ChatMessageResponse,
    ChatResponse as ChatResponseSchema,
    ChatSendRequest,
    StrategyCreateRequest,
    StrategyResponse,
    StrategyUpdateRequest,
)
from app.backend.repositories.lab_backtest_repository import BacktestRepository
from app.backend.repositories.lab_chat_repository import LabChatRepository
from app.backend.repositories.lab_strategy_repository import StrategyRepository
from src.lab.backtest_runner import run_backtest
from src.lab.catalog import CATALOG
from src.lab.charts import (
    render_drawdown_png,
    render_equity_curve_png,
    render_monthly_heatmap_png,
)
from src.lab.chat import ProposeSpecPatch, run_chat_turn
from src.lab.spec.strategy import StrategySpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lab")


# ---- Default scaffold spec (when initial_spec_json not supplied) ----

def _scaffold_spec(strategy_name: str) -> dict:
    return {
        "name": strategy_name,
        "description": "Empty strategy - describe it in chat to fill in.",
        "universe": {"kind": "sp500"},
        "entry": {"combiner": "and", "signals": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
        ]},
        "exit": [{"type": "stop_loss", "mode": "pct", "value": 0.05}],
        "filters": [],
        "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


# ---- Strategy CRUD ----

@router.get("/strategies", response_model=list[StrategyResponse])
def list_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StrategyResponse]:
    rows = StrategyRepository(db).list(user_id=current_user.id)
    return [StrategyResponse.model_validate(r) for r in rows]


@router.post("/strategies", response_model=StrategyResponse, status_code=201)
def create_strategy(
    req: StrategyCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    spec = req.initial_spec_json or _scaffold_spec(req.name)
    try:
        StrategySpec.model_validate(spec)
    except Exception as e:
        raise HTTPException(422, f"Invalid initial_spec_json: {e}")
    repo = StrategyRepository(db)
    if repo.get_by_name(req.name, user_id=current_user.id) is not None:
        raise HTTPException(409, f"Strategy named {req.name!r} already exists")
    try:
        s = repo.create(name=req.name, description=req.description, spec_json=spec, user_id=current_user.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Strategy named {req.name!r} already exists")
    return StrategyResponse.model_validate(s)


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = StrategyRepository(db).get(strategy_id, user_id=current_user.id)
    if s is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    return StrategyResponse.model_validate(s)


@router.patch("/strategies/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: int,
    req: StrategyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = StrategyRepository(db)
    s = repo.get(strategy_id, user_id=current_user.id)
    if s is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    if req.spec_json is not None:
        try:
            StrategySpec.model_validate(req.spec_json)
        except Exception as e:
            raise HTTPException(422, f"Invalid spec_json: {e}")
        s = repo.update_spec(strategy_id, user_id=current_user.id, spec_json=req.spec_json,
                              description=req.description)
        # Also log a manual_edit chat message
        LabChatRepository(db).add(
            strategy_id=strategy_id, role="user_manual_edit",
            content=(req.description or "manual edit"),
            spec_snapshot_json=req.spec_json,
            user_id=current_user.id,
        )
    elif req.name is not None:
        s = repo.rename(strategy_id, req.name, user_id=current_user.id)
    if s is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    return StrategyResponse.model_validate(s)


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = StrategyRepository(db).delete(strategy_id, user_id=current_user.id)
    if not ok:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    return None


# ---- Chat ----

@router.get("/strategies/{strategy_id}/chat", response_model=list[ChatMessageResponse])
def list_chat(
    strategy_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if StrategyRepository(db).get(strategy_id, user_id=current_user.id) is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    rows = LabChatRepository(db).list_for_strategy(strategy_id, user_id=current_user.id, limit=limit)
    # Newest-first from repo -> reverse for chronological UI
    return [ChatMessageResponse.model_validate(r) for r in reversed(rows)]


@router.post("/strategies/{strategy_id}/chat", response_model=ChatResponseSchema)
def post_chat(
    strategy_id: int,
    req: ChatSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategy_repo = StrategyRepository(db)
    chat_repo = LabChatRepository(db)
    strategy = strategy_repo.get(strategy_id, user_id=current_user.id)
    if strategy is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")

    # Save user message
    chat_repo.add(strategy_id=strategy_id, role="user", content=req.message, user_id=current_user.id)

    # Build prior strategies summary (scoped to this user)
    prior_strategies = []
    for s in strategy_repo.list(user_id=current_user.id, limit=5):
        prior_strategies.append({"name": s.name, "verdict": None, "cagr": None})

    history = chat_repo.list_for_strategy(strategy_id, user_id=current_user.id, limit=20)
    # Reverse to chronological for LLM (newest-first -> oldest-first)
    history = list(reversed(history))

    # LLM call
    chat_resp = run_chat_turn(
        current_spec=strategy.spec_json,
        chat_history=history,
        prior_strategies_summary=prior_strategies,
        user_message=req.message,
    )

    root = chat_resp.root
    if isinstance(root, ProposeSpecPatch):
        # Validate patch as a StrategySpec; reject if invalid
        try:
            StrategySpec.model_validate(root.patch)
        except Exception as e:
            # Save as reply explaining the validation failure
            err_msg = chat_repo.add(
                strategy_id=strategy_id, role="assistant",
                content=f"(LLM proposed an invalid patch: {e})",
                user_id=current_user.id,
            )
            return ChatResponseSchema(
                message=ChatMessageResponse.model_validate(err_msg),
                kind="reply",
            )
        # Save AI patch message (not applied yet)
        ai_msg = chat_repo.add(
            strategy_id=strategy_id, role="assistant",
            content=root.rationale,
            spec_patch_json=root.patch,
            spec_snapshot_json=root.patch,  # would-be spec if accepted
            patch_accepted=None,
            user_id=current_user.id,
        )
        return ChatResponseSchema(
            message=ChatMessageResponse.model_validate(ai_msg),
            kind="patch",
            proposed_spec_json=root.patch,
        )
    else:
        ai_msg = chat_repo.add(
            strategy_id=strategy_id, role="assistant",
            content=root.message,
            user_id=current_user.id,
        )
        return ChatResponseSchema(
            message=ChatMessageResponse.model_validate(ai_msg),
            kind="reply",
        )


@router.post("/strategies/{strategy_id}/chat/apply", response_model=StrategyResponse)
def apply_chat_patch(
    strategy_id: int,
    req: ChatApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategy_repo = StrategyRepository(db)
    chat_repo = LabChatRepository(db)
    strategy = strategy_repo.get(strategy_id, user_id=current_user.id)
    if strategy is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    msg = chat_repo.get(req.message_id, user_id=current_user.id)
    if msg is None or msg.strategy_id != strategy_id:
        raise HTTPException(404, f"Message {req.message_id} not found for this strategy")
    if msg.spec_patch_json is None:
        raise HTTPException(400, "Message has no spec patch to apply")
    # Update strategy spec, bump version, mark patch accepted
    s = strategy_repo.update_spec(strategy_id, user_id=current_user.id, spec_json=msg.spec_patch_json)
    chat_repo.mark_patch_accepted(req.message_id, accepted=True)
    return StrategyResponse.model_validate(s)


# ---- Backtest ----

@router.post("/strategies/{strategy_id}/backtest", response_model=BacktestResponse)
def trigger_backtest(
    strategy_id: int,
    _: BacktestRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategy = StrategyRepository(db).get(strategy_id, user_id=current_user.id)
    if strategy is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    try:
        spec = StrategySpec.model_validate(strategy.spec_json)
    except Exception as e:
        raise HTTPException(422, f"Stored spec is invalid: {e}")

    try:
        result = run_backtest(spec, db)
    except Exception as e:
        logger.exception("backtest failed for strategy %s", strategy_id)
        raise HTTPException(500, f"Backtest failed: {type(e).__name__}: {e}")

    # Persist
    is_metrics_dict = _metrics_dict(result.is_metrics)
    oos_metrics_dict = _metrics_dict(result.oos_metrics)

    bt = BacktestRepository(db).create(
        strategy_id=strategy_id,
        spec_snapshot_json=result.spec_snapshot,
        start_date=result.start_date,
        end_date=result.end_date,
        midpoint_date=result.midpoint_date,
        universe_size=result.universe_size,
        is_metrics=is_metrics_dict,
        oos_metrics=oos_metrics_dict,
        degradation_ratio=result.verdict.degradation_ratio if result.verdict else None,
        benchmark_cagr=result.benchmark_cagr,
        verdict_label=result.verdict.label if result.verdict else "insufficient",
        verdict_text=result.verdict.text if result.verdict else (result.error_message or ""),
        trades=result.is_trades + result.oos_trades,
        equity_curve_is=result.equity_curve_is,
        equity_curve_oos=result.equity_curve_oos,
        benchmark_curve=result.benchmark_curve,
        duration_seconds=result.duration_seconds,
        error_message=result.error_message,
        user_id=current_user.id,
    )
    return BacktestResponse.model_validate(bt)


def _metrics_dict(m) -> dict:
    if m is None:
        return {f: None for f in (
            "total_return", "cagr", "sharpe", "sortino", "max_drawdown",
            "calmar", "win_rate", "profit_factor", "n_trades", "avg_holding_days",
        )}
    return {
        "total_return": m.total_return, "cagr": m.cagr,
        "sharpe": m.sharpe, "sortino": m.sortino,
        "max_drawdown": m.max_drawdown, "calmar": m.calmar,
        "win_rate": m.win_rate, "profit_factor": m.profit_factor,
        "n_trades": m.n_trades, "avg_holding_days": m.avg_holding_days,
    }


@router.get("/strategies/{strategy_id}/backtests", response_model=list[BacktestResponse])
def list_backtests(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if StrategyRepository(db).get(strategy_id, user_id=current_user.id) is None:
        raise HTTPException(404, f"Strategy {strategy_id} not found")
    rows = BacktestRepository(db).list_for_strategy(strategy_id, user_id=current_user.id)
    return [BacktestResponse.model_validate(r) for r in rows]


@router.get("/backtests/{backtest_id}", response_model=BacktestResponse)
def get_backtest(
    backtest_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bt = BacktestRepository(db).get(backtest_id, user_id=current_user.id)
    if bt is None:
        raise HTTPException(404, f"Backtest {backtest_id} not found")
    return BacktestResponse.model_validate(bt)


# ---- Backtest charts ----

@router.get("/backtests/{backtest_id}/chart/{chart_type}.png")
def get_backtest_chart(
    backtest_id: int, chart_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bt = BacktestRepository(db).get(backtest_id, user_id=current_user.id)
    if bt is None:
        raise HTTPException(404, f"Backtest {backtest_id} not found")
    if chart_type == "equity_curve":
        png = render_equity_curve_png(
            bt.equity_curve_is or [],
            bt.equity_curve_oos or [],
            benchmark_curve=bt.benchmark_curve,
            midpoint_label=bt.midpoint_date or "",
        )
    elif chart_type == "drawdown":
        combined = (bt.equity_curve_is or []) + (bt.equity_curve_oos or [])
        png = render_drawdown_png(combined)
    elif chart_type == "monthly_heatmap":
        png = render_monthly_heatmap_png(bt.trades_json or [])
    else:
        raise HTTPException(404, f"Unknown chart type {chart_type}")
    return Response(content=png, media_type="image/png")


# ---- Catalog ----

@router.get("/catalog")
def get_catalog():
    return CATALOG
