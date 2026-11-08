"""Cost breakdown entity per SRS §7.11 and §7.18.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class CostBreakdown(db.Model):
    """Authoritative itemized calculation of all transaction fees and statutory charges."""

    __tablename__ = "cost_breakdowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_card_version: Mapped[str] = mapped_column(String(32), nullable=False)
    turnover: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    brokerage: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stt_ctt: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    transaction_charges: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    gst: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    sebi_charges: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stamp_duty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    dp_charges: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_charges: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
