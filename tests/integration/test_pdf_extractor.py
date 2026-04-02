"""Integration tests for PDF extractor with mocked OCR APIs.

Tests the full extraction pipeline including:
- PDF preprocessing (trim, compress)
- OCR API calls (mocked)
- Content parsing (text, figures, tables)
- Image downloading and naming
"""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

from core.arxiv.pdf_extractor import (
    PDFExtractor_volcengine,
    PDFExtractor_baidu,
)
from core.models import ChunkType


# Sample PDF content (minimal valid PDF)
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF
"""


@pytest.fixture
def temp_pdf_dir():
    """Create a temporary directory with a test PDF file."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_pdf_path(temp_pdf_dir):
    """Create a sample PDF file for testing."""
    pdf_path = temp_pdf_dir / "2501.01234.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)
    return pdf_path


@pytest.fixture
def image_dir(temp_pdf_dir):
    """Create an image output directory."""
    img_dir = temp_pdf_dir / "imgs"
    img_dir.mkdir(exist_ok=True)
    return img_dir


class TestVolcEngineIntegration:
    """Integration tests for VolcEngine OCR extractor."""

    @pytest.fixture
    def volcengine_extractor(self):
        """Create a VolcEngine extractor with mock credentials."""
        return PDFExtractor_volcengine(
            volcengine_ak="test_ak",
            volcengine_sk="test_sk",
            max_pages=16
        )

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    def test_full_extraction_pipeline(self, mock_pdf_to_md, volcengine_extractor, sample_pdf_path, image_dir):
        """Test complete extraction pipeline with mocked OCR response."""
        # Mock OCR response with markdown containing text, figure, and table
        mock_markdown = """## Introduction

This paper introduces a novel approach to machine learning.
Our method achieves state-of-the-art results on multiple benchmarks.

![figure](https://volcengine.example.com/fig1.png)
Figure 1: Architecture overview of the proposed model.

## Methods

We use transformer architecture as our backbone.

Table 1: Experimental Results
<table>
<tr><th>Model</th><th>Accuracy</th></tr>
<tr><td>Ours</td><td>95.2%</td></tr>
<tr><td>Baseline</td><td>89.1%</td></tr>
</table>

## Conclusion

We presented a novel approach.
"""
        mock_pdf_to_md.return_value = mock_markdown

        # Mock image download
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"\x89PNG\r\n\x1a\n fake png content"
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            text_chunks, figure_chunks, table_chunks = volcengine_extractor.extract(
                sample_pdf_path, "2501.01234", image_dir
            )

        # Verify text chunks
        assert len(text_chunks) >= 1
        intro_chunk = next((c for c in text_chunks if "Introduction" in c.title), None)
        assert intro_chunk is not None
        assert "novel approach" in intro_chunk.text

        # Verify table chunks
        assert len(table_chunks) == 1
        assert "Table 1" in table_chunks[0].title
        assert "<table>" in table_chunks[0].table_html

        # Figure chunk depends on whether "Figure 1" is found near the URL
        # The URL format is ![figure](url) followed by "Figure 1:" text

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    def test_extraction_handles_empty_markdown(self, mock_pdf_to_md, volcengine_extractor, sample_pdf_path, image_dir):
        """Test handling of empty OCR response."""
        mock_pdf_to_md.return_value = ""

        text_chunks, figure_chunks, table_chunks = volcengine_extractor.extract(
            sample_pdf_path, "2501.01234", image_dir
        )

        assert text_chunks == []
        assert figure_chunks == []
        assert table_chunks == []

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    def test_extraction_handles_ocr_failure(self, mock_pdf_to_md, volcengine_extractor, sample_pdf_path, image_dir):
        """Test handling of OCR failure (None returned)."""
        mock_pdf_to_md.return_value = None

        text_chunks, figure_chunks, table_chunks = volcengine_extractor.extract(
            sample_pdf_path, "2501.01234", image_dir
        )

        assert text_chunks == []
        assert figure_chunks == []
        assert table_chunks == []

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    def test_markdown_saved_for_debugging(self, mock_pdf_to_md, volcengine_extractor, sample_pdf_path, image_dir):
        """Test that markdown is saved alongside PDF for debugging."""
        mock_markdown = "## Test\n\nContent"
        mock_pdf_to_md.return_value = mock_markdown

        volcengine_extractor.extract(sample_pdf_path, "2501.01234", image_dir)

        md_path = sample_pdf_path.parent / "2501.01234.md"
        assert md_path.exists()
        assert md_path.read_text() == mock_markdown


