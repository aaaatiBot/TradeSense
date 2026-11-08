"""Data retention and right-to-erasure service per SRS §7.18 (v3.1, AT-40)."""
from __future__ import annotations

import datetime
from typing import Dict, Optional

from sqlalchemy import and_, or_

from app.extensions import db
from app.models.blockchain_record import BlockchainRecord
from app.models.cost_breakdown import CostBreakdown
from app.models.idempotency import IdempotencyRecord
from app.models.job import JobQueue
from app.models.news_item import NewsItem
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.password_reset import PasswordResetToken
from app.models.price import Price
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.session import Session
from app.models.user import User
from app.utils.clock import Clock
from app.utils.logger import logger


class RetentionService:
    """Service executing scheduled data retention sweeps per SRS §7.18.1 and right-to-erasure per §7.18.3."""

    @classmethod
    def run_retention_sweep(cls, as_of: Optional[datetime.datetime] = None) -> Dict[str, int]:
        """Execute the scheduled rolling retention sweep per SRS §7.18.1 (RET-01, RET-02, RET-03).

        Deletes expired records across tables older than their retention window.
        Idempotent; returns per-table deletion counts and logs them.
        """
        now = as_of or Clock.now()
        counts: Dict[str, int] = {}

        # 1. Sessions: 8 hours
        sessions_cutoff = now - datetime.timedelta(hours=8)
        expired_sessions = Session.query.filter(Session.last_active_at < sessions_cutoff).all()
        counts["sessions"] = len(expired_sessions)
        for s in expired_sessions:
            db.session.delete(s)

        # 2. Password reset tokens: 1 hour
        tokens_cutoff = now - datetime.timedelta(hours=1)
        expired_tokens = PasswordResetToken.query.filter(PasswordResetToken.created_at < tokens_cutoff).all()
        counts["password_reset_tokens"] = len(expired_tokens)
        for t in expired_tokens:
            db.session.delete(t)

        # 3. Idempotency records: 24 hours
        idempotency_cutoff = now - datetime.timedelta(hours=24)
        expired_idemp = IdempotencyRecord.query.filter(IdempotencyRecord.created_at < idempotency_cutoff).all()
        counts["idempotency_records"] = len(expired_idemp)
        for r in expired_idemp:
            db.session.delete(r)

        # 4. Job queue: completed (30 days), failed (90 days)
        jobs_completed_cutoff = now - datetime.timedelta(days=30)
        jobs_failed_cutoff = now - datetime.timedelta(days=90)
        expired_jobs = JobQueue.query.filter(
            or_(
                and_(
                    JobQueue.status.in_(["COMPLETED", "completed"]),
                    or_(
                        JobQueue.completed_at < jobs_completed_cutoff,
                        JobQueue.created_at < jobs_completed_cutoff,
                    ),
                ),
                and_(
                    JobQueue.status.in_(["FAILED", "failed"]),
                    JobQueue.created_at < jobs_failed_cutoff,
                ),
            )
        ).all()
        counts["job_queue"] = len(expired_jobs)
        for j in expired_jobs:
            db.session.delete(j)

        # 5. News items: 90 days
        news_cutoff = now - datetime.timedelta(days=90)
        expired_news = NewsItem.query.filter(NewsItem.created_at < news_cutoff).all()
        counts["news_items"] = len(expired_news)
        for n in expired_news:
            db.session.delete(n)

        # 6. Prices: 2 years (730 days)
        prices_cutoff = now - datetime.timedelta(days=730)
        expired_prices = Price.query.filter(Price.timestamp < prices_cutoff).all()
        counts["prices"] = len(expired_prices)
        for p in expired_prices:
            db.session.delete(p)

        # 7. Recommendations (and cascaded items): 2 years (730 days)
        recs_cutoff = now - datetime.timedelta(days=730)
        expired_recs = Recommendation.query.filter(Recommendation.created_at < recs_cutoff).all()
        counts["recommendations"] = len(expired_recs)
        for rec in expired_recs:
            RecommendationItem.query.filter_by(recommendation_id=rec.id).delete()
            db.session.delete(rec)

        # 8. Paper trades (and cascaded legs): 2 years (730 days)
        trades_cutoff = now - datetime.timedelta(days=730)
        expired_trades = PaperTrade.query.filter(PaperTrade.created_at < trades_cutoff).all()
        counts["paper_trades"] = len(expired_trades)
        for tr in expired_trades:
            PaperTradeLeg.query.filter_by(paper_trade_id=tr.id).delete()
            db.session.delete(tr)

        # 9. Cost breakdowns: 2 years (730 days)
        costs_cutoff = now - datetime.timedelta(days=730)
        expired_costs = CostBreakdown.query.filter(CostBreakdown.created_at < costs_cutoff).all()
        counts["cost_breakdowns"] = len(expired_costs)
        for cb in expired_costs:
            db.session.delete(cb)

        # 10. Blockchain records: 2 years (730 days)
        blockchain_cutoff = now - datetime.timedelta(days=730)
        expired_bc = BlockchainRecord.query.filter(BlockchainRecord.created_at < blockchain_cutoff).all()
        counts["blockchain_records"] = len(expired_bc)
        for bc in expired_bc:
            db.session.delete(bc)

        db.session.commit()

        # RET-03: Log per-table deletion counts
        logger.info(
            "Retention sweep completed successfully per SRS §7.18.2 (RET-03)",
            extra={"extra_data": counts},
        )

        return counts

    @classmethod
    def anonymize_user(cls, user_id: int) -> User:
        """Execute user account erasure per SRS §7.18.3.

        Step 1: is_active = False
        Step 2: Revoke sessions
        Step 3: Personal fields anonymized, anonymized_at set
        Step 4: Recommendations and paper trades retained without personal linkage.
        """
        user = db.session.get(User, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")

        user.is_active = False

        sessions = Session.query.filter_by(user_id=user.id, is_revoked=False).all()
        for s in sessions:
            s.is_revoked = True

        user.email = f"anonymized_{user.id}@tradesense.local"
        user.password_hash = "ANONYMIZED"
        user.anonymized_at = Clock.now()

        db.session.commit()
        logger.info(
            f"User {user_id} anonymized per right-to-erasure SRS §7.18.3",
            extra={"user_id_hashed": f"user_{user_id}_anonymized"},
        )
        return user
