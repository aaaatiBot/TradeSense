"""Structured JSON Logging per SRS §5.7.2 (LOG-M1 through LOG-M5).

Outputs single-line JSON with timestamp, level, event, request_id, user_id (hashed),
and duration_ms where applicable. Redacts sensitive parameters.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from typing import Any, Dict, Optional

from flask import g, has_request_context

from app.utils.clock import Clock

# Sensitive field name patterns to redact
SENSITIVE_PATTERNS = re.compile(
    r"(password|secret|token|api_key|private_key|authorization|bearer|cookie|session_id)",
    re.IGNORECASE,
)


def hash_identifier(identifier: Optional[str]) -> Optional[str]:
    """Deterministically hash sensitive user identifiers for log tracing."""
    if not identifier:
        return None
    return hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:16]


def redact_sensitive_data(data: Any) -> Any:
    """Recursively redact sensitive keys from dictionary and list payloads."""
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if SENSITIVE_PATTERNS.search(str(k)):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_sensitive_data(v)
        return redacted
    elif isinstance(data, (list, tuple)):
        return [redact_sensitive_data(item) for item in data]
    return data


class StructuredJsonFormatter(logging.Formatter):
    """JSON formatter emitting structured log records."""

    def format(self, record: logging.LogRecord) -> str:
        # Use Clock abstraction per SRS §12.3.2 TST-01
        log_payload: Dict[str, Any] = {
            "timestamp": Clock.utcnow().isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }

        # Request context tracing
        if has_request_context():
            request_id = getattr(g, "request_id", None)
            if request_id:
                log_payload["request_id"] = request_id
            user_id = getattr(g, "user_id", None)
            if user_id:
                log_payload["user_id"] = hash_identifier(str(user_id))

        # Additional structured attributes passed in extra
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in log_payload:
                    log_payload[k] = redact_sensitive_data(v)

        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            log_payload["duration_ms"] = duration_ms

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str)


def setup_logging(level_name: str = "INFO") -> logging.Logger:
    """Configure the root logger with StructuredJsonFormatter."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(handler)

    return logging.getLogger("tradesense")


logger = logging.getLogger("tradesense")
