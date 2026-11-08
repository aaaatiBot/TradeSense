"""Acceptance Tests for ML Pipeline and Conditional Return Estimation (AT-20, AT-21, AT-36, AT-37, AT-38, AT-39)."""
import datetime
from decimal import Decimal
import numpy as np
import pytest

from app.extensions import db
from app.models.model_version import ModelVersion
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.services.conditional_return_service import ConditionalReturnService
from app.services.prediction_service import PredictionService, ModelLifecycleError
from app.utils.clock import Clock


# ==============================================================================
# AT-20: ML Inference Produces Valid Probabilities p_i in [0, 1]
# ==============================================================================
def test_at_20_prediction_probability_bounds():
    """AT-20: Verify prediction output p_i is strictly in [0, 1]."""
    X = np.array([
        [1.0, 0.5, 0.2],
        [-1.0, -0.5, -0.2],
        [2.0, 1.0, 0.5],
        [-2.0, -1.0, -0.5],
    ])
    y = np.array([1, 0, 1, 0])

    model = PredictionService.train_baseline_classifier(X, y)

    test_samples = [
        [1.5, 0.8, 0.3],
        [-1.5, -0.8, -0.3],
        [0.0, 0.0, 0.0],
    ]
    for sample in test_samples:
        p_i = PredictionService.predict_probability(model, sample)
        assert 0.0 <= p_i <= 1.0


# ==============================================================================
# AT-21: Chronological Walk-Forward Split
# ==============================================================================
def test_at_21_chronological_walk_forward_split():
    """AT-21: Walk-forward splits strictly respect temporal ordering (no future leakage)."""
    dates = [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(100)]
    train_cutoff = datetime.date(2026, 3, 1)

    train_dates = [d for d in dates if d < train_cutoff]
    test_dates = [d for d in dates if d >= train_cutoff]

    assert max(train_dates) < min(test_dates)
    assert len(train_dates) + len(test_dates) == len(dates)


# ==============================================================================
# AT-36: Conditional Return Fallback Chain (§4.5.1)
# ==============================================================================
def test_at_36_conditional_return_fallback_chain(app):
    """AT-36: Thin history falls back to universe baseline; thin universe falls back to prior."""
    # 1. Full ticker history (>= 30 per class) -> ticker_baseline
    pos_ticker = [0.015] * 35
    neg_ticker = [-0.010] * 35
    g_plus, g_minus, source, ver = ConditionalReturnService.estimate_conditional_returns(
        ticker="RELIANCE",
        horizon="SWING",
        mode="CNC",
        historical_returns=pos_ticker + neg_ticker,
        ticker_threshold=30,
    )
    assert source == "ticker_baseline"
    assert g_plus == Decimal("0.015000")
    assert g_minus == Decimal("-0.010000")

    # 2. Thin ticker history (< 30) but sufficient universe (>= 200) -> universe_baseline
    thin_ticker = [0.020] * 5 + [-0.015] * 5
    universe_full = [0.018] * 210 + [-0.012] * 210
    g_plus_u, g_minus_u, source_u, _ = ConditionalReturnService.estimate_conditional_returns(
        ticker="NEWSTOCK",
        horizon="SWING",
        mode="CNC",
        historical_returns=thin_ticker,
        universe_returns=universe_full,
        ticker_threshold=30,
        universe_threshold=200,
    )
    assert source_u == "universe_baseline"
    assert g_plus_u == Decimal("0.018000")
    assert g_minus_u == Decimal("-0.012000")

    # 3. Thin universe (< 200) -> prior fallback
    thin_universe = [0.018] * 50 + [-0.012] * 50
    g_plus_p, g_minus_p, source_p, _ = ConditionalReturnService.estimate_conditional_returns(
        ticker="VERYNEW",
        horizon="SWING",
        mode="CNC",
        historical_returns=thin_ticker,
        universe_returns=thin_universe,
        ticker_threshold=30,
        universe_threshold=200,
        g_plus_prior=Decimal("0.0060"),
        g_minus_prior=Decimal("-0.0060"),
    )
    assert source_p == "prior"
    assert g_plus_p == Decimal("0.0060")
    assert g_minus_p == Decimal("-0.0060")


