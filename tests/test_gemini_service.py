"""Acceptance tests for Gemini Service & News Sentiment (Phase 10, AT-18).

Verifies:
- AT-18: News headline sentiment analysis (POSITIVE, NEGATIVE, NEUTRAL).
- Non-authoritative educational trade explanations (NWS-04).
- Resilient graceful degradation when API key missing or external error occurs.
- Caching of sentiment scores in news_items table.
"""
from decimal import Decimal
import pytest

from app.extensions import db
from app.models.news_item import NewsItem
from app.services.gemini_service import GeminiService


@pytest.fixture
def gemini_service():
    return GeminiService(api_key="mock_gemini_api_key")


@pytest.fixture
def degraded_gemini_service():
    return GeminiService(api_key="")  # Missing key triggers graceful degradation


def test_at_18_news_sentiment_analysis(app, gemini_service):
    """AT-18: Verifies bullish, bearish, and neutral sentiment classification."""
    with app.app_context():
        # 1. Bullish / Positive headlines
        pos_headlines = [
            "TCS reports record profit growth and beats market expectations",
            "Analysts surge target price with strong upgrade",
        ]
        pos_res = gemini_service.analyze_news_sentiment(ticker="TCS", headlines=pos_headlines)
        assert pos_res["ticker"] == "TCS"
        assert pos_res["sentiment_label"] == "POSITIVE"
        assert pos_res["sentiment_score"] > Decimal("0.0")
        assert "bullish" in pos_res["summary"].lower()

        # 2. Bearish / Negative headlines
        neg_headlines = [
            "Infosys faces severe revenue slump and profit drop",
            "Brokerage issues downgrade following guidance miss",
        ]
        neg_res = gemini_service.analyze_news_sentiment(ticker="INFY", headlines=neg_headlines)
        assert neg_res["ticker"] == "INFY"
        assert neg_res["sentiment_label"] == "NEGATIVE"
        assert neg_res["sentiment_score"] < Decimal("0.0")

        # 3. Neutral headlines
        neutral_headlines = [
            "Reliance Industries announces annual general meeting schedule",
        ]
        neut_res = gemini_service.analyze_news_sentiment(ticker="RELIANCE", headlines=neutral_headlines)
        assert neut_res["sentiment_label"] == "NEUTRAL"
        assert neut_res["sentiment_score"] == Decimal("0.0000")


def test_at_18_graceful_degradation_without_api_key(app, degraded_gemini_service):
    """AT-18: When Gemini API key is missing, falls back gracefully without failing application."""
    with app.app_context():
        headlines = ["Tata Motors reports strong quarterly vehicle sales"]
        res = degraded_gemini_service.analyze_news_sentiment(ticker="TATAMOTORS", headlines=headlines)
        assert res["ticker"] == "TATAMOTORS"
        assert res["degraded"] is True
        assert res["sentiment_label"] in ("POSITIVE", "NEUTRAL")


def test_at_18_graceful_degradation_on_api_error(app, gemini_service, mocker):
    """AT-18: When external API call raises an exception, falls back gracefully."""
    with app.app_context():
        mocker.patch.object(gemini_service, "_call_gemini_api", side_effect=RuntimeError("Gemini API 503 Overloaded"))
        headlines = ["SBI announces expansion in retail banking branches"]
        res = gemini_service.analyze_news_sentiment(ticker="SBIN", headlines=headlines)
        assert res["ticker"] == "SBIN"
        assert res["degraded"] is True
        assert res["sentiment_label"] in ("POSITIVE", "NEUTRAL", "NEGATIVE")


def test_at_18_educational_explanation_generation(gemini_service):
    """AT-18 & NWS-04: Non-authoritative educational explanation includes probability, costs, and disclaimer."""
    explanation = gemini_service.explain_recommendation_item(
        ticker="TCS",
        quantity=5,
        price=Decimal("3500.00"),
        p_i=Decimal("0.680000"),
        expected_return_rate=Decimal("0.032000"),
        indicators={"rsi_14": 58.4},
    )

    assert "TCS was allocated 5 shares" in explanation
    assert "₹3500.00" in explanation
    assert "68.0% probability" in explanation
    assert "3.20%" in explanation
    assert "RSI of 58.4" in explanation
    assert "educational" in explanation.lower()
    assert "not investment advice" in explanation.lower()


def test_sentiment_caching_in_news_items(app, gemini_service):
    """Verifies that sentiment outputs are cached and reuse stored records."""
    with app.app_context():
        headlines = ["Wipro wins multi-million dollar cloud digital transformation deal"]
        res1 = gemini_service.analyze_news_sentiment(ticker="WIPRO", headlines=headlines)
        assert res1["cached"] is False

        # Second call should fetch cached entry
        res2 = gemini_service.analyze_news_sentiment(ticker="WIPRO", headlines=headlines)
        assert res2["cached"] is True
        assert res2["sentiment_score"] == res1["sentiment_score"]
        assert res2["sentiment_label"] == res1["sentiment_label"]
