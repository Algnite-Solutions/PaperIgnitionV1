"""Integration tests for digests (recommendations, feedback, mark-viewed) endpoints."""

import pytest


@pytest.mark.usefixtures("clean_tables")
class TestDigests:
    async def test_add_recommendation(self, client, test_user):
        username = test_user["username"]
        resp = await client.post(
            f"/api/digests/recommend?username={username}",
            json={
                "username": username,
                "paper_id": "2401.00001",
                "title": "Recommended Paper",
                "authors": "Author A",
                "abstract": "Great paper",
                "blog": "# Blog\nThis is a blog post.",
                "blog_title": "Blog Title",
                "blog_abs": "Blog abstract",
                "relevance_score": 0.95,
                "recommendation_reason": "Matches interests",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] is not None

    async def test_get_recommendations(self, client, test_user):
        username = test_user["username"]
        # Add two recommendations
        for i in range(2):
            await client.post(
                f"/api/digests/recommend?username={username}",
                json={
                    "username": username,
                    "paper_id": f"2401.0000{i+1}",
                    "title": f"Paper {i+1}",
                    "authors": f"Author {i+1}",
                    "abstract": f"Abstract {i+1}",
                    "blog": f"# Blog {i+1}\nContent here.",
                    "blog_title": f"Title {i+1}",
                    "blog_abs": f"Abs {i+1}",
                },
            )

        resp = await client.get(f"/api/digests/recommendations/{username}")
        assert resp.status_code == 200
        papers = resp.json()
        assert len(papers) == 2
        # Most recent first
        assert papers[0]["id"] == "2401.00002"

    async def test_feedback_update(self, client, test_user):
        username = test_user["username"]
        paper_id = "2401.feedback"
        # Add recommendation first
        await client.post(
            f"/api/digests/recommend?username={username}",
            json={
                "username": username,
                "paper_id": paper_id,
                "title": "Feedback Paper",
                "authors": "Author",
                "abstract": "Abstract",
                "blog": "# Blog\nContent.",
            },
        )

        # Update feedback
        resp = await client.put(
            f"/api/digests/recommendations/{paper_id}/feedback",
            json={"username": username, "blog_liked": True},
        )
        assert resp.status_code == 200
        assert resp.json()["blog_liked"] is True

    async def test_mark_viewed(self, client, test_user, auth_headers):
        username = test_user["username"]
        paper_id = "2401.viewed"

        # Add recommendation
        await client.post(
            f"/api/digests/recommend?username={username}",
            json={
                "username": username,
                "paper_id": paper_id,
                "title": "Viewed Paper",
                "authors": "Author",
                "abstract": "Abstract",
                "blog": "# Blog\nContent.",
            },
        )

        # Mark as viewed
        resp = await client.post(
            f"/api/digests/{paper_id}/mark-viewed",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["viewed"] is True
