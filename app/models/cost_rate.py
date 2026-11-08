"""Specific cost rate rules per SRS §7.10 and §4.7."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class CostRate(db.Model):
    """Granular statutory and broker charge rules."""

    __tablename__ = "cost_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cost_rate_cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_type: Mapped[str] = mapped_column(String(16), nullable=False)  # CNC or MIS
    rate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(16), nullable=False)  # percentage or flat
    cap_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    min_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )

    card = relationship("CostRateCard", back_populates="rates")
