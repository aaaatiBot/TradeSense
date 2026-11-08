"""Real-time market tick model per SRS §4.3 and Phase 4.5.

Captures streaming tick level data from WebSocket feeds.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class Tick(db.Model):
    """High-frequency market tick record with high-precision Decimal pricing."""

    __tablename__ = "ticks"
    __table_args__ = (
        Index("ix_ticks_ticker_ts_utc", "ticker", "ts_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ts_utc: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=get_current_time
    )
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), default="fyers", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
