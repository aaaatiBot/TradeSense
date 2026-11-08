"""Acceptance tests for Paper Trading & History (Phase 7, AT-16, AT-17, AT-34).

Verifies:
- AT-16: Paper trade execution, idempotency key (SRS §6.3), unanchored recommendation rejection,
  and stock unavailability rejection (UNI-03, TRD-13).
- AT-17: Paper trade closing, realized gross/net P&L after transaction costs, force close delisting.
- AT-34: Trade history retrieval, ownership isolation, expected vs realized P&L separation (EXP-06).
"""
from decimal import Decimal
import pytest

from app.extensions import db
from app.models.model_version import ModelVersion
from app.models.paper_trade import PaperTrade
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.models.stock import Stock
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.paper_trade_service import PaperTradeError, PaperTradeService
from app.utils.clock import Clock


@pytest.fixture
def auth_service():
    return AuthService()


@pytest.fixture
def paper_trade_service():
    return PaperTradeService()


@pytest.fixture
def sample_user(app):
    with app.app_context():
        user = User(
            email="trader@tradesense.edu",
            password_hash="argon2_hash_placeholder",
            role="user",
        )
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def second_user(app):
    with app.app_context():
        user = User(
            email="other_trader@tradesense.edu",
            password_hash="argon2_hash_placeholder",
            role="user",
        )
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def active_stock(app):
    with app.app_context():
        stock = Stock(
            ticker="TCS",
            isin="INE467B01029",
            name="Tata Consultancy Services",
            status="active",
        )
        db.session.add(stock)
        db.session.commit()
        return stock.id


@pytest.fixture
def inactive_stock(app):
    with app.app_context():
        stock = Stock(
            ticker="SUSPENDED_CO",
            isin="INE999X01010",
            name="Suspended Corp",
            status="suspended",
        )
        db.session.add(stock)
        db.session.commit()
        return stock.id


@pytest.fixture
def sample_model_version(app):
    with app.app_context():
        notional = ReferenceNotionalConfig(
            version_tag="v1.0_ref",
            notional_amount=Decimal("500.00"),
            description="Default reference notional",
        )
        db.session.add(notional)
        db.session.commit()

        mv = ModelVersion(
            version_tag="lightgbm_v1",
            artifact_hash="abc123sha256" * 4,
            feature_schema_version="1.0",
            reference_notional_id=notional.id,
            reference_notional=Decimal("500.00"),
            training_data_window_start=Clock.utcnow(),
            training_data_window_end=Clock.utcnow(),
            estimate_source_method_version="1.0",
            is_active=True,
        )
        db.session.add(mv)
        db.session.commit()
        return mv.id


