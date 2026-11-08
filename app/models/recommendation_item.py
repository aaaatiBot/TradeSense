"""Recommendation line items per SRS §7.6, §4.5.1, §6.5.2, and §9.4.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class RecommendationItem(db.Model):
    """Allocated stock position within a recommendation."""

    __tablename__ = "recommendation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_return_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    p_i: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    g_plus: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    g_minus: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    estimate_source: Mapped[str] = mapped_column(String(32), nullable=False)  # ticker_baseline, universe_baseline, prior, challenger
    method_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_notional: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("500.00"), nullable=False
    )
    stock_status_at_creation: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )

    @property
    def entry_price(self) -> Decimal:
        """Calculated entry price per share based on allocated capital and quantity."""
        if self.quantity and self.quantity > 0:
            return (self.allocated_amount / Decimal(str(self.quantity))).quantize(Decimal("0.01"))
        return Decimal("0.00")

    @property
    def shares(self) -> int:
        return self.quantity

    @property
    def allocated_capital(self) -> Decimal:
        return self.allocated_amount

    @property
    def expected_net_pnl(self) -> Decimal:
        return self.expected_return_rate

    recommendation = relationship("Recommendation", back_populates="items")
    stock = relationship("Stock")
