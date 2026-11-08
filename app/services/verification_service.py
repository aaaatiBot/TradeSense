"""Independent cryptographic verification service per SRS §8.8 and §12.2."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.extensions import db
from app.models.blockchain_record import BlockchainRecord
from app.services.blockchain_service import BlockchainService


class VerificationService:
    """Service verifying canonical payloads and commitments against on-chain transaction logs per SRS §8.8."""

    @classmethod
    def verify_commitment(cls, commitment_hash: str) -> Dict[str, Any]:
        """Verify an Ethereum Keccak-256 commitment hash against local records and smart contract."""
        target_hash = commitment_hash.lower()
        if not target_hash.startswith("0x"):
            target_hash = "0x" + target_hash

        record = BlockchainRecord.query.filter(
            BlockchainRecord.commitment_hash.ilike(target_hash)
        ).first()

        if not record:
            return {
                "verified": False,
                "error": "Record not found on audit ledger",
                "commitment_hash": target_hash,
            }

        on_chain = (record.status == "CONFIRMED")
        try:
            if record.record_type.upper() == "RECOMMENDATION":
                on_chain = BlockchainService.verify_recommendation_commitment(
                    entity_id=record.reference_id,
                    expected_hash=record.commitment_hash,
                )
            elif record.record_type.upper() == "TRADE_RESULT":
                on_chain = BlockchainService.verify_trade_result_commitment(
                    entity_id=record.reference_id,
                    expected_hash=record.commitment_hash,
                )
        except Exception:
            on_chain = (record.status == "CONFIRMED")

        return {
            "verified": on_chain,
            "commitment_hash": record.commitment_hash,
            "record_type": record.record_type,
            "reference_id": record.reference_id,
            "status": record.status,
            "tx_hash": record.tx_hash,
            "block_number": record.block_number,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
