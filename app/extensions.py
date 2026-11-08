"""Application Extensions Module.

Initializes SQLAlchemy and other framework extensions.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase
from flask_sqlalchemy import SQLAlchemy


class Base(DeclarativeBase):
    """Declarative Base class for SQLAlchemy models."""
    pass


db = SQLAlchemy(model_class=Base)
