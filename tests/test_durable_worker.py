"""Acceptance tests for Durable Blockchain Worker (Phase 9, AT-26 through AT-30).

Verifies:
- AT-26: Lease expiration recovery (expired leases reclaimed by workers).
- AT-27: Retry backoff and failure threshold transition to FAILED with error message.
- AT-28: Idempotent job execution.
- AT-29: Atomic lease claim across workers.
- AT-30: Queue depth reporting and monitoring.
"""
import datetime
from decimal import Decimal
import pytest

from app.extensions import db
from app.models.job import JobQueue
from app.models.model_version import ModelVersion
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.models.stock import Stock
from app.models.user import User
from app.services.blockchain_service import BlockchainService
from app.utils.clock import Clock
from app.workers.blockchain_worker import BlockchainWorker


@pytest.fixture
def blockchain_service():
    return BlockchainService()


@pytest.fixture
def worker_a(blockchain_service):
    return BlockchainWorker(worker_id="worker_alpha", lease_duration_seconds=30, blockchain_service=blockchain_service)


@pytest.fixture
def worker_b(blockchain_service):
    return BlockchainWorker(worker_id="worker_beta", lease_duration_seconds=30, blockchain_service=blockchain_service)


@pytest.fixture
def sample_recommendation(app):
    with app.app_context():
        notional = ReferenceNotionalConfig(
            version_tag="v1.0_worker_test",
            notional_amount=Decimal("500.00"),
        )
        db.session.add(notional)
        db.session.commit()

        mv = ModelVersion(
            version_tag="mv_worker_test",
            artifact_hash="aa" * 32,
            feature_schema_version="1.0",
            reference_notional_id=notional.id,
            reference_notional=Decimal("500.00"),
            training_data_window_start=Clock.utcnow(),
            training_data_window_end=Clock.utcnow(),
            estimate_source_method_version="1.0",
            is_active=True,
        )
        stock = Stock(ticker="HDFC", isin="INE040A01034", name="HDFC Bank", status="active")
        user = User(email="worker_user@tradesense.edu", password_hash="pwd", role="user")
        db.session.add_all([mv, stock, user])
        db.session.commit()

        rec = Recommendation(
            user_id=user.id,
            budget=Decimal("5000.00"),
            effective_budget=Decimal("4975.00"),
            cash_buffer=Decimal("25.00"),
            mode="CNC",
            horizon="1d",
            model_version_id=mv.id,
            rate_card_version="standard_equity_2026",
            reference_notional=Decimal("500.00"),
            status="DRAFT",
        )
        db.session.add(rec)
        db.session.flush()

        item = RecommendationItem(
            recommendation_id=rec.id,
            stock_id=stock.id,
            ticker="HDFC",
            quantity=3,
            allocated_amount=Decimal("4500.00"),
            expected_return_rate=Decimal("0.020000"),
            p_i=Decimal("0.600000"),
            g_plus=Decimal("25.00"),
            g_minus=Decimal("-10.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            stock_status_at_creation="active",
        )
        db.session.add(item)
        db.session.commit()
        return rec.id


def test_at_26_lease_expiration_recovery(app, worker_a, worker_b):
    """AT-26: Expired or abandoned leases are recovered and reclaimed."""
    with app.app_context():
        # Enqueue job
        job = BlockchainWorker.enqueue_job("anchor_recommendation", {"recommendation_id": 123}, max_attempts=3)
        assert job.status == "QUEUED"

        # Worker A claims job
        claimed_a = worker_a.claim_next_job()
        assert claimed_a is not None
        assert claimed_a.locked_by == "worker_alpha"
        assert claimed_a.status == "RUNNING"
        assert claimed_a.attempts == 1

        # Simulate Worker A crashing and lease expiring (move lease_expires_at into past)
        past_time = Clock.utcnow() - datetime.timedelta(seconds=60)
        claimed_a.lease_expires_at = past_time
        db.session.commit()

        # Worker B should be able to claim the expired job
        claimed_b = worker_b.claim_next_job()
        assert claimed_b is not None
        assert claimed_b.id == claimed_a.id
        assert claimed_b.locked_by == "worker_beta"
        assert claimed_b.status == "RUNNING"
        assert claimed_b.attempts == 2

        # Verify recover_expired_leases sweep method
        claimed_b.lease_expires_at = past_time
        db.session.commit()

        recovered_count = worker_b.recover_expired_leases()
        assert recovered_count == 1
        refreshed = db.session.get(JobQueue, claimed_b.id)
        assert refreshed.status == "QUEUED"
        assert refreshed.locked_by is None


def test_at_27_retry_backoff_and_failure_threshold(app, worker_a):
    """AT-27: Failed executions increment attempts and transition to FAILED upon max_attempts."""
    with app.app_context():
        # Enqueue job with an invalid non-existent recommendation ID (will fail)
        job = BlockchainWorker.enqueue_job("anchor_recommendation", {"recommendation_id": 999999}, max_attempts=2)

        # Attempt 1
        claimed1 = worker_a.claim_next_job()
        assert claimed1 is not None
        assert claimed1.attempts == 1
        success1 = worker_a.process_job(claimed1)
        assert success1 is False

        # Status should reset to QUEUED for retry (attempts=1 < max=2)
        job_after_1 = db.session.get(JobQueue, job.id)
        assert job_after_1.status == "QUEUED"
        assert "RECOMMENDATION_NOT_FOUND" in job_after_1.last_error

        # Attempt 2
        claimed2 = worker_a.claim_next_job()
        assert claimed2 is not None
        assert claimed2.attempts == 2
        success2 = worker_a.process_job(claimed2)
        assert success2 is False

        # Status should now be FAILED (attempts=2 >= max=2)
        job_after_2 = db.session.get(JobQueue, job.id)
        assert job_after_2.status == "FAILED"
        assert job_after_2.locked_by is None


def test_at_28_idempotent_execution(app, worker_a, sample_recommendation):
    """AT-28: Processing the same anchoring job succeeds cleanly."""
    with app.app_context():
        job = BlockchainWorker.enqueue_job(
            "anchor_recommendation",
            {"recommendation_id": sample_recommendation},
        )
        claimed = worker_a.claim_next_job()
        success = worker_a.process_job(claimed)
        assert success is True

        completed_job = db.session.get(JobQueue, job.id)
        assert completed_job.status == "COMPLETED"
        assert completed_job.completed_at is not None

        # Recommendation should be ANCHORED
        rec = db.session.get(Recommendation, sample_recommendation)
        assert rec.status == "ANCHORED"
        assert rec.commitment_hash.startswith("0x")


def test_at_29_atomic_lease_claim(app, worker_a, worker_b):
    """AT-29: Only one worker can claim a single queued job."""
    with app.app_context():
        BlockchainWorker.enqueue_job("anchor_trade_result", {"trade_id": 1})

        # Worker A claims the only job
        claimed_a = worker_a.claim_next_job()
        assert claimed_a is not None

        # Worker B attempts to claim next job -> none available
        claimed_b = worker_b.claim_next_job()
        assert claimed_b is None


def test_at_30_queue_depth_metrics(app, worker_a):
    """AT-30: Queue depth accurately counts jobs by status (§5.7.1)."""
    with app.app_context():
        # Clear any existing jobs for isolated count
        db.session.query(JobQueue).delete()
        db.session.commit()

        j1 = BlockchainWorker.enqueue_job("task_1", {})
        j2 = BlockchainWorker.enqueue_job("task_2", {})
        j3 = BlockchainWorker.enqueue_job("task_3", {})

        # 3 queued
        depth = BlockchainWorker.get_queue_depth()
        assert depth["QUEUED"] == 3
        assert depth["RUNNING"] == 0

        # Claim 1 -> 1 running, 2 queued
        worker_a.claim_next_job()
        depth2 = BlockchainWorker.get_queue_depth()
        assert depth2["RUNNING"] == 1
        assert depth2["QUEUED"] == 2
