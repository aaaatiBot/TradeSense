"""Dashboard and Market Quotes route blueprint per SRS §10 and Phase D."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.market_data_service import MarketDataError, MarketDataService
from app.services.universe_service import UniverseService
from app.utils.response import api_error, api_success

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/v1/dashboard")


@dashboard_bp.route("/quotes", methods=["GET"])
def get_live_quotes():
    """Retrieve current real-time or cached quotes for active universe stocks."""
    stocks = UniverseService.list_active_stocks()
    tickers = [s.ticker for s in stocks] if stocks else ["INFY", "TCS", "RELIANCE", "HDFCBANK", "ICICIBANK", "WIPRO"]
    quotes = []

    for t in tickers:
        try:
            q = MarketDataService.get_quote(t)
            quotes.append({
                "ticker": q["ticker"],
                "price": str(q["price"]),
                "volume": q.get("volume", 0),
                "is_live": q.get("is_live", False),
                "is_stale": q.get("is_stale", False),
                "source": q.get("source", "market_data"),
                "timestamp": q["timestamp"].isoformat() if hasattr(q["timestamp"], "isoformat") else str(q["timestamp"]),
            })
        except Exception:
            continue

    return api_success(data={"quotes": quotes})


@dashboard_bp.route("/quotes/<ticker>", methods=["GET"])
def get_single_quote(ticker: str):
    """Retrieve real-time quote for a specific ticker."""
    try:
        q = MarketDataService.get_quote(ticker)
        return api_success(data={
            "ticker": q["ticker"],
            "price": str(q["price"]),
            "volume": q.get("volume", 0),
            "is_live": q.get("is_live", False),
            "is_stale": q.get("is_stale", False),
            "source": q.get("source", "market_data"),
            "timestamp": q["timestamp"].isoformat() if hasattr(q["timestamp"], "isoformat") else str(q["timestamp"]),
        })
    except MarketDataError as exc:
        return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
    except Exception as exc:
        return api_error(code="QUOTE_ERROR", message=str(exc), status_code=500)
