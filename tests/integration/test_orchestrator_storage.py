"""Integration tests for orchestrator's RDSDBManager against real PostgreSQL."""

from dataclasses import dataclass

import pytest

from orchestrator.storage_util import RDSConfig, RDSDBManager


@dataclass
class FakePaper:
    """Minimal paper object matching what RDSDBManager.insert_paper expects."""
    doc_id: str
    title: str
    authors: list
    abstract: str
    categories: list
    published_date: str = None
    pdf_path: str = None
    html_path: str = None


@pytest.fixture
def rds_manager(ci_config_path):
    from backend.config_utils import load_config

    config = load_config(ci_config_path)
    rds = config["aliyun_rds"]
    rds_config = RDSConfig(
        host=rds["db_host"],
        port=int(rds["db_port"]),
        database=rds["db_name_paper"],
        user=rds["db_user"],
        password=rds["db_password"],
    )
    manager = RDSDBManager(config=rds_config)
    yield manager
    manager.close()


@pytest.mark.usefixtures("clean_tables")
class TestRDSDBManager:
    def test_insert_paper(self, rds_manager):
        paper = FakePaper(
            doc_id="orch_2401.00001",
            title="Orchestrator Test Paper",
            authors=["Author A", "Author B"],
            abstract="Test abstract for orchestrator.",
            categories=["cs.AI"],
        )
        result = rds_manager.insert_paper(paper)
        assert result is True

        # Verify it's in the DB
        fetched = rds_manager.get_paper("orch_2401.00001")
        assert fetched is not None
        assert fetched["title"] == "Orchestrator Test Paper"

    def test_insert_duplicate_paper(self, rds_manager):
        paper = FakePaper(
            doc_id="orch_2401.00002",
            title="Dup Paper",
            authors=["Author"],
            abstract="Duplicate test.",
            categories=["cs.LG"],
        )
        assert rds_manager.insert_paper(paper) is True
        assert rds_manager.insert_paper(paper) is False

    def test_get_all_doc_ids(self, rds_manager):
        papers = [
            FakePaper(
                doc_id=f"orch_2401.0010{i}",
                title=f"Paper {i}",
                authors=["Author"],
                abstract=f"Abstract {i}",
                categories=["cs.AI"],
            )
            for i in range(3)
        ]
        for p in papers:
            rds_manager.insert_paper(p)

        doc_ids = rds_manager.get_all_doc_ids()
        for p in papers:
            assert p.doc_id in doc_ids
