"""Integration tests for auth endpoints (register + login) against real PostgreSQL."""

import uuid

import pytest


@pytest.mark.usefixtures("clean_tables")
class TestAuth:
    async def test_register_new_user(self, client):
        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/api/auth/register-email",
            json={
                "email": f"reg_{unique}@example.com",
                "password": "Secret123!",
                "username": f"reg_{unique}",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user_info"]["email"] == f"reg_{unique}@example.com"

    async def test_register_duplicate_email(self, client):
        unique = uuid.uuid4().hex[:8]
        payload = {
            "email": f"dup_{unique}@example.com",
            "password": "Secret123!",
            "username": f"dup_{unique}",
        }
        resp1 = await client.post("/api/auth/register-email", json=payload)
        assert resp1.status_code == 200

        # Second registration with same email should fail
        payload2 = {**payload, "username": f"dup2_{unique}"}
        resp2 = await client.post("/api/auth/register-email", json=payload2)
        assert resp2.status_code == 400

    async def test_login_success(self, client):
        unique = uuid.uuid4().hex[:8]
        email = f"login_{unique}@example.com"
        password = "Secret123!"

        await client.post(
            "/api/auth/register-email",
            json={"email": email, "password": password, "username": f"login_{unique}"},
        )

        resp = await client.post(
            "/api/auth/login-email",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password(self, client):
        unique = uuid.uuid4().hex[:8]
        email = f"wrong_{unique}@example.com"

        await client.post(
            "/api/auth/register-email",
            json={"email": email, "password": "Correct123!", "username": f"wrong_{unique}"},
        )

        resp = await client.post(
            "/api/auth/login-email",
            json={"email": email, "password": "WrongPassword!"},
        )
        assert resp.status_code == 401
