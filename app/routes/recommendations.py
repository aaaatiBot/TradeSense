"""Recommendations endpoint implementation per SRS §4.2, §4.5, §4.6, §6.1, §7.5, §7.6."""
from __future__ import annotations

from decimal import Decimal
import json
from flask import Blueprint, g, request
from sqlalchemy import func

from app.extensions import db
from app.models.cost_rate_card import CostRateCard
from app.models.job import JobQueue
from app.models.model_version import ModelVersion
from app.models.price import Price
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.models.stock import Stock
from app.services.cost_engine import CostEngine
from app.services.expected_return_service import ExpectedReturnService
from app.services.optimizer_service import OptimizerService
from app.services.universe_service import UniverseService
from app.utils.clock import Clock
from app.utils.decorators import require_auth
from app.utils.metrics import metrics
from app.utils.response import api_error, api_success

recommendations_bp = Blueprint("recommendations", __name__, url_prefix="/api/v1/recommendations")


@recommendations_bp.route("", methods=["POST"])
@require_auth
def generate_recommendations():
    """Generate risk-budgeted stock allocation recommendations per SRS §4.2, §4.5, §4.6."""
    user = g.current_user
    body = request.get_json() or {}

    raw_budget = body.get("budget")
    if raw_budget is None:
        return api_error(code="VALIDATION_ERROR", message="Budget is required", status_code=400)

    try:
        budget = Decimal(str(raw_budget))
    except Exception:
        return api_error(code="VALIDATION_ERROR", message="Invalid budget format", status_code=400)

    if budget < Decimal("500") or budget > Decimal("1000000"):
        return api_error(
            code="BUDGET_OUT_OF_BOUNDS",
            message="Budget must be between ₹500 and ₹1,000,000 per SRS §4.2",
            status_code=400,
        )

    trade_mode = body.get("trade_mode", "CNC").upper()
    if trade_mode not in ["CNC", "MIS"]:
        return api_error(
            code="INVALID_TRADE_MODE",
            message="Trade mode must be 'CNC' or 'MIS'",
            status_code=400,
        )

    horizon = body.get("horizon", "1d")

    # 1. Fetch active stocks from universe
    active_stocks = UniverseService.list_active_stocks()
    if not active_stocks:
        active_stocks = Stock.query.filter(func.lower(Stock.status) == "active").all()
    if not active_stocks:
        return api_error(
            code="NO_ACTIVE_STOCKS",
            message="Stock universe is empty or inactive",
            status_code=409,
        )

    # 2. Reference notional & active model
    ref_config = ReferenceNotionalConfig.query.filter_by(is_active=True).first()
    reference_notional = ref_config.notional_amount if ref_config else Decimal("500.00")

    active_model = ModelVersion.query.filter_by(is_active=True).first()
    if not active_model:
        # Fallback to any model or create a default
        active_model = ModelVersion.query.first()
    model_version_id = active_model.id if active_model else 1

    # 3. Rate card
    rate_card = CostRateCard.query.filter_by(is_active=True).first()
    rate_card_version = rate_card.version if rate_card else "zerodha-2026"

    # 4. Services setup
    cost_engine = CostEngine()
    exp_service = ExpectedReturnService(cost_engine=cost_engine)
    opt_service = OptimizerService(expected_return_service=exp_service, cost_engine=cost_engine)

    candidates = []
    isin_map = {}
    stock_obj_map = {}
    for stock in active_stocks:
        latest_price_row = (
            Price.query.filter_by(stock_id=stock.id)
            .order_by(Price.timestamp.desc())
            .first()
        )
        price = latest_price_row.close if latest_price_row else getattr(stock, "last_price", None) or Decimal("100.00")
        if price <= Decimal("0"):
            continue

        isin_map[stock.ticker] = stock.isin
        stock_obj_map[stock.ticker] = stock
        p_i = Decimal("0.60")

        cand = exp_service.estimate_stock_return(
            ticker=stock.ticker,
            price=price,
            horizon=horizon,
            mode=trade_mode,
            p_i=p_i,
            reference_notional=reference_notional,
        )
        candidates.append(cand)

    # 5. Run integer optimization
    allocation_result = opt_service.optimize_allocation(
        budget=budget,
        candidates=candidates,
        mode=trade_mode,
        horizon=horizon,
        isin_map=isin_map,
    )

    if allocation_result.status != "SUCCESS" or not allocation_result.positions:
        return api_error(
            code="NO_AFFORDABLE_ALLOCATION",
            message="No affordable allocation found under the specified budget and position constraints",
            status_code=400,
        )

    # 6. Persist Recommendation record (§7.5)
    recommendation = Recommendation(
        user_id=user.id,
        budget=budget,
        effective_budget=allocation_result.effective_budget,
        cash_buffer=allocation_result.cash_buffer,
        mode=trade_mode,
        horizon=horizon,
        model_version_id=model_version_id,
        rate_card_version=rate_card_version,
        reference_notional=reference_notional,
        status="DRAFT",
        created_at=Clock.now(),
    )
    db.session.add(recommendation)
    db.session.flush()

    # 7. Persist Recommendation line items (§7.6)
    items_out = []
    for pos in allocation_result.positions:
        stock_obj = stock_obj_map.get(pos.ticker)
        stock_id = stock_obj.id if stock_obj else 1
        item = RecommendationItem(
            recommendation_id=recommendation.id,
            stock_id=stock_id,
            ticker=pos.ticker,
            quantity=pos.quantity,
            allocated_amount=pos.allocated_amount,
            expected_return_rate=pos.expected_gain,
            p_i=pos.p_i,
            g_plus=pos.g_plus,
            g_minus=pos.g_minus,
            estimate_source=pos.estimate_source,
            method_version=pos.method_version,
            reference_notional=pos.reference_notional,
            stock_status_at_creation="active",
            created_at=Clock.now(),
        )
        db.session.add(item)
        items_out.append({
            "ticker": pos.ticker,
            "isin": isin_map.get(pos.ticker, "INUNKNOWN000"),
            "shares": pos.quantity,
            "entry_price": str(pos.price),
            "allocated_capital": str(pos.allocated_amount),
            "expected_net_pnl": str(pos.expected_gain),
            "estimate_source": pos.estimate_source,
            "prior_caution_flag": pos.has_prior_caution,
        })

    # 8. Queue blockchain anchoring job
    job = JobQueue(
        job_type="anchor_recommendation",
        payload=json.dumps({"recommendation_id": recommendation.id}),
        status="QUEUED",
        created_at=Clock.now(),
    )
    db.session.add(job)
    db.session.commit()

    metrics.inc_recommendations_created()

    return api_success(
        data={
            "id": recommendation.id,
            "budget": str(budget),
            "trade_mode": trade_mode,
            "reference_notional": str(reference_notional),
            "total_deployed": str(allocation_result.total_allocated),
            "total_estimated_costs": str(allocation_result.total_modeled_costs),
            "total_expected_net_pnl": str(allocation_result.expected_net_pnl),
            "items": items_out,
            "blockchain_status": "QUEUED",
        },
        status_code=201,
    )


@recommendations_bp.route("/<int:rec_id>", methods=["GET"])
@require_auth
def get_recommendation(rec_id: int):
    """Retrieve details of an existing recommendation."""
    rec = db.session.get(Recommendation, rec_id)
    if not rec:
        return api_error(code="NOT_FOUND", message="Recommendation not found", status_code=404)

    if rec.user_id != g.current_user.id and g.current_user.role != "admin":
        return api_error(code="FORBIDDEN", message="Access denied", status_code=403)

    items = RecommendationItem.query.filter_by(recommendation_id=rec.id).all()
    return api_success(
        data={
            "id": rec.id,
            "budget": str(rec.budget),
            "trade_mode": rec.mode,
            "effective_budget": str(rec.effective_budget),
            "status": rec.status,
            "commitment_hash": rec.commitment_hash,
            "items": [
                {
                    "ticker": it.ticker,
                    "quantity": it.quantity,
                    "allocated_amount": str(it.allocated_amount),
                    "expected_return_rate": str(it.expected_return_rate),
                    "estimate_source": it.estimate_source,
                }
                for it in items
            ],
        },
        status_code=200,
    )
