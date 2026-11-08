"""Application Extensions Module.

Initializes SQLAlchemy, Flask-Limiter, and other framework extensions.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


class Base(DeclarativeBase):
    """Declarative Base class for SQLAlchemy models."""
    pass


db = SQLAlchemy(model_class=Base)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)
