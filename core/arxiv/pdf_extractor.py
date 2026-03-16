"""PDFExtractor: convert PDF to markdown via VolcEngine OCR, then parse into chunks.

Used as fallback when HTML is unavailable. VolcEngine import is guarded.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple

from bs4 import BeautifulSoup

from core.models import TextChunk, FigureChunk, TableChunk, ChunkType
from core.arxiv.downloader import compress_pdf

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract text, figures, and tables from PDF via OCR."""

    def __init__(self, volcengine_ak: str, volcengine_sk: str,
                 max_pages: int = 16):
        self.volcengine_ak = volcengine_ak
        self.volcengine_sk = volcengine_sk
        self.max_pages = max_pages

    def extract(
        self,
        pdf_path: Path | str,
        doc_id: str,
        image_dir: Path | str,
    ) -> tuple[list[TextChunk], list[FigureChunk], list[TableChunk]]:
        """Convert PDF to markdown via OCR, then parse into chunks.

        Args:
            pdf_path: Path to the PDF file
            doc_id: Paper identifier
            image_dir: Directory to save extracted images

        Returns:
            Tuple of (text_chunks, figure_chunks, table_chunks)
        """
        pdf_path = Path(pdf_path)
        image_dir = Path(image_dir)

        markdown = self._pdf_to_markdown(pdf_path)
        if markdown is None:
            logger.warning("OCR failed for %s, returning empty chunks", doc_id)
            return [], [], []

        # Save markdown for debugging
        md_path = pdf_path.parent / f"{doc_id}.md"
        md_path.write_text(markdown, encoding="utf-8")

        text_chunks = self._parse_text(markdown)
        figure_chunks = self._parse_figures(markdown, doc_id, image_dir)
        table_chunks = self._parse_tables(markdown)

        return text_chunks, figure_chunks, table_chunks

    def _pdf_to_markdown(self, pdf_path: Path) -> str | None:
        """Convert PDF to markdown using VolcEngine OCR."""
        try:
            from volcengine.visual.VisualService import VisualService
        except ImportError:
            logger.error("volcengine package not installed, cannot extract PDF")
            return None

        visual_service = VisualService()
        visual_service.set_ak(self.volcengine_ak)
        visual_service.set_sk(self.volcengine_sk)

        # Compress if too large
        if pdf_path.stat().st_size > 7.5 * 1024 * 1024:
            logger.info("PDF >7.5MB, compressing: %s", pdf_path.name)
            try:
                compress_pdf(pdf_path)
            except Exception as e:
                logger.warning("Compression failed: %s, trying original", e)

        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        form = {
            "image_base64": base64.b64encode(pdf_content).decode(),
            "image_url": "",
            "version": "v3",
            "page_start": 0,
            "page_num": self.max_pages,
            "table_mode": "html",
            "filter_header": "true",
        }

        try:
            resp = visual_service.ocr_pdf(form)

            if not isinstance(resp, dict) or "data" not in resp:
                logger.error("OCR response missing 'data': %s", type(resp))
                return None

            if resp["data"] is None:
                logger.error("OCR data is None")
                return None

            markdown = resp["data"].get("markdown")
            if not markdown:
                logger.error("OCR returned empty markdown")
                return None

            return markdown

        except Exception as e:
            logger.error("OCR request failed: %s", e)
            return None

    def _parse_text(self, markdown: str) -> list[TextChunk]:
        """Parse markdown sections into text chunks."""
        all_text: list[TextChunk] = []

        try:
            # Remove image references
            cleaned = re.sub(r"^!\[fig_[^\n]*\n?", "", markdown, flags=re.MULTILINE)

            # Find top-level headings (## but not subsections like ## 2.1)
            pattern = r"(?:^|\n)(##\s+(?!(?:[A-Za-z]+\.)?\d+\.\d+)[^\n]+)"
            matches = list(re.finditer(pattern, cleaned))

            boundaries = [m.start() for m in matches]
            boundaries.append(len(cleaned))

            for i in range(len(matches)):
                start = boundaries[i]
                end = boundaries[i + 1]
                section_text = cleaned[start:end].strip()
                header_line = matches[i].group(1).strip()
                title = header_line.lstrip("#").strip()

                all_text.append(TextChunk(
                    id=f"text_{i + 1}",
                    type=ChunkType.TEXT,
                    title=title,
                    caption=title,
                    text=section_text,
                ))

        except Exception as e:
            logger.error("Error parsing text: %s", e)

        return all_text

    def _parse_figures(
        self,
        markdown: str,
        doc_id: str,
        image_dir: Path,
    ) -> list[FigureChunk]:
        """Parse figure references from markdown and download images."""
        import requests

        figures: list[FigureChunk] = []
        image_dir.mkdir(parents=True, exist_ok=True)

        # Find all image URLs
        url_pattern = r"!\[.*?\]\((https?://[^\)]+)\)"
        urls = re.findall(url_pattern, markdown)

        for url in urls:
            name = self._extract_figure_name(markdown, url)
            if not name:
                continue
            name = f"{doc_id}_{name}"
            caption = self._extract_caption(markdown, url)

            save_path = image_dir / f"{name}.png"
            try:
                response = requests.get(url, stream=True, timeout=15)
                response.raise_for_status()
                save_path.write_bytes(response.content)
                logger.info("Downloaded figure: %s", name)

                figures.append(FigureChunk(
                    id=None,
                    title=name,
                    type=ChunkType.FIGURE,
                    image_path=str(save_path),
                    alt_text="Refer to caption",
                    caption=caption,
                ))
            except Exception as e:
                logger.error("Failed to download figure %s: %s", url, e)

        return figures

    def _parse_tables(self, markdown: str) -> list[TableChunk]:
        """Parse HTML tables from markdown."""
        tables: list[TableChunk] = []

        try:
            soup = BeautifulSoup(markdown, "html.parser")
            for idx, table in enumerate(soup.find_all("table")):
                table_html = str(table)
                table_pos = markdown.find(table_html)
                context_before = markdown[max(0, table_pos - 500):table_pos]

                caption_match = re.search(
                    r"(Table\s*\d+[.:]?\s*)([^\n<]+)", context_before, re.IGNORECASE
                )
                if caption_match:
                    table_name = caption_match.group(1).strip().rstrip(":").rstrip(".")
                    caption_text = caption_match.group(2).strip()
                else:
                    table_name = f"table_{idx + 1}"
                    caption_text = ""

                tables.append(TableChunk(
                    id=None,
                    title=table_name,
                    type=ChunkType.TABLE,
                    table_html=table_html,
                    caption=caption_text,
                ))

        except Exception as e:
            logger.error("Error parsing tables: %s", e)

        return tables

    @staticmethod
    def _extract_figure_name(content: str, url: str) -> str:
        """Extract figure name from text following the URL."""
        url_end = content.find(url) + len(url)
        post = content[url_end:].strip()
        match = re.search(r"(fig(?:ure)?\.?\s*\d+)", post, re.IGNORECASE)
        if match:
            name = match.group(0).replace(".", "").replace(" ", "")
            name = name[0].upper() + name[1:]
            if name.startswith("Fig") and not name.startswith("Figure"):
                name = "Figure" + name[3:]
            return name
        return ""

    @staticmethod
    def _extract_caption(content: str, url: str) -> str:
        """Extract caption text following the URL."""
        url_end = content.find(url) + len(url)
        post = content[url_end:].lstrip()
        match = re.search(
            r"(fig(?:ure)?\.?\s*\d+[a-zA-Z]?\.*.*?)\n", post, re.IGNORECASE | re.DOTALL
        )
        return match.group(1).strip() if match else ""
