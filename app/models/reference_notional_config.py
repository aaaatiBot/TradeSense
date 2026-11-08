"""Reference trade-size configuration entity per SRS §9.4.1."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class ReferenceNotionalConfig(db.Model):
    """Configurable reference notional (default ₹500) per SRS §9.4.1."""

    __tablename__ = "reference_notional_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_tag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    notional_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("500.00"), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
