"""Conditional-return estimates entity per SRS §7.17 and §4.5.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class ConditionalReturnEstimate(db.Model):
    """Estimated G+ and G- magnitudes per (ticker, horizon, mode) triple."""

    __tablename__ = "conditional_return_estimates"
    __table_args__ = (
        UniqueConstraint("ticker", "horizon", "mode", "method_version", name="uq_cond_return_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    g_plus: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    g_minus: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    estimate_source: Mapped[str] = mapped_column(String(32), nullable=False)
    method_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calculated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
