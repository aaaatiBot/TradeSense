"""API deprecation registry model per SRS §6.6 (API versioning and deprecation)."""
from __future__ import annotations

import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class ApiDeprecation(db.Model):
    """Registry of deprecated API endpoints with Sunset dates per RFC 8594."""

    __tablename__ = "api_deprecations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(16), default="*", nullable=False)
    deprecation_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sunset_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alternative_endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
