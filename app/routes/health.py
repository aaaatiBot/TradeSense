"""Health check endpoint per SRS §5.7.4 and §6.1."""
from __future__ import annotations

import time
from typing import Any, Dict
from flask import Blueprint, current_app
from sqlalchemy import text

from app.extensions import db
from app.utils.clock import Clock
from app.utils.response import api_error, api_success

health_bp = Blueprint("health", __name__, url_prefix="/api/v1")


@health_bp.route("/health", methods=["GET"])
def get_health():
    """Report dependency health status (database, market_data, gemini, blockchain).

    Per §5.7.4:
    Each dependency returns 'ok', 'degraded', or 'down'.
    Non-essential dependencies (Gemini, market data, blockchain) being down
    do not render the primary application unhealthy.
    """
    dependencies: Dict[str, Dict[str, Any]] = {}
    now_iso = Clock.utcnow().isoformat()

    # 1. Database Check (Essential)
    db_status = "down"
    db_reason = None
    db_latency_ms = None
    try:
        t0 = time.perf_counter()
        db.session.execute(text("SELECT 1"))
        latency = (time.perf_counter() - t0) * 1000.0
        db_status = "ok"
        db_latency_ms = round(latency, 2)
    except Exception as exc:
        db_status = "down"
        db_reason = f"database connection error: {str(exc)}"

    dep_db = {"status": db_status, "checked_at": now_iso}
    if db_latency_ms is not None:
        dep_db["latency_ms"] = db_latency_ms
    if db_reason:
        dep_db["reason"] = db_reason
    dependencies["database"] = dep_db

    # 2. Market Data Check (Non-essential for Phase 1)
    provider = current_app.config.get("MARKET_DATA_PROVIDER")
    api_key = current_app.config.get("MARKET_DATA_API_KEY")
    if not provider or provider == "none":
        dependencies["market_data"] = {
            "status": "down",
            "reason": "no market data provider configured",
            "checked_at": now_iso,
        }
    elif not api_key:
        dependencies["market_data"] = {
            "status": "down",
            "reason": "MARKET_DATA_API_KEY not set",
            "checked_at": now_iso,
        }
    else:
        dependencies["market_data"] = {
            "status": "ok",
            "provider": provider,
            "checked_at": now_iso,
        }

    # 3. Gemini Check (Non-essential)
    gemini_key = current_app.config.get("GEMINI_API_KEY")
    if not gemini_key:
        dependencies["gemini"] = {
            "status": "down",
            "reason": "GEMINI_API_KEY not set",
            "checked_at": now_iso,
        }
    else:
        dependencies["gemini"] = {
            "status": "ok",
            "model": current_app.config.get("GEMINI_MODEL"),
            "checked_at": now_iso,
        }

    # 4. Blockchain Check (Non-essential)
    rpc_url = current_app.config.get("BLOCKCHAIN_PROVIDER_URL")
    if not rpc_url:
        dependencies["blockchain"] = {
            "status": "down",
            "reason": "BLOCKCHAIN_PROVIDER_URL not set",
            "checked_at": now_iso,
        }
    else:
        dependencies["blockchain"] = {
            "status": "ok",
            "chain_id": current_app.config.get("BLOCKCHAIN_CHAIN_ID"),
            "checked_at": now_iso,
        }

    # If the essential database check failed, return 503
    if db_status == "down":
        return api_error(
            code="SERVICE_UNAVAILABLE",
            message="Essential dependency database is down",
            status_code=503,
            details={"dependencies": dependencies},
        )

    # Determine overall status: 'healthy' or 'degraded'
    non_essential_down = any(
        dep["status"] != "ok" for k, dep in dependencies.items() if k != "database"
    )
    overall_status = "degraded" if non_essential_down else "healthy"

    data = {
        "status": overall_status,
        "timestamp": now_iso,
        "dependencies": dependencies,
    }
    return api_success(data=data, status_code=200)
