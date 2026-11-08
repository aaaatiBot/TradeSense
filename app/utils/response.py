"""Standard API response envelope helpers per SRS §6.1."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Response, g, jsonify


def get_current_request_id() -> str:
    """Retrieve the current request ID from Flask g or fallback to empty string."""
    return getattr(g, "request_id", "")


def api_success(data: Any = None, status_code: int = 200) -> Tuple[Response, int]:
    """Return standard success response envelope:

    { "ok": true, "data": ..., "error": null, "request_id": "..." }
    """
    payload = {
        "ok": True,
        "data": data if data is not None else {},
        "error": None,
        "request_id": get_current_request_id(),
    }
    response = jsonify(payload)
    return response, status_code


def api_error(
    code: str,
    message: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None,
) -> Tuple[Response, int]:
    """Return standard error response envelope:

    { "ok": false, "data": null, "error": { "code": "...", "message": "...", "details": ... }, "request_id": "..." }
    """
    error_payload: Dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        error_payload["details"] = details

    payload = {
        "ok": False,
        "data": None,
        "error": error_payload,
        "request_id": get_current_request_id(),
    }
    response = jsonify(payload)
    return response, status_code
