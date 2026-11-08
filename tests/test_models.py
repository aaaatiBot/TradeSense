"""Tests for database models, constraints, Decimal fields, and anonymization."""
import datetime
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    User,
    Session,
    PasswordResetToken,
    Stock,
    Price,
    ReferenceNotionalConfig,
    ModelVersion,
    ConditionalReturnEstimate,
    CostRateCard,
    CostRate,
    Recommendation,
    RecommendationItem,
    CostBreakdown,
    PaperTrade,
    PaperTradeLeg,
    BlockchainRecord,
    NewsItem,
    JobQueue,
    IdempotencyRecord,
    ApiDeprecation,
    DisclaimerRegistry,
)
from app.utils.clock import Clock


def test_user_creation_and_anonymization(app):
    """Verify user anonymization (§7.18.3) preserves records and supports nulls."""
    user = User(
        email="trader@example.com",
        password_hash="argon2id$hashed",
        role="user",
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()

    assert user.id is not None
    assert user.is_active is True
    assert user.anonymized_at is None

    # Simulate account deletion / anonymization per §7.18.3
    user.is_active = False
    user.email = None
    user.password_hash = None
    user.anonymized_at = Clock.utcnow()
    db.session.commit()

    reloaded = db.session.get(User, user.id)
    assert reloaded.is_active is False
    assert reloaded.email is None
    assert reloaded.password_hash is None
    assert reloaded.anonymized_at is not None


def test_user_sessions_cascade_delete(app):
    """Verify deleting a user cascades to sessions."""
    user = User(email="cascade@example.com", password_hash="hash")
    db.session.add(user)
    db.session.commit()

    session = Session(
        user_id=user.id,
        session_token_hash="tok_hash_123",
        expires_at=Clock.utcnow() + datetime.timedelta(hours=8),
        last_active_at=Clock.utcnow(),
    )
    db.session.add(session)
    db.session.commit()

    db.session.delete(user)
    db.session.commit()

    assert db.session.get(Session, session.id) is None


def test_stock_and_price_precision(app):
    """Verify Stock status and high-precision Decimal fields in Price (§7.4)."""
    stock = Stock(
        ticker="RELIANCE",
        name="Reliance Industries Ltd",
        isin="INE002A01018",
        exchange="NSE",
        status="active",
    )
    db.session.add(stock)
    db.session.commit()

    price = Price(
        stock_id=stock.id,
        ticker="RELIANCE",
        timestamp=Clock.utcnow(),
        open=Decimal("2850.5000"),
        high=Decimal("2890.7500"),
        low=Decimal("2840.1000"),
        close=Decimal("2880.2500"),
        volume=1500000,
        source="market_data",
    )
    db.session.add(price)
    db.session.commit()

    reloaded = db.session.get(Price, price.id)
    assert isinstance(reloaded.close, Decimal)
    assert reloaded.close == Decimal("2880.2500")


def test_model_version_provenance_fields(app):
    """Verify ModelVersion records all required provenance fields (§9.8.5, Correction 2)."""
    notional = ReferenceNotionalConfig(
        version_tag="v1.0-default",
        notional_amount=Decimal("500.00"),
        is_active=True,
    )
    db.session.add(notional)
    db.session.commit()

    mv = ModelVersion(
        version_tag="lgbm-2026-w45",
        artifact_hash="a" * 64,
        feature_schema_version="v2.1",
        reference_notional_id=notional.id,
        reference_notional=Decimal("500.00"),
        training_data_window_start=Clock.utcnow() - datetime.timedelta(days=365),
        training_data_window_end=Clock.utcnow(),
        estimate_source_method_version="1.0",
        evaluation_report='{"mcc": 0.18, "brier": 0.22}',
        is_active=True,
    )
    db.session.add(mv)
    db.session.commit()

    reloaded = db.session.get(ModelVersion, mv.id)
    assert reloaded.feature_schema_version == "v2.1"
    assert reloaded.reference_notional == Decimal("500.00")
    assert reloaded.estimate_source_method_version == "1.0"


def test_cost_rate_card_verification_fields(app):
    """Verify CostRateCard contains verified_at and source_reference (§4.7, Correction 2)."""
    card = CostRateCard(
        version="v2026.1",
        name="Zerodha Equity Standard",
        effective_from=Clock.utcnow(),
        verified_at=Clock.utcnow(),
        source_reference="https://zerodha.com/charges/#tab-equities",
        is_active=True,
    )
    db.session.add(card)
    db.session.commit()

    reloaded = db.session.get(CostRateCard, card.id)
    assert reloaded.source_reference == "https://zerodha.com/charges/#tab-equities"
    assert reloaded.verified_at is not None


def test_api_deprecation_registry(app):
    """Verify ApiDeprecation entity (§6.6, Correction 2)."""
    dep = ApiDeprecation(
        endpoint="/api/v1/legacy-summary",
        method="GET",
        deprecation_date=Clock.utcnow(),
        sunset_date=Clock.utcnow() + datetime.timedelta(days=90),
        alternative_endpoint="/api/v1/recommendations",
    )
    db.session.add(dep)
    db.session.commit()

    reloaded = db.session.get(ApiDeprecation, dep.id)
    assert reloaded.endpoint == "/api/v1/legacy-summary"
    assert reloaded.sunset_date > reloaded.deprecation_date


def test_disclaimer_registry_uniqueness(app):
    """Verify DisclaimerRegistry unique constraint on (screen_name, version) (§15.1, Correction 2)."""
    d1 = DisclaimerRegistry(
        screen_name="dashboard",
        version="1.0",
        disclaimer_text="This is an educational simulation.",
        is_mandatory=True,
    )
    db.session.add(d1)
    db.session.commit()

    d2 = DisclaimerRegistry(
        screen_name="dashboard",
        version="1.0",
        disclaimer_text="Duplicate text",
        is_mandatory=True,
    )
    db.session.add(d2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_idempotency_record_uniqueness(app):
    """Verify IdempotencyRecord unique constraint per (user_id, idempotency_key, request_path)."""
    user = User(email="idem@example.com", password_hash="hash")
    db.session.add(user)
    db.session.commit()

    rec1 = IdempotencyRecord(
        user_id=user.id,
        idempotency_key="key-12345",
        request_path="/api/v1/paper-trades",
        request_hash="hash1",
        expires_at=Clock.utcnow() + datetime.timedelta(hours=24),
    )
    db.session.add(rec1)
    db.session.commit()

    rec2 = IdempotencyRecord(
        user_id=user.id,
        idempotency_key="key-12345",
        request_path="/api/v1/paper-trades",
        request_hash="hash2",
        expires_at=Clock.utcnow() + datetime.timedelta(hours=24),
    )
    db.session.add(rec2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
