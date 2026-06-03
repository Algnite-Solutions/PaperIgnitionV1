import httpx


class PaperIgnitionClient:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        }

    def find_similar(self, query: str, top_k: int = 10, similarity_cutoff: float = 0.1):
        resp = httpx.post(
            f"{self._base_url}/api/papers/find_similar",
            json={"query": query, "top_k": top_k, "similarity_cutoff": similarity_cutoff},
            headers=self._headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def find_similar_bm25(self, query: str, top_k: int = 10):
        resp = httpx.post(
            f"{self._base_url}/api/papers/find_similar_bm25",
            json={"query": query, "top_k": top_k},
            headers=self._headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_paper_metadata(self, doc_id: str):
        resp = httpx.get(
            f"{self._base_url}/api/papers/metadata/{doc_id}",
            headers=self._headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_paper_content(self, paper_id: str):
        resp = httpx.get(
            f"{self._base_url}/api/papers/content/{paper_id}",
            headers=self._headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.text

    def get_paper_full_text(self, doc_id: str):
        resp = httpx.get(
            f"{self._base_url}/api/papers/full_text/{doc_id}",
            headers=self._headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.text

    def get_recommendations(self, username: str, limit: int = 50):
        resp = httpx.get(
            f"{self._base_url}/api/digests/recommendations/{username}",
            params={"limit": limit},
            headers=self._headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_blog_content(self, paper_id: str, username: str):
        resp = httpx.get(
            f"{self._base_url}/api/digests/blog_content/{paper_id}/{username}",
            headers=self._headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.text
