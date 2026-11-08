"""User model per SRS §7.1 and §7.18.3 (Account deletion and anonymization)."""
from __future__ import annotations

import datetime
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import TimestampMixin


class User(db.Model, TimestampMixin):
    """User account entity.

    Per §7.18.3:
    When deleted/anonymized, is_active is set False, anonymized_at is populated,
    and personal fields (email, password_hash) become anonymized placeholders or null.
    Recommendations and paper trades are retained for audit.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    anonymized_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="user", passive_deletes=True)
    paper_trades = relationship("PaperTrade", back_populates="user", passive_deletes=True)
