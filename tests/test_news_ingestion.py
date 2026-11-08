"""Acceptance tests for Continuous News Ingestion and Asynchronous Gemini Sentiment (Phase 4.5).

Verifies:
- Headline normalization and deterministic SHA-256 hashing.
- Deduplication of incoming articles by headline hash.
- Initial ingestion stores sentiment=None (un-scored).
- Ticker symbol matching from headlines and summaries.
- Asynchronous batch sentiment scoring via GeminiService.score_unscored_news.
- Non-blocking sentiment retrieval via GeminiService.get_ticker_sentiment (sentiment_available=False fallback).
- JobWorker execution of 'news_poll' and 'score_news' background tasks.
"""
from decimal import Decimal
import datetime
import pytest
from unittest.mock import MagicMock, patch

from app.extensions import db
from app.models.news_item import NewsItem
from app.services.gemini_service import GeminiService
from app.services.news_ingestion_service import NewsIngestionService
from app.workers.job_worker import JobWorker
from app.utils.clock import Clock


def test_headline_normalization_and_hash():
    """Verifies headline normalization and consistent SHA-256 digest."""
    h1 = "  INFY Reports   Record Q3 Profit  Surge! "
    h2 = "infy reports record q3 profit surge!"
    h3 = "infy reports record q3 profit surge"

    norm1 = NewsIngestionService.normalize_headline(h1)
    norm2 = NewsIngestionService.normalize_headline(h2)
    assert norm1 == "infy reports record q3 profit surge!"
    assert norm1 == norm2

    hash1 = NewsIngestionService.compute_headline_hash(h1)
    hash2 = NewsIngestionService.compute_headline_hash(h2)
    hash3 = NewsIngestionService.compute_headline_hash(h3)

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64


def test_article_deduplication_by_sha256(app):
    """Verifies identical headlines are deduplicated and not inserted multiple times."""
    with app.app_context():
        articles = [
            {
                "ticker": "INFY",
                "headline": "Infosys signs major cloud transformation deal",
                "summary": "Large European enterprise signs multi-year deal.",
                "source": "economictimes",
                "published_at": Clock.utcnow(),
            },
            {
                "ticker": "INFY",
                "headline": "   infosys signs   major cloud transformation deal   ",  # Normalized duplicate
                "summary": "Duplicate wire report.",
                "source": "ndtv",
                "published_at": Clock.utcnow(),
            },
            {
                "ticker": "TCS",
                "headline": "TCS announces quarterly dividend payout",
                "summary": "Board approves dividend for shareholders.",
                "source": "moneycontrol",
                "published_at": Clock.utcnow(),
            },
        ]

        count = NewsIngestionService.ingest_articles(articles)
        assert count == 2  # Only 2 distinct headlines

        items = NewsItem.query.all()
        assert len(items) == 2

        # All ingested items must start with sentiment=None
        for it in items:
            assert it.sentiment_score is None
            assert it.sentiment_label is None
            assert it.headline_hash is not None

        # Re-ingesting the exact same batch inserts 0
        second_count = NewsIngestionService.ingest_articles(articles)
        assert second_count == 0
        assert NewsItem.query.count() == 2


def test_ticker_matching_from_content():
    """Verifies that ticker symbols are resolved correctly from headlines or fallback to MARKET."""
    t1 = NewsIngestionService.match_ticker("TCS quarterly results show steady growth in banking sector")
    assert t1 == "TCS"

    t2 = NewsIngestionService.match_ticker("Infosys strengthens partnership with global tech giants")
    assert t2 == "INFY"

    t3 = NewsIngestionService.match_ticker("Reliance Industries raises capital for green energy project")
    assert t3 == "RELIANCE"

    t4 = NewsIngestionService.match_ticker("RBI keeps repo rate unchanged at 6.5 percent")
    assert t4 == "MARKET"


