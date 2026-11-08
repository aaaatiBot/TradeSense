"""Paper trades API endpoints per SRS §4.8, §6.1, §6.3, §6.5."""
from __future__ import annotations

from flask import Blueprint, g, request

from app.services.paper_trade_service import PaperTradeError, PaperTradeService
from app.utils.decorators import require_auth
from app.utils.response import api_error, api_success

paper_trades_bp = Blueprint("paper_trades", __name__, url_prefix="/api/v1/paper-trades")
paper_trade_service = PaperTradeService()


@paper_trades_bp.route("", methods=["POST"])
@require_auth
def open_paper_trade():
    """Open a simulated paper trade from an anchored recommendation.

    Requires Idempotency-Key header per SRS §6.3.
    """
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return api_error(
            code="MISSING_IDEMPOTENCY_KEY",
            message="Idempotency-Key header is required",
            status_code=400,
        )

    data = request.get_json(silent=True) or {}
    recommendation_id = data.get("recommendation_id")
    if not recommendation_id:
        return api_error(
            code="VALIDATION_ERROR",
            message="recommendation_id is required",
            status_code=400,
        )

    execution_prices = data.get("execution_prices", {})

    try:
        trade, was_cached = paper_trade_service.open_paper_trade(
            user_id=g.user.id,
            recommendation_id=recommendation_id,
            idempotency_key=idempotency_key,
            request_path=request.path,
            execution_prices=execution_prices,
        )
        status_code = 200 if was_cached else 201
        return api_success(
            data={
                "trade_id": trade.id,
                "status": trade.status,
                "mode": trade.mode,
                "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
                "legs_count": len(trade.legs),
                "was_cached": was_cached,
            },
            status_code=status_code,
        )
    except PaperTradeError as e:
        return api_error(
            code=e.code,
            message=e.message,
            status_code=e.status_code,
        )


@paper_trades_bp.route("/<int:trade_id>/close", methods=["POST"])
@require_auth
def close_paper_trade(trade_id: int):
    """Close an open paper trade and calculate realized net P&L."""
    data = request.get_json(silent=True) or {}
    exit_prices = data.get("exit_prices", {})

    try:
        trade = paper_trade_service.close_paper_trade(
            paper_trade_id=trade_id,
            user_id=g.user.id,
            exit_prices=exit_prices,
        )
        return api_success(
            data={
                "trade_id": trade.id,
                "status": trade.status,
                "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
                "total_gross_pnl": str(trade.total_gross_pnl),
                "total_net_pnl": str(trade.total_net_pnl),
                "affected_by_universe_change": trade.affected_by_universe_change,
            },
            status_code=200,
        )
    except PaperTradeError as e:
        return api_error(
            code=e.code,
            message=e.message,
            status_code=e.status_code,
        )
