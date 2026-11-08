"""Authentication and Authorization Decorators per SRS §4.1 (FR-AUTH)."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import g, redirect, request, session, url_for

from app.extensions import get_supabase
from app.models.user import User
from app.services.auth_service import AuthService, AuthenticationError
from app.utils.response import api_error


def get_token_from_header() -> Optional[str]:
    """Extract Bearer token from HTTP Authorization header or cookie/session."""
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

    # Check session token in session if present
    sess_token = session.get("session_token")
    if sess_token:
        return sess_token

    # Check Supabase access_token in session if present
    sb_token = session.get("sb_access_token")
    if sb_token:
        return sb_token

    return None


def login_required(f: Callable) -> Callable:
    """Decorator checking supabase.auth.get_session() or active session for web views."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        supabase = get_supabase()
        user_email = None

        if supabase:
            try:
                sb_session = supabase.auth.get_session()
                if sb_session and sb_session.user:
                    user_email = sb_session.user.email
            except Exception:
                pass

        # Check local session fallback
        if not user_email:
            user_email = session.get("user_email")

        if not user_email:
            if request.path.startswith("/api/"):
                return api_error(code="UNAUTHENTICATED", message="Authentication required", status_code=401)
            return redirect(url_for("ui.login_view", next=request.path))

        user = User.query.filter_by(email=user_email).first()
        g.current_user = user
        g.user = user
        return f(*args, **kwargs)

    return decorated_function


def require_auth(f: Callable) -> Callable:
    """Decorator requiring a valid active user session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_header()
        if not token:
            return api_error(
                code="UNAUTHENTICATED",
                message="Authorization header with Bearer token is required",
                status_code=401,
            )

        try:
            user, session_record = AuthService.verify_session_token(token)
            g.current_user = user
            g.user = user
            g.current_session = session_record
            g.user_id = user.id
            g.raw_token = token
        except AuthenticationError as exc:
            return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
        except Exception as exc:
            return api_error(code="AUTH_FAILED", message=str(exc), status_code=401)

        return f(*args, **kwargs)

    return decorated_function


def require_role(required_role: str) -> Callable:
    """Decorator enforcing Role-Based Access Control (e.g. admin)."""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        @require_auth
        def decorated_function(*args, **kwargs):
            current_user: Optional[User] = getattr(g, "current_user", None)
            if current_user is None or current_user.role != required_role:
                return api_error(
                    code="FORBIDDEN",
                    message=f"Access requires '{required_role}' privileges",
                    status_code=403,
                )
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def verify_user_ownership(resource_user_id: Optional[int], current_user: User) -> bool:
    """Verify resource ownership to prevent Insecure Direct Object References (IDOR, AUTH-08).

    Administrators have global visibility; regular users can only access their own resources.
    """
    if current_user.role == "admin":
        return True
    return resource_user_id == current_user.id
