"""Time abstraction per SRS §12.3.2 (TST-01, TST-02, TST-03).

All time reads in domain services, models, and loggers shall go through
this Clock abstraction, not datetime.now() or datetime.utcnow().
"""
from __future__ import annotations

import datetime
from typing import Optional


class Clock:
    """Thread-safe / deterministic Clock abstraction for TradeSense."""

    _fixed_datetime: Optional[datetime.datetime] = None

    @classmethod
    def now(cls, tz: Optional[datetime.tzinfo] = datetime.timezone.utc) -> datetime.datetime:
        """Return the current time with timezone awareness.

        Defaults to UTC if no timezone is provided.
        """
        if cls._fixed_datetime is not None:
            if cls._fixed_datetime.tzinfo is None:
                dt = cls._fixed_datetime.replace(tzinfo=datetime.timezone.utc)
            else:
                dt = cls._fixed_datetime
            return dt if tz is None else dt.astimezone(tz)
        return datetime.datetime.now(tz=tz or datetime.timezone.utc)

    @classmethod
    def utcnow(cls) -> datetime.datetime:
        """Return current time in UTC with timezone awareness."""
        return cls.now(tz=datetime.timezone.utc)

    @classmethod
    def ensure_utc(cls, dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
        """Ensure a datetime is timezone-aware in UTC (normalizing SQLite naive returns)."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)

    @classmethod
    def set_fixed(cls, dt: Optional[datetime.datetime]) -> None:
        """Fix the clock to a specific datetime for deterministic tests."""
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        cls._fixed_datetime = dt

    @classmethod
    def reset(cls) -> None:
        """Reset the clock to real system time."""
        cls._fixed_datetime = None
