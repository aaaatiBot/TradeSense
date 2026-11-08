"""Acceptance Tests for Market Data, Features, and Universe Service (AT-05, AT-06, AT-19, AT-41)."""
import datetime
from decimal import Decimal
import pytest

from app.extensions import db
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.stock import Stock
from app.services.feature_service import FeatureService
from app.services.market_data_service import MarketDataService, MarketDataError
from app.services.universe_service import UniverseService, UniverseError
from app.utils.clock import Clock


# ==============================================================================
# AT-05: Market Data Integrity & Sequence Validation
# ==============================================================================
def test_at_05_bar_integrity_rejections():
    """AT-05: Rejects negative prices, inverted high/low, and invalid bounds."""
    now = Clock.utcnow()

    # 1. Negative price
    with pytest.raises(MarketDataError, match="strictly positive"):
        MarketDataService.validate_bar(
            open_val=Decimal("-10.0"), high_val=Decimal("15.0"), low_val=Decimal("5.0"),
            close_val=Decimal("12.0"), volume=1000, timestamp=now
        )

    # 2. Inverted High < Low
    with pytest.raises(MarketDataError, match="High .* cannot be lower than Low"):
        MarketDataService.validate_bar(
            open_val=Decimal("100.0"), high_val=Decimal("90.0"), low_val=Decimal("95.0"),
            close_val=Decimal("92.0"), volume=1000, timestamp=now
        )

    # 3. High < Open or Close
    with pytest.raises(MarketDataError, match="High .* must be >= Open"):
        MarketDataService.validate_bar(
            open_val=Decimal("110.0"), high_val=Decimal("105.0"), low_val=Decimal("95.0"),
            close_val=Decimal("100.0"), volume=1000, timestamp=now
        )

    # 4. Low > Open or Close
    with pytest.raises(MarketDataError, match="Low .* must be <= Open"):
        MarketDataService.validate_bar(
            open_val=Decimal("90.0"), high_val=Decimal("105.0"), low_val=Decimal("95.0"),
            close_val=Decimal("100.0"), volume=1000, timestamp=now
        )

    # 5. Negative volume
    with pytest.raises(MarketDataError, match="Volume cannot be negative"):
        MarketDataService.validate_bar(
            open_val=Decimal("100.0"), high_val=Decimal("105.0"), low_val=Decimal("95.0"),
            close_val=Decimal("100.0"), volume=-50, timestamp=now
        )


def test_at_05_sequence_time_order():
    """AT-05: Rejects non-monotonic / out-of-order timestamps in bar sequences."""
    base_t = Clock.utcnow()
    bars = [
        {"timestamp": base_t, "open": 100, "high": 105, "low": 95, "close": 102, "volume": 100},
        {"timestamp": base_t - datetime.timedelta(minutes=1), "open": 102, "high": 106, "low": 98, "close": 103, "volume": 100},
    ]
    with pytest.raises(MarketDataError, match="TIME_ORDER_INVALID"):
        MarketDataService.validate_sequence(bars)


# ==============================================================================
# AT-06: Stale Market Data Detection
# ==============================================================================
def test_at_06_stale_data_detection():
    """AT-06: Rejects data older than staleness threshold (default 24h)."""
    now = Clock.utcnow()
    fresh_time = now - datetime.timedelta(hours=2)
    stale_time = now - datetime.timedelta(hours=25)

    assert MarketDataService.check_freshness(fresh_time, max_staleness_hours=24) is True

    with pytest.raises(MarketDataError, match="STALE_MARKET_DATA"):
        MarketDataService.check_freshness(stale_time, max_staleness_hours=24)


def test_market_data_ingest_and_retrieval(app):
    """Verify market data ingestion into database and chronological querying."""
    stock = Stock(ticker="INFY", name="Infosys Ltd", isin="INE009A01021", status="active")
    db.session.add(stock)
    db.session.commit()

    base_time = Clock.utcnow() - datetime.timedelta(days=5)
    bars = [
        {"timestamp": base_time + datetime.timedelta(days=1), "open": 1400, "high": 1420, "low": 1390, "close": 1410, "volume": 50000},
        {"timestamp": base_time + datetime.timedelta(days=2), "open": 1410, "high": 1435, "low": 1405, "close": 1430, "volume": 60000},
    ]

    count = MarketDataService.ingest_bars("INFY", bars)
    assert count == 2

    # Ingest again with update
    bars_updated = [
        {"timestamp": base_time + datetime.timedelta(days=1), "open": 1400, "high": 1420, "low": 1390, "close": 1415, "volume": 55000},
    ]
    count_update = MarketDataService.ingest_bars("INFY", bars_updated)
    assert count_update == 0  # updated existing row

    retrieved = MarketDataService.get_historical_prices("INFY")
    assert len(retrieved) == 2
    assert retrieved[0].close == Decimal("1415.0000")


