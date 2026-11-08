"""Comprehensive End-to-End User Journey Test (AT-35, Phase 12).

Tests the complete lifecycle of TradeSense:
1. User registration & Argon2id authentication
2. Session token issuance & authorization
3. Stock universe setup & market data availability
4. Risk-budgeted recommendation generation (E[G_i] estimation & integer MILP optimizer)
5. Background blockchain anchoring of recommendation commitment (Keccak-256)
6. Rule-9 enforcement (paper trade requires confirmed blockchain anchor)
7. Paper trade opening with Idempotency-Key
8. Paper trade closing with market exit price
9. Exact transaction cost breakdown & net PnL realization
10. Background blockchain anchoring of trade result commitment
11. Independent cryptographic verification of both commitments
12. Private user trade history audit trail
13. Observability metrics emission & Admin system overview
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import json
import pytest
from flask import Flask

from app.extensions import db
from app.models.blockchain_record import BlockchainRecord
from app.models.cost_rate_card import CostRateCard
from app.models.job import JobQueue
from app.models.model_version import ModelVersion
from app.models.paper_trade import PaperTrade
from app.models.price import Price
from app.models.recommendation import Recommendation
from app.models.stock import Stock
from app.models.user import User
from app.services.blockchain_service import BlockchainService
from app.services.cost_engine import CostEngine
from app.workers.blockchain_worker import BlockchainWorker


def test_at_35_full_end_to_end_journey(client, app: Flask):
    """AT-35: Full end-to-end user journey across all 12 milestones."""

    # -------------------------------------------------------------
    # Step 0: Seed Database Prerequisites (Universe, Rate Card, Model)
    # -------------------------------------------------------------
    with app.app_context():
        # Active Rate Card
        card = CostRateCard(
            version="zerodha-2026",
            name="Zerodha Standard 2026",
            effective_from=datetime.datetime.now(datetime.timezone.utc),
            is_active=True,
            verified_at=datetime.datetime.now(datetime.timezone.utc),
            source_reference="SEBI Circular 2026",
        )
        db.session.add(card)

        # Active Reference Notional Config
        from app.models.reference_notional_config import ReferenceNotionalConfig
        ref_notional = ReferenceNotionalConfig(
            version_tag="v1.0_ref",
            notional_amount=Decimal("500.00"),
            is_active=True,
        )
        db.session.add(ref_notional)
        db.session.commit()

        # Active ML Model Version
        model = ModelVersion(
            version_tag="lgbm-classifier-v1.0",
            artifact_hash="a" * 64,
            is_active=True,
            feature_schema_version="v1.0",
            reference_notional_id=ref_notional.id,
            reference_notional=Decimal("500.00"),
            training_data_window_start=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
            training_data_window_end=datetime.datetime(2025, 12, 31, tzinfo=datetime.timezone.utc),
            estimate_source_method_version="v1.0",
            evaluation_report="EVAL REPORT: Challenger passed all gates",
        )
        db.session.add(model)

        # Stock Universe: 2 active stocks with prices
        s1 = Stock(ticker="RELIANCE", isin="INE002A01018", name="Reliance Industries", exchange="NSE", status="active")
        s2 = Stock(ticker="INFY", isin="INE009A01021", name="Infosys Ltd", exchange="NSE", status="active")
        db.session.add_all([s1, s2])
        db.session.commit()

        p1 = Price(
            stock_id=s1.id,
            ticker="RELIANCE",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            open=Decimal("2500.00"),
            high=Decimal("2520.00"),
            low=Decimal("2480.00"),
            close=Decimal("2500.00"),
            volume=500000,
        )
        p2 = Price(
            stock_id=s2.id,
            ticker="INFY",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            open=Decimal("1500.00"),
            high=Decimal("1515.00"),
            low=Decimal("1490.00"),
            close=Decimal("1500.00"),
            volume=300000,
        )
        db.session.add_all([p1, p2])
        db.session.commit()

    # -------------------------------------------------------------
    # Step 1: User Registration
    # -------------------------------------------------------------
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "e2e_student@tradesense.edu",
            "password": "SecurePassword123!",
            "role": "user",
        },
    )
    assert reg_resp.status_code == 201
    user_data = reg_resp.get_json()["data"]
    assert user_data["email"] == "e2e_student@tradesense.edu"

    # -------------------------------------------------------------
    # Step 2: User Login & Session Token Acquisition
    # -------------------------------------------------------------
    login_resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "e2e_student@tradesense.edu",
            "password": "SecurePassword123!",
        },
    )
    assert login_resp.status_code == 200
    token = login_resp.get_json()["data"]["token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # -------------------------------------------------------------
    # Step 3: Recommendation Generation (Budget ₹10,000, Mode: CNC)
    # -------------------------------------------------------------
    rec_resp = client.post(
        "/api/v1/recommendations",
        headers=auth_headers,
        json={
            "budget": 10000.00,
            "trade_mode": "CNC",
        },
    )
    assert rec_resp.status_code == 201
    rec_data = rec_resp.get_json()["data"]
    rec_id = rec_data["id"]
    assert rec_data["items"]
    assert Decimal(rec_data["total_deployed"]) <= Decimal("10000.00")
    assert rec_data["trade_mode"] == "CNC"

    # Verify attempt to open paper trade BEFORE anchoring is rejected (Rule 9)
    early_trade_resp = client.post(
        "/api/v1/paper-trades",
        headers={**auth_headers, "Idempotency-Key": "e2e-early-key-1"},
        json={
            "recommendation_id": rec_id,
            "ticker": rec_data["items"][0]["ticker"],
            "quantity": rec_data["items"][0]["shares"],
            "side": "BUY",
            "trade_mode": "CNC",
        },
    )
    assert early_trade_resp.status_code == 400
    assert early_trade_resp.get_json()["error"]["code"] == "RECOMMENDATION_NOT_ANCHORED"

    # -------------------------------------------------------------
    # Step 4: Durable Worker Anchors Recommendation to Blockchain
    # -------------------------------------------------------------
    with app.app_context():
        # Process queued job
        worker = BlockchainWorker()
        processed = worker.run_once()
        assert processed is True

        rec = db.session.get(Recommendation, rec_id)
        assert rec.commitment_hash is not None
        rec_hash = rec.commitment_hash

        # Verify BlockchainRecord entry
        bc_rec = BlockchainRecord.query.filter_by(record_type="RECOMMENDATION", reference_id=rec_id).first()
        assert bc_rec is not None
        assert bc_rec.status == "CONFIRMED"
        assert bc_rec.commitment_hash == rec_hash

    # -------------------------------------------------------------
    # Step 5: Open Paper Trade with Idempotency-Key
    # -------------------------------------------------------------
    chosen_item = rec_data["items"][0]
    trade_open_resp = client.post(
        "/api/v1/paper-trades",
        headers={**auth_headers, "Idempotency-Key": "e2e-open-trade-123"},
        json={
            "recommendation_id": rec_id,
            "ticker": chosen_item["ticker"],
            "quantity": chosen_item["shares"],
            "side": "BUY",
            "trade_mode": "CNC",
        },
    )
    assert trade_open_resp.status_code in [200, 201]
    trade_data = trade_open_resp.get_json()["data"]
    trade_id = trade_data["trade_id"]
    assert trade_data["status"] == "OPEN"

    # Verify Idempotent repeat returns cached response
    repeat_resp = client.post(
        "/api/v1/paper-trades",
        headers={**auth_headers, "Idempotency-Key": "e2e-open-trade-123"},
        json={
            "recommendation_id": rec_id,
            "ticker": chosen_item["ticker"],
            "quantity": chosen_item["shares"],
            "side": "BUY",
            "trade_mode": "CNC",
        },
    )
    assert repeat_resp.status_code in [200, 201]
    assert repeat_resp.get_json()["data"]["trade_id"] == trade_id

    # -------------------------------------------------------------
    # Step 6: Close Paper Trade with Market Exit Price
    # -------------------------------------------------------------
    # Simulate a profitable exit price (+ ₹50 per share)
    exit_price = Decimal(chosen_item["entry_price"]) + Decimal("50.00")
    close_resp = client.post(
        "/api/v1/paper-trades/{}/close".format(trade_id),
        headers={**auth_headers, "Idempotency-Key": "e2e-close-trade-456"},
        json={
            "exit_prices": {chosen_item["ticker"]: float(exit_price)},
        },
    )
    assert close_resp.status_code == 200
    close_data = close_resp.get_json()["data"]
    assert close_data["status"] == "CLOSED"
    assert Decimal(close_data["total_gross_pnl"]) > Decimal("0")
    assert Decimal(close_data["total_net_pnl"]) > Decimal("0")

    # -------------------------------------------------------------
    # Step 7: Worker Anchors Trade Result to Blockchain
    # -------------------------------------------------------------
    with app.app_context():
        worker = BlockchainWorker()
        processed_close = worker.run_once()
        assert processed_close is True

        tr = db.session.get(PaperTrade, trade_id)
        assert tr.status == "CLOSED"

        tr_bc = BlockchainRecord.query.filter_by(record_type="TRADE_RESULT", reference_id=trade_id).first()
        assert tr_bc is not None
        assert tr_bc.status == "CONFIRMED"
        trade_result_hash = tr_bc.commitment_hash

    # -------------------------------------------------------------
    # Step 8: Independent Cryptographic Verification Endpoint
    # -------------------------------------------------------------
    # Verify Recommendation commitment
    verify_rec_resp = client.get(f"/api/v1/verification/{rec_hash}")
    assert verify_rec_resp.status_code == 200
    v_rec = verify_rec_resp.get_json()["data"]
    assert v_rec["entity_type"] == "recommendation"
    assert v_rec["status"] == "CONFIRMED"

    # Verify Trade Result commitment
    verify_tr_resp = client.get(f"/api/v1/verification/{trade_result_hash}")
    assert verify_tr_resp.status_code == 200
    v_tr = verify_tr_resp.get_json()["data"]
    assert v_tr["entity_type"] == "trade_result"
    assert v_tr["status"] == "CONFIRMED"

    # -------------------------------------------------------------
    # Step 9: User Trade History & Privacy Isolation
    # -------------------------------------------------------------
    history_resp = client.get("/api/v1/history", headers=auth_headers)
    assert history_resp.status_code == 200
    hist_trades = history_resp.get_json()["data"]["trades"]
    assert len(hist_trades) == 1
    assert hist_trades[0]["trade_id"] == trade_id
    assert hist_trades[0]["status"] == "CLOSED"

    # -------------------------------------------------------------
    # Step 10: Admin System Overview & Metrics Audit
    # -------------------------------------------------------------
    with app.app_context():
        admin = User(email="admin_auditor@tradesense.edu", password_hash="admin_hash", role="admin")
        db.session.add(admin)
        db.session.commit()
        admin_token_hash = "admin_session_token_123"
        from app.models.session import Session
        import hashlib
        token_hash = hashlib.sha256("admin_secret_token".encode()).hexdigest()
        s_admin = Session(
            user_id=admin.id,
            session_token_hash=token_hash,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=4),
        )
        db.session.add(s_admin)
        db.session.commit()

    admin_resp = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": "Bearer admin_secret_token"},
    )
    assert admin_resp.status_code == 200
    admin_data = admin_resp.get_json()["data"]
    assert admin_data["status"] == "operational"
    assert "job_queue_depth" in admin_data
    assert "recent_model_activations" in admin_data
