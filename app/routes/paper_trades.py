"""Paper trades route blueprint stub per SRS §4.8 (Phase 7 deliverable)."""
from flask import Blueprint

paper_trades_bp = Blueprint("paper_trades", __name__, url_prefix="/api/v1/paper-trades")
