"""Authentication route blueprint stub per SRS §4.1 (Phase 2 deliverable)."""
from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
