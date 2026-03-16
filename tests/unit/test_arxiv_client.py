"""Unit tests for ArxivClient."""
from core.arxiv.client import ArxivClient


def test_client_init():
    client = ArxivClient(max_results=10)
    assert client.max_results == 10


def test_client_default_max_results():
    client = ArxivClient()
    assert client.max_results is None or isinstance(client.max_results, int)