@pytest.fixture
def anchored_recommendation(app, sample_user, active_stock, sample_model_version):
    with app.app_context():
        rec = Recommendation(
            user_id=sample_user,
            budget=Decimal("10000.00"),
            effective_budget=Decimal("9950.00"),
            cash_buffer=Decimal("50.00"),
            mode="CNC",
            horizon="1d",
            model_version_id=sample_model_version,
            rate_card_version="standard_equity_2026",
            reference_notional=Decimal("500.00"),
            status="ANCHORED",  # Rule 9: Must be anchored!
            commitment_hash="0x" + "11" * 32,
        )
        db.session.add(rec)
        db.session.flush()

        item = RecommendationItem(
            recommendation_id=rec.id,
            stock_id=active_stock,
            ticker="TCS",
            quantity=2,
            allocated_amount=Decimal("7000.00"),
            expected_return_rate=Decimal("0.025000"),
            p_i=Decimal("0.650000"),
            g_plus=Decimal("100.000000"),
            g_minus=Decimal("-50.000000"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            stock_status_at_creation="active",
        )
        db.session.add(item)
        db.session.commit()
        return rec.id


def test_at_16_open_paper_trade_success_and_idempotency(app, sample_user, anchored_recommendation, paper_trade_service):
    """AT-16: Paper trade opens from anchored recommendation; respects Idempotency-Key (§6.3)."""
    with app.app_context():
        key = "idemp_key_test_001"
        trade, was_cached = paper_trade_service.open_paper_trade(
            user_id=sample_user,
            recommendation_id=anchored_recommendation,
            idempotency_key=key,
            execution_prices={"TCS": Decimal("3500.00")},
        )
        assert was_cached is False
        assert trade.status == "OPEN"
        assert trade.mode == "CNC"
        assert len(trade.legs) == 1
        assert trade.legs[0].action == "BUY"
        assert trade.legs[0].quantity == 2
        assert trade.legs[0].price == Decimal("3500.00")
        assert trade.legs[0].cost_breakdown_id is not None

        # Repeat request with IDENTICAL payload -> cached response returned
        trade_repeat, was_cached_repeat = paper_trade_service.open_paper_trade(
            user_id=sample_user,
            recommendation_id=anchored_recommendation,
            idempotency_key=key,
            execution_prices={"TCS": Decimal("3500.00")},
        )
        assert was_cached_repeat is True
        assert trade_repeat.id == trade.id

        # Repeat request with DIFFERENT payload -> 409 Conflict
        with pytest.raises(PaperTradeError) as exc:
            paper_trade_service.open_paper_trade(
                user_id=sample_user,
                recommendation_id=anchored_recommendation,
                idempotency_key=key,
                execution_prices={"TCS": Decimal("3600.00")},  # Different price
            )
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"
        assert exc.value.status_code == 409


def test_at_16_rule_9_reject_unanchored_recommendation(app, sample_user, active_stock, sample_model_version, paper_trade_service):
    """Rule 9: Rejects paper trade before recommendation anchoring."""
    with app.app_context():
        draft_rec = Recommendation(
            user_id=sample_user,
            budget=Decimal("5000.00"),
            effective_budget=Decimal("4975.00"),
            cash_buffer=Decimal("25.00"),
            mode="CNC",
            horizon="1d",
            model_version_id=sample_model_version,
            rate_card_version="standard_equity_2026",
            reference_notional=Decimal("500.00"),
            status="DRAFT",  # Not ANCHORED!
        )
        db.session.add(draft_rec)
        db.session.flush()

        item = RecommendationItem(
            recommendation_id=draft_rec.id,
            stock_id=active_stock,
            ticker="TCS",
            quantity=1,
            allocated_amount=Decimal("3500.00"),
            expected_return_rate=Decimal("0.020000"),
            p_i=Decimal("0.600000"),
            g_plus=Decimal("50.00"),
            g_minus=Decimal("-25.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
        )
        db.session.add(item)
        db.session.commit()

        with pytest.raises(PaperTradeError) as exc:
            paper_trade_service.open_paper_trade(
                user_id=sample_user,
                recommendation_id=draft_rec.id,
            )
        assert exc.value.code == "RECOMMENDATION_NOT_ANCHORED"


def test_at_16_uni_03_trd_13_reject_inactive_stock(app, sample_user, inactive_stock, sample_model_version, paper_trade_service):
    """UNI-03 & TRD-13: Re-validates stock status at open; rejects with STOCK_UNAVAILABLE (409) if not active."""
    with app.app_context():
        rec = Recommendation(
            user_id=sample_user,
            budget=Decimal("1000.00"),
            effective_budget=Decimal("995.00"),
            cash_buffer=Decimal("5.00"),
            mode="CNC",
            horizon="1d",
            model_version_id=sample_model_version,
            rate_card_version="standard_equity_2026",
            reference_notional=Decimal("500.00"),
            status="ANCHORED",
        )
        db.session.add(rec)
        db.session.flush()

        item = RecommendationItem(
            recommendation_id=rec.id,
            stock_id=inactive_stock,
            ticker="SUSPENDED_CO",
            quantity=5,
            allocated_amount=Decimal("500.00"),
            expected_return_rate=Decimal("0.010000"),
            p_i=Decimal("0.550000"),
            g_plus=Decimal("10.00"),
            g_minus=Decimal("-5.00"),
            estimate_source="prior",
            method_version="1.0",
        )
        db.session.add(item)
        db.session.commit()

        with pytest.raises(PaperTradeError) as exc:
            paper_trade_service.open_paper_trade(
                user_id=sample_user,
                recommendation_id=rec.id,
            )
        assert exc.value.code == "STOCK_UNAVAILABLE"
        assert exc.value.status_code == 409


def test_at_17_close_paper_trade_and_realized_pnl(app, sample_user, anchored_recommendation, paper_trade_service):
    """AT-17: Closing paper trade calculates realized gross and net P&L after modeled costs."""
    with app.app_context():
        # Open trade (Buy 2 TCS @ 3500 = 7000 turnover)
        trade, _ = paper_trade_service.open_paper_trade(
            user_id=sample_user,
            recommendation_id=anchored_recommendation,
            execution_prices={"TCS": Decimal("3500.00")},
        )
        assert trade.status == "OPEN"

        # Close trade (Sell 2 TCS @ 3600 = 7200 turnover)
        # Gross profit = 2 * (3600 - 3500) = +200.00
        closed_trade = paper_trade_service.close_paper_trade(
            paper_trade_id=trade.id,
            user_id=sample_user,
            exit_prices={"TCS": Decimal("3600.00")},
        )

        assert closed_trade.status == "CLOSED"
        assert closed_trade.closed_at is not None
        assert closed_trade.total_gross_pnl == Decimal("200.00")
        # Net profit must be strictly less than gross profit due to transaction charges (STT, DP, GST, slippage)
        assert closed_trade.total_net_pnl < closed_trade.total_gross_pnl
        assert closed_trade.total_net_pnl > Decimal("150.00")  # Should be ~ 170-180 after ~20-30 costs
        assert len(closed_trade.legs) == 2  # 1 BUY, 1 SELL

        # Re-closing an already closed trade should fail
        with pytest.raises(PaperTradeError) as exc:
            paper_trade_service.close_paper_trade(
                paper_trade_id=trade.id,
                user_id=sample_user,
            )
        assert exc.value.code == "TRADE_ALREADY_CLOSED"


def test_at_34_user_history_and_isolation(app, sample_user, second_user, anchored_recommendation, paper_trade_service):
    """AT-34: History querying, ownership isolation, and expected vs realized P&L separation (EXP-06)."""
    with app.app_context():
        trade, _ = paper_trade_service.open_paper_trade(
            user_id=sample_user,
            recommendation_id=anchored_recommendation,
            execution_prices={"TCS": Decimal("3500.00")},
        )
        paper_trade_service.close_paper_trade(
            paper_trade_id=trade.id,
            user_id=sample_user,
            exit_prices={"TCS": Decimal("3550.00")},
        )

        # Query user 1 history
        user1_hist = paper_trade_service.get_user_history(user_id=sample_user)
        assert len(user1_hist) == 1
        t_hist = user1_hist[0]
        assert t_hist["trade_id"] == trade.id
        assert t_hist["status"] == "CLOSED"
        assert t_hist["expected_pnl"] is not None  # EXP-06
        assert Decimal(t_hist["realized_gross_pnl"]) == Decimal("100.00")
        assert t_hist["realized_net_pnl"] is not None
        assert "educational simulation" in t_hist["disclaimer"]

        # Isolation: User 2 must see 0 trades
        user2_hist = paper_trade_service.get_user_history(user_id=second_user)
        assert len(user2_hist) == 0

        # User 2 cannot close User 1's trade
        with pytest.raises(PaperTradeError) as exc:
            paper_trade_service.close_paper_trade(
                paper_trade_id=trade.id,
                user_id=second_user,
            )
        assert exc.value.code == "FORBIDDEN"
        assert exc.value.status_code == 403


def test_paper_trade_api_endpoints(client, anchored_recommendation, app):
    """Verifies HTTP API endpoints for /api/v1/paper-trades and /api/v1/history."""
    # Register and login to obtain a valid bearer token
    email = "api_user_pt@example.com"
    pwd = "StrongPassword123!"
    client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    token = login_resp.json["data"]["token"]
    user_id = login_resp.json["data"]["user"]["id"]

    with app.app_context():
        rec = db.session.get(Recommendation, anchored_recommendation)
        rec.user_id = user_id
        db.session.commit()

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Missing Idempotency-Key header on POST /api/v1/paper-trades
    resp = client.post(
        "/api/v1/paper-trades",
        json={"recommendation_id": anchored_recommendation},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"

    # 2. Open paper trade with Idempotency-Key
    headers_with_key = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "api_test_key_123",
    }
    resp_open = client.post(
        "/api/v1/paper-trades",
        json={"recommendation_id": anchored_recommendation},
        headers=headers_with_key,
    )
    assert resp_open.status_code == 201
    trade_id = resp_open.json["data"]["trade_id"]

    # 3. Close paper trade
    resp_close = client.post(
        f"/api/v1/paper-trades/{trade_id}/close",
        json={"exit_prices": {"TCS": "3580.00"}},
        headers=headers,
    )
    assert resp_close.status_code == 200
    assert resp_close.json["data"]["status"] == "CLOSED"

    # 4. Query history
    resp_hist = client.get("/api/v1/history", headers=headers)
    assert resp_hist.status_code == 200
    trades = resp_hist.json["data"]["trades"]
    assert len(trades) >= 1
    assert "Past performance" in resp_hist.json["data"]["disclaimer"]
