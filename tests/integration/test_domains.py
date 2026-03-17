"""Integration tests for domains and health endpoints."""

class TestDomains:
    async def test_list_domains(self, client):
        resp = await client.get("/api/domains")
        assert resp.status_code == 200
        domains = resp.json()
        assert len(domains) == 13
        codes = {d["code"] for d in domains}
        assert "NLP" in codes
        assert "CV" in codes
        assert "LLM" in codes

    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
