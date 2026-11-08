"""Administrator routes per SRS §10.1 and §4.1 (AUTH-07)."""
from flask import Blueprint, g

from app.utils.decorators import require_role
from app.utils.response import api_success

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.route("/overview", methods=["GET"])
@require_role("admin")
def get_admin_overview():
    """Retrieve administrator system overview (requires admin role)."""
    return api_success(
        data={
            "admin_id": g.current_user.id,
            "status": "operational",
            "message": "Welcome, Administrator",
        },
        status_code=200,
    )
