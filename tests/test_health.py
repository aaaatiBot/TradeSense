"""Tests for health endpoint per SRS §5.7.4, §6.1, and Corrections 3 & 5."""
import uuid
from unittest.mock import patch
from flask.testing import FlaskClient


def test_health_check_envelope_and_request_id(client: FlaskClient):
    """Verify GET /api/v1/health response envelope and UUIDv4 request ID."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["error"] is None
    assert "request_id" in payload
    assert "data" in payload

    # Verify request_id is valid UUIDv4
    req_id = payload["request_id"]
    parsed_uuid = uuid.UUID(req_id, version=4)
    assert str(parsed_uuid) == req_id

    # Verify X-Request-ID header matches envelope request_id
    header_req_id = response.headers.get("X-Request-ID")
    assert header_req_id == req_id


def test_health_check_preserves_client_request_id(client: FlaskClient):
    """Verify health endpoint echoes custom incoming X-Request-ID header."""
    custom_id = str(uuid.uuid4())
    response = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["request_id"] == custom_id
    assert response.headers.get("X-Request-ID") == custom_id


def test_health_check_dependencies_honesty(client: FlaskClient):
    """Verify dependency status honesty and reasons (Correction 3)."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.get_json()["data"]

    deps = data["dependencies"]
    assert "database" in deps
    assert "market_data" in deps
    assert "gemini" in deps
    assert "blockchain" in deps

    # Database is essential and up
    assert deps["database"]["status"] == "ok"
    assert "latency_ms" in deps["database"]

    # Market data has honest reason when API key not set
    assert deps["market_data"]["status"] == "down"
    assert deps["market_data"]["reason"] in [
        "MARKET_DATA_API_KEY not set",
        "no market data provider configured",
    ]

    # Gemini has honest reason when API key not set
    assert deps["gemini"]["status"] == "down"
    assert deps["gemini"]["reason"] == "GEMINI_API_KEY not set"

    # Blockchain has honest reason when RPC URL not set
    assert deps["blockchain"]["status"] == "down"
    assert deps["blockchain"]["reason"] == "BLOCKCHAIN_PROVIDER_URL not set"


def test_health_check_gemini_down_does_not_fail_app(client: FlaskClient):
    """Verify Gemini being unavailable does not make the overall app down per SRS §2.1."""
    response = client.get("/api/v1/health")
    payload = response.get_json()

    # Overall application response is ok=True (status=degraded since non-essential service is down)
    assert payload["ok"] is True
    assert payload["data"]["status"] in ["healthy", "degraded"]
    assert response.status_code == 200


def test_health_check_database_failure_returns_503(client: FlaskClient):
    """Verify essential dependency database failure returns 503 and ok=False."""
    with patch("app.extensions.db.session.execute", side_effect=Exception("DB connection timeout")):
        response = client.get("/api/v1/health")
        assert response.status_code == 503

        payload = response.get_json()
        assert payload["ok"] is False
        assert payload["data"] is None
        assert payload["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "database is down" in payload["error"]["message"].lower()
