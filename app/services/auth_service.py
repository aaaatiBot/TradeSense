"""Authentication and session management service per SRS §4.1 (FR-AUTH) and §7.18.3."""
from __future__ import annotations

import datetime
import hashlib
import re
import secrets
from typing import Optional, Tuple

import argon2
from argon2.exceptions import VerifyMismatchError
from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.password_reset import PasswordResetToken
from app.models.session import Session
from app.models.user import User
from app.utils.clock import Clock

EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-\.]+$")


class AuthenticationError(Exception):
    """Exception raised for authentication or credential validation failures."""
    def __init__(self, code: str, message: str, status_code: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AuthService:
    """Core domain service for user authentication, password security, and session management."""

    @classmethod
    def get_password_hasher(cls) -> argon2.PasswordHasher:
        """Instantiate an Argon2id hasher using application configuration (AUTH-02)."""
        time_cost = current_app.config.get("ARGON2_TIME_COST", 3)
        memory_cost = current_app.config.get("ARGON2_MEMORY_COST", 65536)
        parallelism = current_app.config.get("ARGON2_PARALLELISM", 4)
        return argon2.PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            type=argon2.Type.ID,
        )

    @classmethod
    def validate_email(cls, email: str) -> None:
        """Validate email format."""
        if not email or not EMAIL_REGEX.match(email.strip()):
            raise AuthenticationError("INVALID_EMAIL", "Invalid email address format", status_code=400)

    @classmethod
    def validate_password_strength(cls, password: str) -> None:
        """Validate password meets minimum security requirements (min 8 chars, upper, lower, digit, symbol)."""
        if not password or len(password) < 8:
            raise AuthenticationError(
                "WEAK_PASSWORD", "Password must be at least 8 characters long", status_code=400
            )
        if not re.search(r"[A-Z]", password):
            raise AuthenticationError(
                "WEAK_PASSWORD", "Password must contain at least one uppercase letter", status_code=400
            )
        if not re.search(r"[a-z]", password):
            raise AuthenticationError(
                "WEAK_PASSWORD", "Password must contain at least one lowercase letter", status_code=400
            )
        if not re.search(r"\d", password):
            raise AuthenticationError(
                "WEAK_PASSWORD", "Password must contain at least one digit", status_code=400
            )
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_]", password):
            raise AuthenticationError(
                "WEAK_PASSWORD", "Password must contain at least one special character", status_code=400
            )

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a plaintext password using Argon2id."""
        hasher = cls.get_password_hasher()
        return hasher.hash(password)

    @classmethod
    def verify_password(cls, password_hash: str, password: str) -> bool:
        """Verify password against Argon2id hash with constant-time comparison."""
        hasher = cls.get_password_hasher()
        try:
            return hasher.verify(password_hash, password)
        except (VerifyMismatchError, Exception):
            return False

    @classmethod
    def register_user(cls, email: str, password: str, role: str = "user") -> User:
        """Register a new user account (AUTH-01, AUTH-02)."""
        email_clean = email.strip().lower()
        cls.validate_email(email_clean)
        cls.validate_password_strength(password)

        # Check existing user
        existing_user = db.session.execute(
            select(User).where(User.email == email_clean)
        ).scalar_one_or_none()

        if existing_user is not None:
            raise AuthenticationError("EMAIL_EXISTS", "An account with this email already exists", status_code=409)

        password_hash = cls.hash_password(password)
        user = User(
            email=email_clean,
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        return user

    @classmethod
    def login_user(
        cls,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Tuple[User, str, datetime.datetime]:
        """Authenticate user credentials and create a new session (AUTH-03, AUTH-04, AUTH-05)."""
        email_clean = email.strip().lower()
        user = db.session.execute(
            select(User).where(User.email == email_clean)
        ).scalar_one_or_none()

        if user is None or not user.password_hash:
            raise AuthenticationError("INVALID_CREDENTIALS", "Invalid email or password", status_code=401)

        if not user.is_active:
            raise AuthenticationError("ACCOUNT_INACTIVE", "Account has been deactivated or deleted", status_code=403)

        if not cls.verify_password(user.password_hash, password):
            raise AuthenticationError("INVALID_CREDENTIALS", "Invalid email or password", status_code=401)

        # Generate cryptographically secure token
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        # Session lifetime per SRS §7.18.1 and config (default 8 hours)
        lifetime_hours = current_app.config.get("SESSION_LIFETIME_HOURS", 8)
        now = Clock.utcnow()
        expires_at = now + datetime.timedelta(hours=lifetime_hours)

        ua_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:16] if user_agent else None

        session = Session(
            user_id=user.id,
            session_token_hash=token_hash,
            user_agent_hash=ua_hash,
            ip_address=ip_address,
            expires_at=expires_at,
            last_active_at=now,
            created_at=now,
        )
        db.session.add(session)
        db.session.commit()

        return user, raw_token, expires_at

    @classmethod
    def verify_session_token(cls, raw_token: str) -> Tuple[User, Session]:
        """Verify an authentication session token and update last active timestamp."""
        if not raw_token:
            raise AuthenticationError("UNAUTHENTICATED", "Missing authorization token", status_code=401)

        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        session = db.session.execute(
            select(Session).where(Session.session_token_hash == token_hash)
        ).scalar_one_or_none()

        if session is None:
            raise AuthenticationError("INVALID_SESSION", "Invalid session token", status_code=401)

        now = Clock.utcnow()
        expires_at = Clock.ensure_utc(session.expires_at)
        if now > expires_at:
            db.session.delete(session)
            db.session.commit()
            raise AuthenticationError("SESSION_EXPIRED", "Session has expired", status_code=401)

        user = session.user
        if user is None or not user.is_active:
            raise AuthenticationError("ACCOUNT_INACTIVE", "Account is deactivated", status_code=403)

        # Sliding activity update
        session.last_active_at = now
        db.session.commit()

        return user, session

    @classmethod
    def logout_session(cls, raw_token: str) -> bool:
        """Revoke active session token on user logout (AUTH-06)."""
        if not raw_token:
            return False

        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        session = db.session.execute(
            select(Session).where(Session.session_token_hash == token_hash)
        ).scalar_one_or_none()

        if session is not None:
            db.session.delete(session)
            db.session.commit()
            return True
        return False

    @classmethod
    def request_password_reset(cls, email: str) -> Optional[str]:
        """Generate a single-use password reset token with 1-hour expiry (AUTH-09)."""
        email_clean = email.strip().lower()
        user = db.session.execute(
            select(User).where(User.email == email_clean)
        ).scalar_one_or_none()

        if user is None or not user.is_active:
            return None

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        lifetime_hours = current_app.config.get("PASSWORD_RESET_TOKEN_LIFETIME_HOURS", 1)
        now = Clock.utcnow()
        expires_at = now + datetime.timedelta(hours=lifetime_hours)

        reset_record = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
        )
        db.session.add(reset_record)
        db.session.commit()

        return raw_token

    @classmethod
    def confirm_password_reset(cls, raw_token: str, new_password: str) -> bool:
        """Validate single-use reset token and update user password."""
        cls.validate_password_strength(new_password)
        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

        reset_record = db.session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
            )
        ).scalar_one_or_none()

        if reset_record is None:
            raise AuthenticationError("INVALID_RESET_TOKEN", "Invalid or already used password reset token", status_code=400)

        now = Clock.utcnow()
        expires_at = Clock.ensure_utc(reset_record.expires_at)
        if now > expires_at:
            raise AuthenticationError("RESET_TOKEN_EXPIRED", "Password reset token has expired", status_code=400)

        user = reset_record.user
        if user is None or not user.is_active:
            raise AuthenticationError("ACCOUNT_INACTIVE", "Associated user account is inactive", status_code=403)

        # Update password hash
        user.password_hash = cls.hash_password(new_password)
        reset_record.used_at = now

        # Invalidate all active sessions for security
        for s in list(user.sessions):
            db.session.delete(s)

        db.session.commit()
        return True

    @classmethod
    def anonymize_user(cls, user_id: int) -> bool:
        """Right to erasure per SRS §7.18.3 (AUTH-12). Soft-deletes user and wipes PII."""
        user = db.session.get(User, user_id)
        if user is None:
            raise AuthenticationError("USER_NOT_FOUND", "User not found", status_code=404)

        now = Clock.utcnow()
        user.is_active = False
        user.anonymized_at = now
        user.email = None
        user.password_hash = None

        # Revoke all active sessions
        for s in list(user.sessions):
            db.session.delete(s)

        # Invalidate any unused password reset tokens
        for t in list(user.password_resets):
            db.session.delete(t)

        db.session.commit()
        return True
