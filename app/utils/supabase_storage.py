"""Flask Session Storage adapter for Supabase Auth.

Stores Supabase auth tokens in Flask's signed session cookie (SyncSupportedStorage).
"""
from __future__ import annotations

import logging
from typing import Optional
from flask import session
from supabase_auth import SyncSupportedStorage

logger = logging.getLogger("tradesense.supabase_storage")


class FlaskSessionStorage(SyncSupportedStorage):
    """Adapter bridging Supabase Auth storage to Flask's session cookie dictionary."""

    def __init__(self, session_prefix: str = "sb_auth_") -> None:
        self.prefix = session_prefix

    def _format_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get_item(self, key: str) -> Optional[str]:
        """Retrieve token or auth state string from Flask session."""
        try:
            val = session.get(self._format_key(key))
            return str(val) if val is not None else None
        except RuntimeError:
            # Outside request context (e.g. background job / testing)
            return None

    def set_item(self, key: str, value: str) -> None:
        """Store token or auth state string into Flask session."""
        try:
            session[self._format_key(key)] = value
            session.modified = True
        except RuntimeError:
            pass

    def remove_item(self, key: str) -> None:
        """Remove token or auth state string from Flask session."""
        try:
            session.pop(self._format_key(key), None)
            session.modified = True
        except RuntimeError:
            pass