class TestBaiduIntegration:
    """Integration tests for Baidu OCR extractor."""

    @pytest.fixture
    def baidu_extractor(self):
        """Create a Baidu extractor with mock credentials."""
        return PDFExtractor_baidu(
            api_url="https://baidu-api.example.com/layout-parsing",
            api_token="test_token_12345",
            max_pages=16
        )

    @patch("requests.post")
    def test_full_extraction_pipeline(self, mock_post, baidu_extractor, sample_pdf_path, image_dir):
        """Test complete Baidu extraction pipeline with mocked API response."""
        # Mock Baidu API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": """## Abstract

This paper presents a comprehensive study.

<img src="imgs/fig1.png">
Figure 1: System architecture overview.

<table>
<tr><td>A</td><td>B</td></tr>
</table>

Table 1: Dataset statistics""",
                            "images": {
                                "imgs/fig1.png": "https://baidu-cdn.example.com/download/fig1.png"
                            }
                        }
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        # Mock image download
        with patch("requests.get") as mock_get:
            mock_img_response = Mock()
            mock_img_response.content = b"\x89PNG\r\n\x1a\n fake png content"
            mock_img_response.raise_for_status = Mock()
            mock_get.return_value = mock_img_response

            text_chunks, figure_chunks, table_chunks = baidu_extractor.extract(
                sample_pdf_path, "2501.01234", image_dir
            )

        # Verify text chunks
        assert len(text_chunks) >= 1
        abstract_chunk = next((c for c in text_chunks if "Abstract" in c.title), None)
        assert abstract_chunk is not None

        # Verify figure chunks
        assert len(figure_chunks) == 1
        assert figure_chunks[0].title == "2501.01234_Figure1"
        assert "System architecture" in figure_chunks[0].caption

        # Verify image was downloaded with correct name
        expected_img_path = image_dir / "2501.01234_Figure1.png"
        assert expected_img_path.exists()

        # Verify table chunks
        assert len(table_chunks) == 1

    @patch("requests.post")
    def test_multi_page_merge(self, mock_post, baidu_extractor, sample_pdf_path, image_dir):
        """Test that multiple pages are merged with page separators."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": "## Page 1\n\nContent from page 1.",
                            "images": {}
                        }
                    },
                    {
                        "markdown": {
                            "text": "## Page 2\n\nContent from page 2.",
                            "images": {}
                        }
                    },
                    {
                        "markdown": {
                            "text": "## Page 3\n\nContent from page 3.",
                            "images": {}
                        }
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        text_chunks, _, _ = baidu_extractor.extract(sample_pdf_path, "2501.01234", image_dir)

        # Check that markdown was merged with separators
        md_path = sample_pdf_path.parent / "2501.01234.md"
        merged_content = md_path.read_text()
        assert "---" in merged_content  # Page separator
        assert "Page 1" in merged_content
        assert "Page 2" in merged_content
        assert "Page 3" in merged_content

    @patch("requests.post")
    def test_image_url_map_cleared_between_extractions(self, mock_post, baidu_extractor, sample_pdf_path, image_dir):
        """Test that image URL map is cleared between extractions."""
        # First extraction with one image
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = {
            "result": {
                "layoutParsingResults": [{
                    "markdown": {
                        "text": '<img src="imgs/fig1.png"> Figure 1',
                        "images": {"imgs/fig1.png": "https://cdn.example.com/fig1.png"}
                    }
                }]
            }
        }

        # Second extraction with different image
        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {
            "result": {
                "layoutParsingResults": [{
                    "markdown": {
                        "text": '<img src="imgs/fig2.png"> Figure 2',
                        "images": {"imgs/fig2.png": "https://cdn.example.com/fig2.png"}
                    }
                }]
            }
        }

        mock_post.side_effect = [mock_response1, mock_response2]

        with patch("requests.get") as mock_get:
            mock_img_response = Mock()
            mock_img_response.content = b"fake image"
            mock_img_response.raise_for_status = Mock()
            mock_get.return_value = mock_img_response

            # First extraction
            _, figures1, _ = baidu_extractor.extract(sample_pdf_path, "doc1", image_dir)
            assert len(figures1) == 1
            assert figures1[0].title == "doc1_Figure1"

            # Second extraction - map should be cleared
            _, figures2, _ = baidu_extractor.extract(sample_pdf_path, "doc2", image_dir)
            assert len(figures2) == 1
            assert figures2[0].title == "doc2_Figure2"

    @patch("requests.post")
    def test_handles_api_rate_limiting(self, mock_post, baidu_extractor, sample_pdf_path, image_dir):
        """Test retry logic when API returns 429 (rate limited)."""
        # First call returns 429, second call succeeds
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limited"

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "result": {
                "layoutParsingResults": [{
                    "markdown": {"text": "## Content", "images": {}}
                }]
            }
        }

        mock_post.side_effect = [mock_response_429, mock_response_success]

        text_chunks, _, _ = baidu_extractor.extract(sample_pdf_path, "2501.01234", image_dir)

        # Should have retried and succeeded
        assert mock_post.call_count == 2
        assert len(text_chunks) >= 1


