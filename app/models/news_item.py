"""News sentiment and headline cache model per SRS §7.13 and §7.18.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class NewsItem(db.Model):
    """Cached market news and Gemini sentiment analysis outputs."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    sentiment_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
