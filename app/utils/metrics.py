"""Observability and Metrics per SRS §5.7.1 (AT-44)."""
from __future__ import annotations

import threading
from typing import Any, Dict


class MetricsCollector:
    """Thread-safe in-memory metrics collector per SRS §5.7.1."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_metrics()
            return cls._instance

    def _init_metrics(self):
        self.lock = threading.Lock()
        # Counters
        self.http_requests_total: Dict[tuple[str, str, int], int] = {}
        self.http_request_durations: list[float] = []
        self.recommendations_created_total: int = 0
        self.paper_trades_opened_total: int = 0
        self.paper_trades_closed_total: int = 0
        self.blockchain_anchor_failures_total: int = 0
        self.model_inference_durations: Dict[str, list[float]] = {}
        self.estimate_source_distribution: Dict[str, int] = {
            "model_estimate": 0,
            "universe_baseline": 0,
            "prior": 0,
        }
        self.external_api_calls_total: Dict[tuple[str, str], int] = {}

    def reset(self):
        """Reset all metrics (useful for isolated tests)."""
        with self.lock:
            self._init_metrics()

    def record_http_request(self, endpoint: str, method: str, status: int, duration_seconds: float):
        with self.lock:
            key = (endpoint, method, status)
            self.http_requests_total[key] = self.http_requests_total.get(key, 0) + 1
            self.http_request_durations.append(duration_seconds)

    def inc_recommendations_created(self):
        with self.lock:
            self.recommendations_created_total += 1

    def inc_paper_trades_opened(self):
        with self.lock:
            self.paper_trades_opened_total += 1

    def inc_paper_trades_closed(self):
        with self.lock:
            self.paper_trades_closed_total += 1

    def inc_blockchain_anchor_failures(self):
        with self.lock:
            self.blockchain_anchor_failures_total += 1

    def record_model_inference(self, model_version: str, duration_seconds: float):
        with self.lock:
            if model_version not in self.model_inference_durations:
                self.model_inference_durations[model_version] = []
            self.model_inference_durations[model_version].append(duration_seconds)

    def inc_estimate_source(self, source: str):
        with self.lock:
            self.estimate_source_distribution[source] = (
                self.estimate_source_distribution.get(source, 0) + 1
            )

    def record_external_api_call(self, provider: str, status: str):
        with self.lock:
            key = (provider, status)
            self.external_api_calls_total[key] = self.external_api_calls_total.get(key, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of current metrics."""
        with self.lock:
            return {
                "http_requests_total": {
                    f"{k[0]}_{k[1]}_{k[2]}": v for k, v in self.http_requests_total.items()
                },
                "http_requests_count": sum(self.http_requests_total.values()),
                "recommendations_created_total": self.recommendations_created_total,
                "paper_trades_opened_total": self.paper_trades_opened_total,
                "paper_trades_closed_total": self.paper_trades_closed_total,
                "blockchain_anchor_failures_total": self.blockchain_anchor_failures_total,
                "estimate_source_distribution": dict(self.estimate_source_distribution),
                "external_api_calls_total": {
                    f"{k[0]}_{k[1]}": v for k, v in self.external_api_calls_total.items()
                },
            }


metrics = MetricsCollector()
