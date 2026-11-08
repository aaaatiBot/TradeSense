"""Acceptance tests for Live WebSocket Tick Ingestion Service (Phase 4.5).

Verifies:
- Tick validation (strictly positive price, non-negative volume, valid ticker).
- Thread-safe in-memory latest tick caching and DB persistence to `ticks` table.
- Disconnection handling and exponential backoff retry scheduling via `job_queue`.
- Max retries threshold and halt behavior.
- Market hours detection (09:15 - 15:30 IST, Mon-Fri).
- Tick staleness checking against 5-second threshold.
"""
from decimal import Decimal
import datetime
import json
import pytest

from app.extensions import db
from app.models.job import JobQueue
from app.models.tick import Tick
from app.services.live_tick_service import (
    LiveTickService,
    clear_tick_cache,
    get_cached_tick,
    set_cached_tick,
)
from app.utils.clock import Clock


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure in-memory tick cache is cleared before and after each test."""
    clear_tick_cache()
    yield
    clear_tick_cache()


def test_tick_validation_and_persistence(app):
    """Verifies valid tick writes to database and updates thread-safe memory cache."""
    with app.app_context():
        service = LiveTickService(app=app)
        now = Clock.utcnow()

        tick_record = service.on_tick({
            "ticker": "INFY",
            "price": Decimal("1520.50"),
            "volume": 125,
            "timestamp": now,
            "source": "fyers",
        })

        assert tick_record.id is not None
        assert tick_record.ticker == "INFY"
        assert tick_record.price == Decimal("1520.50")
        assert tick_record.volume == 125
        assert tick_record.source == "fyers"

        # Check in-memory cache
        cached = service.get_latest_tick("INFY")
        assert cached is not None
        assert cached["ticker"] == "INFY"
        assert cached["price"] == Decimal("1520.50")
        assert cached["volume"] == 125

        # Check DB query
        saved = db.session.get(Tick, tick_record.id)
        assert saved is not None
        assert saved.price == Decimal("1520.50")


def test_tick_validation_errors(app):
    """Verifies that invalid tick prices, empty tickers, or negative volumes are rejected."""
    with app.app_context():
        service = LiveTickService(app=app)

        # Empty ticker
        with pytest.raises(ValueError, match="ticker cannot be empty"):
            service.on_tick({"ticker": "", "price": Decimal("100.00")})

        # Non-positive price
        with pytest.raises(ValueError, match="must be strictly positive"):
            service.on_tick({"ticker": "TCS", "price": Decimal("0.00")})

        with pytest.raises(ValueError, match="must be strictly positive"):
            service.on_tick({"ticker": "TCS", "price": Decimal("-10.50")})

        # Negative volume
        with pytest.raises(ValueError, match="volume cannot be negative"):
            service.on_tick({"ticker": "TCS", "price": Decimal("3500.00"), "volume": -5})


def test_websocket_disconnect_and_exponential_backoff(app):
    """Verifies disconnection schedules live_tick_reconnect job with 2^n backoff."""
    with app.app_context():
        service = LiveTickService(app=app)
        service.subscribed_symbols = {"INFY", "TCS"}

        # First disconnect -> retry 1 -> delay 2^1 = 2s
        job1 = service.on_disconnect(error=ConnectionResetError("Socket reset by peer"))
        assert job1 is not None
        assert job1.job_type == "live_tick_reconnect"
        payload1 = json.loads(job1.payload)
        assert payload1["attempt"] == 1
        assert payload1["delay_seconds"] == 2
        assert "INFY" in payload1["symbols"]
        assert "TCS" in payload1["symbols"]

        # Second disconnect -> retry 2 -> delay 2^2 = 4s
        job2 = service.on_disconnect(error=TimeoutError("Heartbeat timed out"))
        assert job2 is not None
        payload2 = json.loads(job2.payload)
        assert payload2["attempt"] == 2
        assert payload2["delay_seconds"] == 4

        # Retries up to max_retries (5)
        service.on_disconnect()  # 3 -> 8s
        service.on_disconnect()  # 4 -> 16s
        job5 = service.on_disconnect()  # 5 -> 32s
        assert job5 is not None
        assert json.loads(job5.payload)["delay_seconds"] == 32

        # 6th attempt exceeds max_retries
        job6 = service.on_disconnect()
        assert job6 is None


def test_market_hours_detection():
    """Verifies market hours check for NSE trading window (09:15 - 15:30 IST, Mon-Fri)."""
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

    # Wednesday 11:00 AM IST -> Within market hours
    wednesday_market = datetime.datetime(2026, 3, 11, 11, 0, 0, tzinfo=ist)
    assert LiveTickService.is_market_hours(wednesday_market) is True

    # Wednesday 08:30 AM IST -> Pre-market (closed)
    wednesday_pre = datetime.datetime(2026, 3, 11, 8, 30, 0, tzinfo=ist)
    assert LiveTickService.is_market_hours(wednesday_pre) is False

    # Wednesday 16:00 PM IST -> Post-market (closed)
    wednesday_post = datetime.datetime(2026, 3, 11, 16, 0, 0, tzinfo=ist)
    assert LiveTickService.is_market_hours(wednesday_post) is False

    # Sunday 11:00 AM IST -> Weekend (closed)
    sunday_market = datetime.datetime(2026, 3, 15, 11, 0, 0, tzinfo=ist)
    assert LiveTickService.is_market_hours(sunday_market) is False


def test_staleness_check_during_market_hours():
    """Verifies is_cache_stale detects ticks older than 5 seconds during active market hours."""
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    # Fix clock to Wednesday 10:00 AM IST
    market_time = datetime.datetime(2026, 3, 11, 10, 0, 0, tzinfo=ist)
    Clock.set_fixed(market_time)

    service = LiveTickService(staleness_seconds=5.0)

    # 1. No cached tick -> Stale
    assert service.is_cache_stale("RELIANCE") is True

    # 2. Fresh tick (2 seconds ago) -> Not stale
    set_cached_tick("RELIANCE", {
        "ticker": "RELIANCE",
        "price": Decimal("2450.00"),
        "ts_utc": Clock.utcnow() - datetime.timedelta(seconds=2),
    })
    assert service.is_cache_stale("RELIANCE") is False

    # 3. Old tick (6 seconds ago) -> Stale
    set_cached_tick("RELIANCE", {
        "ticker": "RELIANCE",
        "price": Decimal("2450.00"),
        "ts_utc": Clock.utcnow() - datetime.timedelta(seconds=6),
    })
    assert service.is_cache_stale("RELIANCE") is True


def test_live_tick_service_start_stop(app):
    """Verifies that LiveTickService starts background daemon thread and shuts down cleanly."""
    service = LiveTickService(app=app)
    assert service.is_running is False

    service.start(symbols=["INFY", "TCS"])
    assert service.is_running is True
    assert "INFY" in service.subscribed_symbols
    assert "TCS" in service.subscribed_symbols

    service.stop()
    assert service.is_running is False


def test_job_worker_schedule_periodic_tasks(app):
    """Verifies JobWorker enqueues periodic aggregation, news polling, and scoring jobs."""
    from app.workers.job_worker import JobWorker

    with app.app_context():
        worker = JobWorker(app=app)
        tasks = worker.schedule_periodic_tasks()

        assert "tick_aggregate" in tasks
        assert "news_poll" in tasks
        assert "score_news" in tasks

        # Subsequent call does not duplicate already queued jobs
        tasks2 = worker.schedule_periodic_tasks()
        assert tasks2 == {}


def test_dashboard_quotes_api(client, app):
    """Verifies GET /api/v1/dashboard/quotes returns live and cached quotes."""
    set_cached_tick("INFY", {
        "ticker": "INFY",
        "price": Decimal("1530.00"),
        "volume": 50,
        "ts_utc": Clock.utcnow(),
        "source": "market_simulator",
    })

    res = client.get("/api/v1/dashboard/quotes")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "quotes" in data
    infy_q = next((q for q in data["quotes"] if q["ticker"] == "INFY"), None)
    assert infy_q is not None
    assert infy_q["price"] == "1530.00"
    assert infy_q["is_live"] is True



