"""Unit tests for core models."""
from core.models import DocSet, TextChunk, FigureChunk, TableChunk


def test_docset_creation():
    ds = DocSet(doc_id="2401.12345", title="Test Paper", authors=["Author A"], abstract="Test abstract")
    assert ds.doc_id == "2401.12345"
    assert ds.title == "Test Paper"
    assert len(ds.authors) == 1


def test_docset_defaults():
    ds = DocSet(doc_id="test")
    assert ds.text_chunks == []
    assert ds.figure_chunks == []
    assert ds.table_chunks == []
    assert ds.pdf_path is None


def test_text_chunk():
    tc = TextChunk(chunk_id="chunk_0", text="Some text content", chunk_order=0)
    assert tc.chunk_id == "chunk_0"
    assert tc.text == "Some text content"
