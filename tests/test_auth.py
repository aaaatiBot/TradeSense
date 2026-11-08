"""Acceptance Tests for Authentication and Authorization per SRS §12 (AT-02, AT-03, AT-04)."""
import datetime
import hashlib
import uuid
import pytest
from flask import g
from flask.testing import FlaskClient

from app.extensions import db
from app.models.session import Session
from app.models.user import User
from app.services.auth_service import AuthService, AuthenticationError
from app.utils.clock import Clock
from app.utils.decorators import verify_user_ownership


# ==============================================================================
# AT-02: Registration, Password Hashing, Login, and Session Revocation
# ==============================================================================
def test_at_02_registration_validation_and_argon2id(client: FlaskClient):
    """AT-02: Verify registration, password strength validation, and Argon2id hashing."""
    # 1. Reject invalid email
    res = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "Password123!"})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "INVALID_EMAIL"

    # 2. Reject weak passwords
    weak_passwords = [
        "short1!",        # < 8 chars
        "alllowercase1!", # No uppercase
        "ALLUPPERCASE1!", # No lowercase
        "NoDigitsHere!",  # No digit
        "NoSpecialChar1", # No symbol
    ]
    for weak in weak_passwords:
        res = client.post("/api/v1/auth/register", json={"email": "test@example.com", "password": weak})
        assert res.status_code == 400
        assert res.get_json()["error"]["code"] == "WEAK_PASSWORD"

    # 3. Successful registration with strong password
    valid_email = "valid_user@example.com"
    valid_password = "SecurePassword123!"
    res = client.post("/api/v1/auth/register", json={"email": valid_email, "password": valid_password})
    assert res.status_code == 201

    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["data"]["email"] == valid_email
    assert payload["data"]["role"] == "user"

    # Verify user exists in database with Argon2id hash
    user = db.session.query(User).filter_by(email=valid_email).first()
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert user.is_active is True

    # 4. Reject duplicate email registration
    res_dup = client.post("/api/v1/auth/register", json={"email": valid_email, "password": valid_password})
    assert res_dup.status_code == 409
    assert res_dup.get_json()["error"]["code"] == "EMAIL_EXISTS"


def test_at_02_login_and_logout_revocation(client: FlaskClient):
    """AT-02: Verify login returns secure token, stores SHA-256 hash, and logout revokes token."""
    email = "trader_auth@example.com"
    password = "CorrectPassword123!"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})

    # 1. Invalid login password
    res_bad = client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword999!"})
    assert res_bad.status_code == 401
    assert res_bad.get_json()["error"]["code"] == "INVALID_CREDENTIALS"

    # 2. Valid login
    res_login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res_login.status_code == 200
    login_data = res_login.get_json()["data"]

    token = login_data["token"]
    assert len(token) > 20
    assert "expires_at" in login_data
    assert login_data["user"]["email"] == email

    # Verify session is stored as SHA-256 hash, never raw token
    expected_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session_db = db.session.query(Session).filter_by(session_token_hash=expected_hash).first()
    assert session_db is not None
    assert session_db.user_id == login_data["user"]["id"]

    # 3. Access authenticated endpoint
    auth_header = {"Authorization": f"Bearer {token}"}
    res_me = client.get("/api/v1/auth/me", headers=auth_header)
    assert res_me.status_code == 200
    assert res_me.get_json()["data"]["email"] == email

    # 4. Logout revokes token
    res_logout = client.post("/api/v1/auth/logout", headers=auth_header)
    assert res_logout.status_code == 200

    # 5. Subsequent access is rejected
    res_post_logout = client.get("/api/v1/auth/me", headers=auth_header)
    assert res_post_logout.status_code == 401
    assert res_post_logout.get_json()["error"]["code"] == "INVALID_SESSION"