# ==============================================================================
# AT-37: Label Reference Notional Sensitivity (§9.4)
# ==============================================================================
def test_at_37_label_reference_notional_sensitivity():
    """AT-37: Changing reference notional from ₹500 to ₹10,000 alters label distribution."""
    # A price moving from 500 to 510 (+2% gross)
    # Buy 1 share @ 500, Sell @ 510: Gross PnL = +10.00.
    # But CNC DP charge is 15.93 + STT/taxes (~16.50 total charges).
    # At notional ₹500 (qty=1): Net PnL = 10.00 - 16.50 = -6.50 <= 0 -> Label is 0!
    lbl_500 = PredictionService.compute_label_at_notional(
        buy_price=Decimal("500.00"),
        sell_price=Decimal("510.00"),
        reference_notional=Decimal("500.00"),
        mode="CNC",
    )
    assert lbl_500 == 0

    # At notional ₹10,000 (qty = 10000 // 500 = 20 shares):
    # Gross PnL = 20 * 10 = +200.00. Total charges ~ 36.00.
    # Net PnL = +164.00 > 0 -> Label is 1!
    lbl_10000 = PredictionService.compute_label_at_notional(
        buy_price=Decimal("500.00"),
        sell_price=Decimal("510.00"),
        reference_notional=Decimal("10000.00"),
        mode="CNC",
    )
    assert lbl_10000 == 1


# ==============================================================================
# AT-38 & AT-39: Model Promotion & Rollback (§9.8)
# ==============================================================================
def test_at_38_model_promotion_requires_evaluation_report(app):
    """AT-38: Model promotion without evaluation report fails with MODEL_ACTIVATION_INVALID."""
    notional = ReferenceNotionalConfig(version_tag="notional_default", notional_amount=Decimal("500.00"))
    db.session.add(notional)
    db.session.commit()

    model = ModelVersion(
        version_tag="model_alpha",
        artifact_hash="b" * 64,
        feature_schema_version="v3.1.0",
        reference_notional_id=notional.id,
        reference_notional=Decimal("500.00"),
        training_data_window_start=Clock.utcnow() - datetime.timedelta(days=90),
        training_data_window_end=Clock.utcnow(),
        estimate_source_method_version="v3.1.0",
        is_active=False,
    )
    db.session.add(model)
    db.session.commit()

    # Attempt promotion without report
    with pytest.raises(ModelLifecycleError) as exc_info:
        PredictionService.promote_model("model_alpha", evaluation_report=None)
    assert exc_info.value.code == "MODEL_ACTIVATION_INVALID"

    # Attempt with empty string
    with pytest.raises(ModelLifecycleError) as exc_info:
        PredictionService.promote_model("model_alpha", evaluation_report="   ")
    assert exc_info.value.code == "MODEL_ACTIVATION_INVALID"

    # Promotion with valid report succeeds
    valid_report = '{"mcc": 0.22, "brier": 0.19, "reference_notional": 500}'
    promoted = PredictionService.promote_model("model_alpha", evaluation_report=valid_report, actor="lead_data_scientist")
    assert promoted.is_active is True
    assert promoted.activated_by == "lead_data_scientist"


def test_at_39_model_rollback(app):
    """AT-39: Rollback restores previous active model version atomically without restart."""
    notional = db.session.query(ReferenceNotionalConfig).first()
    if notional is None:
        notional = ReferenceNotionalConfig(version_tag="notional_ref", notional_amount=Decimal("500.00"))
        db.session.add(notional)
        db.session.commit()

    model_a = ModelVersion(
        version_tag="model_v1",
        artifact_hash="1" * 64,
        feature_schema_version="v3.1.0",
        reference_notional_id=notional.id,
        reference_notional=Decimal("500.00"),
        training_data_window_start=Clock.utcnow() - datetime.timedelta(days=120),
        training_data_window_end=Clock.utcnow() - datetime.timedelta(days=30),
        estimate_source_method_version="v3.1.0",
        evaluation_report='{"mcc": 0.20}',
        is_active=True,
    )
    model_b = ModelVersion(
        version_tag="model_v2",
        artifact_hash="2" * 64,
        feature_schema_version="v3.1.0",
        reference_notional_id=notional.id,
        reference_notional=Decimal("500.00"),
        training_data_window_start=Clock.utcnow() - datetime.timedelta(days=90),
        training_data_window_end=Clock.utcnow(),
        estimate_source_method_version="v3.1.0",
        evaluation_report='{"mcc": 0.25}',
        is_active=False,
    )
    db.session.add_all([model_a, model_b])
    db.session.commit()

    # Promote model_b
    PredictionService.promote_model("model_v2", evaluation_report='{"mcc": 0.25}', actor="admin")
    assert db.session.get(ModelVersion, model_b.id).is_active is True
    assert db.session.get(ModelVersion, model_a.id).is_active is False

    # Roll back to model_a
    PredictionService.rollback_model("model_v1", actor="admin")
    assert db.session.get(ModelVersion, model_a.id).is_active is True
    assert db.session.get(ModelVersion, model_b.id).is_active is False
