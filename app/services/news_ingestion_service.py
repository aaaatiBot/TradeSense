"""Continuous RSS and news feed ingestion service per Phase 4.5 and SRS §4.9.

Deduplicates news headlines using SHA-256 hashes of normalized titles and
persists un-scored headlines into `news_items` for asynchronous sentiment scoring.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional
import feedparser
from sqlalchemy import select

from app.extensions import db
from app.models.news_item import NewsItem
from app.services.universe_service import UniverseService
from app.utils.clock import Clock

logger = logging.getLogger("tradesense.news_ingestion")


class NewsIngestionService:
    """Ingests and deduplicates streaming financial news feeds."""

    DEFAULT_FEEDS = [
        "https://feeds.feedburner.com/ndtvprofit-latest",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://www.livemint.com/rss/markets",
    ]

    @staticmethod
    def normalize_headline(headline: str) -> str:
        """Normalize headline text: strip whitespace, lowercase, condense multiple spaces."""
        cleaned = re.sub(r"\s+", " ", str(headline or "")).strip().lower()
        return cleaned

    @classmethod
    def compute_headline_hash(cls, headline: str) -> str:
        """Compute deterministic SHA-256 digest of normalized headline string."""
        normalized = cls.normalize_headline(headline)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def match_ticker(cls, text: str) -> str:
        """Resolve ticker symbol from headline or summary text."""
        from flask import has_app_context

        upper_text = text.upper()

        # Query active universe tickers if in application context
        if has_app_context():
            try:
                active_stocks = UniverseService.list_active_stocks()
                for s in active_stocks:
                    if re.search(rf"\b{re.escape(s.ticker.upper())}\b", upper_text):
                        return s.ticker
                    if s.name and s.name.upper() in upper_text:
                        return s.ticker
            except Exception:
                pass

        # Static alias mapping for major Indian equities
        alias_map = {
            "INFY": ["INFY", "INFOSYS"],
            "TCS": ["TCS", "TATA CONSULTANCY"],
            "RELIANCE": ["RELIANCE", "RIL", "JIO"],
            "HDFCBANK": ["HDFCBANK", "HDFC BANK"],
            "ICICIBANK": ["ICICIBANK", "ICICI BANK"],
            "WIPRO": ["WIPRO"],
            "ITC": ["ITC"],
            "SBIN": ["SBIN", "STATE BANK OF INDIA", "SBI"],
        }
        for ticker, aliases in alias_map.items():
            for alias in aliases:
                if re.search(rf"\b{re.escape(alias)}\b", upper_text):
                    return ticker

        return "MARKET"

    @classmethod
    def parse_entry(cls, entry: Any, feed_source: str = "rss") -> Optional[Dict[str, Any]]:
        """Extract standardized dictionary from a feedparser entry."""
        title = getattr(entry, "title", None)
        if not title:
            return None

        summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        # Remove HTML tags if present in summary
        summary = re.sub(r"<[^>]+>", "", summary).strip()

        # Parse publication timestamp
        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            try:
                published_at = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                published_at = Clock.utcnow()
        else:
            published_at = Clock.utcnow()

        headline_hash = cls.compute_headline_hash(title)
        ticker = cls.match_ticker(f"{title} {summary}")

        return {
            "ticker": ticker,
            "headline": str(title).strip(),
            "summary": summary,
            "headline_hash": headline_hash,
            "published_at": published_at,
            "source": feed_source,
        }

    @classmethod
    def ingest_articles(cls, articles: List[Dict[str, Any]]) -> int:
        """Deduplicate and insert articles into news_items with sentiment=None."""
        if not articles:
            return 0

        inserted_count = 0
        now = Clock.utcnow()

        for art in articles:
            h_hash = art.get("headline_hash") or cls.compute_headline_hash(art["headline"])
            
            # Check duplicate by hash
            existing = db.session.execute(
                select(NewsItem).where(NewsItem.headline_hash == h_hash)
            ).scalar_one_or_none()

            if existing is not None:
                continue

            # Also check by exact headline for backward compatibility
            existing_by_title = db.session.execute(
                select(NewsItem).where(NewsItem.headline == art["headline"])
            ).scalar_one_or_none()
            if existing_by_title is not None:
                continue

            pub_at = Clock.ensure_utc(art.get("published_at") or now)
            item = NewsItem(
                ticker=art.get("ticker", "MARKET"),
                headline=art["headline"],
                summary=art.get("summary"),
                headline_hash=h_hash,
                sentiment_score=None,  # Un-scored per requirement
                sentiment_label=None,  # Un-scored per requirement
                source=art.get("source", "news_feed"),
                published_at=pub_at,
                created_at=now,
            )
            db.session.add(item)
            inserted_count += 1

        if inserted_count > 0:
            db.session.commit()
            logger.info(f"Ingested {inserted_count} new news items into news_items table")

        return inserted_count

    @classmethod
    def poll_feeds(cls, feeds: Optional[List[str]] = None) -> int:
        """Poll configured RSS feeds and ingest new deduplicated articles."""
        feed_urls: List[str] = []
        if feeds:
            feed_urls = feeds
        else:
            env_feeds = os.getenv("NEWS_RSS_FEEDS", "")
            if env_feeds:
                feed_urls = [f.strip() for f in env_feeds.split(",") if f.strip()]
            if not feed_urls:
                feed_urls = cls.DEFAULT_FEEDS

        all_articles = []
        for url in feed_urls:
            try:
                parsed = feedparser.parse(url)
                for entry in parsed.entries:
                    article_dict = cls.parse_entry(entry, feed_source=url)
                    if article_dict:
                        all_articles.append(article_dict)
            except Exception as exc:
                logger.warning(f"Failed to fetch or parse news feed {url}: {exc}")

        return cls.ingest_articles(all_articles)
