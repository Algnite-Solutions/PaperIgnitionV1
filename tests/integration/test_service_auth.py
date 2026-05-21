"""Integration tests verifying service-token and JWT protection on all endpoints."""

import pytest  # noqa: I001


# All 13 C4 service-token-protected endpoints (users + digests)
_SERVICE_GET_ENDPOINTS = [
    "GET /api/users/all",
    "GET /api/users/boost-requested",
]


def _svc_path(spec):
    method, path = spec.split(" ", 1)
    return method, path


@pytest.mark.usefixtures("clean_tables")
class TestServiceTokenProtection:
    """All 13 C4 endpoints must reject requests without a valid service token."""

    @pytest.mark.parametrize("spec", [
        "GET /api/users/all",
        "GET /api/users/boost-requested",
    ])
    async def test_get_rejects_without_token(self, client, test_user, spec):
        method, path = _svc_path(spec)
        resp = await client.request(method, path)
        assert resp.status_code == 401, f"Expected 401 for {spec} without token, got {resp.status_code}"

    async def test_user_endpoints_reject_without_token(self, client, test_user):
        """Per-user service-token-protected endpoints in users.py."""
        username = test_user["username"]

        for path in [
            f"/api/users/by_email/{username}",
            f"/api/users/profile-pool/{username}",
            f"/api/users/boost-history/{username}",
        ]:
            resp = await client.get(path)
            assert resp.status_code == 401, f"Expected 401 for GET {path}, got {resp.status_code}"

    async def test_user_post_endpoints_reject_without_token(self, client, test_user):
        """POST service-token-protected endpoints in users.py."""
        username = test_user["username"]

        resp = await client.post(
            f"/api/users/boost-complete/{username}",
            json={"profile_json": {}},
        )
        assert resp.status_code == 401

        resp = await client.post(
            f"/api/users/profile-pool/{username}",
            json={"entries": [], "active_entry_index": 0},
        )
        assert resp.status_code == 401

        resp = await client.post(
            f"/api/users/boost-history/{username}",
            json={"boost_number": 1, "cumulative_likes": 0, "pool_version": 1},
        )
        assert resp.status_code == 401

    async def test_digest_endpoints_reject_without_token(self, client, test_user):
        """All 5 C4 digests endpoints reject without service token."""
        username = test_user["username"]
        paper_id = "2401.svc_test"

        # GET recommendations
        resp = await client.get(f"/api/digests/recommendations/{username}")
        assert resp.status_code == 401

        # GET blog content
        resp = await client.get(f"/api/digests/blog_content/{paper_id}/{username}")
        assert resp.status_code == 401

        # POST recommend
        resp = await client.post(
            f"/api/digests/recommend?username={username}",
            json={"username": username, "paper_id": paper_id, "title": "T", "blog": "B"},
        )
        assert resp.status_code == 401

        # PUT feedback
        resp = await client.put(
            f"/api/digests/recommendations/{paper_id}/feedback",
            json={"username": username, "blog_liked": True},
        )
        assert resp.status_code == 401

        # POST retrieve_results/save
        resp = await client.post(
            "/api/digests/retrieve_results/save",
            json={"username": username, "query": "q", "search_strategy": "s",
                  "retrieve_ids": [], "top_k_ids": []},
        )
        assert resp.status_code == 401


@pytest.mark.usefixtures("clean_tables")
class TestSearchJWTProtection:
    """Search endpoints require JWT auth (protects DashScope embedding cost)."""

    async def test_find_similar_requires_jwt(self, client):
        resp = await client.post(
            "/api/papers/find_similar",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401

    async def test_find_similar_bm25_requires_jwt(self, client):
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401

    async def test_compat_find_similar_requires_jwt(self, client):
        resp = await client.post(
            "/find_similar/",
            json={"query": "test", "top_k": 5},
        )
        assert resp.status_code == 401
