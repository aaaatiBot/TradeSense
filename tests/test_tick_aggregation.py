"""Acceptance tests for 1-minute Tick Aggregation Service and 1m Feature Extraction (Phase 4.5).

Verifies:
- Accurate OHLCV aggregation from raw ticks across 1-minute buckets.
- Open (first tick), High (max tick), Low (min tick), Close (last tick), Volume (sum).
- Re-aggregation / upsert behavior when late ticks arrive in an existing bucket.
- Feature extraction on 1-minute OHLCV bars via FeatureService.build_features_from_bars.
- Background worker execution of 'tick_aggregate' job type.
"""
from decimal import Decimal
import datetime
import pytest

from app.extensions import db
from app.models.price import Price
from app.models.stock import Stock
from app.models.tick import Tick
from app.services.feature_service import FeatureService
from app.services.tick_aggregation_service import TickAggregationService
from app.workers.job_worker import JobWorker
from app.utils.clock import Clock


@pytest.fixture
def test_stock(app):
    """Seed test stock into database."""
    with app.app_context():
        stock = Stock.query.filter_by(ticker="INFY").first()
        if not stock:
            stock = Stock(
                ticker="INFY",
                name="Infosys Ltd",
                isin="INE009A01021",
                exchange="NSE",
                status="active",
            )
            db.session.add(stock)
            db.session.commit()
            db.session.refresh(stock)
        return stock


def test_ohlcv_aggregation_accuracy(app, test_stock):
    """Verifies that ticks in 1-minute buckets aggregate to accurate Decimal OHLCV values."""
    with app.app_context():
        base_time = datetime.datetime(2026, 3, 11, 10, 0, 0, tzinfo=datetime.timezone.utc)
        Clock.set_fixed(base_time + datetime.timedelta(minutes=5))

        # Bucket 1: 10:01:00 UTC
        t1 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=5),
            price=Decimal("1500.00"),
            volume=10,
            source="fyers",
        )
        t2 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=20),
            price=Decimal("1515.50"),  # High
            volume=25,
            source="fyers",
        )
        t3 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=35),
            price=Decimal("1492.25"),  # Low
            volume=15,
            source="fyers",
        )
        t4 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=50),
            price=Decimal("1508.00"),  # Close
            volume=50,
            source="fyers",
        )

        # Bucket 2: 10:02:00 UTC
        t5 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=2, seconds=10),
            price=Decimal("1508.00"),  # Open
            volume=40,
            source="fyers",
        )
        t6 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=2, seconds=45),
            price=Decimal("1522.00"),  # High & Close
            volume=60,
            source="fyers",
        )

        db.session.add_all([t1, t2, t3, t4, t5, t6])
        db.session.commit()

        # Run aggregation
        count = TickAggregationService.run_once(lookback_minutes=10)
        assert count == 2

        # Verify Bucket 1 bar
        bucket1_dt = base_time + datetime.timedelta(minutes=1)
        bar1 = Price.query.filter_by(stock_id=test_stock.id, timestamp=bucket1_dt).first()
        assert bar1 is not None
        assert bar1.ticker == "INFY"
        assert bar1.open == Decimal("1500.00")
        assert bar1.high == Decimal("1515.50")
        assert bar1.low == Decimal("1492.25")
        assert bar1.close == Decimal("1508.00")
        assert bar1.volume == 10 + 25 + 15 + 50  # 100
        assert bar1.frequency == "1m"

        # Verify Bucket 2 bar
        bucket2_dt = base_time + datetime.timedelta(minutes=2)
        bar2 = Price.query.filter_by(stock_id=test_stock.id, timestamp=bucket2_dt).first()
        assert bar2 is not None
        assert bar2.open == Decimal("1508.00")
        assert bar2.high == Decimal("1522.00")
        assert bar2.low == Decimal("1508.00")
        assert bar2.close == Decimal("1522.00")
        assert bar2.volume == 40 + 60  # 100
        assert bar2.frequency == "1m"


def test_bucket_reaggregation_upsert(app, test_stock):
    """Verifies that late arriving ticks update an existing 1-minute OHLCV bar."""
    with app.app_context():
        base_time = datetime.datetime(2026, 3, 11, 10, 0, 0, tzinfo=datetime.timezone.utc)
        Clock.set_fixed(base_time + datetime.timedelta(minutes=3))

        # Initial tick
        t1 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=10),
            price=Decimal("1500.00"),
            volume=50,
            source="fyers",
        )
        db.session.add(t1)
        db.session.commit()

        TickAggregationService.run_once(lookback_minutes=5)

        bucket1_dt = base_time + datetime.timedelta(minutes=1)
        bar = Price.query.filter_by(stock_id=test_stock.id, timestamp=bucket1_dt).first()
        assert bar.high == Decimal("1500.00")
        assert bar.volume == 50

        # Late arriving tick with higher price
        t2 = Tick(
            ticker="INFY",
            ts_utc=base_time + datetime.timedelta(minutes=1, seconds=45),
            price=Decimal("1535.00"),
            volume=30,
            source="fyers",
        )
        db.session.add(t2)
        db.session.commit()

        TickAggregationService.run_once(lookback_minutes=5)

        # Refresh
        db.session.expire_all()
        updated_bar = Price.query.filter_by(stock_id=test_stock.id, timestamp=bucket1_dt).first()
        assert updated_bar.high == Decimal("1535.00")
        assert updated_bar.close == Decimal("1535.00")
        assert updated_bar.volume == 80


def test_feature_extraction_from_1m_bars(app, test_stock):
    """Verifies that FeatureService calculates technical indicators on 1-minute series."""
    with app.app_context():
        bars = []
        base_dt = datetime.datetime(2026, 3, 11, 9, 30, 0, tzinfo=datetime.timezone.utc)

        # Generate 40 synthetic 1-minute bars
        for i in range(40):
            price_val = Decimal(str(1500.0 + i * 2.0))
            bar = Price(
                stock_id=test_stock.id,
                ticker="INFY",
                timestamp=base_dt + datetime.timedelta(minutes=i),
                open=price_val - Decimal("1.0"),
                high=price_val + Decimal("2.0"),
                low=price_val - Decimal("2.0"),
                close=price_val,
                volume=1000 + i * 50,
                frequency="1m",
                source="tick_aggregation",
            )
            bars.append(bar)

        db.session.add_all(bars)
        db.session.commit()

        # Extract features using 1m bars
        features = FeatureService.build_features_from_bars(bars, frequency="1m")

        assert features["frequency"] == "1m"
        assert features["current_close"] == 1500.0 + 39 * 2.0
        assert features["sma_5"] is not None
        assert features["sma_20"] is not None
        assert features["rsi_14"] is not None
        assert features["macd"] is not None
        assert features["vol_ratio"] is not None


def test_job_worker_processes_tick_aggregation(app, test_stock):
    """Verifies that JobWorker claims and executes 'tick_aggregate' background job."""
    with app.app_context():
        now = Clock.utcnow()
        t = Tick(
            ticker="INFY",
            ts_utc=now - datetime.timedelta(seconds=30),
            price=Decimal("1550.00"),
            volume=100,
            source="fyers",
        )
        db.session.add(t)
        db.session.commit()

        worker = JobWorker(app=app)
        job = JobWorker.enqueue_job("tick_aggregate", {"lookback_minutes": 5})
        assert job.status == "QUEUED"

        did_run = worker.run_once()
        assert did_run is True

        db.session.expire_all()
        updated_job = db.session.get(type(job), job.id)
        assert updated_job.status == "COMPLETED"
