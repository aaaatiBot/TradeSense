"""Administrator routes per SRS §10.1 and §5.7.3 (AUTH-07, AT-44)."""
from __future__ import annotations

import datetime
from flask import Blueprint, g
from sqlalchemy import func

from app.extensions import db
from app.models.blockchain_record import BlockchainRecord
from app.models.job import JobQueue
from app.models.model_version import ModelVersion
from app.models.recommendation_item import RecommendationItem
from app.utils.clock import Clock
from app.utils.decorators import require_role
from app.utils.metrics import metrics
from app.utils.response import api_success

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.route("/overview", methods=["GET"])
@require_role("admin")
def get_admin_overview():
    """Retrieve administrator system overview per SRS §5.7.3 and §10.1."""
    # 1. Current job queue depth by status
    queue_counts = (
        db.session.query(JobQueue.status, func.count(JobQueue.id))
        .group_by(JobQueue.status)
        .all()
    )
    job_queue_depth = {status: count for status, count in queue_counts}

    # 2. Recent blockchain anchor failures
    failures = (
        BlockchainRecord.query.filter_by(status="failed")
        .order_by(BlockchainRecord.created_at.desc())
        .limit(10)
        .all()
    )
    recent_anchor_failures = [
        {
            "id": f.id,
            "entity_type": f.entity_type,
            "entity_id": f.entity_id,
            "error": f.error_message,
        }
        for f in failures
    ]

    # 3. Recent model activation events
    active_models = (
        ModelVersion.query.filter_by(is_active=True)
        .order_by(ModelVersion.created_at.desc())
        .limit(5)
        .all()
    )
    recent_model_activations = [
        {
            "id": m.id,
            "version_tag": m.version_tag,
            "activated_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in active_models
    ]

    # 4. Current estimate_source distribution over the last 24h
    cutoff_24h = Clock.now() - datetime.timedelta(hours=24)
    dist_counts = (
        db.session.query(RecommendationItem.estimate_source, func.count(RecommendationItem.id))
        .filter(RecommendationItem.created_at >= cutoff_24h)
        .group_by(RecommendationItem.estimate_source)
        .all()
    )
    estimate_source_distribution_24h = {source: count for source, count in dist_counts}
    if not estimate_source_distribution_24h:
        estimate_source_distribution_24h = metrics.estimate_source_distribution

    return api_success(
        data={
            "admin_id": g.current_user.id,
            "status": "operational",
            "job_queue_depth": job_queue_depth,
            "recent_anchor_failures": recent_anchor_failures,
            "recent_model_activations": recent_model_activations,
            "estimate_source_distribution_24h": estimate_source_distribution_24h,
        },
        status_code=200,
    )


@admin_bp.route("/metrics", methods=["GET"])
def get_metrics():
    """Retrieve raw application metrics per SRS §5.7.1 and AT-44."""
    return api_success(data=metrics.snapshot(), status_code=200)
