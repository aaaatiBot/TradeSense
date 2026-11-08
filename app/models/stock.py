"""Stock universe model per SRS §6.5 (Stock status and universe-change handling)."""
from __future__ import annotations

from typing import List
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin


class Stock(db.Model, TimestampMixin):
    """Stock entity with lifecycle status per SRS §6.5.1."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isin: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    prices = relationship("Price", back_populates="stock", cascade="all, delete-orphan")
