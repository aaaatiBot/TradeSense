"""Recommendation model per SRS §7.5 and §7.18.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class Recommendation(db.Model):
    """Stock advisory portfolio recommendation."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    effective_budget: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cash_buffer: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # CNC or MIS
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("model_versions.id"), nullable=False
    )
    rate_card_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_notional: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("500.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    commitment_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True, index=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="recommendations")
    model_version = relationship("ModelVersion")
    items = relationship("RecommendationItem", back_populates="recommendation", cascade="all, delete-orphan")
