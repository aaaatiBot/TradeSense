"""Market data ingestion, validation, and freshness service per SRS §4.3 (FR-MKT)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from app.extensions import db
from app.models.price import Price
from app.models.stock import Stock
from app.services.universe_service import UniverseService
from app.utils.clock import Clock


class MarketDataError(Exception):
    """Exception raised for market data integrity, corruption, or staleness failures."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class MarketDataService:
    """Ingests, validates, and manages OHLCV market price series."""

    DEFAULT_MAX_STALENESS_HOURS = 24

    @classmethod
    def validate_bar(
        cls,
        open_val: Decimal,
        high_val: Decimal,
        low_val: Decimal,
        close_val: Decimal,
        volume: int,
        timestamp: datetime.datetime,
    ) -> None:
        """Validate single price bar integrity (AT-05)."""
        if open_val <= 0 or high_val <= 0 or low_val <= 0 or close_val <= 0:
            raise MarketDataError("INVALID_PRICE", "All price components (O,H,L,C) must be strictly positive")
        if volume < 0:
            raise MarketDataError("INVALID_VOLUME", "Volume cannot be negative")
        if high_val < low_val:
            raise MarketDataError("CORRUPTED_BAR", f"High ({high_val}) cannot be lower than Low ({low_val})")
        if high_val < open_val or high_val < close_val:
            raise MarketDataError("CORRUPTED_BAR", f"High ({high_val}) must be >= Open ({open_val}) and Close ({close_val})")
        if low_val > open_val or low_val > close_val:
            raise MarketDataError("CORRUPTED_BAR", f"Low ({low_val}) must be <= Open ({open_val}) and Close ({close_val})")

    @classmethod
    def validate_sequence(cls, bars: List[Dict[str, Any]]) -> None:
        """Validate a sequence of bars for monotonic time ordering and integrity (AT-05)."""
        if not bars:
            return

        last_dt: Optional[datetime.datetime] = None
        for i, bar in enumerate(bars):
            ts = bar["timestamp"]
            ts_utc = Clock.ensure_utc(ts)
            if last_dt is not None and ts_utc <= last_dt:
                raise MarketDataError(
                    "TIME_ORDER_INVALID",
                    f"Bar at index {i} timestamp ({ts_utc}) is not strictly greater than previous ({last_dt})",
                )
            cls.validate_bar(
                open_val=Decimal(str(bar["open"])),
                high_val=Decimal(str(bar["high"])),
                low_val=Decimal(str(bar["low"])),
                close_val=Decimal(str(bar["close"])),
                volume=int(bar["volume"]),
                timestamp=ts_utc,
            )
            last_dt = ts_utc

    @classmethod
    def check_freshness(
        cls,
        latest_timestamp: datetime.datetime,
        max_staleness_hours: Optional[int] = None,
    ) -> bool:
        """Check if market data timestamp is within staleness threshold (AT-06)."""
        limit = max_staleness_hours or cls.DEFAULT_MAX_STALENESS_HOURS
        now = Clock.utcnow()
        ts_utc = Clock.ensure_utc(latest_timestamp)
        age = now - ts_utc
        if age > datetime.timedelta(hours=limit):
            raise MarketDataError(
                "STALE_MARKET_DATA",
                f"Market data timestamp ({ts_utc.isoformat()}) exceeds max staleness limit of {limit}h (age: {age.total_seconds() / 3600:.1f}h)",
            )
        return True

    @classmethod
    def ingest_bars(
        cls,
        ticker: str,
        bars: List[Dict[str, Any]],
        source: str = "market_data",
    ) -> int:
        """Validate and insert price bars into database."""
        stock = UniverseService.get_stock(ticker)
        if stock is None:
            raise MarketDataError("STOCK_NOT_FOUND", f"Cannot ingest data for unknown stock '{ticker}'", status_code=404)

        cls.validate_sequence(bars)
        count = 0
        for b in bars:
            ts = Clock.ensure_utc(b["timestamp"])
            # Upsert or insert price
            existing = db.session.execute(
                select(Price).where(Price.stock_id == stock.id, Price.timestamp == ts)
            ).scalar_one_or_none()

            if existing is None:
                price = Price(
                    stock_id=stock.id,
                    ticker=stock.ticker,
                    timestamp=ts,
                    open=Decimal(str(b["open"])),
                    high=Decimal(str(b["high"])),
                    low=Decimal(str(b["low"])),
                    close=Decimal(str(b["close"])),
                    volume=int(b["volume"]),
                    source=source,
                )
                db.session.add(price)
                count += 1
            else:
                existing.open = Decimal(str(b["open"]))
                existing.high = Decimal(str(b["high"]))
                existing.low = Decimal(str(b["low"]))
                existing.close = Decimal(str(b["close"]))
                existing.volume = int(b["volume"])

        db.session.commit()
        return count

    @classmethod
    def get_historical_prices(cls, ticker: str, limit: int = 100) -> List[Price]:
        """Retrieve recent historical prices in chronological order."""
        stock = UniverseService.get_stock(ticker)
        if stock is None:
            return []
        return list(
            db.session.execute(
                select(Price)
                .where(Price.stock_id == stock.id)
                .order_by(Price.timestamp.asc())
                .limit(limit)
            ).scalars().all()
        )
