"""Unit tests for core.arxiv.pdf_extractor module.

Tests the base class methods and both OCR backend implementations
with mocked API calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from core.arxiv.pdf_extractor import (
    PDFExtractorBase,
    PDFExtractor_volcengine,
    PDFExtractor_baidu,
    PDFExtractor,
)
from core.models import ChunkType, FigureChunk, TableChunk, TextChunk


class TestNormalizeFigureName:
    """Tests for _normalize_figure_name static method."""

    def test_normalize_fig_with_dot(self):
        """fig. 1 -> Figure1"""
        result = PDFExtractorBase._normalize_figure_name("fig. 1")
        assert result == "Figure1"

    def test_normalize_fig_with_space(self):
        """Fig 2 -> Figure2"""
        result = PDFExtractorBase._normalize_figure_name("Fig 2")
        assert result == "Figure2"

    def test_normalize_figure_lowercase(self):
        """figure3 -> Figure3"""
        result = PDFExtractorBase._normalize_figure_name("figure3")
        assert result == "Figure3"

    def test_normalize_figure_mixed_case(self):
        """FIGURE4 -> FIGURE4 (only first letter capitalized)"""
        result = PDFExtractorBase._normalize_figure_name("FIGURE4")
        assert result == "FIGURE4"

    def test_normalize_fig_with_dot_and_space(self):
        """fig.  5 -> Figure5 (multiple spaces)"""
        result = PDFExtractorBase._normalize_figure_name("fig.  5")
        assert result == "Figure5"

    def test_normalize_already_figure(self):
        """Figure6 -> Figure6 (no change needed)"""
        result = PDFExtractorBase._normalize_figure_name("Figure6")
        assert result == "Figure6"


class TestExtractFigureName:
    """Tests for _extract_figure_name static method (URL-based, used by VolcEngine)."""

    def test_extract_figure_name_after_url(self):
        """Figure name appears after the image URL."""
        content = "![image](https://example.com/img.png) Figure 1 shows the architecture."
        result = PDFExtractorBase._extract_figure_name(content, "https://example.com/img.png")
        assert result == "Figure1"

    def test_extract_figure_name_before_url(self):
        """Figure name appears before the image URL (caption precedes image)."""
        content = "As shown in Fig. 2 below: ![image](https://example.com/img.png)"
        result = PDFExtractorBase._extract_figure_name(content, "https://example.com/img.png")
        assert result == "Figure2"

    def test_extract_figure_name_not_found(self):
        """No figure name found near the URL."""
        content = "![image](https://example.com/img.png) This is an illustration."
        result = PDFExtractorBase._extract_figure_name(content, "https://example.com/img.png")
        assert result == ""

    def test_extract_figure_name_url_not_in_content(self):
        """URL not found in content."""
        content = "Some text without the URL"
        result = PDFExtractorBase._extract_figure_name(content, "https://example.com/img.png")
        assert result == ""

    def test_extract_figure_name_far_away(self):
        """Figure name is too far from URL (>300 chars after)."""
        content = "![image](https://example.com/img.png)" + "x" * 400 + " Figure 1"
        result = PDFExtractorBase._extract_figure_name(content, "https://example.com/img.png")
        assert result == ""


class TestExtractFigureNameFromImgRef:
    """Tests for _extract_figure_name_from_img_ref static method (used by Baidu)."""

    def test_extract_after_img_ref(self):
        """Figure name appears after src="..."."""
        content = '<img src="imgs/abc.png"> Figure 1: Architecture diagram'
        result = PDFExtractorBase._extract_figure_name_from_img_ref(content, 'src="imgs/abc.png"')
        assert result == "Figure1"

    def test_extract_before_img_ref(self):
        """Figure name appears before src="..."."""
        content = 'See Fig. 2 below: <img src="imgs/def.png">'
        result = PDFExtractorBase._extract_figure_name_from_img_ref(content, 'src="imgs/def.png"')
        assert result == "Figure2"

    def test_extract_not_found(self):
        """No figure name found."""
        content = '<img src="imgs/abc.png"> Some description without figure reference'
        result = PDFExtractorBase._extract_figure_name_from_img_ref(content, 'src="imgs/abc.png"')
        assert result == ""

    def test_extract_ref_not_in_content(self):
        """Image reference not found in content."""
        content = "Some text without the image reference"
        result = PDFExtractorBase._extract_figure_name_from_img_ref(content, 'src="imgs/abc.png"')
        assert result == ""


class TestParseText:
    """Tests for _parse_text method."""

    def setup_method(self):
        """Create a minimal concrete implementation for testing."""
        class ConcreteExtractor(PDFExtractorBase):
            def _pdf_to_markdown(self, pdf_path):
                return ""

        self.extractor = ConcreteExtractor()

    def test_parse_text_single_section(self):
        """Parse a single section with ## heading."""
        markdown = """## Introduction

This is the introduction section.
It has multiple lines."""
        result = self.extractor._parse_text(markdown)
        assert len(result) == 1
        assert result[0].title == "Introduction"
        assert "Introduction" in result[0].text

    def test_parse_text_multiple_sections(self):
        """Parse multiple sections."""
        markdown = """## Introduction

Intro content.

## Methods

Methods content.

## Results

Results content."""
        result = self.extractor._parse_text(markdown)
        assert len(result) == 3
        assert result[0].title == "Introduction"
        assert result[1].title == "Methods"
        assert result[2].title == "Results"

    def test_parse_text_ignores_subsections(self):
        """Subsections like ## 2.1 should be ignored as top-level headings."""
        markdown = """## Introduction

Intro content.

## 2.1 Detailed Method

This subsection should not create a new chunk.

## Results

Results content."""
        result = self.extractor._parse_text(markdown)
        # Should only have Introduction and Results, not 2.1
        titles = [c.title for c in result]
        assert "Introduction" in titles
        assert "Results" in titles
        assert "2.1 Detailed Method" not in titles

    def test_parse_text_removes_image_references(self):
        """Image references like ![fig_xxx](...) should be removed."""
        markdown = """## Introduction

![fig_abc](https://example.com/img.png)

This is content after the image."""
        result = self.extractor._parse_text(markdown)
        assert len(result) == 1
        assert "![fig_" not in result[0].text

    def test_parse_text_empty(self):
        """Empty markdown returns empty list."""
        result = self.extractor._parse_text("")
        assert result == []


