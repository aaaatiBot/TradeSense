"""Independent verification route blueprint stub per SRS §8.8 (Phase 8 deliverable)."""
from flask import Blueprint

verification_bp = Blueprint("verification", __name__, url_prefix="/api/v1/verification")
