"""Acceptance tests for Phase 11: UI, Security, Retention, Monitoring.

Covers:
- AT-31: Security headers & CORS
- AT-32: Rate limiting (HTTP 429)
- AT-33: XSS sanitization
- AT-40: Retention policy enforcement (§7.18)
- AT-43: Regulatory & ethical disclaimer presence (§15.1)
- AT-44: Monitoring metrics emission (§5.7.1)
- AT-45: API deprecation & sunset headers (§6.6)
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import pytest
from flask import Flask

from app.extensions import db, limiter
from app.models.api_deprecation import ApiDeprecation
from app.models.blockchain_record import BlockchainRecord
from app.models.cost_breakdown import CostBreakdown
from app.models.idempotency import IdempotencyRecord
from app.models.job import JobQueue
from app.models.news_item import NewsItem
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.password_reset import PasswordResetToken
from app.models.price import Price
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.session import Session
from app.models.stock import Stock
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.disclaimer_service import DisclaimerService
from app.services.retention_service import RetentionService
from app.utils.clock import Clock
from app.utils.metrics import metrics


def test_at_31_security_headers_and_cors(client):
    """AT-31: Verify required HTTP security headers and CORS headers are emitted."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_at_32_rate_limiting(app: Flask):
    """AT-32: Verify rate limiting triggers HTTP 429 when threshold exceeded."""
    @app.route("/api/v1/test-rate-limit")
    @limiter.limit("2 per second")
    def rate_limited_endpoint():
        return "OK"

    test_client = app.test_client()

    # First 2 requests succeed
    r1 = test_client.get("/api/v1/test-rate-limit")
    assert r1.status_code == 200
    r2 = test_client.get("/api/v1/test-rate-limit")
    assert r2.status_code == 200

    # 3rd request should hit rate limit (429)
    r3 = test_client.get("/api/v1/test-rate-limit")
    assert r3.status_code == 429


def test_at_33_xss_sanitization(client):
    """AT-33: Verify Jinja2 template auto-escapes potentially malicious input to prevent XSS."""
    malicious_hash = "<script>alert('XSS-ATTACK');</script>"
    resp = client.get(f"/verification?hash={malicious_hash}")
    assert resp.status_code == 200

    # Script tag must be escaped and NOT rendered executable
    response_text = resp.get_data(as_text=True)
    assert "<script>alert('XSS-ATTACK');</script>" not in response_text
    assert "&lt;script&gt;alert(&#39;XSS-ATTACK&#39;);&lt;/script&gt;" in response_text or "&#34;" in response_text or "&lt;script&gt;" in response_text


