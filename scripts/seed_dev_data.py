"""Seed development database with active universe, rate cards, model version, and live yfinance market data."""
from __future__ import annotations

import datetime
from decimal import Decimal
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models.cost_rate_card import CostRateCard
from app.models.model_version import ModelVersion
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.models.stock import Stock
from app.services.disclaimer_service import DisclaimerService
from app.services.market_data_service import MarketDataService


def seed_database():
    app = create_app("development")
    with app.app_context():
        print("--- [1/5] Seeding Disclaimers ---")
        DisclaimerService.seed_disclaimers()

        print("--- [2/5] Seeding Rate Cards & Model Versions ---")
        now = datetime.datetime.now(datetime.timezone.utc)

        card = CostRateCard.query.filter_by(version="zerodha-2026").first()
        if not card:
            card = CostRateCard(
                version="zerodha-2026",
                name="Zerodha Standard 2026",
                effective_from=now,
                is_active=True,
                verified_at=now,
                source_reference="SEBI Circular 2026",
            )
            db.session.add(card)

        ref = ReferenceNotionalConfig.query.filter_by(version_tag="v1.0_ref").first()
        if not ref:
            ref = ReferenceNotionalConfig(
                version_tag="v1.0_ref",
                notional_amount=Decimal("500.00"),
                is_active=True,
            )
            db.session.add(ref)

        model = ModelVersion.query.filter_by(version_tag="lgbm-classifier-v1.0").first()
        if not model:
            model = ModelVersion(
                version_tag="lgbm-classifier-v1.0",
                artifact_hash="a" * 64,
                feature_schema_version="v1.0",
                reference_notional_id=ref.id,
                reference_notional=Decimal("500.00"),
                training_data_window_start=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
                training_data_window_end=datetime.datetime(2025, 12, 31, tzinfo=datetime.timezone.utc),
                estimate_source_method_version="v1.0",
                evaluation_report="EVAL REPORT: Challenger passed all gates",
                is_active=True,
            )
            db.session.add(model)

        db.session.commit()

        print("--- [3/5] Seeding Stock Universe ---")
        stocks_data = [
            ("RELIANCE", "Reliance Industries Limited", "INE002A01018"),
            ("TCS", "Tata Consultancy Services Limited", "INE467B01029"),
            ("INFY", "Infosys Limited", "INE009A01021"),
            ("ITC", "ITC Limited", "INE154A01025"),
            ("TATASTEEL", "Tata Steel Limited", "INE081A01020"),
            ("ONGC", "Oil and Natural Gas Corporation", "INE213A01029"),
            ("NTPC", "NTPC Limited", "INE733E01010"),
            ("BEL", "Bharat Electronics Limited", "INE263A01024"),
        ]

        for ticker, name, isin in stocks_data:
            s = Stock.query.filter_by(ticker=ticker).first()
            if not s:
                s = Stock(
                    ticker=ticker,
                    name=name,
                    isin=isin,
                    exchange="NSE",
                    status="active",
                )
                db.session.add(s)

        db.session.commit()

        print("--- [4/5] Polling yfinance for Stock Universe Prices ---")
        tickers = [s[0] for s in stocks_data]
        res = MarketDataService.poll_latest_prices(tickers)
        print("Polling Results:", res)

        print("--- [5/5] Verification ---")
        active_stocks = Stock.query.filter_by(status="active").all()
        print(f"Total active stocks: {len(active_stocks)}")
        for s in active_stocks:
            try:
                q = MarketDataService.get_quote(s.ticker)
                print(f"  {s.ticker:10}: Price={q['price']} (Source={q['source']}, Delayed={q.get('is_delayed')})")
            except Exception as e:
                print(f"  {s.ticker:10}: Error retrieving quote: {e}")

        print("--- Database seeding complete! ---")


if __name__ == "__main__":
    seed_database()
