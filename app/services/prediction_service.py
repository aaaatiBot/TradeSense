"""Machine Learning prediction and model lifecycle service per SRS §4.4, §9.4, and §9.8."""
from __future__ import annotations

import datetime
from decimal import Decimal
import json
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from sklearn.linear_model import LogisticRegression
from sqlalchemy import select

from app.extensions import db
from app.models.model_version import ModelVersion
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.services.cost_engine import CostEngine
from app.utils.clock import Clock


class ModelLifecycleError(Exception):
    """Exception raised for model registration, validation, or promotion errors."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class PredictionService:
    """Handles LightGBM/Logistic classifier inference, labeling at reference notional, and lifecycle."""

    DEFAULT_REFERENCE_NOTIONAL = Decimal("500.00")

    @classmethod
    def compute_label_at_notional(
        cls,
        buy_price: Decimal,
        sell_price: Decimal,
        reference_notional: Optional[Decimal] = None,
        mode: str = "CNC",
        isin: str = "INE000000000",
        ticker: str = "TICKER",
    ) -> int:
        """Assign binary label (1 if net return > 0 at reference notional, else 0) per SRS §9.4.1."""
        notional = reference_notional or cls.DEFAULT_REFERENCE_NOTIONAL
        qty = max(1, int(notional // buy_price))

        cost_res = CostEngine.calculate_round_trip(
            ticker=ticker,
            isin=isin,
            quantity=qty,
            buy_price=buy_price,
            sell_price=sell_price,
            mode=mode,
        )
        gross_pnl = Decimal(str(qty)) * (sell_price - buy_price)
        net_pnl = gross_pnl - cost_res.total_charges
        return 1 if net_pnl > 0 else 0

    @classmethod
    def generate_labels_for_series(
        cls,
        prices: List[Decimal],
        reference_notional: Decimal,
        mode: str = "CNC",
    ) -> List[int]:
        """Generate binary labels across a price series at a given reference notional (AT-37)."""
        labels = []
        for i in range(len(prices) - 1):
            lbl = cls.compute_label_at_notional(
                buy_price=prices[i],
                sell_price=prices[i + 1],
                reference_notional=reference_notional,
                mode=mode,
            )
            labels.append(lbl)
        return labels

    @classmethod
    def train_baseline_classifier(
        cls, X: np.ndarray, y: np.ndarray
    ) -> LogisticRegression:
        """Train baseline logistic regression classifier (ML-01)."""
        model = LogisticRegression(random_state=42, max_iter=200)
        model.fit(X, y)
        return model

    @classmethod
    def predict_probability(
        cls, model: Any, feature_vector: List[float]
    ) -> float:
        """Predict probability p_i in [0, 1] of positive net return (AT-20)."""
        X = np.array([feature_vector])
        if hasattr(model, "predict_proba"):
            prob = float(model.predict_proba(X)[0][1])
        else:
            # Fallback deterministic sigmoid
            z = sum(feature_vector)
            prob = 1.0 / (1.0 + math.exp(-z))
        return min(1.0, max(0.0, prob))

    @classmethod
    def promote_model(
        cls,
        version_tag: str,
        evaluation_report: Optional[str],
        actor: str = "admin",
    ) -> ModelVersion:
        """Promote model version to active status with validation per SRS §9.8.2 and AT-38."""
        if not evaluation_report or not evaluation_report.strip():
            raise ModelLifecycleError(
                "MODEL_ACTIVATION_INVALID",
                "Model activation requires an explicit evaluation report with walk-forward metrics",
            )

        model = db.session.execute(
            select(ModelVersion).where(ModelVersion.version_tag == version_tag)
        ).scalar_one_or_none()

        if model is None:
            raise ModelLifecycleError("MODEL_NOT_FOUND", f"Model version '{version_tag}' not found", status_code=404)

        # Deactivate all currently active models
        active_models = db.session.execute(
            select(ModelVersion).where(ModelVersion.is_active == True)
        ).scalars().all()
        for m in active_models:
            m.is_active = False

        # Atomically promote target model
        now = Clock.utcnow()
        model.is_active = True
        model.evaluation_report = evaluation_report
        model.activated_at = now
        model.activated_by = actor

        db.session.commit()
        return model

    @classmethod
    def rollback_model(
        cls,
        target_version_tag: str,
        actor: str = "admin",
    ) -> ModelVersion:
        """Rollback to a previously active model version atomically per SRS §9.8.3."""
        model = db.session.execute(
            select(ModelVersion).where(ModelVersion.version_tag == target_version_tag)
        ).scalar_one_or_none()

        if model is None:
            raise ModelLifecycleError("MODEL_NOT_FOUND", f"Target model '{target_version_tag}' not found", status_code=404)

        active_models = db.session.execute(
            select(ModelVersion).where(ModelVersion.is_active == True)
        ).scalars().all()
        for m in active_models:
            m.is_active = False

        now = Clock.utcnow()
        model.is_active = True
        model.activated_at = now
        model.activated_by = f"{actor} (rollback)"

        db.session.commit()
        return model

    @classmethod
    def get_active_model(cls) -> Optional[ModelVersion]:
        """Fetch current active model version."""
        return db.session.execute(
            select(ModelVersion).where(ModelVersion.is_active == True)
        ).scalar_one_or_none()
