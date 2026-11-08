"""Blockchain audit record model per SRS §7.12 and §7.18.1."""
from __future__ import annotations

import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import get_current_time


class BlockchainRecord(db.Model):
    """On-chain commitment audit tracking entity."""

    __tablename__ = "blockchain_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)  # RECOMMENDATION or TRADE_RESULT
    reference_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    commitment_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    canonical_payload: Mapped[str] = mapped_column(Text, nullable=False)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True, index=True)
    block_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, CONFIRMED, FAILED
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=get_current_time, nullable=False
    )
    confirmed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
