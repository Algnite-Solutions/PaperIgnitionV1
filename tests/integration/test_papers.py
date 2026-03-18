"""Integration tests for paper endpoints against real PostgreSQL + pgvector."""

import json

import pytest


@pytest.mark.usefixtures("clean_tables")
class TestPapers:
    async def test_paper_metadata_not_found(self, client):
        resp = await client.get("/api/papers/metadata/nonexistent_doc_id")
        assert resp.status_code == 404

    async def test_insert_and_get_paper_metadata(self, client, paper_db_conn):
        """Seed a paper via SQL, then GET its metadata via API."""
        doc_id = "2401.00001"
        with paper_db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO papers (doc_id, title, abstract, authors, categories, pdf_path)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    doc_id,
                    "Test Paper Title",
                    "This is a test abstract.",
                    json.dumps(["Author A", "Author B"]),
                    json.dumps(["cs.AI", "cs.LG"]),
                    "/pdfs/test.pdf",
                ),
            )
        paper_db_conn.commit()

        resp = await client.get(f"/api/papers/metadata/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id
        assert data["title"] == "Test Paper Title"
        assert "Author A" in data["authors"]
        assert "cs.AI" in data["categories"]

    async def test_find_similar_with_mock_embedding(self, client, paper_db_conn, mock_dashscope):
        """
        Seed paper_embeddings with known vectors, mock DashScope,
        POST /api/papers/find_similar, verify pgvector cosine similarity works.
        """
        # Create two papers with known embeddings
        dim = 1536

        # Paper A: unit vector along first axis
        vec_a = [0.0] * dim
        vec_a[0] = 1.0

        # Paper B: unit vector along second axis (orthogonal to A)
        vec_b = [0.0] * dim
        vec_b[1] = 1.0

        vec_a_str = "[" + ",".join(str(v) for v in vec_a) + "]"
        vec_b_str = "[" + ",".join(str(v) for v in vec_b) + "]"

        with paper_db_conn.cursor() as cur:
            # Insert papers
            cur.execute(
                "INSERT INTO papers (doc_id, title, abstract) VALUES (%s, %s, %s)",
                ("sim_paper_a", "Paper About Transformers", "A study on attention mechanisms."),
            )
            cur.execute(
                "INSERT INTO papers (doc_id, title, abstract) VALUES (%s, %s, %s)",
                ("sim_paper_b", "Paper About CNNs", "Convolutional networks for vision."),
            )
            # Insert embeddings
            cur.execute(
                "INSERT INTO paper_embeddings (doc_id, title, abstract, embedding) VALUES (%s, %s, %s, %s)",
                ("sim_paper_a", "Paper About Transformers", "A study on attention mechanisms.", vec_a_str),
            )
            cur.execute(
                "INSERT INTO paper_embeddings (doc_id, title, abstract, embedding) VALUES (%s, %s, %s, %s)",
                ("sim_paper_b", "Paper About CNNs", "Convolutional networks for vision.", vec_b_str),
            )
        paper_db_conn.commit()

        # Search — mock_dashscope returns a deterministic vector, so we just verify
        # that pgvector returns results and similarity scores are valid floats
        # Verify data is actually in the DB before querying
        with paper_db_conn.cursor() as cur:
            cur.execute("SELECT doc_id FROM paper_embeddings")
            rows = cur.fetchall()
            assert len(rows) >= 2, f"Expected 2+ embeddings, got {rows}"

        resp = await client.post(
            "/api/papers/find_similar",
            json={"query": "attention transformers", "top_k": 10, "similarity_cutoff": 0.0},
        )
        assert resp.status_code == 200, f"find_similar failed: {resp.text}"
        data = resp.json()
        assert data["total"] >= 1, f"No results returned. Response: {data}"
        assert len(data["results"]) >= 1

        # Verify our seeded papers appear with valid similarity scores
        result_ids = {r["doc_id"] for r in data["results"]}
        assert result_ids & {"sim_paper_a", "sim_paper_b"}, "Expected at least one seeded paper in results"
        for result in data["results"]:
            assert 0.0 <= result["similarity"] <= 1.0

    async def test_paper_content_not_found(self, client):
        resp = await client.get("/api/papers/content/nonexistent_doc_id")
        assert resp.status_code == 404