def test_at_40_retention_policy_enforcement(app: Flask, client):
    """AT-40: Retention policy enforcement per SRS §7.18.1.

    Records older than their retention window are deleted; records within window are untouched.
    """
    fixed_now = datetime.datetime(2026, 11, 8, 12, 0, 0, tzinfo=datetime.timezone.utc)
    Clock.set_fixed(fixed_now)
    try:
        with app.app_context():
            # Setup user
            u = User(email="retention_test@example.com", password_hash="hash", role="user")
            db.session.add(u)
            db.session.commit()

            # 1. Sessions: 8h retention
            old_session = Session(
                user_id=u.id,
                session_token_hash="old_s",
                expires_at=fixed_now - datetime.timedelta(hours=10),
                last_active_at=fixed_now - datetime.timedelta(hours=9),
            )
            fresh_session = Session(
                user_id=u.id,
                session_token_hash="fresh_s",
                expires_at=fixed_now + datetime.timedelta(hours=4),
                last_active_at=fixed_now - datetime.timedelta(hours=2),
            )

            # 2. Password reset tokens: 1h retention
            old_token = PasswordResetToken(
                user_id=u.id,
                token_hash="old_tok",
                expires_at=fixed_now - datetime.timedelta(hours=2),
                created_at=fixed_now - datetime.timedelta(hours=2),
            )
            fresh_token = PasswordResetToken(
                user_id=u.id,
                token_hash="fresh_tok",
                expires_at=fixed_now + datetime.timedelta(minutes=30),
                created_at=fixed_now - datetime.timedelta(minutes=30),
            )

            # 3. Idempotency: 24h retention
            old_idemp = IdempotencyRecord(
                user_id=u.id,
                idempotency_key="old_key",
                request_path="/api/v1/paper-trades",
                request_hash="reqhash_old",
                response_code=200,
                response_body="{}",
                created_at=fixed_now - datetime.timedelta(hours=26),
                expires_at=fixed_now - datetime.timedelta(hours=2),
            )
            fresh_idemp = IdempotencyRecord(
                user_id=u.id,
                idempotency_key="fresh_key",
                request_path="/api/v1/paper-trades",
                request_hash="reqhash_fresh",
                response_code=200,
                response_body="{}",
                created_at=fixed_now - datetime.timedelta(hours=2),
                expires_at=fixed_now + datetime.timedelta(hours=22),
            )

            # 4. Job queue: completed (30d), failed (90d)
            old_job = JobQueue(
                job_type="anchor_recommendation",
                payload="{}",
                status="COMPLETED",
                completed_at=fixed_now - datetime.timedelta(days=32),
                created_at=fixed_now - datetime.timedelta(days=32),
            )
            fresh_job = JobQueue(
                job_type="anchor_recommendation",
                payload="{}",
                status="COMPLETED",
                completed_at=fixed_now - datetime.timedelta(days=10),
                created_at=fixed_now - datetime.timedelta(days=10),
            )

            # 5. Prices: 2 years (730d)
            stock = Stock(ticker="RETTEST", isin="INE000000099", name="Ret Test", exchange="NSE")
            db.session.add(stock)
            db.session.commit()

            old_price = Price(
                stock_id=stock.id,
                ticker=stock.ticker,
                timestamp=fixed_now - datetime.timedelta(days=800),
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("102"),
                volume=1000,
            )
            fresh_price = Price(
                stock_id=stock.id,
                ticker=stock.ticker,
                timestamp=fixed_now - datetime.timedelta(days=100),
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("102"),
                volume=1000,
            )

            db.session.add_all([
                old_session, fresh_session,
                old_token, fresh_token,
                old_idemp, fresh_idemp,
                old_job, fresh_job,
                old_price, fresh_price,
            ])
            db.session.commit()

            # Run sweep
            counts = RetentionService.run_retention_sweep(as_of=fixed_now)

            assert counts["sessions"] == 1
            assert counts["password_reset_tokens"] == 1
            assert counts["idempotency_records"] == 1
            assert counts["job_queue"] == 1
            assert counts["prices"] == 1

            # Verify old deleted, fresh untouched
            assert db.session.get(Session, old_session.id) is None
            assert db.session.get(Session, fresh_session.id) is not None

            assert db.session.get(PasswordResetToken, old_token.id) is None
            assert db.session.get(PasswordResetToken, fresh_token.id) is not None

            assert db.session.get(IdempotencyRecord, old_idemp.id) is None
            assert db.session.get(IdempotencyRecord, fresh_idemp.id) is not None

            assert db.session.get(JobQueue, old_job.id) is None
            assert db.session.get(JobQueue, fresh_job.id) is not None

            assert db.session.get(Price, old_price.id) is None
            assert db.session.get(Price, fresh_price.id) is not None

            # Verify idempotence - running again deletes 0 records
            counts_second = RetentionService.run_retention_sweep(as_of=fixed_now)
            for tbl, cnt in counts_second.items():
                assert cnt == 0
    finally:
        Clock.reset()


