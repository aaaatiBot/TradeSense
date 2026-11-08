"""Tick aggregation service per Phase 4.5.

Aggregates raw tick events from the `ticks` table into 1-minute OHLCV price bars
and upserts them into the durable `prices` table with frequency='1m'.
"""
from __future__ import annotations

from collections import defaultdict
import datetime
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from app.extensions import db
from app.models.price import Price
from app.models.stock import Stock
from app.models.tick import Tick
from app.services.universe_service import UniverseService
from app.utils.clock import Clock

logger = logging.getLogger("tradesense.tick_aggregation")


class TickAggregationService:
    """Aggregates high-frequency ticks into 1-minute OHLCV bars."""

    @classmethod
    def run_once(
        cls,
        since: Optional[datetime.datetime] = None,
        lookback_minutes: int = 5,
    ) -> int:
        """Run a single pass of tick aggregation over recent ticks.
        
        Args:
            since: Minimum tick timestamp to process. Defaults to now - lookback_minutes.
            lookback_minutes: Default window if since is not specified.
            
        Returns:
            Number of 1-minute OHLCV bars created or updated.
        """
        now = Clock.utcnow()
        min_ts = since or (now - datetime.timedelta(minutes=lookback_minutes))
        min_ts_utc = Clock.ensure_utc(min_ts)

        # Retrieve ticks within the time window ordered chronologically
        stmt = (
            select(Tick)
            .where(Tick.ts_utc >= min_ts_utc)
            .order_by(Tick.ticker.asc(), Tick.ts_utc.asc(), Tick.id.asc())
        )
        ticks = db.session.execute(stmt).scalars().all()
        if not ticks:
            logger.debug(f"No ticks found since {min_ts_utc}")
            return 0

        # Group ticks by (ticker, minute_bucket)
        grouped: Dict[tuple[str, datetime.datetime], List[Tick]] = defaultdict(list)
        for t in ticks:
            bucket = Clock.ensure_utc(t.ts_utc).replace(second=0, microsecond=0)
            grouped[(t.ticker.upper().strip(), bucket)].append(t)

        bars_count = 0
        stock_cache: Dict[str, Optional[Stock]] = {}

        for (ticker, bucket), bucket_ticks in grouped.items():
            if ticker not in stock_cache:
                stock_cache[ticker] = UniverseService.get_stock(ticker)

            stock = stock_cache[ticker]
            if stock is None:
                # If stock not found in DB, skip bar insertion
                logger.warning(f"Skipping tick aggregation for unknown stock '{ticker}'")
                continue

            # Calculate OHLCV
            open_price = bucket_ticks[0].price
            close_price = bucket_ticks[-1].price
            high_price = max(t.price for t in bucket_ticks)
            low_price = min(t.price for t in bucket_ticks)
            volume = sum(t.volume for t in bucket_ticks)

            # Check if bar already exists
            existing_price = db.session.execute(
                select(Price).where(
                    Price.stock_id == stock.id,
                    Price.timestamp == bucket,
                )
            ).scalar_one_or_none()

            if existing_price is None:
                bar = Price(
                    stock_id=stock.id,
                    ticker=stock.ticker,
                    timestamp=bucket,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    frequency="1m",
                    source="tick_aggregation",
                )
                db.session.add(bar)
            else:
                existing_price.high = max(existing_price.high, high_price)
                existing_price.low = min(existing_price.low, low_price)
                existing_price.close = close_price
                existing_price.volume = volume
                existing_price.frequency = "1m"
                existing_price.source = "tick_aggregation"

            bars_count += 1

        db.session.commit()
        logger.info(f"Aggregated {len(ticks)} ticks into {bars_count} 1-minute bars")
        return bars_count