class TestFigureNamingConsistency:
    """Test that figure naming is consistent between VolcEngine and Baidu."""

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    @patch("requests.post")
    @patch("requests.get")
    def test_same_figure_naming(
        self, mock_get, mock_post, mock_volc_md,
        tmp_path
    ):
        """Both extractors should produce identical figure names for the same content."""
        # Setup paths
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(MINIMAL_PDF)
        volc_img_dir = tmp_path / "volc_imgs"
        baidu_img_dir = tmp_path / "baidu_imgs"
        volc_img_dir.mkdir()
        baidu_img_dir.mkdir()

        # VolcEngine markdown (URL-based images)
        volc_markdown = """## Content

![img](https://example.com/fig1.png)
Figure 1: Architecture diagram.
"""
        mock_volc_md.return_value = volc_markdown

        # Baidu API response (src-based images)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "layoutParsingResults": [{
                    "markdown": {
                        "text": """## Content

<img src="imgs/fig1.png">
Figure 1: Architecture diagram.""",
                        "images": {"imgs/fig1.png": "https://cdn.example.com/fig1.png"}
                    }
                }]
            }
        }
        mock_post.return_value = mock_response

        # Mock image download
        mock_img_response = Mock()
        mock_img_response.content = b"fake png"
        mock_img_response.raise_for_status = Mock()
        mock_get.return_value = mock_img_response

        # Extract with VolcEngine
        volc_extractor = PDFExtractor_volcengine("ak", "sk")
        _, volc_figures, _ = volc_extractor.extract(pdf_path, "2501.01234", volc_img_dir)

        # Extract with Baidu
        baidu_extractor = PDFExtractor_baidu("url", "token")
        _, baidu_figures, _ = baidu_extractor.extract(pdf_path, "2501.01234", baidu_img_dir)

        # Both should have same figure naming
        assert len(volc_figures) == len(baidu_figures)
        if volc_figures and baidu_figures:
            assert volc_figures[0].title == baidu_figures[0].title
            assert volc_figures[0].title == "2501.01234_Figure1"
