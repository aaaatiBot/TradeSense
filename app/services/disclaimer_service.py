"""Disclaimer service per SRS §15.1 and AT-43."""
from __future__ import annotations

from typing import List

from app.extensions import db
from app.models.disclaimer import DisclaimerRegistry

# Statutory disclaimers mapped per SRS §15.1
SCREEN_DISCLAIMERS = {
    "login": [
        "This is an educational simulation. Not investment advice. No real orders are placed."
    ],
    "dashboard": [
        "This is an educational simulation. Not investment advice. No real orders are placed."
    ],
    "recommendation": [
        "This is an educational simulation. Not investment advice. No real orders are placed.",
        "Predictions are uncertain. Expected returns are estimates, not guarantees.",
        "Simulated fills may differ from real-market execution.",
    ],
    "paper_trade_result": [
        "This is an educational simulation. Not investment advice. No real orders are placed.",
        "Predictions are uncertain. Expected returns are estimates, not guarantees.",
        "Simulated fills may differ from real-market execution.",
        "Transaction costs depend on the selected rate card and are subject to change.",
    ],
    "verification": [
        "Blockchain anchoring proves commitment integrity, not financial correctness."
    ],
    "history": [
        "This is an educational simulation. Not investment advice. No real orders are placed.",
        "Past performance does not guarantee future results.",
    ],
}


class DisclaimerService:
    """Service to register and retrieve statutory disclaimers per SRS §15.1."""

    @classmethod
    def seed_disclaimers(cls) -> None:
        """Seed the disclaimer registry table with all mandatory disclaimers from §15.1."""
        for screen, texts in SCREEN_DISCLAIMERS.items():
            for idx, text in enumerate(texts, 1):
                version = f"v1.0_{idx}"
                existing = DisclaimerRegistry.query.filter_by(
                    screen_name=screen, version=version
                ).first()
                if not existing:
                    entry = DisclaimerRegistry(
                        screen_name=screen,
                        disclaimer_text=text,
                        version=version,
                        is_mandatory=True,
                    )
                    db.session.add(entry)
        db.session.commit()

    @classmethod
    def get_disclaimers(cls, screen_name: str) -> List[str]:
        """Retrieve all mandatory disclaimers for a given screen."""
        records = (
            DisclaimerRegistry.query.filter_by(screen_name=screen_name, is_mandatory=True)
            .order_by(DisclaimerRegistry.id.asc())
            .all()
        )
        if records:
            return [r.disclaimer_text for r in records]
        # Fallback to in-code spec if registry not yet populated in session
        return SCREEN_DISCLAIMERS.get(screen_name, [])
