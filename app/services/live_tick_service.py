"""Live WebSocket tick ingestion service per Phase 4.5 and SRS §4.3.

Provides thread-safe in-memory caching of the latest market ticks,
durable persistence to the `ticks` table, exponential backoff reconnection
scheduling via `job_queue`, and market hour staleness checks.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set

from flask import current_app, has_app_context
from sqlalchemy import select

from app.extensions import db
from app.models.job import JobQueue
from app.models.tick import Tick
from app.utils.clock import Clock

logger = logging.getLogger("tradesense.live_ticks")

# Global thread-safe in-memory tick cache
_TICK_CACHE: Dict[str, Dict[str, Any]] = {}
_TICK_CACHE_LOCK = threading.Lock()


def get_cached_tick(ticker: str) -> Optional[Dict[str, Any]]:
    """Retrieve the latest cached tick for a ticker in a thread-safe manner."""
    normalized = ticker.upper().strip()
    with _TICK_CACHE_LOCK:
        item = _TICK_CACHE.get(normalized)
        if item is None:
            return None
        return dict(item)


def set_cached_tick(ticker: str, tick_data: Dict[str, Any]) -> None:
    """Store the latest tick into the thread-safe in-memory cache."""
    normalized = ticker.upper().strip()
    with _TICK_CACHE_LOCK:
        _TICK_CACHE[normalized] = dict(tick_data)


def clear_tick_cache() -> None:
    """Clear in-memory tick cache (primarily used in testing)."""
    with _TICK_CACHE_LOCK:
        _TICK_CACHE.clear()


class LiveTickService:
    """WebSocket client manager for live tick data streaming."""

    DEFAULT_STALENESS_SECONDS = 5.0
    MAX_RETRY_ATTEMPTS = 5

    def __init__(
        self,
        app=None,
        provider: str = "fyers",
        client_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        access_token: Optional[str] = None,
        max_retries: int = MAX_RETRY_ATTEMPTS,
        staleness_seconds: float = DEFAULT_STALENESS_SECONDS,
    ) -> None:
        self.app = app
        self.provider = provider
        self.client_id = client_id or os.getenv("FYERS_CLIENT_ID", "")
        self.secret_key = secret_key or os.getenv("FYERS_SECRET_KEY", "")
        self.access_token = access_token or os.getenv("FYERS_ACCESS_TOKEN", "")
        self.max_retries = max_retries
        self.staleness_seconds = staleness_seconds

        self.retry_count = 0
        self.is_running = False
        self.subscribed_symbols: Set[str] = set()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ws_client = None

    def _get_app_context(self):
        """Yield an application context safely if not already inside one."""
        if has_app_context():
            class _NoOpContext:
                def __enter__(self):
                    return current_app
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            return _NoOpContext()
        elif self.app is not None:
            return self.app.app_context()
        else:
            from app import create_app
            app_inst = create_app(os.getenv("FLASK_ENV", "testing"))
            return app_inst.app_context()

    @staticmethod
    def is_market_hours(dt: Optional[datetime.datetime] = None) -> bool:
        """Check if given timestamp (or current Clock time) is within NSE market hours (09:15 - 15:30 IST, Mon-Fri)."""
        check_dt = dt or Clock.now()
        # Convert check_dt to IST (UTC + 5:30)
        ist_offset = datetime.timedelta(hours=5, minutes=30)
        ist_tz = datetime.timezone(ist_offset)
        if check_dt.tzinfo is None:
            # Treat as UTC
            check_dt = check_dt.replace(tzinfo=datetime.timezone.utc)
        ist_dt = check_dt.astimezone(ist_tz)

        # NSE trading days: Monday (0) to Friday (4)
        if ist_dt.weekday() >= 5:
            return False

        # NSE market hours: 09:15 to 15:30 IST
        market_open = datetime.time(9, 15, 0)
        market_close = datetime.time(15, 30, 0)
        return market_open <= ist_dt.time() <= market_close

    def is_cache_stale(self, ticker: str, max_age_seconds: Optional[float] = None) -> bool:
        """Check if cached tick is older than threshold. Only enforced during market hours."""
        cached = get_cached_tick(ticker)
        if cached is None:
            return True

        threshold = max_age_seconds or self.staleness_seconds
        now = Clock.utcnow()
        tick_time = cached.get("ts_utc")
        if not tick_time:
            return True

        tick_time_utc = Clock.ensure_utc(tick_time)
        age_seconds = (now - tick_time_utc).total_seconds()

        # If currently within market hours, strict 5s staleness applies
        if self.is_market_hours(now):
            return age_seconds > threshold
        return False

    def get_latest_tick(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Always reads from the in-memory latest tick cache."""
        return get_cached_tick(ticker)

    def on_tick(self, tick_data: Dict[str, Any]) -> Tick:
        """Validate tick data, write to ticks database table, and update memory cache."""
        ticker = str(tick_data.get("ticker", "")).upper().strip()
        if not ticker:
            raise ValueError("Tick ticker cannot be empty")

        raw_price = tick_data.get("price")
        if raw_price is None:
            raise ValueError(f"Tick price is required for ticker {ticker}")
        price = Decimal(str(raw_price))
        if price <= Decimal("0"):
            raise ValueError(f"Tick price must be strictly positive, got {price}")

        raw_vol = tick_data.get("volume", 0)
        volume = int(raw_vol)
        if volume < 0:
            raise ValueError(f"Tick volume cannot be negative, got {volume}")

        raw_ts = tick_data.get("timestamp") or tick_data.get("ts_utc") or Clock.utcnow()
        ts_utc = Clock.ensure_utc(raw_ts)
        source = str(tick_data.get("source", self.provider))

        # Update thread-safe in-memory cache
        cached_entry = {
            "ticker": ticker,
            "price": price,
            "volume": volume,
            "ts_utc": ts_utc,
            "source": source,
        }
        set_cached_tick(ticker, cached_entry)

        # Persist tick to database
        tick_record = Tick(
            ticker=ticker,
            ts_utc=ts_utc,
            price=price,
            volume=volume,
            source=source,
            created_at=Clock.utcnow(),
        )

        with self._get_app_context():
            db.session.add(tick_record)
            db.session.commit()

        return tick_record

    def on_disconnect(self, error: Optional[Exception] = None) -> Optional[JobQueue]:
        """Handle WebSocket disconnection by logging and scheduling reconnection with exponential backoff."""
        logger.warning(f"WebSocket disconnected: {error}. Scheduling reconnection.")
        self.is_running = False

        self.retry_count += 1
        if self.retry_count > self.max_retries:
            logger.error(f"WebSocket exceeded max retries ({self.max_retries}). Halting auto-reconnect.")
            return None

        # Exponential backoff: 2^n seconds (2, 4, 8, 16, 32...)
        backoff_seconds = 2 ** self.retry_count

        with self._get_app_context():
            payload = {
                "attempt": self.retry_count,
                "delay_seconds": backoff_seconds,
                "symbols": list(self.subscribed_symbols),
                "error": str(error) if error else "Connection lost",
            }
            job = JobQueue(
                job_type="live_tick_reconnect",
                payload=json.dumps(payload, sort_keys=True),
                status="QUEUED",
                attempts=0,
                max_attempts=3,
                created_at=Clock.utcnow(),
            )
            db.session.add(job)
            db.session.commit()
            logger.info(
                f"Enqueued live_tick_reconnect job #{job.id} with {backoff_seconds}s backoff (attempt {self.retry_count}/{self.max_retries})"
            )
            return job

    def start(self, symbols: Optional[List[str]] = None) -> None:
        """Start WebSocket streaming client in a non-blocking daemon thread."""
        if self.is_running:
            return

        if symbols:
            self.subscribed_symbols.update(s.upper().strip() for s in symbols)

        self._stop_event.clear()
        self.is_running = True

        def _socket_loop():
            logger.info(f"LiveTickService worker started for symbols: {list(self.subscribed_symbols)}")
            if self.provider == "fyers" and self.access_token:
                try:
                    # In production with live token, connect via fyers_apiv3
                    from fyers_apiv3.FyersWebsocket import data_ws

                    def _on_message(message):
                        # Fyers tick format adapter
                        if isinstance(message, dict) and "symbol" in message:
                            sym = message["symbol"].replace("NSE:", "").replace("-EQ", "")
                            self.on_tick({
                                "ticker": sym,
                                "price": Decimal(str(message.get("ltp", 0))),
                                "volume": int(message.get("vol_traded_today", 0)),
                                "timestamp": Clock.utcnow(),
                                "source": "fyers",
                            })

                    def _on_error(err):
                        self.on_disconnect(Exception(str(err)))

                    def _on_close(msg):
                        self.on_disconnect(Exception(f"Socket closed: {msg}"))

                    fyers_client = data_ws.FyersDataSocket(
                        access_token=f"{self.client_id}:{self.access_token}",
                        log_path="",
                        litemode=True,
                        write_to_file=False,
                        reconnect=False,  # We manage durable reconnection via job_queue
                        on_connect=lambda: logger.info("Connected to Fyers DataSocket"),
                        on_close=_on_close,
                        on_error=_on_error,
                        on_message=_on_message,
                    )
                    self._ws_client = fyers_client
                    fyers_client.connect()
                except Exception as exc:
                    self.on_disconnect(exc)
            else:
                # Simulated / Standby loop for dev and testing
                while not self._stop_event.is_set():
                    time.sleep(0.5)

        self._worker_thread = threading.Thread(target=_socket_loop, daemon=True, name="LiveTickWorker")
        self._worker_thread.start()

    def stop(self) -> None:
        """Gracefully stop WebSocket streaming and worker thread."""
        self._stop_event.set()
        self.is_running = False
        if self._ws_client is not None:
            try:
                if hasattr(self._ws_client, "close_connection"):
                    self._ws_client.close_connection()
                elif hasattr(self._ws_client, "close"):
                    self._ws_client.close()
            except Exception as e:
                logger.warning(f"Error closing socket: {e}")
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        logger.info("LiveTickService stopped.")
