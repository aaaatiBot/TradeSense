"""Administrator route blueprint stub per SRS §10.1 (Phase 11 deliverable)."""
from flask import Blueprint

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")
