"""Application Extensions Module.

Initializes SQLAlchemy, Flask-Limiter, and other framework extensions.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from typing import Optional
from supabase import create_client, Client, ClientOptions
from app.utils.supabase_storage import FlaskSessionStorage


class Base(DeclarativeBase):
    """Declarative Base class for SQLAlchemy models."""
    pass


db = SQLAlchemy(model_class=Base)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)


def get_supabase(use_session_storage: bool = True) -> Optional[Client]:
    """Client factory for Supabase using PKCE flow and FlaskSessionStorage."""
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_ANON_KEY", "")

    if not supabase_url or not supabase_key:
        return None

    if use_session_storage:
        opts = ClientOptions(
            flow_type="pkce",
            storage=FlaskSessionStorage(),
            auto_refresh_token=True,
            persist_session=True,
        )
    else:
        opts = ClientOptions(
            flow_type="pkce",
            auto_refresh_token=False,
            persist_session=False,
        )

    return create_client(supabase_url, supabase_key, options=opts)

