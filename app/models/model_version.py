"""Machine Learning model version entity per SRS §7.16 and §9.8.5."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import get_current_time


class ModelVersion(db.Model):
    """Registered ML model version with full provenance and evaluation reports."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_tag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_notional_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reference_notional_configs.id"), nullable=False
    )
    reference_notional: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("500.00"), nullable=False)
    training_data_window_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    training_data_window_end: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimate_source_method_version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    evaluation_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )

    reference_notional_config = relationship("ReferenceNotionalConfig")
