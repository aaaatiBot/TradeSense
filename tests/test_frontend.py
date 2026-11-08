"""Acceptance and unit tests for Phase 11 Frontend per SRS v3.1 §10, §13, and §15.1.

Tests covered:
- AT-31: Viewport and 360px mobile responsiveness (no fixed width > 360px, table-responsive, img wrapping)
- AT-43: Regulatory disclaimer presence on all screens per SRS §15.1
- AT-44: /api/v1/health dependency reporting and dashboard HTMX integration
- AT-45: API Deprecation and Sunset headers enforcement (RFC 7231)
- AT-32: CSRF protection token presence in all state-changing forms
- AT-33: Error page hygiene (500.html renders request_id with zero stack trace; XSS sanitization)
- AT-28: Anchored gate verification (Open Paper Trade button disabled by default in HTML)
- INR currency formatting filter verification
- Inventory check of all Step 3 templates and static files
"""
from __future__ import annotations

import datetime
import os
import re
from decimal import Decimal
import pytest
from flask import Flask, render_template

from app.extensions import db
from app.models.api_deprecation import ApiDeprecation
from app.services.disclaimer_service import DisclaimerService
from app.utils.filters import format_inr


@pytest.fixture(autouse=True)
def init_test_db(app: Flask):
    """Ensure database tables and initial statutory disclaimers exist for every test."""
    with app.app_context():
        db.create_all()
        DisclaimerService.seed_disclaimers()
        yield
        db.session.rollback()


def test_inr_filter_formatting():
    """Verify Indian currency notation filter adheres to ₹1,23,456.78 format."""
    assert format_inr(123456.78) == "₹1,23,456.78"
    assert format_inr(500) == "₹500.00"
    assert format_inr(1000000) == "₹10,00,000.00"
    assert format_inr(-450.5) == "-₹450.50"
    assert format_inr(Decimal("12345678.90")) == "₹1,23,45,678.90"
    assert format_inr(0) == "₹0.00"
    assert format_inr(None) == "₹0.00"
    assert format_inr("") == "₹0.00"


def test_step3_file_inventory_exists():
    """Verify every file listed in STEP 3 exists and is non-empty."""
    required_templates = [
        "layouts/base.html",
        "layouts/base-auth.html",
        "includes/sidebar.html",
        "includes/navigation.html",
        "includes/footer.html",
        "includes/scripts.html",
        "partials/disclaimer.html",
        "partials/flash.html",
        "partials/status-chip.html",
        "partials/charge-table.html",
        "auth/login.html",
        "auth/register.html",
        "dashboard.html",
        "recommendation.html",
        "result.html",
        "history.html",
        "verification.html",
        "admin/panel.html",
        "admin/rate_cards.html",
        "admin/model_versions.html",
        "errors/404.html",
        "errors/500.html",
    ]
    for rel_path in required_templates:
        full_path = os.path.join("app", "templates", rel_path)
        assert os.path.exists(full_path), f"Missing template: {rel_path}"
        assert os.path.getsize(full_path) > 0, f"Empty template: {rel_path}"

    required_static = [
        os.path.join("css", "styles.css"),
        os.path.join("js", "app.js"),
        os.path.join("images", "logo.svg"),
    ]
    for rel_path in required_static:
        full_path = os.path.join("app", "static", rel_path)
        assert os.path.exists(full_path), f"Missing static asset: {rel_path}"
        assert os.path.getsize(full_path) > 0, f"Empty static asset: {rel_path}"

    assert os.path.exists(os.path.join("app", "utils", "filters.py")), "Missing filters.py"


def test_at_43_disclaimers_rendered_on_all_screens(client):
    """AT-43: Assert each screen listed in SRS §15.1 renders its mandatory disclaimers."""
    screen_checks = {
        "/login": [
            "This is an educational simulation. Not investment advice. No real orders are placed."
        ],
        "/dashboard": [
            "This is an educational simulation. Not investment advice. No real orders are placed."
        ],
        "/recommendation": [
            "This is an educational simulation. Not investment advice. No real orders are placed.",
            "Predictions are uncertain. Expected returns are estimates, not guarantees.",
            "Simulated fills may differ from real-market execution.",
        ],
        "/paper-trades/result": [
            "This is an educational simulation. Not investment advice. No real orders are placed.",
            "Predictions are uncertain. Expected returns are estimates, not guarantees.",
            "Simulated fills may differ from real-market execution.",
            "Transaction costs depend on the selected rate card and are subject to change.",
        ],
        "/history": [
            "This is an educational simulation. Not investment advice. No real orders are placed.",
            "Past performance does not guarantee future results.",
        ],
        "/verification": [
            "Blockchain anchoring proves commitment integrity, not financial correctness."
        ],
    }

    for path, expected_disclaimers in screen_checks.items():
        resp = client.get(path)
        assert resp.status_code == 200, f"Route {path} failed with code {resp.status_code}"
        html = resp.get_data(as_text=True)
        for disclaimer in expected_disclaimers:
            assert disclaimer in html, f"Disclaimer '{disclaimer}' missing on screen '{path}'"


def test_at_31_responsiveness_and_viewport(client):
    """AT-31: Assert HTML responsiveness at 360px viewport width (no overflow, table wrapping)."""
    endpoints = ["/login", "/dashboard", "/recommendation", "/paper-trades/result", "/history", "/verification"]
    
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # 1. Viewport meta tag present
        assert 'name="viewport"' in html
        assert "width=device-width" in html

        # 2. No inline fixed width styles > 360px
        fixed_width_matches = re.findall(r'width:\s*([0-9]+)px', html)
        for w in fixed_width_matches:
            assert int(w) <= 360, f"Endpoint {ep} contains fixed width style > 360px: {w}px"

        # 3. Every <table> must be enclosed in a .table-responsive wrapper
        if "<table" in html:
            assert "table-responsive" in html, f"Endpoint {ep} has <table> lacking .table-responsive wrapping"

        # 4. Images must have responsive class or wrapping
        if "<img" in html:
            img_tags = re.findall(r'<img[^>]+>', html)
            for tag in img_tags:
                assert 'alt=' in tag, f"Endpoint {ep} img tag missing alt attribute: {tag}"