def test_batch_sentiment_scoring_and_fallback(app):
    """Verifies that GeminiService asynchronously scores un-scored news items."""
    with app.app_context():
        now = Clock.utcnow()
        item1 = NewsItem(
            ticker="INFY",
            headline="Infosys shares surge 4% after record profit beat",
            summary="Bullish outlook drives IT index rally.",
            headline_hash=NewsIngestionService.compute_headline_hash("Infosys shares surge 4% after record profit beat"),
            sentiment_score=None,
            sentiment_label=None,
            source="ndtv",
            published_at=now,
            created_at=now,
        )
        item2 = NewsItem(
            ticker="TCS",
            headline="TCS faces revenue decline amid macroeconomic slump",
            summary="Bearish headwinds affect client spending.",
            headline_hash=NewsIngestionService.compute_headline_hash("TCS faces revenue decline amid macroeconomic slump"),
            sentiment_score=None,
            sentiment_label=None,
            source="ndtv",
            published_at=now,
            created_at=now,
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        gemini_service = GeminiService()
        scored_count = gemini_service.score_unscored_news(limit=10)
        assert scored_count == 2

        db.session.expire_all()
        scored1 = db.session.get(NewsItem, item1.id)
        scored2 = db.session.get(NewsItem, item2.id)

        assert scored1.sentiment_label == "POSITIVE"
        assert scored1.sentiment_score > Decimal("0")

        assert scored2.sentiment_label == "NEGATIVE"
        assert scored2.sentiment_score < Decimal("0")

        # Second run has nothing unscored
        assert gemini_service.score_unscored_news(limit=10) == 0


def test_non_blocking_sentiment_retrieval(app):
    """Verifies get_ticker_sentiment returns sentiment_available=False when no sentiment exists."""
    with app.app_context():
        gemini_service = GeminiService()

        # Unknown or unscored ticker -> does not block or fail
        res = gemini_service.get_ticker_sentiment("UNKNOWN_STOCK")
        assert res["sentiment_available"] is False
        assert res["sentiment_score"] is None
        assert res["sentiment_label"] is None

        # Add scored news for WIPRO
        now = Clock.utcnow()
        wipro_news = NewsItem(
            ticker="WIPRO",
            headline="Wipro wins digital transformation contract",
            summary="Steady positive momentum.",
            headline_hash=NewsIngestionService.compute_headline_hash("Wipro wins digital transformation contract"),
            sentiment_score=Decimal("0.4000"),
            sentiment_label="POSITIVE",
            source="reuters",
            published_at=now,
            created_at=now,
        )
        db.session.add(wipro_news)
        db.session.commit()

        wipro_res = gemini_service.get_ticker_sentiment("WIPRO")
        assert wipro_res["sentiment_available"] is True
        assert wipro_res["sentiment_score"] == Decimal("0.4000")
        assert wipro_res["sentiment_label"] == "POSITIVE"


def test_poll_feeds_with_mocked_rss(app):
    """Verifies that poll_feeds parses RSS XML feeds and ingests articles into news_items."""
    with app.app_context():
        fake_entry = MagicMock()
        fake_entry.title = "Infosys expands global delivery network"
        fake_entry.summary = "New delivery center opened in Europe."
        fake_entry.published_parsed = (2026, 3, 11, 10, 30, 0, 2, 70, 0)

        fake_feed = MagicMock()
        fake_feed.entries = [fake_entry]

        with patch("feedparser.parse", return_value=fake_feed):
            count = NewsIngestionService.poll_feeds(feeds=["https://test.feed/rss"])
            assert count == 1

            saved = NewsItem.query.filter_by(ticker="INFY").first()
            assert saved is not None
            assert saved.headline == "Infosys expands global delivery network"
            assert saved.source == "https://test.feed/rss"
            assert saved.sentiment_score is None


def test_job_worker_processes_news_poll_and_scoring(app):
    """Verifies JobWorker claims and runs 'news_poll' and 'score_news' background jobs."""
    with app.app_context():
        worker = JobWorker(app=app)

        # 1. News poll job
        with patch.object(NewsIngestionService, "poll_feeds", return_value=3) as mock_poll:
            job_poll = JobWorker.enqueue_job("news_poll", {})
            did_run = worker.run_once()
            assert did_run is True
            mock_poll.assert_called_once()
            db.session.expire_all()
            assert db.session.get(type(job_poll), job_poll.id).status == "COMPLETED"

        # 2. Score news job
        with patch.object(GeminiService, "score_unscored_news", return_value=2) as mock_score:
            job_score = JobWorker.enqueue_job("score_news", {"limit": 10})
            did_run = worker.run_once()
            assert did_run is True
            mock_score.assert_called_once_with(limit=10)
            db.session.expire_all()
            assert db.session.get(type(job_score), job_score.id).status == "COMPLETED"
