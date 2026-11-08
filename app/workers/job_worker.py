"""General background job worker and streaming scheduler per Phase 4.5.

Runs the WebSocket client in a dedicated daemon thread, periodically schedules
tick aggregation and news ingestion tasks, claims jobs from the durable `job_queue`
table via atomic lease locking, and processes retries.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select

from app.extensions import db
from app.models.job import JobQueue
from app.services.gemini_service import GeminiService
from app.services.live_tick_service import LiveTickService
from app.services.news_ingestion_service import NewsIngestionService
from app.services.tick_aggregation_service import TickAggregationService
from app.workers.blockchain_worker import BlockchainWorker
from app.utils.clock import Clock

logger = logging.getLogger("tradesense.job_worker")


class JobWorker(BlockchainWorker):
    """Background durable job worker and streaming service orchestrator."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        lease_duration_seconds: int = 60,
        live_tick_service: Optional[LiveTickService] = None,
        tick_agg_interval_seconds: int = 60,
        news_poll_interval_seconds: Optional[int] = None,
        sentiment_interval_seconds: int = 300,
        app=None,
    ) -> None:
        super().__init__(worker_id=worker_id, lease_duration_seconds=lease_duration_seconds)
        self.app = app
        self.live_tick_service = live_tick_service or LiveTickService(app=app)
        self.tick_agg_interval = tick_agg_interval_seconds
        self.news_poll_interval = (
            news_poll_interval_seconds
            if news_poll_interval_seconds is not None
            else int(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "60"))
        )
        self.sentiment_interval = sentiment_interval_seconds

        self._stop_event = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None

    def schedule_periodic_tasks(self) -> Dict[str, Optional[JobQueue]]:
        """Enqueue recurring maintenance and ingestion tasks if not already queued."""
        now = Clock.utcnow()
        scheduled = {}

        # 1. Tick aggregation
        existing_agg = db.session.execute(
            select(JobQueue).where(
                JobQueue.job_type == "tick_aggregate",
                JobQueue.status.in_(["QUEUED", "RUNNING"]),
            )
        ).scalar_one_or_none()
        if existing_agg is None:
            job = self.enqueue_job("tick_aggregate", {"lookback_minutes": 5}, max_attempts=3)
            scheduled["tick_aggregate"] = job

        # 2. News poll
        existing_news = db.session.execute(
            select(JobQueue).where(
                JobQueue.job_type == "news_poll",
                JobQueue.status.in_(["QUEUED", "RUNNING"]),
            )
        ).scalar_one_or_none()
        if existing_news is None:
            job = self.enqueue_job("news_poll", {}, max_attempts=3)
            scheduled["news_poll"] = job

        # 3. Batch sentiment scoring
        existing_score = db.session.execute(
            select(JobQueue).where(
                JobQueue.job_type == "score_news",
                JobQueue.status.in_(["QUEUED", "RUNNING"]),
            )
        ).scalar_one_or_none()
        if existing_score is None:
            job = self.enqueue_job("score_news", {"limit": 10}, max_attempts=3)
            scheduled["score_news"] = job

        return scheduled

    def start(self, universe_symbols: Optional[List[str]] = None) -> None:
        """Start streaming WebSocket client and background worker threads."""
        self._stop_event.clear()

        # Start live WebSocket tick ingestion in its dedicated thread
        self.live_tick_service.start(symbols=universe_symbols)

        # Worker loop for processing jobs
        def _job_loop():
            logger.info(f"JobWorker [{self.worker_id}] processing loop started")
            while not self._stop_event.is_set():
                try:
                    if self.app:
                        with self.app.app_context():
                            self.recover_expired_leases()
                            did_work = self.run_once()
                    else:
                        self.recover_expired_leases()
                        did_work = self.run_once()

                    if not did_work:
                        time.sleep(1.0)
                except Exception as exc:
                    logger.error(f"Error in job worker loop: {exc}")
                    time.sleep(2.0)

        # Scheduler loop for periodic triggers
        def _scheduler_loop():
            last_tick_agg = 0.0
            last_news_poll = 0.0
            last_sentiment = 0.0

            while not self._stop_event.is_set():
                now_mono = time.monotonic()
                try:
                    is_market = LiveTickService.is_market_hours()
                    poll_interval = min(60, self.news_poll_interval) if is_market else self.news_poll_interval

                    if self.app:
                        with self.app.app_context():
                            if now_mono - last_tick_agg >= self.tick_agg_interval:
                                self.enqueue_job("tick_aggregate", {"lookback_minutes": 5})
                                last_tick_agg = now_mono
                            if now_mono - last_news_poll >= poll_interval:
                                self.enqueue_job("news_poll", {})
                                last_news_poll = now_mono
                            if now_mono - last_sentiment >= self.sentiment_interval:
                                self.enqueue_job("score_news", {"limit": 10})
                                last_sentiment = now_mono
                    else:
                        if now_mono - last_tick_agg >= self.tick_agg_interval:
                            self.enqueue_job("tick_aggregate", {"lookback_minutes": 5})
                            last_tick_agg = now_mono
                        if now_mono - last_news_poll >= poll_interval:
                            self.enqueue_job("news_poll", {})
                            last_news_poll = now_mono
                        if now_mono - last_sentiment >= self.sentiment_interval:
                            self.enqueue_job("score_news", {"limit": 10})
                            last_sentiment = now_mono
                except Exception as exc:
                    logger.error(f"Error in scheduler loop: {exc}")

                time.sleep(2.0)

        self._worker_thread = threading.Thread(target=_job_loop, daemon=True, name=f"JobWorker-{self.worker_id}")
        self._scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="JobScheduler")

        self._worker_thread.start()
        self._scheduler_thread.start()
        logger.info(f"JobWorker [{self.worker_id}] started successfully")

    def stop(self) -> None:
        """Gracefully terminate background workers and WebSocket stream."""
        self._stop_event.set()
        self.live_tick_service.stop()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2.0)

        logger.info(f"JobWorker [{self.worker_id}] stopped")
