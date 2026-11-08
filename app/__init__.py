"""TradeSense Application Factory per SRS §3.2 and §3.3."""
from __future__ import annotations

import os
import time
from typing import Optional, Type
import uuid

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from app.config import BaseConfig, config_by_name
from app.extensions import db, limiter
from app.routes import register_routes
from app.utils.clock import Clock
from app.utils.logger import logger, setup_logging
from app.utils.response import api_error


def create_app(config_name: Optional[str] = None) -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__)

    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development").lower()

    config_class: Type[BaseConfig] = config_by_name.get(config_name, config_by_name["development"])
    app.config.from_object(config_class)

    # Validate configuration rules (raises ValueError on insecure/missing required settings)
    config_class.validate()

    # Configure structured JSON logging per SRS §5.7.2
    setup_logging(app.config.get("LOG_LEVEL", "INFO"))

    # Initialize extensions
    db.init_app(app)
    limiter.init_app(app)

    # Request Lifecycle Hooks
    @app.before_request
    def before_request_hook():
        # Inject UUIDv4 request ID into context
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        g.request_id = request_id
        g.start_time = time.perf_counter()

    @app.after_request
    def after_request_hook(response):
        # Attach request_id to response header
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id

        # Calculate duration
        start_time = getattr(g, "start_time", None)
        duration_ms = None
        if start_time is not None:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # Log request completion with duration (LOG-M1)
        if request.path != "/api/v1/health":  # keep health endpoint logs less noisy unless debug
            logger.info(
                f"{request.method} {request.path} {response.status_code}",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.path,
                        "status_code": response.status_code,
                    },
                    "duration_ms": duration_ms,
                },
            )

        return response

    # Global Error Handlers returning standard §6.1 envelopes
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = exc.name.upper().replace(" ", "_")
        return api_error(code=code, message=exc.description, status_code=exc.code or 500)

    @app.errorhandler(Exception)
    def handle_generic_exception(exc: Exception):
        logger.exception(f"Unhandled server error: {exc}")
        return api_error(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred",
            status_code=500,
        )

    # Register all blueprints
    register_routes(app)

    return app
