"""Base model utilities and TimestampMixin per SRS §12.3.2 (TST-01).

All timestamp generation uses the Clock abstraction, never datetime.now().
"""
from __future__ import annotations

import datetime
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.utils.clock import Clock


def get_current_time() -> datetime.datetime:
    """Helper callable returning current UTC time via Clock abstraction."""
    return Clock.utcnow()


class TimestampMixin:
    """Provides created_at and updated_at datetime fields using Clock abstraction."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_current_time,
        nullable=False,
    )

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_current_time,
        onupdate=get_current_time,
        nullable=False,
    )
