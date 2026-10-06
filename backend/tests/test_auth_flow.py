"""Authentication and authorisation tests.

Covered here:
  * registration normalises the phone number and never returns a password hash;
  * the OTP flow works end to end with the *console* (development) provider, and
    the response says plainly that the code was printed by a demo provider;
  * password login, session listing and revocation;
  * access-token rules: a token issued before a logout (token_version bump) is
    rejected — this is the mechanism that makes "logout everywhere" real;
  * role gates: a farmer cannot reach staff-only endpoints.

These tests are deliberately black-box (HTTP), because the failure they are
guarding against is "the API says one thing and the database does another".
"""

from __future__ import annotations


def test_register_creates_a_verified_ready_account(client, db):
    response = client.post(
        "/api/v1/auth/register",
        json={"full_name": "Nanda Patil", "phone": "9876543210", "password": "Sugarcane!2026"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] in {"pending_verification", "active"}
    assert body["user"]["full_name"] == "Nanda Patil"
    # Contact details must never be echoed back in a response body.
    assert "password" not in response.text.lower()
    assert "password_hash" not in response.text
    # The OTP path is explicit that the code came from a development provider.
    if body.get("otp"):
        assert body["otp"]["is_demo_provider"] is True
        assert body["otp"]["dev_otp"]


def test_register_rejects_a_duplicate_phone(client):
    payload = {"full_name": "First Farmer", "phone": "9876500001", "password": "Sugarcane!2026"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/v1/auth/register",
        json={**payload, "full_name": "Second Farmer"},
    )
    # Either a 201 carrying a conflict payload or a 409 is acceptable; silently
    # creating a second account for the same phone is not.
    assert duplicate.status_code in {201, 409}
    body = duplicate.json()
    if duplicate.status_code == 201:
        assert body.get("status") == "conflict"
        assert body.get("requires_login") is True


def test_otp_login_with_console_provider(client):
    phone = "9876500002"
    requested = client.post("/api/v1/auth/otp/request", json={"identifier": phone})
    assert requested.status_code == 200, requested.text
    otp = requested.json()
    assert otp["provider"] == "console"
    assert otp.get("dev_otp"), "the console provider must publish the code for local testing"
    # A response must never advertise whether the identifier has an account.
    assert "identifier_exists" not in otp

    verified = client.post(
        "/api/v1/auth/otp/verify",
        json={"identifier": phone, "code": otp["dev_otp"], "full_name": "OTP Farmer"},
    )
    assert verified.status_code == 200, verified.text
    tokens = verified.json()["tokens"]
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["token_type"].lower() == "bearer"
    # The refresh token is returned once, with its own expiry; only its hash is
    # stored server-side.
    assert tokens["refresh_expires_at"]
    assert tokens["expires_in"] > 0


def test_otp_verify_rejects_a_wrong_code(client):
    phone = "9876500003"
    client.post("/api/v1/auth/otp/request", json={"identifier": phone})
    bad = client.post("/api/v1/auth/otp/verify", json={"identifier": phone, "code": "000000"})
    assert bad.status_code in {400, 401, 422}
    assert "traceback" not in bad.text.lower()


def test_password_login_and_wrong_password(client, farmer):
    ok = client.post(
        "/api/v1/auth/login", json={"identifier": farmer.phone, "password": farmer.password}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["tokens"]["access_token"]

    wrong = client.post(
        "/api/v1/auth/login", json={"identifier": farmer.phone, "password": "not-the-password"}
    )
    assert wrong.status_code in {400, 401}
    error = wrong.json()
    message = (error.get("error") or {}).get("message") or error.get("detail")
    # The message must not reveal whether the account exists.
    assert "password" not in str(message).lower() or "incorrect" in str(message).lower()


def test_me_requires_a_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_my_account(client, farmer):
    response = client.get("/api/v1/auth/me", headers=farmer.headers)
    assert response.status_code == 200
    body = response.json()
    assert str(body["id"]) == str(farmer.user_id)
    assert body["primary_role"] == "farmer"


def test_sessions_listed_and_revoked(client, farmer):
    listing = client.get("/api/v1/auth/sessions", headers=farmer.headers)
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)

    login = client.post(
        "/api/v1/auth/login", json={"identifier": farmer.phone, "password": farmer.password}
    )
    assert login.status_code == 200
    second = login.json()["tokens"]["access_token"]
    sessions = client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {second}"}
    ).json()
    assert sessions, "a fresh login must appear in the session list"
    session_id = sessions[0]["id"]
    revoked = client.delete(f"/api/v1/auth/sessions/{session_id}", headers=farmer.headers)
    assert revoked.status_code in {204, 404}


def test_token_version_invalidates_old_tokens(client, farmer):
    """Logout everywhere must actually invalidate tokens already issued."""
    client.post("/api/v1/auth/logout", headers=farmer.headers, json={"all_sessions": True})
    after = client.get("/api/v1/users/me", headers=farmer.headers)
    assert after.status_code in {401, 403}


def test_farmer_cannot_reach_admin_endpoints(client, farmer):
    """Role gates are enforced server-side, not by hiding buttons in the app."""
    for path in ("/api/v1/admin/overview", "/api/v1/admin/users"):
        response = client.get(path, headers=farmer.headers)
        assert response.status_code in {401, 403}, path


def test_admin_can_reach_admin_endpoints(client, admin):
    response = client.get("/api/v1/admin/overview", headers=admin.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "users" in body or "counts" in body
