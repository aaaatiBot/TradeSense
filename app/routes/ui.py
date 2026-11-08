"""User Interface routes per SRS §10 and §15.1 (AT-43)."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from app.services.disclaimer_service import DisclaimerService

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


@ui_bp.route("/dashboard", methods=["GET"])
def dashboard_view():
    """Dashboard screen with mandatory disclaimer per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("dashboard")
    return render_template("dashboard.html", disclaimers=disclaimers)


@ui_bp.route("/recommendation", methods=["GET"])
def recommendation_view():
    """Recommendation screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("recommendation")
    return render_template("recommendation.html", disclaimers=disclaimers, recommendations=[])


@ui_bp.route("/paper-trades/result", methods=["GET"])
def paper_trade_result_view():
    """Paper trade result screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("paper_trade_result")
    return render_template("paper_trade_result.html", disclaimers=disclaimers, trade=None)


@ui_bp.route("/history", methods=["GET"])
def history_view():
    """History screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("history")
    return render_template("history.html", disclaimers=disclaimers, trades=[])


@ui_bp.route("/verification", methods=["GET"])
def verification_view():
    """Verification screen with mandatory disclaimers per SRS §15.1."""
    disclaimers = DisclaimerService.get_disclaimers("verification")
    query_hash = request.args.get("hash", "")
    return render_template("verification.html", disclaimers=disclaimers, query_hash=query_hash)