class TestParseTables:
    """Tests for _parse_tables method."""

    def setup_method(self):
        class ConcreteExtractor(PDFExtractorBase):
            def _pdf_to_markdown(self, pdf_path):
                return ""

        self.extractor = ConcreteExtractor()

    def test_parse_single_table(self):
        """Parse a single HTML table."""
        markdown = """Some text before.

Table 1: Experimental results

<table>
<tr><td>A</td><td>B</td></tr>
</table>

Some text after."""
        result = self.extractor._parse_tables(markdown)
        assert len(result) == 1
        assert "Table 1" in result[0].title
        assert "Experimental results" in result[0].caption

    def test_parse_multiple_tables(self):
        """Parse multiple HTML tables."""
        markdown = """
Table 1: First table
<table><tr><td>1</td></tr></table>

Table 2: Second table
<table><tr><td>2</td></tr></table>
"""
        result = self.extractor._parse_tables(markdown)
        assert len(result) == 2

    def test_parse_table_no_caption(self):
        """Table without caption gets default name."""
        markdown = """<table><tr><td>Data</td></tr></table>"""
        result = self.extractor._parse_tables(markdown)
        assert len(result) == 1
        assert result[0].title == "table_1"
        assert result[0].caption == ""

    def test_parse_no_tables(self):
        """No tables in markdown returns empty list."""
        markdown = "Just text, no tables here."
        result = self.extractor._parse_tables(markdown)
        assert result == []


class TestPDFExtractorVolcengine:
    """Tests for PDFExtractor_volcengine class."""

    def test_init(self):
        """Test initialization with credentials."""
        extractor = PDFExtractor_volcengine(
            volcengine_ak="test_ak",
            volcengine_sk="test_sk",
            max_pages=20
        )
        assert extractor.volcengine_ak == "test_ak"
        assert extractor.volcengine_sk == "test_sk"
        assert extractor.max_pages == 20

    def test_default_max_pages(self):
        """Default max_pages should be 16."""
        extractor = PDFExtractor_volcengine(ak="test", sk="test")
        assert extractor.max_pages == 16

    @patch("core.arxiv.pdf_extractor.PDFExtractor_volcengine._pdf_to_markdown")
    def test_extract_returns_chunks(self, mock_pdf_to_md, tmp_path):
        """extract() should return text, figure, and table chunks."""
        mock_pdf_to_md.return_value = """## Introduction

This is intro text.

Figure 1: Architecture
![img](https://example.com/fig1.png)

Table 1: Results
<table><tr><td>1</td></tr></table>
"""
        extractor = PDFExtractor_volcengine(ak="test", sk="test")

        # Create a temp PDF file
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

        image_dir = tmp_path / "imgs"
        image_dir.mkdir()

        # Mock the download in _parse_figures
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"fake image"
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            text_chunks, figure_chunks, table_chunks = extractor.extract(
                pdf_path, "2501.01234", image_dir
            )

        assert len(text_chunks) == 1
        assert text_chunks[0].title == "Introduction"
        # Figure might be skipped if no Figure name found near URL
        assert len(table_chunks) == 1


