"""Acceptance tests for Market Data Fallback and Live Tick Cache Integration (Phase 4.5).

Verifies:
- get_quote returns live tick from in-memory cache when fresh (is_live=True, is_stale=False).
- get_quote falls back to database / REST path when cache is stale (> 5 seconds during market hours).
- get_quote falls back to database / REST path when cache is empty.
- get_latest_tick always queries the cache directly without database fallback.
- Proper error handling (MarketDataError 404) for unknown stocks with no price history.
"""
from decimal import Decimal
import datetime
import pytest

from app.extensions import db
from app.models.price import Price
from app.models.stock import Stock
from app.services.live_tick_service import clear_tick_cache, set_cached_tick
from app.services.market_data_service import MarketDataError, MarketDataService
from app.utils.clock import Clock


@pytest.fixture(autouse=True)
def clean_cache():
    """Clear in-memory tick cache before and after test."""
    clear_tick_cache()
    yield
    clear_tick_cache()


@pytest.fixture
def test_stock_with_db_price(app):
    """Seed test stock and database historical price record."""
    with app.app_context():
        stock = Stock.query.filter_by(ticker="TCS").first()
        if not stock:
            stock = Stock(
                ticker="TCS",
                name="Tata Consultancy Services",
                isin="INE467B01029",
                exchange="NSE",
                status="active",
            )
            db.session.add(stock)
            db.session.commit()
            db.session.refresh(stock)

        db_price = Price(
            stock_id=stock.id,
            ticker="TCS",
            timestamp=datetime.datetime(2026, 3, 11, 9, 15, 0, tzinfo=datetime.timezone.utc),
            open=Decimal("3800.00"),
            high=Decimal("3850.00"),
            low=Decimal("3790.00"),
            close=Decimal("3820.00"),
            volume=50000,
            frequency="1d",
            source="eod_rest",
        )
        db.session.add(db_price)
        db.session.commit()
        return stock


def test_quote_returns_cached_tick_when_fresh(app, test_stock_with_db_price):
    """Verifies that get_quote serves from live cache when tick is within 5 seconds."""
    with app.app_context():
        # Set market hours: Wednesday 11:00 AM IST
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_market = datetime.datetime(2026, 3, 11, 11, 0, 0, tzinfo=ist)
        Clock.set_fixed(now_market)

        # Store a fresh tick in cache (1 second old)
        fresh_time = Clock.utcnow() - datetime.timedelta(seconds=1)
        set_cached_tick("TCS", {
            "ticker": "TCS",
            "price": Decimal("3845.50"),
            "volume": 200,
            "ts_utc": fresh_time,
            "source": "fyers_ws",
        })

        quote = MarketDataService.get_quote("TCS")

        assert quote["ticker"] == "TCS"
        assert quote["price"] == Decimal("3845.50")
        assert quote["is_live"] is True
        assert quote["is_stale"] is False
        assert quote["source"] == "fyers_ws"


def test_quote_falls_back_to_db_when_cache_is_stale_in_market_hours(app, test_stock_with_db_price):
    """Verifies that get_quote falls back to database when cached tick is > 5s old during market hours."""
    with app.app_context():
        # Wednesday 11:30 AM IST (active market hours)
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_market = datetime.datetime(2026, 3, 11, 11, 30, 0, tzinfo=ist)
        Clock.set_fixed(now_market)

        # Stale tick (15 seconds old)
        stale_time = Clock.utcnow() - datetime.timedelta(seconds=15)
        set_cached_tick("TCS", {
            "ticker": "TCS",
            "price": Decimal("3899.00"),
            "volume": 10,
            "ts_utc": stale_time,
            "source": "fyers_ws",
        })

        # Cache says stale, so get_quote falls back to database price (3820.00)
        quote = MarketDataService.get_quote("TCS")

        assert quote["ticker"] == "TCS"
        assert quote["price"] == Decimal("3820.00")
        assert quote["is_live"] is False
        assert quote["is_stale"] is True
        assert quote["source"] == "eod_rest"


def test_quote_falls_back_to_db_when_cache_is_empty(app, test_stock_with_db_price):
    """Verifies get_quote serves from database when cache is completely empty."""
    with app.app_context():
        # Empty cache
        clear_tick_cache()

        quote = MarketDataService.get_quote("TCS")

        assert quote["ticker"] == "TCS"
        assert quote["price"] == Decimal("3820.00")
        assert quote["is_live"] is False
        assert quote["is_stale"] is False
        assert quote["source"] == "eod_rest"


def test_get_latest_tick_only_reads_cache():
    """Verifies get_latest_tick returns None on cache miss without querying database."""
    clear_tick_cache()
    assert MarketDataService.get_latest_tick("TCS") is None

    set_cached_tick("TCS", {
        "ticker": "TCS",
        "price": Decimal("3810.00"),
        "ts_utc": Clock.utcnow(),
    })
    cached = MarketDataService.get_latest_tick("TCS")
    assert cached is not None
    assert cached["price"] == Decimal("3810.00")


def test_quote_unknown_stock_raises_error(app):
    """Verifies unknown stock with no cache and no DB raises MarketDataError 404."""
    with app.app_context():
        with pytest.raises(MarketDataError) as exc_info:
            MarketDataService.get_quote("NON_EXISTENT_TICKER")

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "STOCK_NOT_FOUND"