# ==============================================================================
# AT-03: Session Expiration and Rejection of Invalid/Tampered Tokens
# ==============================================================================
def test_at_03_session_expiration(client: FlaskClient):
    """AT-03: Verify expired session tokens are rejected with SESSION_EXPIRED."""
    email = "expiry_test@example.com"
    password = "SecurePassword123!"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})

    res_login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = res_login.get_json()["data"]["token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Session works initially
    res_me1 = client.get("/api/v1/auth/me", headers=auth_header)
    assert res_me1.status_code == 200

    # Fast-forward clock by 9 hours (session lifetime is 8 hours)
    future_time = Clock.utcnow() + datetime.timedelta(hours=9)
    Clock.set_fixed(future_time)

    res_me2 = client.get("/api/v1/auth/me", headers=auth_header)
    assert res_me2.status_code == 401
    assert res_me2.get_json()["error"]["code"] == "SESSION_EXPIRED"


def test_at_03_tampered_and_missing_token_rejection(client: FlaskClient):
    """AT-03: Verify tampered or missing tokens are rejected."""
    # Missing header
    res_none = client.get("/api/v1/auth/me")
    assert res_none.status_code == 401
    assert res_none.get_json()["error"]["code"] == "UNAUTHENTICATED"

    # Malformed / forged token
    res_bad = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged-fake-token-12345"})
    assert res_bad.status_code == 401
    assert res_bad.get_json()["error"]["code"] == "INVALID_SESSION"


# ==============================================================================
# AT-04: Role-Based Access Control and Resource Ownership Isolation
# ==============================================================================
def test_at_04_role_based_access_control(client: FlaskClient):
    """AT-04: Verify admin privileges are required for admin routes."""
    # 1. Create regular user
    user_email = "regular_trader@example.com"
    user_pass = "TraderPass123!"
    client.post("/api/v1/auth/register", json={"email": user_email, "password": user_pass, "role": "user"})
    res_u = client.post("/api/v1/auth/login", json={"email": user_email, "password": user_pass})
    user_token = res_u.get_json()["data"]["token"]

    # 2. Regular user cannot access admin route -> 403 Forbidden
    res_forbidden = client.get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {user_token}"})
    assert res_forbidden.status_code == 403
    assert res_forbidden.get_json()["error"]["code"] == "FORBIDDEN"

    # 3. Create admin user
    admin_email = "admin_super@example.com"
    admin_pass = "AdminPass123!"
    client.post("/api/v1/auth/register", json={"email": admin_email, "password": admin_pass, "role": "admin"})
    res_a = client.post("/api/v1/auth/login", json={"email": admin_email, "password": admin_pass})
    admin_token = res_a.get_json()["data"]["token"]

    # 4. Admin accesses admin route -> 200 OK
    res_admin = client.get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert res_admin.get_json()["data"]["status"] == "operational"


def test_at_04_resource_ownership_isolation(app):
    """AT-04: Verify resource ownership validation blocks IDOR."""
    user1 = User(id=101, email="user1@example.com", role="user")
    user2 = User(id=102, email="user2@example.com", role="user")
    admin = User(id=999, email="admin@example.com", role="admin")

    # Regular user can only access their own resources
    assert verify_user_ownership(resource_user_id=101, current_user=user1) is True
    assert verify_user_ownership(resource_user_id=102, current_user=user1) is False

    # Admin has cross-user administrative access
    assert verify_user_ownership(resource_user_id=101, current_user=admin) is True
    assert verify_user_ownership(resource_user_id=102, current_user=admin) is True


# ==============================================================================
# Additional Security Flows: Password Reset, Edge Cases, and Account Erasure
# ==============================================================================
def test_password_reset_flow(client: FlaskClient):
    """Verify single-use password reset tokens and session invalidation."""
    email = "reset_user@example.com"
    old_pass = "OldPassword123!"
    new_pass = "NewPassword456@"
    client.post("/api/v1/auth/register", json={"email": email, "password": old_pass})

    # Log in and establish session
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": old_pass})
    old_token = login_res.get_json()["data"]["token"]

    # Request reset token
    req_res = client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert req_res.status_code == 200
    reset_token = req_res.get_json()["data"]["reset_token"]
    assert reset_token is not None

    # Confirm reset with new password
    confirm_res = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": new_pass},
    )
    assert confirm_res.status_code == 200

    # Old password no longer works
    assert client.post("/api/v1/auth/login", json={"email": email, "password": old_pass}).status_code == 401

    # Old session is revoked
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401

    # New password works
    login_new = client.post("/api/v1/auth/login", json={"email": email, "password": new_pass})
    assert login_new.status_code == 200


def test_account_deletion_and_anonymization(client: FlaskClient):
    """Verify right to erasure (§7.18.3, AUTH-12) anonymizes PII and deactivates login."""
    email = "to_delete@example.com"
    password = "DeletePassword123!"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login_res.get_json()["data"]["token"]

    # Delete account
    del_res = client.delete("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 200

    # Session is revoked
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    # Login fails with deactivated status
    login_attempt = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_attempt.status_code in [401, 403]


def test_auth_service_edge_cases(app):
    """Verify error handling on boundary and edge conditions."""
    # 1. Verify session token with empty token
    with pytest.raises(AuthenticationError, match="Missing authorization token"):
        AuthService.verify_session_token("")

    # 2. Logout session with empty token or non-existent token
    assert AuthService.logout_session("") is False
    assert AuthService.logout_session("non-existent-token") is False

    # 3. Password reset request for non-existent email returns None
    assert AuthService.request_password_reset("nonexistent@example.com") is None

    # 4. Confirm password reset with invalid token
    with pytest.raises(AuthenticationError, match="Invalid or already used password reset token"):
        AuthService.confirm_password_reset("invalid-token", "NewPassword123!")

    # 5. Confirm password reset with expired token
    user = AuthService.register_user("expired_reset@example.com", "Password123!")
    reset_tok = AuthService.request_password_reset("expired_reset@example.com")
    Clock.set_fixed(Clock.utcnow() + datetime.timedelta(hours=2))
    with pytest.raises(AuthenticationError, match="Password reset token has expired"):
        AuthService.confirm_password_reset(reset_tok, "NewPassword123!")
    Clock.reset()

    # 6. Anonymize non-existent user ID
    with pytest.raises(AuthenticationError, match="User not found"):
        AuthService.anonymize_user(999999)
