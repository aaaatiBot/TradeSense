"""Paper trading execution and lifecycle service per SRS §4.8 (FR-TRD).

Phase 7 deliverable.
Manages simulated trade open, tracking, price marks, and realized P&L.
Requirements:
- TRD-01 through TRD-12: Simulated order fills, lifecycle, itemized costs.
- TRD-13 & UNI-03: Re-validates stock status at open; rejects with STOCK_UNAVAILABLE if not active.
- Rule 9: Rejects paper trade before recommendation anchoring.
- §6.3: Idempotency-Key required on POST /paper-trades, 24-hour expiration, 409 on payload mismatch.
- EXP-06: Distinguishes expected P&L from realized paper-trade P&L.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import select

from app.extensions import db
from app.models.cost_breakdown import CostBreakdown
from app.models.idempotency import IdempotencyRecord
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.recommendation import Recommendation
from app.models.stock import Stock
from app.services.cost_engine import CostEngine, CostResult
from app.services.universe_service import UniverseService
from app.utils.clock import Clock


class PaperTradeError(Exception):
    """Domain exception for paper trading errors."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class PaperTradeService:
    """Service tracking simulated trade execution, price marks, and realized P&L."""

    def __init__(
        self,
        cost_engine: Optional[CostEngine] = None,
        universe_service: Optional[UniverseService] = None,
    ) -> None:
        self.cost_engine = cost_engine or CostEngine()
        self.universe_service = universe_service or UniverseService()

    def open_paper_trade(
        self,
        user_id: int,
        recommendation_id: int,
        idempotency_key: Optional[str] = None,
        request_path: str = "/api/v1/paper-trades",
        execution_prices: Optional[Dict[str, Union[Decimal, str, float]]] = None,
    ) -> Tuple[PaperTrade, bool]:
        """Open a new simulated paper trade from an anchored recommendation.

        Returns:
            Tuple of (PaperTrade, was_cached: bool)
        """
        now = Clock.utcnow()
        execution_prices = execution_prices or {}

        # 1. Idempotency Check per SRS §6.3
        payload_dict = {
            "user_id": user_id,
            "recommendation_id": recommendation_id,
            "execution_prices": {k: str(v) for k, v in execution_prices.items()},
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload_dict, sort_keys=True).encode("utf-8")
        ).hexdigest()

        if idempotency_key:
            existing_record = db.session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                    IdempotencyRecord.request_path == request_path,
                )
            ).scalar_one_or_none()

            if existing_record:
                if Clock.ensure_utc(existing_record.expires_at) > now:
                    if existing_record.request_hash == payload_hash:
                        # Return previously created trade
                        cached_body = json.loads(existing_record.response_body or "{}")
                        trade_id = cached_body.get("trade_id")
                        if trade_id:
                            trade = db.session.get(PaperTrade, trade_id)
                            if trade:
                                return trade, True
                    else:
                        raise PaperTradeError(
                            "IDEMPOTENCY_CONFLICT",
                            "Idempotency key reused with different payload",
                            status_code=409,
                        )
                else:
                    # Expired (> 24 hours), clear existing record
                    db.session.delete(existing_record)
                    db.session.flush()

        # 2. Fetch and Validate Recommendation
        rec = db.session.get(Recommendation, recommendation_id)
        if not rec:
            raise PaperTradeError("RECOMMENDATION_NOT_FOUND", "Recommendation does not exist", status_code=404)

        if rec.user_id is not None and rec.user_id != user_id:
            raise PaperTradeError("FORBIDDEN", "Recommendation does not belong to user", status_code=403)

        # Non-negotiable Rule 9: "Do not allow paper trades before recommendation anchoring"
        if rec.status not in ("ANCHORED", "ACTIVE"):
            raise PaperTradeError(
                "RECOMMENDATION_NOT_ANCHORED",
                f"Cannot execute paper trade on unanchored recommendation (status: {rec.status})",
                status_code=400,
            )

        if rec.expires_at and Clock.ensure_utc(rec.expires_at) < now:
            raise PaperTradeError(
                "RECOMMENDATION_EXPIRED",
                "Recommendation has expired",
                status_code=400,
            )

        if not rec.items:
            raise PaperTradeError(
                "RECOMMENDATION_EMPTY",
                "Recommendation contains no allocated items",
                status_code=400,
            )

        # 3. UNI-03 & TRD-13: Re-validate stock status at trade open
        for item in rec.items:
            stock = db.session.get(Stock, item.stock_id)
            if not stock or stock.status != "active":
                raise PaperTradeError(
                    "STOCK_UNAVAILABLE",
                    f"Stock '{item.ticker}' is '{getattr(stock, 'status', 'unknown')}', not active",
                    status_code=409,
                )

        # 4. Create Paper Trade
        trade = PaperTrade(
            user_id=user_id,
            recommendation_id=rec.id,
            mode=rec.mode,
            status="OPEN",
            opened_at=now,
            affected_by_universe_change=False,
            created_at=now,
        )
        db.session.add(trade)
        db.session.flush()

        # 5. Create Order BUY Legs and Modeled Entry Costs
        for item in rec.items:
            stock = db.session.get(Stock, item.stock_id)
            fill_price_val = execution_prices.get(item.ticker)
            if fill_price_val is not None:
                fill_price = Decimal(str(fill_price_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            elif stock and getattr(stock, "last_price", None):
                fill_price = stock.last_price
            else:
                fill_price = item.allocated_amount / Decimal(str(item.quantity))
                fill_price = fill_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Compute entry buy leg costs
            buy_cost_res: CostResult = self.cost_engine.calculate_single_leg(
                quantity=item.quantity,
                price=fill_price,
                action="BUY",
                mode=rec.mode,
            )

            cost_breakdown = buy_cost_res.to_breakdown_model()
            db.session.add(cost_breakdown)
            db.session.flush()

            leg = PaperTradeLeg(
                paper_trade_id=trade.id,
                stock_id=item.stock_id,
                ticker=item.ticker,
                action="BUY",
                quantity=item.quantity,
                price=fill_price,
                cost_breakdown_id=cost_breakdown.id,
                executed_at=now,
                created_at=now,
            )
            db.session.add(leg)

        db.session.flush()

        # 6. Store Idempotency Record
        if idempotency_key:
            record = IdempotencyRecord(
                user_id=user_id,
                idempotency_key=idempotency_key,
                request_path=request_path,
                request_hash=payload_hash,
                response_code=201,
                response_body=json.dumps({"trade_id": trade.id, "status": trade.status}),
                created_at=now,
                expires_at=now + datetime.timedelta(hours=24),
            )
            db.session.add(record)

        db.session.commit()
        return trade, False

    def close_paper_trade(
        self,
        paper_trade_id: int,
        user_id: int,
        exit_prices: Optional[Dict[str, Union[Decimal, str, float]]] = None,
        force_delisted: bool = False,
    ) -> PaperTrade:
        """Close an open paper trade and calculate realized net P&L after costs."""
        now = Clock.utcnow()
        exit_prices = exit_prices or {}

        trade = db.session.get(PaperTrade, paper_trade_id)
        if not trade:
            raise PaperTradeError("PAPER_TRADE_NOT_FOUND", "Paper trade not found", status_code=404)

        if trade.user_id is not None and trade.user_id != user_id:
            raise PaperTradeError("FORBIDDEN", "Paper trade does not belong to user", status_code=403)

        if trade.status != "OPEN":
            raise PaperTradeError(
                "TRADE_ALREADY_CLOSED",
                f"Paper trade is already in state '{trade.status}'",
                status_code=400,
            )

        # Collect BUY legs to compute realized returns
        buy_legs = [leg for leg in trade.legs if leg.action == "BUY"]
        if not buy_legs:
            raise PaperTradeError("CORRUPT_TRADE_STATE", "Open paper trade has no BUY legs", status_code=500)

        total_gross_pnl = Decimal("0.00")
        portfolio_trades: List[Tuple[str, str, int, Decimal, Decimal]] = []

        # Create matching SELL legs
        for buy_leg in buy_legs:
            stock = db.session.get(Stock, buy_leg.stock_id)
            isin = stock.isin if stock and stock.isin else f"INE_{buy_leg.ticker}"

            exit_val = exit_prices.get(buy_leg.ticker)
            if exit_val is not None:
                sell_price = Decimal(str(exit_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            elif stock and getattr(stock, "last_price", None):
                sell_price = stock.last_price
            else:
                sell_price = buy_leg.price

            # Leg Gross PnL = (sell_price - buy_price) * quantity
            leg_gross = (sell_price - buy_leg.price) * Decimal(str(buy_leg.quantity))
            total_gross_pnl += leg_gross

            # Compute sell leg costs
            sell_cost_res: CostResult = self.cost_engine.calculate_single_leg(
                quantity=buy_leg.quantity,
                price=sell_price,
                action="SELL",
                mode=trade.mode,
            )
            cost_breakdown = sell_cost_res.to_breakdown_model()
            db.session.add(cost_breakdown)
            db.session.flush()

            sell_leg = PaperTradeLeg(
                paper_trade_id=trade.id,
                stock_id=buy_leg.stock_id,
                ticker=buy_leg.ticker,
                action="SELL",
                quantity=buy_leg.quantity,
                price=sell_price,
                cost_breakdown_id=cost_breakdown.id,
                executed_at=now,
                created_at=now,
            )
            db.session.add(sell_leg)

            portfolio_trades.append(
                (buy_leg.ticker, isin, buy_leg.quantity, buy_leg.price, sell_price)
            )

        # Calculate exact round trip transaction charges across portfolio via CostEngine (FR-CST)
        round_trip_costs: CostResult = self.cost_engine.calculate_portfolio_costs(
            trades=portfolio_trades,
            mode=trade.mode,
        )
        total_modeled_costs = round_trip_costs.total_charges

        # Net Realized P&L = Gross P&L - Total Round-Trip Costs
        total_net_pnl = (total_gross_pnl - total_modeled_costs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        trade.status = "FORCE_CLOSED_DELISTED" if force_delisted else "CLOSED"
        trade.closed_at = now
        trade.total_gross_pnl = total_gross_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        trade.total_net_pnl = total_net_pnl
        if force_delisted:
            trade.affected_by_universe_change = True

        db.session.commit()
        return trade

    def get_user_history(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Retrieve user paper trade execution history distinguishing expected vs realized P&L (EXP-06, AT-34)."""
        stmt = select(PaperTrade).where(PaperTrade.user_id == user_id)
        if status:
            stmt = stmt.where(PaperTrade.status == status.upper())
        stmt = stmt.order_by(PaperTrade.created_at.desc()).limit(limit).offset(offset)

        trades = db.session.execute(stmt).scalars().all()
        history = []
        for t in trades:
            rec = t.recommendation
            expected_pnl = None
            if rec and rec.items:
                # Sum items expected net returns
                expected_gain_sum = sum(
                    (Decimal(str(item.quantity)) * (
                        item.p_i * item.g_plus + (Decimal("1.0") - item.p_i) * item.g_minus
                    )) for item in rec.items
                )
                expected_pnl = str(expected_gain_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

            history.append({
                "trade_id": t.id,
                "recommendation_id": t.recommendation_id,
                "mode": t.mode,
                "status": t.status,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                "affected_by_universe_change": t.affected_by_universe_change,
                "expected_pnl": expected_pnl,  # EXP-06
                "realized_gross_pnl": str(t.total_gross_pnl) if t.total_gross_pnl is not None else None,
                "realized_net_pnl": str(t.total_net_pnl) if t.total_net_pnl is not None else None,
                "legs_count": len(t.legs),
                "disclaimer": "This is an educational simulation. Not investment advice. No real orders are placed.",
            })

        return history
