"""Integration tests verifying service-token protection on orchestrator-facing endpoints."""

import pytest  # noqa: I001

# Parametrized list of (method, path) for all service-token-protected endpoints
_SERVICE_ENDPOINTS = [
    ("GET", "/api/users/all"),
    ("GET", "/api/users/boost-requested"),
]


@pytest.mark.usefixtures("clean_tables")
class TestServiceTokenProtection:
    @pytest.mark.parametrize("method,path", _SERVICE_ENDPOINTS)
    async def test_rejects_without_token(self, client, test_user, method, path):
        resp = await client.request(method, path)
        assert resp.status_code == 401, f"Expected 401 for {method} {path} without token, got {resp.status_code}"

    @pytest.mark.parametrize("method,path", _SERVICE_ENDPOINTS)
    async def test_rejects_bad_token(self, client, test_user, method, path):
        resp = await client.request(method, path, headers={"X-Service-Token": "wrong-token"})
        assert resp.status_code == 401, f"Expected 401 for {method} {path} with bad token"

    @pytest.mark.parametrize("method,path", _SERVICE_ENDPOINTS)
    async def test_allows_valid_token(self, client, test_user, service_headers, method, path):
        resp = await client.request(method, path, headers=service_headers)
        assert resp.status_code in (200, 404), f"Expected 200/404 for {method} {path} with valid token, got {resp.status_code}"

    async def test_user_endpoints_reject_without_token(self, client, test_user):
        """Verify per-user service-token-protected endpoints reject without token."""
        username = test_user["username"]

        resp = await client.get(f"/api/users/by_email/{username}")
        assert resp.status_code == 401

        resp = await client.get(f"/api/users/profile-pool/{username}")
        assert resp.status_code == 401

        resp = await client.get(f"/api/users/boost-history/{username}")
        assert resp.status_code == 401

    async def test_search_endpoints_require_jwt(self, client):
        """Verify find_similar and find_similar_bm25 require JWT auth."""
        resp = await client.post(
            "/api/papers/find_similar",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401

        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401

    async def test_compat_find_similar_requires_jwt(self, client):
        """Verify the compat /find_similar/ route also requires JWT auth."""
        resp = await client.post(
            "/find_similar/",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401