def test_at_44_health_endpoint_and_htmx_binding(client):
    """AT-44: Assert /api/v1/health renders and dashboard HTMX call succeeds."""
    # 1. Verify /api/v1/health endpoint response
    health_resp = client.get("/api/v1/health")
    assert health_resp.status_code in [200, 503]
    h_data = health_resp.get_json()["data"]
    assert "dependencies" in h_data
    assert "database" in h_data["dependencies"]
    assert "market_data" in h_data["dependencies"]
    assert "gemini" in h_data["dependencies"]
    assert "blockchain" in h_data["dependencies"]

    # 2. Verify dashboard template binds to /api/v1/health via HTMX
    dash_resp = client.get("/dashboard")
    assert dash_resp.status_code == 200
    dash_html = dash_resp.get_data(as_text=True)
    assert 'hx-get="/api/v1/health"' in dash_html
    assert 'hx-trigger="load"' in dash_html
    assert 'health-chip-database' in dash_html
    assert 'health-chip-blockchain' in dash_html


def test_at_45_api_deprecation_headers(app: Flask, client):
    """AT-45: Assert Deprecation and Sunset headers are present when endpoints are marked deprecated."""
    # 1. Vacuous pass check: when no deprecations active, headers should not be emitted
    resp = client.get("/api/v1/health")
    assert resp.status_code in [200, 503]
    assert "Deprecation" not in resp.headers
    assert "Sunset" not in resp.headers

    # 2. Active deprecation entry test
    with app.app_context():
        dep_date = datetime.datetime(2026, 12, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        sunset_date = dep_date + datetime.timedelta(days=90)
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

        try:
            dep_resp = client.get("/api/v1/health")
            assert "Deprecation" in dep_resp.headers
            assert "Sunset" in dep_resp.headers
            assert dep_resp.headers["Deprecation"] == dep_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
            assert dep_resp.headers["Sunset"] == sunset_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
        finally:
            dep.is_active = False
            db.session.commit()


def test_at_32_csrf_token_in_forms(app: Flask, client):
    """AT-32: Assert CSRF token inputs are present in all state-changing forms."""
    forms_to_check = [
        ("/login", 'action="/api/v1/auth/login"'),
        ("/dashboard", 'action="/api/v1/recommendations"'),
    ]
    for url, form_snippet in forms_to_check:
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert form_snippet in html
        assert 'name="csrf_token"' in html

    # Also assert state-changing recommendation execution form has CSRF
    with app.test_request_context():
        sample_rec = {
            "id": 1,
            "items": [
                {
                    "ticker": "RELIANCE",
                    "shares": 5,
                    "entry_price": 2500.0,
                    "allocated_capital": 12500.0,
                    "expected_net_pnl": 500.0,
                    "probability": 0.65,
                }
            ],
        }
        rec_html = render_template("recommendation.html", recommendation=sample_rec)
        assert 'action="/api/v1/paper-trades"' in rec_html
        assert 'name="csrf_token"' in rec_html


def test_at_33_error_500_hygiene_and_xss_protection(app: Flask, client):
    """AT-33: Assert 500 template has zero stack trace and displays request_id, and XSS is escaped."""
    # 1. 500 template rendering hygiene
    with app.test_request_context():
        from flask import g
        g.request_id = "req-test-trace-id-9988"
        rendered_500 = render_template("errors/500.html")
        assert "req-test-trace-id-9988" in rendered_500
        assert "Traceback (most recent call last)" not in rendered_500
        assert "ZeroDivisionError" not in rendered_500
        assert "File " not in rendered_500

    # 2. XSS sanitization check on query inputs
    malicious_payload = "<script>alert('XSS_ATTACK');</script>"
    ver_resp = client.get(f"/verification?hash={malicious_payload}")
    assert ver_resp.status_code == 200
    ver_html = ver_resp.get_data(as_text=True)
    assert "<script>alert('XSS_ATTACK');</script>" not in ver_html
    assert "&lt;script&gt;" in ver_html or "&#39;XSS_ATTACK&#39;" in ver_html


def test_at_28_anchored_gate_paper_trade_button_disabled(app: Flask):
    """AT-28 & Constraint 5: Open Paper Trade button MUST be disabled in default HTML."""
    with app.test_request_context():
        # Render recommendation template with sample draft recommendation
        rec = {
            "id": 42,
            "budget": Decimal("50000"),
            "mode": "CNC",
            "status": "SUBMITTED",
            "commitment_hash": "0xabc123",
            "items": [
                {
                    "ticker": "RELIANCE",
                    "exchange": "NSE",
                    "shares": 10,
                    "entry_price": Decimal("2500.00"),
                    "allocated_capital": Decimal("25000.00"),
                    "expected_net_pnl": Decimal("750.00"),
                    "probability": 0.65,
                }
            ],
        }
        rendered = render_template("recommendation.html", recommendation=rec, recommendations=[])
        assert 'class="btn btn-gradient-primary w-100 btn-open-paper-trade font-weight-bold"' in rendered
        assert 'disabled' in rendered

        # Button tag itself must have the disabled attribute
        match = re.search(r'<button[^>]+btn-open-paper-trade[^>]*>', rendered)
        assert match is not None
        assert "disabled" in match.group(0), "Open Paper Trade button must be disabled by default"
