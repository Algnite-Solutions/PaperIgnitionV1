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
            json={"query": "attention transformers", "top_k": 10, "similarity_cutoff": -1.0},
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

    async def test_find_similar_bm25(self, client, paper_db_conn):
        """
        Test BM25 full-text search endpoint.
        Seeds papers with known content, POST /api/papers/find_similar_bm25,
        verify results are ranked correctly by BM25 score.
        """
        # Seed test papers with distinct content for BM25 matching
        test_papers = [
            {
                "doc_id": "bm25_001",
                "title": "Deep Learning with Transformers and Attention",
                "abstract": "This paper explores transformer architectures with attention mechanisms for natural language processing tasks.",
            },
            {
                "doc_id": "bm25_002",
                "title": "Convolutional Neural Networks for Computer Vision",
                "abstract": "CNN architectures for image classification and object detection using convolutional layers.",
            },
            {
                "doc_id": "bm25_003",
                "title": "Attention is All You Need: Transformer Models",
                "abstract": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
            },
            {
                "doc_id": "bm25_004",
                "title": "Reinforcement Learning for Game Playing",
                "abstract": "Using deep reinforcement learning to master complex games through self-play and policy gradients.",
            },
        ]

        with paper_db_conn.cursor() as cur:
            for paper in test_papers:
                cur.execute(
                    """
                    INSERT INTO papers (doc_id, title, abstract)
                    VALUES (%s, %s, %s)
                    """,
                    (paper["doc_id"], paper["title"], paper["abstract"]),
                )
        paper_db_conn.commit()

        # Test 1: Search for "transformer attention" - should return bm25_001 and bm25_003
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "transformer attention", "top_k": 10},
        )
        assert resp.status_code == 200, f"BM25 search failed: {resp.text}"
        data = resp.json()
        assert data["total"] >= 2, f"Expected at least 2 results for 'transformer attention', got {data['total']}"
        assert data["query"] == "transformer attention"

        result_ids = [r["doc_id"] for r in data["results"]]
        # Papers with "transformer" and "attention" should rank highest
        assert "bm25_001" in result_ids or "bm25_003" in result_ids, \
            "Expected transformer/attention papers in results"

        # Verify BM25 scores are positive floats
        for result in data["results"]:
            assert result["similarity"] > 0, f"BM25 score should be positive, got {result['similarity']}"
            assert "title" in result
            assert "abstract" in result

        # Test 2: Search for "convolutional neural" - should return bm25_002
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "convolutional neural", "top_k": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        result_ids = [r["doc_id"] for r in data["results"]]
        assert "bm25_002" in result_ids, "Expected CNN paper in results for 'convolutional neural'"

        # Test 3: Search with exclude filter
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={
                "query": "transformer",
                "top_k": 10,
                "filters": {"exclude": {"doc_ids": ["bm25_001"]}},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        result_ids = [r["doc_id"] for r in data["results"]]
        assert "bm25_001" not in result_ids, "Excluded paper should not appear in results"
        # bm25_003 should still appear
        assert "bm25_003" in result_ids, "Expected bm25_003 (not excluded) in results"

        # Test 4: Empty query should return 400
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "   ", "top_k": 10},
        )
        assert resp.status_code == 400, "Empty query should return 400"

    async def test_find_similar_bm25_no_results(self, client, paper_db_conn):
        """
        Test BM25 endpoint when no papers match the query.
        """
        # Seed a paper with unrelated content
        with paper_db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO papers (doc_id, title, abstract)
                VALUES (%s, %s, %s)
                """,
                ("bm25_unrelated", "Quantum Computing Algorithms", "Shor's algorithm for factoring large numbers."),
            )
        paper_db_conn.commit()

        # Search for something completely unrelated
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={"query": "medieval history castles", "top_k": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0, "Expected no results for unrelated query"
        assert len(data["results"]) == 0

    async def test_find_similar_bm25_with_date_filter(self, client, paper_db_conn):
        """
        Test BM25 endpoint with date range filter.
        """
        from datetime import datetime, timezone

        # Seed papers with different dates
        test_papers = [
            {
                "doc_id": "bm25_date_001",
                "title": "Machine Learning in 2023",
                "abstract": "Advances in machine learning during 2023.",
                "published_date": datetime(2023, 6, 15, tzinfo=timezone.utc),
            },
            {
                "doc_id": "bm25_date_002",
                "title": "Deep Learning in 2024",
                "abstract": "Deep learning breakthroughs in 2024.",
                "published_date": datetime(2024, 1, 10, tzinfo=timezone.utc),
            },
            {
                "doc_id": "bm25_date_003",
                "title": "AI in 2025",
                "abstract": "Artificial intelligence trends in 2025.",
                "published_date": datetime(2025, 3, 20, tzinfo=timezone.utc),
            },
        ]

        with paper_db_conn.cursor() as cur:
            for paper in test_papers:
                cur.execute(
                    """
                    INSERT INTO papers (doc_id, title, abstract, published_date)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (paper["doc_id"], paper["title"], paper["abstract"], paper["published_date"]),
                )
        paper_db_conn.commit()

        # Search with date filter - should only return 2024 papers
        resp = await client.post(
            "/api/papers/find_similar_bm25",
            json={
                "query": "learning",
                "top_k": 10,
                "filters": {
                    "include": {
                        "published_date": ["2024-01-01", "2024-12-31"]
                    }
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        result_ids = [r["doc_id"] for r in data["results"]]
        assert "bm25_date_002" in result_ids, "Expected 2024 paper in results"
        assert "bm25_date_001" not in result_ids, "2023 paper should be filtered out"
        assert "bm25_date_003" not in result_ids, "2025 paper should be filtered out"
