"""Independent verification route implementation per SRS §8.8 (Phase 8/12)."""
from __future__ import annotations

from flask import Blueprint, request

from app.models.blockchain_record import BlockchainRecord
from app.services.verification_service import VerificationService
from app.utils.response import api_error, api_success

verification_bp = Blueprint("verification", __name__, url_prefix="/api/v1/verification")


@verification_bp.route("/<string:commitment_hash>", methods=["GET"])
def verify_hash(commitment_hash: str):
    """Independently verify a commitment hash against the immutable ledger per SRS §8.8."""
    result = VerificationService.verify_commitment(commitment_hash)
    if not result.get("record_type"):
        return api_error(
            code="RECORD_NOT_FOUND",
            message=result.get("error", "No commitment record found"),
            status_code=404,
        )

    return api_success(
        data={
            "payload_hash": result["commitment_hash"],
            "commitment_hash": result["commitment_hash"],
            "entity_type": result["record_type"].lower(),
            "entity_id": result["reference_id"],
            "status": result["status"],
            "tx_hash": result["tx_hash"],
            "block_number": result["block_number"],
            "anchored_at": result["created_at"],
            "on_chain_verified": result["verified"],
        },
        status_code=200,
    )


@verification_bp.route("", methods=["POST"])
def verify_payload():
    """Verify a payload or commitment hash submitted in JSON body."""
    body = request.get_json() or {}
    commitment_hash = body.get("commitment_hash")
    if not commitment_hash:
        return api_error(
            code="VALIDATION_ERROR",
            message="Field 'commitment_hash' is required",
            status_code=400,
        )
    return verify_hash(commitment_hash)
