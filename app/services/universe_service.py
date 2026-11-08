"""Stock universe lifecycle service per SRS §6.5 (v3.1) and UNI-01 through UNI-05."""
from __future__ import annotations

from typing import List, Optional
from sqlalchemy import select

from app.extensions import db
from app.models.paper_trade import PaperTrade
from app.models.stock import Stock
from app.utils.clock import Clock
from app.utils.logger import logger

VALID_STOCK_STATUSES = {"active", "suspended", "delisted", "under_surveillance"}


class UniverseError(Exception):
    """Exception raised for stock universe or availability violations."""
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class UniverseService:
    """Manages stock universe, status changes, and trade safeguards."""

    @classmethod
    def get_stock(cls, ticker: str) -> Optional[Stock]:
        """Fetch stock by ticker symbol."""
        return db.session.execute(
            select(Stock).where(Stock.ticker == ticker.strip().upper())
        ).scalar_one_or_none()

    @classmethod
    def list_active_stocks(cls) -> List[Stock]:
        """List all active stocks eligible for recommendations (UNI-01)."""
        return list(
            db.session.execute(
                select(Stock).where(Stock.status == "active").order_by(Stock.ticker)
            ).scalars().all()
        )

    @classmethod
    def set_stock_status(cls, ticker: str, new_status: str, actor: str = "admin") -> Stock:
        """Update a stock's lifecycle status and handle impacted open trades (UNI-01, UNI-04, UNI-05)."""
        clean_status = new_status.strip().lower()
        if clean_status not in VALID_STOCK_STATUSES:
            raise ValueError(f"Invalid stock status '{new_status}'. Allowed: {VALID_STOCK_STATUSES}")

        stock = cls.get_stock(ticker)
        if stock is None:
            raise UniverseError("STOCK_NOT_FOUND", f"Stock '{ticker}' not found in universe", status_code=404)

        old_status = stock.status
        if old_status == clean_status:
            return stock

        stock.status = clean_status
        now = Clock.utcnow()

        # Audit log status transition (UNI-05)
        logger.info(
            f"Stock universe status changed for {stock.ticker}: {old_status} -> {clean_status}",
            extra={
                "extra_data": {
                    "event": "universe_status_change",
                    "ticker": stock.ticker,
                    "old_status": old_status,
                    "new_status": clean_status,
                    "actor": actor,
                    "timestamp": now.isoformat(),
                }
            },
        )

        # UNI-04: If delisted, force-close open paper trades
        if clean_status == "delisted":
            cls._force_close_delisted_trades(stock.id, now)

        db.session.commit()
        return stock

    @classmethod
    def validate_stock_active_for_trade(cls, ticker: str) -> Stock:
        """Verify stock is strictly 'active' prior to opening a paper trade (UNI-03, AT-41)."""
        stock = cls.get_stock(ticker)
        if stock is None:
            raise UniverseError("STOCK_UNAVAILABLE", f"Stock '{ticker}' does not exist", status_code=409)

        if stock.status != "active":
            raise UniverseError(
                "STOCK_UNAVAILABLE",
                f"Stock '{ticker}' is currently {stock.status} and cannot be traded",
                status_code=409,
            )
        return stock

    @classmethod
    def _force_close_delisted_trades(cls, stock_id: int, closed_at) -> None:
        """Force close open paper trades containing delisted stock (UNI-04)."""
        open_trades = db.session.execute(
            select(PaperTrade).where(PaperTrade.status == "OPEN")
        ).scalars().all()

        for trade in open_trades:
            has_stock = any(leg.stock_id == stock_id for leg in trade.legs)
            if has_stock:
                trade.status = "FORCE_CLOSED_DELISTED"
                trade.closed_at = closed_at
                trade.affected_by_universe_change = True
                logger.warning(
                    f"Paper trade #{trade.id} force-closed due to stock delisting (stock_id={stock_id})"
                )
