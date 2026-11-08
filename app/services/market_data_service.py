"""Market data ingestion, validation, and freshness service per SRS §4.3 (FR-MKT)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from app.extensions import db
from app.models.price import Price
from app.models.stock import Stock
from app.services.live_tick_service import LiveTickService, get_cached_tick, set_cached_tick
from app.services.universe_service import UniverseService
from app.utils.clock import Clock
from app.utils.logger import logger


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
    def get_latest_tick(cls, ticker: str) -> Optional[Dict[str, Any]]:
        """Always reads latest tick directly from in-memory cache."""
        return get_cached_tick(ticker)

    @classmethod
    def poll_latest_prices(cls, tickers: Optional[List[str]] = None) -> Dict[str, Any]:
        """Poll latest market data using yfinance (Phase D).
        
        Fetches 1-minute OHLCV bars using the .NS suffix for Indian equities (e.g. RELIANCE.NS).
        Parses data, updates the in-memory tick cache, and inserts OHLCV bars into `prices`.
        Handles cases where Yahoo returns empty data.
        """
        import yfinance as yf

        if not tickers:
            active_stocks = UniverseService.list_active_stocks()
            tickers = [s.ticker for s in active_stocks] if active_stocks else ["RELIANCE", "TCS", "INFY"]

        clean_tickers = [t.replace(".NS", "").upper().strip() for t in tickers]
        results = {"polled": clean_tickers, "success": [], "failed": [], "bars_count": 0}

        for ticker in clean_tickers:
            yf_symbol = f"{ticker}.NS" if not ticker.endswith(".NS") else ticker
            try:
                ticker_obj = yf.Ticker(yf_symbol)
                df = ticker_obj.history(period="1d", interval="1m")

                if df is None or df.empty:
                    df = ticker_obj.history(period="5d", interval="1m")

                if df is None or df.empty:
                    results["failed"].append(ticker)
                    continue

                stock = UniverseService.get_stock(ticker)
                if stock is None:
                    # Auto-provision stock entity in active universe so price bars link foreign key
                    stock = Stock(
                        ticker=ticker,
                        name=f"{ticker} Limited",
                        isin=f"IN{ticker[:8].ljust(8, '0')}01",
                        exchange="NSE",
                        status="active",
                    )
                    db.session.add(stock)
                    db.session.flush()

                bars_for_ticker = 0

                for idx, row in df.tail(10).iterrows():
                    bar_dt = Clock.ensure_utc(idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx)
                    o_val = Decimal(str(round(float(row["Open"]), 4)))
                    h_val = Decimal(str(round(float(row["High"]), 4)))
                    l_val = Decimal(str(round(float(row["Low"]), 4)))
                    c_val = Decimal(str(round(float(row["Close"]), 4)))
                    v_val = int(row["Volume"])

                    if stock is not None:
                        existing = db.session.execute(
                            select(Price).where(
                                Price.stock_id == stock.id,
                                Price.timestamp == bar_dt,
                            )
                        ).scalar_one_or_none()

                        if existing is None:
                            new_price = Price(
                                stock_id=stock.id,
                                ticker=ticker,
                                timestamp=bar_dt,
                                open=o_val,
                                high=h_val,
                                low=l_val,
                                close=c_val,
                                volume=v_val,
                                frequency="1m",
                                source="yfinance",
                            )
                            db.session.add(new_price)
                        else:
                            existing.high = max(existing.high, h_val)
                            existing.low = min(existing.low, l_val)
                            existing.close = c_val
                            existing.volume = v_val
                            existing.source = "yfinance"

                        bars_for_ticker += 1

                # Update in-memory latest tick cache
                latest_row = df.iloc[-1]
                latest_dt = Clock.ensure_utc(df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1])
                latest_close = Decimal(str(round(float(latest_row["Close"]), 4)))
                latest_vol = int(latest_row["Volume"])

                set_cached_tick(ticker, {
                    "ticker": ticker,
                    "price": latest_close,
                    "volume": latest_vol,
                    "ts_utc": latest_dt,
                    "source": "yfinance",
                })

                results["success"].append(ticker)
                results["bars_count"] += bars_for_ticker

            except Exception as exc:
                logger.warning(f"Error polling market data for {ticker}: {exc}")
                results["failed"].append(ticker)

        db.session.commit()
        return results

    @classmethod
    def get_quote(cls, ticker: str) -> Dict[str, Any]:
        """Fetch stock quote with yfinance polling and 15-minute staleness check (SRS §4.3).
        
        Reads from latest cache or prices table populated by poll_latest_prices.
        Flags quote as is_stale=True if older than 15 minutes during market hours.
        """
        cached = cls.get_latest_tick(ticker)
        now = Clock.utcnow()
        in_market_hours = LiveTickService.is_market_hours(now)
        staleness_limit_15m = 15.0 * 60.0

        if cached is not None:
            ts = cached.get("ts_utc")
            ts_utc = Clock.ensure_utc(ts) if ts else now
            age_seconds = (now - ts_utc).total_seconds()
            source = cached.get("source", "live_tick_cache")

            # Realtime/WebSocket tick cache expires after 5s during market hours;
            # yfinance polling feed expires after 15m.
            cache_ttl = 5.0 if source in ("fyers_ws", "market_simulator", "live_tick_cache") else staleness_limit_15m
            cache_is_stale = in_market_hours and (age_seconds > cache_ttl)

            if not cache_is_stale:
                is_live = source in ("fyers_ws", "market_simulator", "live_tick_cache")
                return {
                    "ticker": ticker.upper().strip(),
                    "price": cached["price"],
                    "volume": cached.get("volume", 0),
                    "timestamp": ts_utc,
                    "source": source,
                    "is_live": is_live,
                    "is_delayed": source == "yfinance",
                    "is_stale": False,
                }

        # Fallback to database / REST persistence layer
        stock = UniverseService.get_stock(ticker)
        if stock is None:
            raise MarketDataError("STOCK_NOT_FOUND", f"Stock '{ticker}' not found in active universe", status_code=404)

        latest_price_row = db.session.execute(
            select(Price)
            .where(Price.stock_id == stock.id)
            .order_by(Price.timestamp.desc())
            .limit(1)
        ).scalar_one_or_none()

        if latest_price_row is not None:
            ts_utc = Clock.ensure_utc(latest_price_row.timestamp)
            age_seconds = (now - ts_utc).total_seconds()
            is_stale_15m = in_market_hours and (age_seconds > staleness_limit_15m)
            was_cache_stale = cached is not None

            return {
                "ticker": ticker.upper().strip(),
                "price": latest_price_row.close,
                "volume": latest_price_row.volume,
                "timestamp": latest_price_row.timestamp,
                "source": latest_price_row.source or "prices_table",
                "is_live": False,
                "is_delayed": True,
                "is_stale": was_cache_stale or is_stale_15m,
            }

        last_p = getattr(stock, "last_price", None)
        if last_p is not None and last_p > 0:
            return {
                "ticker": ticker.upper().strip(),
                "price": Decimal(str(last_p)),
                "volume": 0,
                "timestamp": now,
                "source": "stock_metadata",
                "is_live": False,
                "is_delayed": True,
                "is_stale": True,
            }

        raise MarketDataError("PRICE_NOT_FOUND", f"No price data available for '{ticker}'", status_code=404)


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