def test_at_43_disclaimer_presence_on_all_screens(client, app: Flask):
    """AT-43: Verify every screen listed in §15.1 renders the required disclaimers."""
    with app.app_context():
        DisclaimerService.seed_disclaimers()

    # 1. Login screen
    resp_login = client.get("/login")
    assert resp_login.status_code == 200
    text_login = resp_login.get_data(as_text=True)
    assert "This is an educational simulation. Not investment advice. No real orders are placed." in text_login

    # 2. Dashboard screen
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    text_dash = resp_dash.get_data(as_text=True)
    assert "This is an educational simulation. Not investment advice. No real orders are placed." in text_dash

    # 3. Recommendation screen
    resp_rec = client.get("/recommendation")
    assert resp_rec.status_code == 200
    text_rec = resp_rec.get_data(as_text=True)
    assert "This is an educational simulation. Not investment advice. No real orders are placed." in text_rec
    assert "Predictions are uncertain. Expected returns are estimates, not guarantees." in text_rec
    assert "Simulated fills may differ from real-market execution." in text_rec

    # 4. Paper-trade result screen
    resp_trade = client.get("/paper-trades/result")
    assert resp_trade.status_code == 200
    text_trade = resp_trade.get_data(as_text=True)
    assert "This is an educational simulation. Not investment advice. No real orders are placed." in text_trade
    assert "Predictions are uncertain. Expected returns are estimates, not guarantees." in text_trade
    assert "Simulated fills may differ from real-market execution." in text_trade
    assert "Transaction costs depend on the selected rate card and are subject to change." in text_trade

    # 5. Verification screen
    resp_ver = client.get("/verification")
    assert resp_ver.status_code == 200
    text_ver = resp_ver.get_data(as_text=True)
    assert "Blockchain anchoring proves commitment integrity, not financial correctness." in text_ver

    # 6. History screen
    resp_hist = client.get("/history")
    assert resp_hist.status_code == 200
    text_hist = resp_hist.get_data(as_text=True)
    assert "This is an educational simulation. Not investment advice. No real orders are placed." in text_hist
    assert "Past performance does not guarantee future results." in text_hist


def test_at_44_monitoring_metrics_and_health_reporting(client, app: Flask):
    """AT-44: Verify monitoring metrics emission and /health per-dependency reporting."""
    metrics.reset()

    # Health endpoint reports per-dependency status
    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code in [200, 503]
    h_data = health_resp.get_json()["data"]
    assert "dependencies" in h_data
    assert "database" in h_data["dependencies"]
    assert "market_data" in h_data["dependencies"]
    assert "gemini" in h_data["dependencies"]
    assert "blockchain" in h_data["dependencies"]

    # Trigger some metrics
    metrics.inc_recommendations_created()
    metrics.inc_paper_trades_opened()
    metrics.inc_paper_trades_closed()
    metrics.inc_blockchain_anchor_failures()
    metrics.inc_estimate_source("model_estimate")
    metrics.record_external_api_call("gemini", "success")

    snapshot = metrics.snapshot()
    assert snapshot["recommendations_created_total"] == 1
    assert snapshot["paper_trades_opened_total"] == 1
    assert snapshot["paper_trades_closed_total"] == 1
    assert snapshot["blockchain_anchor_failures_total"] == 1
    assert snapshot["estimate_source_distribution"]["model_estimate"] == 1
    assert snapshot["external_api_calls_total"]["gemini_success"] == 1

    # Request metrics recorded in after_request
    assert snapshot["http_requests_count"] >= 1


def test_at_45_api_deprecation_and_sunset_headers(client, app: Flask):
    """AT-45: Verify a deprecated endpoint returns Deprecation and Sunset headers per §6.6."""
    with app.app_context():
        dep_date = datetime.datetime(2026, 12, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        # 90 days after per §6.6 API-05
        sunset_date = dep_date + datetime.timedelta(days=95)

        # Deprecate the test endpoint
        dep = ApiDeprecation(
            endpoint="/api/v1/health",
            method="GET",
            deprecation_date=dep_date,
            sunset_date=sunset_date,
            alternative_endpoint="/api/v2/health",
            is_active=True,
        )
        db.session.add(dep)
        db.session.commit()

        # Call endpoint
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

        # Verify Deprecation and Sunset headers present
        assert "Deprecation" in resp.headers
        assert "Sunset" in resp.headers
        assert resp.headers["Deprecation"] == dep_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
        assert resp.headers["Sunset"] == sunset_date.strftime("%a, %d %b %Y %H:%M:%S GMT")

        # Deactivate deprecation and verify headers removed
        dep.is_active = False
        db.session.commit()

        resp2 = client.get("/api/v1/health")
        assert "Deprecation" not in resp2.headers
        assert "Sunset" not in resp2.headers
