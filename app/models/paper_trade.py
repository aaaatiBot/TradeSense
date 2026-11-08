"""Paper trade model per SRS §7.7, §6.5, and §7.18.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class PaperTrade(db.Model):
    """Simulated trade execution lifecycle entity."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommendation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # CNC or MIS
    status: Mapped[str] = mapped_column(
        String(32), default="OPEN", nullable=False
    )  # OPEN, CLOSED, FORCE_CLOSED_DELISTED
    opened_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    affected_by_universe_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_gross_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    total_net_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    commitment_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True, index=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )

    user = relationship("User", back_populates="paper_trades")
    recommendation = relationship("Recommendation")
    legs = relationship("PaperTradeLeg", back_populates="paper_trade", cascade="all, delete-orphan")
