"""History API endpoints per SRS §4.8, §6.1, §15.1."""
from __future__ import annotations

from flask import Blueprint, g, request

from app.services.paper_trade_service import PaperTradeService
from app.utils.decorators import require_auth
from app.utils.response import api_success

history_bp = Blueprint("history", __name__, url_prefix="/api/v1/history")
paper_trade_service = PaperTradeService()


@history_bp.route("", methods=["GET"])
@require_auth
def get_user_trade_history():
    """Retrieve the authenticated user's paper trading history."""
    status = request.args.get("status")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    history = paper_trade_service.get_user_history(
        user_id=g.user.id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return api_success(
        data={
            "trades": history,
            "disclaimer": "Past performance does not guarantee future results.",
        },
        status_code=200,
    )
