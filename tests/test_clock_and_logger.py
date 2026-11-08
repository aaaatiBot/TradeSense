"""Tests for Clock abstraction and structured JSON logger with secret redaction."""
import datetime
import json
import logging
from app.utils.clock import Clock
from app.utils.logger import StructuredJsonFormatter, redact_sensitive_data, hash_identifier


def test_clock_fixed_time():
    """Verify Clock.set_fixed makes time deterministic."""
    fixed_time = datetime.datetime(2026, 11, 8, 12, 0, 0, tzinfo=datetime.timezone.utc)
    Clock.set_fixed(fixed_time)

    assert Clock.now() == fixed_time
    assert Clock.utcnow() == fixed_time

    Clock.reset()
    assert Clock.now() != fixed_time


def test_sensitive_data_redaction():
    """Verify passwords, tokens, API keys and private keys are redacted."""
    data = {
        "username": "investor1",
        "password": "SuperSecretPassword123",
        "api_key": "live_gemini_key",
        "private_key": "0x1234567890abcdef",
        "nested": {
            "session_token": "token_abc123",
            "safe_field": "valid_value",
        },
        "list_items": [
            {"bearer": "secret_bearer_token"},
            {"amount": 500},
        ],
    }

    redacted = redact_sensitive_data(data)

    assert redacted["password"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["private_key"] == "[REDACTED]"
    assert redacted["nested"]["session_token"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "valid_value"
    assert redacted["list_items"][0]["bearer"] == "[REDACTED]"
    assert redacted["list_items"][1]["amount"] == 500


def test_hash_identifier():
    """Verify hash_identifier produces deterministic non-reversible hashes."""
    h1 = hash_identifier("user@example.com")
    h2 = hash_identifier("user@example.com")
    h3 = hash_identifier("other@example.com")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16


def test_structured_json_formatter():
    """Verify StructuredJsonFormatter outputs valid single-line JSON."""
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="tradesense",
        level=logging.INFO,
        pathname="app.py",
        lineno=10,
        msg="Test event",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["event"] == "Test event"
    assert "timestamp" in parsed
