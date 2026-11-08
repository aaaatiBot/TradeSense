"""Route blueprint registrations."""
from flask import Flask

from app.routes.health import health_bp
from app.routes.auth import auth_bp
from app.routes.dashboard import dashboard_bp
from app.routes.recommendations import recommendations_bp
from app.routes.paper_trades import paper_trades_bp
from app.routes.history import history_bp
from app.routes.verification import verification_bp
from app.routes.admin import admin_bp
from app.routes.ui import ui_bp


def register_routes(app: Flask) -> None:
    """Register all application route blueprints."""
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(paper_trades_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(verification_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(ui_bp)

