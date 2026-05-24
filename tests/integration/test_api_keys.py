"""Integration tests for per-user API key authentication."""

import pytest


@pytest.mark.usefixtures("clean_tables")
class TestApiKeyManagement:
    async def test_create_api_key(self, client, auth_headers):
        resp = await client.post(
            "/api/users/me/api-keys",
            json={"name": "my-agent-key"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-agent-key"
        assert data["key"].startswith("pi_live_")
        assert len(data["key"]) > len("pi_live_")

    async def test_list_api_keys(self, client, auth_headers):
        await client.post(
            "/api/users/me/api-keys",
            json={"name": "list-test-key"},
            headers=auth_headers,
        )
        resp = await client.get("/api/users/me/api-keys", headers=auth_headers)
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) >= 1
        assert any(k["name"] == "list-test-key" for k in keys)

    async def test_revoke_api_key(self, client, auth_headers):
        create_resp = await client.post(
            "/api/users/me/api-keys",
            json={"name": "revoke-test"},
            headers=auth_headers,
        )
        key_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/users/me/api-keys/{key_id}/revoke",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        list_resp = await client.get("/api/users/me/api-keys", headers=auth_headers)
        keys = list_resp.json()
        target = next(k for k in keys if k["id"] == key_id)
        assert target["revoked_at"] is not None

    async def test_delete_api_key_requires_revocation(self, client, auth_headers):
        create_resp = await client.post(
            "/api/users/me/api-keys",
            json={"name": "delete-test"},
            headers=auth_headers,
        )
        key_id = create_resp.json()["id"]

        # Should fail without revocation first
        resp = await client.delete(
            f"/api/users/me/api-keys/{key_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 400

        # Revoke then delete
        await client.post(f"/api/users/me/api-keys/{key_id}/revoke", headers=auth_headers)
        resp = await client.delete(f"/api/users/me/api-keys/{key_id}", headers=auth_headers)
        assert resp.status_code == 200

    async def test_management_requires_jwt(self, client, api_key_headers):
        """API key cannot be used to manage API keys."""
        resp = await client.post(
            "/api/users/me/api-keys",
            json={"name": "should-fail"},
            headers=api_key_headers,
        )
        assert resp.status_code == 401


@pytest.mark.usefixtures("clean_tables")
class TestApiKeyAuthentication:
    async def test_find_similar_with_api_key(self, client, api_key_headers, paper_db_conn, mock_dashscope):
        dim = 1536
        vec = [0.0] * dim
        vec[0] = 1.0
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"

        with paper_db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO papers (doc_id, title, abstract) VALUES (%s, %s, %s)",
                ("apikey_test_paper", "API Key Test", "Testing API key auth."),
            )
            cur.execute(
                "INSERT INTO paper_embeddings (doc_id, title, abstract, embedding) VALUES (%s, %s, %s, %s)",
                ("apikey_test_paper", "API Key Test", "Testing API key auth.", vec_str),
            )
        paper_db_conn.commit()

        resp = await client.post(
            "/api/papers/find_similar",
            json={"query": "test", "top_k": 5, "similarity_cutoff": -1.0},
            headers=api_key_headers,
        )
        assert resp.status_code == 200

    async def test_find_similar_bm25_with_api_key(self, client, api_key_headers, paper_db_conn):
        with paper_db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO papers (doc_id, title, abstract) VALUES (%s, %s, %s)",
                ("apikey_bm25_test", "API Key BM25 Test", "Testing API key auth for BM25."),
            )
        paper_db_conn.commit()

        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "API key", "top_k": 5},
            headers=api_key_headers,
        )
        assert resp.status_code == 200

    async def test_compat_find_similar_with_api_key(self, client, api_key_headers, paper_db_conn, mock_dashscope):
        resp = await client.post(
            "/find_similar/",
            json={"query": "test", "top_k": 5, "similarity_cutoff": -1.0},
            headers=api_key_headers,
        )
        assert resp.status_code == 200

    async def test_revoked_key_rejected(self, client, auth_headers):
        create_resp = await client.post(
            "/api/users/me/api-keys",
            json={"name": "to-revoke"},
            headers=auth_headers,
        )
        raw_key = create_resp.json()["key"]
        key_id = create_resp.json()["id"]

        await client.post(f"/api/users/me/api-keys/{key_id}/revoke", headers=auth_headers)

        resp = await client.post(
            "/api/papers/find_similar",
            json={"query": "test", "top_k": 5},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 401

    async def test_digests_recommendations_with_api_key(self, client, api_key_headers, test_user):
        username = test_user["username"]
        resp = await client.get(
            f"/api/digests/recommendations/{username}",
            headers=api_key_headers,
        )
        assert resp.status_code == 200

    async def test_api_key_cannot_access_other_user_digests(self, client, api_key_headers):
        resp = await client.get(
            "/api/digests/recommendations/other_user",
            headers=api_key_headers,
        )
        assert resp.status_code == 401

    async def test_api_key_cannot_access_favorites(self, client, api_key_headers):
        """API key should NOT work on JWT-only endpoints like favorites."""
        resp = await client.get("/api/favorites/list", headers=api_key_headers)
        assert resp.status_code == 401