# ==============================================================================
# AT-19: Feature Engineering Leak-Free Verification
# ==============================================================================
def test_at_19_leak_free_feature_extraction():
    """AT-19: Verify technical features at time t depend strictly on data <= t."""
    base_time = datetime.datetime(2026, 1, 1, 9, 15, tzinfo=datetime.timezone.utc)
    bars = []
    for i in range(30):
        bars.append({
            "timestamp": base_time + datetime.timedelta(days=i),
            "close": 100.0 + i * 2.0,
            "volume": 1000 + i * 10,
        })

    # Extract features at index 15
    feat_t15_original = FeatureService.extract_features_at_point(bars, target_index=15)

    # Now alter future bar (index 20) drastically
    bars_corrupted_future = [dict(b) for b in bars]
    bars_corrupted_future[20]["close"] = 99999.0
    bars_corrupted_future[20]["volume"] = 9999999

    feat_t15_after_future_change = FeatureService.extract_features_at_point(bars_corrupted_future, target_index=15)

    # Past features at t=15 must be exactly identical (zero lookahead leakage)
    assert feat_t15_original["sma_5"] == feat_t15_after_future_change["sma_5"]
    assert feat_t15_original["sma_20"] == feat_t15_after_future_change["sma_20"]
    assert feat_t15_original["ret_1d"] == feat_t15_after_future_change["ret_1d"]
    assert feat_t15_original["rsi_14"] == feat_t15_after_future_change["rsi_14"]


# ==============================================================================
# AT-41: Universe-Change Handling & Delisting Protections (SRS §6.5)
# ==============================================================================
def test_at_41_universe_change_rejection(app):
    """AT-41: Rejects paper trade on suspended or delisted stocks with STOCK_UNAVAILABLE."""
    stock = Stock(
        ticker="TATAMOTORS",
        name="Tata Motors Ltd",
        isin="INE155A01022",
        exchange="NSE",
        status="active",
    )
    db.session.add(stock)
    db.session.commit()

    # Active stock can be traded
    active_stock = UniverseService.validate_stock_active_for_trade("TATAMOTORS")
    assert active_stock.status == "active"

    # Administrator suspends the stock
    UniverseService.set_stock_status("TATAMOTORS", "suspended", actor="admin")

    # Trading is immediately blocked with STOCK_UNAVAILABLE (AT-41)
    with pytest.raises(UniverseError) as exc_info:
        UniverseService.validate_stock_active_for_trade("TATAMOTORS")
    assert exc_info.value.code == "STOCK_UNAVAILABLE"


def test_at_41_delisting_force_close_open_trades(app):
    """AT-41: Stock delisting force-closes open trades with FORCE_CLOSED_DELISTED."""
    stock = Stock(
        ticker="DELISTEDCO",
        name="Delisted Corporation",
        isin="INE999X01011",
        exchange="NSE",
        status="active",
    )
    db.session.add(stock)
    db.session.commit()

    # Create dummy open trade
    trade = PaperTrade(
        user_id=None,
        recommendation_id=1,
        mode="CNC",
        status="OPEN",
        opened_at=Clock.utcnow(),
    )
    db.session.add(trade)
    db.session.flush()

    leg = PaperTradeLeg(
        paper_trade_id=trade.id,
        stock_id=stock.id,
        ticker="DELISTEDCO",
        action="BUY",
        quantity=10,
        price=Decimal("100.00"),
        executed_at=Clock.utcnow(),
    )
    db.session.add(leg)
    db.session.commit()

    # Delist the stock
    UniverseService.set_stock_status("DELISTEDCO", "delisted", actor="compliance_admin")

    # Verify open trade was force-closed
    reloaded_trade = db.session.get(PaperTrade, trade.id)
    assert reloaded_trade.status == "FORCE_CLOSED_DELISTED"
    assert reloaded_trade.affected_by_universe_change is True
    assert reloaded_trade.closed_at is not None
