"""Integration tests for favorites endpoints."""

import pytest


@pytest.mark.usefixtures("clean_tables")
class TestFavorites:
    async def test_add_favorite(self, client, test_user, auth_headers):
        resp = await client.post(
            "/api/favorites/add",
            json={
                "paper_id": "2401.00001",
                "title": "Test Paper",
                "authors": "Author A",
                "abstract": "Abstract text",
                "url": "https://arxiv.org/abs/2401.00001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json().get("message") == "Paper added to favorites"

    async def test_remove_favorite(self, client, test_user, auth_headers):
        # Add first
        await client.post(
            "/api/favorites/add",
            json={
                "paper_id": "2401.00002",
                "title": "Paper to Remove",
                "authors": "Author B",
                "abstract": "Will be removed",
            },
            headers=auth_headers,
        )

        # Remove
        resp = await client.delete("/api/favorites/remove/2401.00002", headers=auth_headers)
        assert resp.status_code == 200

        # Verify removed
        resp = await client.get("/api/favorites/list", headers=auth_headers)
        paper_ids = [f["paper_id"] for f in resp.json()]
        assert "2401.00002" not in paper_ids

    async def test_list_favorites(self, client, test_user, auth_headers):
        # Add two papers
        for i in range(2):
            await client.post(
                "/api/favorites/add",
                json={
                    "paper_id": f"2401.1000{i}",
                    "title": f"Fav Paper {i}",
                    "authors": f"Author {i}",
                    "abstract": f"Abstract {i}",
                },
                headers=auth_headers,
            )

        resp = await client.get("/api/favorites/list", headers=auth_headers)
        assert resp.status_code == 200
        favorites = resp.json()
        assert len(favorites) == 2
        # Most recent first (desc order)
        assert favorites[0]["paper_id"] == "2401.10001"
