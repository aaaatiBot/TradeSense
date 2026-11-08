"""User Interface routes per SRS §10 and §15.1 (AT-43)."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.paper_trade import PaperTrade
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.services.disclaimer_service import DisclaimerService
from app.services.universe_service import UniverseService

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/login", methods=["GET"])
def login_view():
    """Login screen with mandatory disclaimer per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("login")
    return render_template("login.html", disclaimers=disclaimers)


@ui_bp.route("/register", methods=["GET"])
def register_view():
    """Register screen with mandatory disclaimer per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("login")
    return render_template("auth/register.html", disclaimers=disclaimers)


@ui_bp.route("/logout", methods=["GET", "POST"])
def logout_view():
    """Web UI logout clearing session and redirecting to login."""
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("ui.login_view"))


@ui_bp.route("/dashboard", methods=["GET"])
def dashboard_view():
    """Dashboard screen with mandatory disclaimer per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("dashboard")
    active_stocks = UniverseService.list_active_stocks()
    return render_template("dashboard.html", disclaimers=disclaimers, active_stocks=active_stocks)


@ui_bp.route("/recommendation", methods=["GET"])
def recommendation_view():
    """Recommendation screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("recommendation")
    rec_id = request.args.get("id", type=int)
    rec = None
    if rec_id:
        rec = db.session.get(Recommendation, rec_id)
    if not rec and hasattr(g, "current_user") and g.current_user:
        rec = (
            Recommendation.query.filter_by(user_id=g.current_user.id)
            .order_by(Recommendation.created_at.desc())
            .first()
        )

    items = []
    if rec:
        items = RecommendationItem.query.filter_by(recommendation_id=rec.id).all()

    return render_template(
        "recommendation.html",
        disclaimers=disclaimers,
        recommendation=rec,
        recommendations=items,
    )


@ui_bp.route("/paper-trades/result", methods=["GET"])
def paper_trade_result_view():
    """Paper trade result screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("paper_trade_result")
    trade_id = request.args.get("trade_id", type=int)
    trade = None
    if trade_id:
        trade = db.session.get(PaperTrade, trade_id)
    if not trade and hasattr(g, "current_user") and g.current_user:
        trade = (
            PaperTrade.query.filter_by(user_id=g.current_user.id)
            .order_by(PaperTrade.opened_at.desc())
            .first()
        )
    return render_template("paper_trade_result.html", disclaimers=disclaimers, trade=trade)


@ui_bp.route("/history", methods=["GET"])
def history_view():
    """History screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("history")
    trades = []
    if hasattr(g, "current_user") and g.current_user:
        trades = (
            PaperTrade.query.filter_by(user_id=g.current_user.id)
            .order_by(PaperTrade.opened_at.desc())
            .all()
        )
    return render_template("history.html", disclaimers=disclaimers, trades=trades)


@ui_bp.route("/verification", methods=["GET"])
def verification_view():
    """Verification screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("verification")
    query_hash = request.args.get("hash", "")
    return render_template("verification.html", disclaimers=disclaimers, query_hash=query_hash)
