"""Authentication routes per SRS §4.1 (FR-AUTH) and §7.18.3."""
from __future__ import annotations

from flask import Blueprint, current_app, g, redirect, request, session, url_for

from app.extensions import get_supabase, limiter
from app.models.user import User
from app.services.auth_service import AuthService, AuthenticationError
from app.utils.clock import Clock
from app.utils.decorators import require_auth
from app.utils.response import api_error, api_success

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("20 per minute")
def register():
    """Register a new user account (AUTH-01, AUTH-02) with Supabase Auth synchronization."""
    payload = request.get_json() or {}
    email = payload.get("email")
    password = payload.get("password")
    role = payload.get("role", "user")

    if not email or not password:
        return api_error(code="MISSING_CREDENTIALS", message="Email and password are required", status_code=400)

    try:
        # Sync with Supabase Auth if client is configured
        supabase = get_supabase()
        supabase_uid = None
        if supabase:
            try:
                sb_res = supabase.auth.sign_up({"email": email, "password": password})
                if sb_res and sb_res.user:
                    supabase_uid = sb_res.user.id
            except Exception as sb_err:
                current_app.logger.warning(f"Supabase sign_up warning: {sb_err}")

        # Local user persistence
        user = AuthService.register_user(email=email, password=password, role=role)
        session["user_id"] = user.id
        session["user_email"] = user.email

        return api_success(
            data={"user_id": user.id, "email": user.email, "role": user.role, "supabase_uid": supabase_uid},
            status_code=201,
        )
    except AuthenticationError as exc:
        return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
    except Exception as exc:
        return api_error(code="REGISTRATION_FAILED", message=str(exc), status_code=500)


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    """Authenticate credentials via Supabase / AuthService and set session (AUTH-03, AUTH-04, AUTH-05)."""
    payload = request.get_json() or {}
    email = payload.get("email")
    password = payload.get("password")

    if not email or not password:
        return api_error(code="MISSING_CREDENTIALS", message="Email and password are required", status_code=400)

    user_agent = request.headers.get("User-Agent")
    ip_address = request.remote_addr

    try:
        supabase = get_supabase()
        sb_token = None
        if supabase:
            try:
                sb_auth = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if sb_auth and sb_auth.session:
                    sb_token = sb_auth.session.access_token
                    session["sb_access_token"] = sb_token
            except Exception as sb_err:
                current_app.logger.warning(f"Supabase sign_in warning: {sb_err}")

        user, raw_token, expires_at = AuthService.login_user(
            email=email, password=password, user_agent=user_agent, ip_address=ip_address
        )
        session["user_id"] = user.id
        session["user_email"] = user.email
        session["session_token"] = raw_token

        return api_success(
            data={
                "token": raw_token,
                "supabase_token": sb_token,
                "expires_at": expires_at.isoformat(),
                "user": {"id": user.id, "email": user.email, "role": user.role},
            },
            status_code=200,
        )
    except AuthenticationError as exc:
        return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
    except Exception as exc:
        return api_error(code="LOGIN_FAILED", message=str(exc), status_code=500)


@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """Revoke active session in AuthService and Supabase (AUTH-06)."""
    token = getattr(g, "raw_token", None)
    if token:
        AuthService.logout_session(token)

    supabase = get_supabase()
    if supabase:
        try:
            supabase.auth.sign_out()
        except Exception:
            pass

    session.clear()
    return api_success(data={"message": "Successfully logged out"}, status_code=200)



@auth_bp.route("/me", methods=["GET"])
@require_auth
def get_current_user():
    """Retrieve authenticated user profile and roles."""
    user = g.current_user
    created_at = Clock.ensure_utc(user.created_at)
    return api_success(
        data={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "created_at": created_at.isoformat() if created_at else None,
        },
        status_code=200,
    )


@auth_bp.route("/password-reset/request", methods=["POST"])
@limiter.limit("5 per minute")
def request_password_reset():
    """Issue a single-use password reset token (AUTH-09)."""
    payload = request.get_json() or {}
    email = payload.get("email")
    if not email:
        return api_error(code="MISSING_EMAIL", message="Email is required", status_code=400)

    reset_token = AuthService.request_password_reset(email)

    data = {"message": "If the account exists, a reset token has been dispatched"}
    # In testing/dev mode, expose token for validation convenience
    if current_app.config.get("TESTING") or current_app.config.get("DEBUG"):
        data["reset_token"] = reset_token

    return api_success(data=data, status_code=200)


@auth_bp.route("/password-reset/confirm", methods=["POST"])
@limiter.limit("10 per minute")
def confirm_password_reset():
    """Verify reset token and update user password."""
    payload = request.get_json() or {}
    token = payload.get("token")
    new_password = payload.get("new_password")

    if not token or not new_password:
        return api_error(code="MISSING_PARAMETERS", message="Token and new_password are required", status_code=400)

    try:
        AuthService.confirm_password_reset(token, new_password)
        return api_success(data={"message": "Password has been successfully reset"}, status_code=200)
    except AuthenticationError as exc:
        return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
    except Exception as exc:
        return api_error(code="RESET_FAILED", message=str(exc), status_code=500)


@auth_bp.route("/me", methods=["DELETE"])
@require_auth
def delete_account():
    """Execute account deletion and anonymization per right to erasure (§7.18.3, AUTH-12)."""
    user_id = g.current_user.id
    try:
        AuthService.anonymize_user(user_id)
        return api_success(
            data={"message": "Account has been permanently deactivated and personal data anonymized"},
            status_code=200,
        )
    except AuthenticationError as exc:
        return api_error(code=exc.code, message=exc.message, status_code=exc.status_code)
    except Exception as exc:
        return api_error(code="DELETION_FAILED", message=str(exc), status_code=500)
