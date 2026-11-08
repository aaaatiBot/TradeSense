"""Paper trade order leg per SRS §7.8 and §7.18.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class PaperTradeLeg(db.Model):
    """Individual simulated execution leg (BUY/SELL) within a paper trade."""

    __tablename__ = "paper_trade_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_trades.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # BUY or SELL
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cost_breakdown_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cost_breakdowns.id"), nullable=True
    )
    executed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )

    paper_trade = relationship("PaperTrade", back_populates="legs")
    stock = relationship("Stock")
    cost_breakdown = relationship("CostBreakdown")