class TestPDFExtractorBaidu:
    """Tests for PDFExtractor_baidu class."""

    def test_init(self):
        """Test initialization with API credentials."""
        extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token",
            max_pages=10
        )
        assert extractor.api_url == "https://api.example.com/ocr"
        assert extractor.api_token == "test_token"
        assert extractor.max_pages == 10

    def test_default_options(self):
        """Test default option values."""
        extractor = PDFExtractor_baidu(url="url", token="token")
        assert extractor.use_doc_orientation_classify is False
        assert extractor.use_doc_unwarping is False
        assert extractor.use_chart_recognition is False

    @patch("requests.post")
    def test_pdf_to_markdown_success(self, mock_post, tmp_path):
        """Test successful PDF to markdown conversion."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": "## Introduction\n\nContent here.",
                            "images": {}
                        }
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token"
        )

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

        result = extractor._pdf_to_markdown(pdf_path)

        assert result is not None
        assert "## Introduction" in result
        assert extractor._image_url_map == {}

    @patch("requests.post")
    def test_pdf_to_markdown_with_images(self, mock_post, tmp_path):
        """Test that image URLs are collected from response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": '<img src="imgs/fig1.png"> Figure 1',
                            "images": {
                                "imgs/fig1.png": "https://cdn.example.com/fig1.png"
                            }
                        }
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token"
        )

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

        result = extractor._pdf_to_markdown(pdf_path)

        assert result is not None
        assert extractor._image_url_map == {
            "imgs/fig1.png": "https://cdn.example.com/fig1.png"
        }

    @patch("requests.post")
    def test_pdf_to_markdown_api_error(self, mock_post, tmp_path):
        """Test handling of API errors."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token"
        )

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

        result = extractor._pdf_to_markdown(pdf_path)

        assert result is None

    @patch("requests.post")
    def test_pdf_to_markdown_missing_result(self, mock_post, tmp_path):
        """Test handling of missing 'result' in response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "Something went wrong"}
        mock_post.return_value = mock_response

        extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token"
        )

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

        result = extractor._pdf_to_markdown(pdf_path)

        assert result is None


class TestPDFExtractorBaiduParseFigures:
    """Tests for PDFExtractor_baidu._parse_figures method."""

    def setup_method(self):
        self.extractor = PDFExtractor_baidu(
            api_url="https://api.example.com/ocr",
            api_token="test_token"
        )

    def test_parse_figures_with_valid_mapping(self, tmp_path):
        """Test figure parsing with valid URL mapping."""
        self.extractor._image_url_map = {
            "imgs/fig1.png": "https://cdn.example.com/fig1.png"
        }

        markdown = '<img src="imgs/fig1.png"> Figure 1: Architecture diagram'
        image_dir = tmp_path / "imgs"
        image_dir.mkdir()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"fake image data"
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            figures = self.extractor._parse_figures(markdown, "2501.01234", image_dir)

        assert len(figures) == 1
        assert figures[0].title == "2501.01234_Figure1"
        assert "Architecture" in figures[0].caption

    def test_parse_figures_skips_no_url_mapping(self, tmp_path):
        """Figures without URL mapping should be skipped."""
        self.extractor._image_url_map = {}  # Empty mapping

        markdown = '<img src="imgs/fig1.png"> Figure 1: Architecture'
        image_dir = tmp_path / "imgs"
        image_dir.mkdir()

        figures = self.extractor._parse_figures(markdown, "2501.01234", image_dir)

        assert len(figures) == 0

    def test_parse_figures_skips_no_figure_name(self, tmp_path):
        """Images without Figure name should be skipped."""
        self.extractor._image_url_map = {
            "imgs/img1.png": "https://cdn.example.com/img1.png"
        }

        markdown = '<img src="imgs/img1.png"> Just an image without figure reference'
        image_dir = tmp_path / "imgs"
        image_dir.mkdir()

        figures = self.extractor._parse_figures(markdown, "2501.01234", image_dir)

        assert len(figures) == 0

    def test_parse_figures_avoids_duplicates(self, tmp_path):
        """Same figure referenced multiple times should only be processed once."""
        self.extractor._image_url_map = {
            "imgs/fig1.png": "https://cdn.example.com/fig1.png"
        }

        # Same figure referenced twice
        markdown = '''
<img src="imgs/fig1.png"> Figure 1: First reference

Some text...

<img src="imgs/fig1.png"> Figure 1: Second reference
'''
        image_dir = tmp_path / "imgs"
        image_dir.mkdir()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = b"fake image"
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            figures = self.extractor._parse_figures(markdown, "2501.01234", image_dir)

        assert len(figures) == 1


class TestDefaultAlias:
    """Test that PDFExtractor alias points to the correct class."""

    def test_default_is_volcengine(self):
        """PDFExtractor should alias to PDFExtractor_volcengine."""
        assert PDFExtractor is PDFExtractor_volcengine
