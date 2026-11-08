"""Disclaimer registry model per SRS §15.1 and AT-43."""
from __future__ import annotations

import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class DisclaimerRegistry(db.Model):
    """Central registry of mandatory regulatory & ethical disclaimers per screen."""

    __tablename__ = "disclaimer_registry"
    __table_args__ = (
        UniqueConstraint("screen_name", "version", name="uq_disclaimer_screen_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screen_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    disclaimer_text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
